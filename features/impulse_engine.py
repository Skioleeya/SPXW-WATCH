"""
L3 — IV 冲量引擎。
==================
唯一职责：计算"某个行权价的 IV 在过去 N 分钟内变化了多少、速率多快"。

数学定义
--------
::

    ΔIV(N)     = (IV_now − IV_{now−N}) × 100        单位：波动率点
    Impulse(N) = ΔIV(N) / (N / 60)                  单位：波动率点 / 分钟

为什么用"最近不晚于目标时刻"的点而不是插值
------------------------------------------
0DTE 的报价是稀疏、不规则的。对 IV 做时间插值会产生原数据里并不存在的平滑度，
在判断"突然的波动率冲量"时恰恰会把尖峰抹掉。因此这里取时间上最接近目标时刻
且不晚于它的那笔真实 tick，并用 ``min_span_ratio`` 保证这个点不会离目标时刻太远
（太远就判定为历史不足，返回空，而不是硬算一个假数字）。

依赖：L0。
"""

from __future__ import annotations

from config import loader
from contracts.enums import Quality
from contracts.feature import ImpulseCell, WindowDelta
from contracts.tick import OptionTick, OptionRef
from core.ring_buffer import RingBuffer

_CFG = "features"


class ImpulseEngine:
    """把单个分片的时间序列折算成动能读数。"""

    __slots__ = ("_windows", "_min_span_ratio", "_min_abs_iv")

    def __init__(self, feat_cfg: dict) -> None:
        windows = loader.as_float_list(
            feat_cfg, "impulse_windows_seconds", module=_CFG
        )
        # 升序去重，保证 primary_impulse() 取到的是最短窗口。
        self._windows = tuple(sorted({int(w) for w in windows if w > 0}))
        self._min_span_ratio = loader.as_float(
            feat_cfg, "impulse_min_span_ratio", module=_CFG
        )
        self._min_abs_iv = loader.as_float(
            feat_cfg, "impulse_min_abs_iv", module=_CFG
        )

    @property
    def windows(self) -> tuple[int, ...]:
        return self._windows

    # ------------------------------------------------------------------ #
    # 单点计算
    # ------------------------------------------------------------------ #

    def cell(
        self,
        ref: OptionRef,
        buffer: RingBuffer[OptionTick] | None,
        quality: Quality,
        now: float,
    ) -> ImpulseCell | None:
        """构造一个网格点的动能读数。历史不足时 ``windows`` 为空。"""
        if buffer is None or not buffer:
            return None

        latest = buffer.latest()
        if latest is None:
            return None

        tick = latest.value
        if tick.iv < self._min_abs_iv:
            return None

        windows: list[WindowDelta] = []
        for seconds in self._windows:
            delta = self._window_delta(buffer, tick, now, seconds)
            if delta is not None:
                windows.append(delta)

        return ImpulseCell(
            ref=ref,
            iv=tick.iv,
            quality=quality,
            age_s=max(now - tick.ts, 0.0),
            ts=tick.ts,
            delta=tick.delta,
            opt_price=tick.opt_price,
            windows=tuple(windows),
        )

    def _window_delta(
        self,
        buffer: RingBuffer[OptionTick],
        tick: OptionTick,
        now: float,
        seconds: int,
    ) -> WindowDelta | None:
        """取窗口前的基准点并计算增量。"""
        tolerance = seconds * self._min_span_ratio
        base = buffer.at_or_before(now - seconds, tolerance)
        if base is None:
            return None

        # 基准点必须严格早于当前点，否则说明窗口内只有一笔数据。
        if base.ts >= tick.ts:
            return None

        delta_vol_points = (tick.iv - base.value.iv) * 100.0
        return WindowDelta(
            seconds=seconds,
            iv_ago=base.value.iv,
            delta_vol_points=delta_vol_points,
            impulse_per_min=delta_vol_points / (seconds / 60.0),
        )

    # ------------------------------------------------------------------ #
    # 批量
    # ------------------------------------------------------------------ #

    def cells_for(
        self,
        entries: list[tuple[OptionRef, RingBuffer[OptionTick] | None, Quality]],
        now: float,
    ) -> tuple[ImpulseCell, ...]:
        """批量构造，跳过无法计算的网格点。"""
        out: list[ImpulseCell] = []
        for ref, buffer, quality in entries:
            cell = self.cell(ref, buffer, quality, now)
            if cell is not None:
                out.append(cell)
        return tuple(out)
