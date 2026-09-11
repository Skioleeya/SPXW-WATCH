"""
L3 — 25Δ Skew 引擎。
====================
唯一职责：从一批网格点里算出 25Δ 偏度，并维护一条按时间桶去重的折线序列。

三个读数
--------
* **ATM IV** —— 在 (Strike, IV) 点列上插值到现价，避免整数关口跳变。
* **25Δ Skew** —— 25Δ Put IV 减 25Δ Call IV（单位波动率点）。市场恐慌时
  下行保护被抢购，这个值会迅速向正方向扩大，是最灵敏的情绪突变信号。
* **Butterfly** —— (Put25 + Call25)/2 − ATM IV，衡量两翼相对平值整体抬升
  的程度，用来区分"整体波动率抬升"与"单纯偏度形变"。

为什么按时间桶去重
------------------
推送频率是亚秒级的，若每个推送帧都往序列里塞一个点，一分钟就能堆出上百个点，
前端折线会被噪声糊死。这里以热力图的时间桶（默认 60 秒）为粒度，同一桶内只
保留最后一次读数，序列长度天然被会话长度封顶。

依赖：L0、L3（DeltaLocator）。
"""

from __future__ import annotations

from config import loader
from contracts.enums import TRUSTWORTHY_QUALITIES, OptionRight, Quality
from contracts.feature import ImpulseCell, SkewPoint

from features.delta_locator import DeltaLocator

_FEAT = "features"
_SERIAL = "serialization"


class SkewEngine:
    """25Δ 偏度计算与序列维护。"""

    __slots__ = (
        "_locator", "_target_delta", "_max_points", "_clock",
        "_series", "_latest",
    )

    def __init__(self, feat_cfg: dict, serial_cfg: dict, clock) -> None:
        self._locator = DeltaLocator(feat_cfg)
        self._target_delta = loader.as_float(
            feat_cfg, "skew_target_delta", module=_FEAT
        )
        self._max_points = loader.as_int(
            serial_cfg, "skew_series_max_points", module=_SERIAL
        )
        self._clock = clock
        self._series: dict[int, SkewPoint] = {}
        self._latest: SkewPoint | None = None

    # ------------------------------------------------------------------ #
    # 计算
    # ------------------------------------------------------------------ #

    def compute(
        self,
        cells: tuple[ImpulseCell, ...],
        spot: float,
        now: float,
    ) -> SkewPoint:
        """算一个 SkewPoint，并写入当前时间桶。"""
        put_samples: list[tuple[float | None, float, float]] = []
        call_samples: list[tuple[float | None, float, float]] = []
        smile: list[tuple[float, float]] = []

        for cell in cells:
            # 只采信可信的点：一个 GLITCH 点会同时污染 25Δ 插值结果和 ATM 微笑
            # 插值，而这两者正是 Skew 的全部输入。
            if cell.quality not in TRUSTWORTHY_QUALITIES:
                continue
            if cell.right is OptionRight.PUT:
                put_samples.append((cell.delta, cell.strike, cell.iv))
            else:
                call_samples.append((cell.delta, cell.strike, cell.iv))
            smile.append((cell.strike, cell.iv))

        atm_iv = DeltaLocator.interpolate_iv_at_strike(smile, spot) if smile else None

        put25 = self._locator.locate(put_samples, -abs(self._target_delta))
        call25 = self._locator.locate(call_samples, abs(self._target_delta))

        skew = None
        butterfly = None
        if put25 is not None and call25 is not None:
            skew = (put25.iv - call25.iv) * 100.0
            if atm_iv is not None:
                butterfly = ((put25.iv + call25.iv) / 2.0 - atm_iv) * 100.0

        point = SkewPoint(
            ts=now,
            spot=spot,
            atm_iv=atm_iv,
            put25_iv=put25.iv if put25 else None,
            call25_iv=call25.iv if call25 else None,
            put25_strike=put25.strike if put25 else None,
            call25_strike=call25.strike if call25 else None,
            put25_delta=put25.target_delta if put25 else None,
            call25_delta=call25.target_delta if call25 else None,
            skew_25d_vol_points=skew,
            butterfly_vol_points=butterfly,
            quality=self._quality(put25, call25),
        )

        self._latest = point
        self._store(point)
        return point

    @staticmethod
    def _quality(put25, call25) -> Quality:
        if put25 is not None and call25 is not None:
            return Quality.OK
        if put25 is not None or call25 is not None:
            return Quality.STALE
        return Quality.MISSING

    # ------------------------------------------------------------------ #
    # 序列
    # ------------------------------------------------------------------ #

    def _store(self, point: SkewPoint) -> None:
        """按时间桶写入；同一桶覆盖，保证序列按会话长度封顶。"""
        index = self._clock.bucket_index_of_ts(point.ts)
        self._series[index] = point

        if len(self._series) > self._max_points:
            cutoff = index - self._max_points
            for key in [k for k in self._series if k < cutoff]:
                del self._series[key]

    def series(self) -> tuple[SkewPoint, ...]:
        """按时间升序返回折线序列。"""
        return tuple(self._series[k] for k in sorted(self._series))

    def latest(self) -> SkewPoint | None:
        return self._latest

    def reset(self) -> None:
        self._series.clear()
        self._latest = None

    @property
    def target_delta(self) -> float:
        return abs(self._target_delta)
