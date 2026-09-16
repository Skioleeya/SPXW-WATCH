"""
L6 — 25Δ 偏度与平值读数编码。
==============================
唯一职责：把 ``SkewPoint`` 序列与 ``AtmSnapshot`` 编码成前端折线图与顶部读数
所需的 JSON。

为什么用列式（columnar）而不是行式
----------------------------------
折线图有 4 条序列（Skew / ATM / 25Δ Put / 25Δ Call），行式编码会把键名重复
390 遍。列式把每个指标各放一个数组，载荷体积大约只有行式的三分之一，而
ECharts 的 ``dataset`` 原生支持列式输入。

时间轴同时给 ``ts``（epoch 秒）与 ``label``（市场时区 HH:MM）——只用 epoch
的话，前端拿浏览器本地时区去格式化，非美东的用户会看到错位的时间轴。

依赖：L0、L6（numeric）。
"""

from __future__ import annotations

from typing import Iterable

from config import loader
from contracts.feature import AtmSnapshot, SkewPoint

from serialization.numeric import round_opt

_CFG = "serialization"


class SkewSerializer:
    """偏度序列与平值读数编码器。"""

    __slots__ = ("_iv_decimals", "_price_decimals", "_clock")

    def __init__(self, serial_cfg: dict, clock) -> None:
        self._iv_decimals = loader.as_int(serial_cfg, "iv_decimals", module=_CFG)
        self._price_decimals = loader.as_int(
            serial_cfg, "price_decimals", module=_CFG
        )
        self._clock = clock

    # ------------------------------------------------------------------ #
    # 折线序列
    # ------------------------------------------------------------------ #

    def encode_series(self, points: Iterable[SkewPoint]) -> dict:
        """
        编码整条 25Δ 偏度序列。

        ``bucket`` 是每个点所属的**基线时间桶序号**。前端按用户选的周期把基线桶
        并组，必须知道每个点落在哪个基线桶里 —— 用下标推断不行（某个桶可能整段
        没有读数，序列里就不存在那个点），用时间戳现算则是把后端的桶口径抄一遍。
        随帧下发，前端只做 ``floor(bucket / group)``。

        ``label`` 与 ``bucket`` 同源算出，不各算一次：两者都来自同一个
        ``bucket_index_of_ts``，分开算等于把同一个换算跑两遍。
        """
        rows = list(points)
        buckets = [self._clock.bucket_index_of_ts(p.ts) for p in rows]

        return {
            "ts": [round(float(p.ts), 3) for p in rows],
            "bucket": buckets,
            "label": [self._clock.bucket_label(b) for b in buckets],
            "skew": [round_opt(p.skew_25d_vol_points, 3) for p in rows],
            "atm": [round_opt(self._as_vol_points(p.atm_iv), 3) for p in rows],
            "put25": [round_opt(self._as_vol_points(p.put25_iv), 3) for p in rows],
            "call25": [round_opt(self._as_vol_points(p.call25_iv), 3) for p in rows],
            "spot": [round(float(p.spot), self._price_decimals) for p in rows],
            "count": len(rows),
        }

    def encode_latest(self, point: SkewPoint | None) -> dict | None:
        if point is None:
            return None
        return {
            "ts": round(float(point.ts), 3),
            "label": self._label(point.ts),
            "skew": round_opt(point.skew_25d_vol_points, 3),
            "atm": round_opt(self._as_vol_points(point.atm_iv), 3),
            "put25": round_opt(self._as_vol_points(point.put25_iv), 3),
            "call25": round_opt(self._as_vol_points(point.call25_iv), 3),
            "put25_strike": round_opt(point.put25_strike, self._price_decimals),
            "call25_strike": round_opt(point.call25_strike, self._price_decimals),
            "butterfly": round_opt(point.butterfly_vol_points, 3),
            "quality": str(point.quality),
        }

    # ------------------------------------------------------------------ #
    # 平值读数
    # ------------------------------------------------------------------ #

    def encode_atm(self, atm: AtmSnapshot | None) -> dict | None:
        if atm is None:
            return None
        return {
            "spot": round(float(atm.spot), self._price_decimals),
            "atm_strike": round_opt(atm.atm_strike, self._price_decimals),
            "atm_iv": round_opt(self._as_vol_points(atm.atm_iv), 3),
            "atm_delta": round_opt(atm.atm_delta, 3),
            "straddle": round_opt(atm.straddle_price, self._price_decimals),
            "put25_iv": round_opt(self._as_vol_points(atm.put25_iv), 3),
            "call25_iv": round_opt(self._as_vol_points(atm.call25_iv), 3),
            "skew_25d": round_opt(atm.skew_25d_vol_points, 3),
            "butterfly": round_opt(atm.butterfly_vol_points, 3),
            "ts": round(float(atm.ts), 3),
        }

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _label(self, ts: float) -> str:
        return self._clock.bucket_label(self._clock.bucket_index_of_ts(ts))

    def _as_vol_points(self, iv: float | None) -> float | None:
        """
        IV 小数 → 波动率点。

        内部计算全程用小数（0.14），前端展示与比较一律用波动率点（14.0），
        换算只在这一处发生，避免两头各转一次导致 100 倍错误。
        """
        if iv is None:
            return None
        return float(iv) * 100.0
