"""
L2 — 现价就地留存。
====================
唯一职责：包在真实 sink 外面的一层薄壳 —— 把现价就地留一份给窗口计算用，
其余 tick 原样转发。

为什么需要它
------------
``IbkrFeed`` 算 ATM 窗口需要现价。最直接的写法是去读 L3 的存储，但 L2 → L3 是
反向依赖：采集层不该知道状态层的存在。就地留一份，依赖方向就保持单向。

它同时记下现价的时间戳，这一点不是可选的：窗口跟随必须知道"这个价格有多旧"。
现价断流时 ``last_spot`` 仍保留最后一个值，代码上看不出异常，但那个价格可能
已经是几分钟前的 —— 用它重建窗口会订错档位，且不报任何错。判断逻辑见
``acquisition.feed_service`` 的 ``_spot_stale()``。

依赖：L0（config / contracts）与 L1（core）。
"""

from __future__ import annotations

from typing import Any

from contracts.ports import TickSink
from contracts.tick import SpotTick, StatusEvent


class SpotTap:
    """把现价留一份给窗口计算，其余原样转发给真实 sink。"""

    __slots__ = ("_inner", "last_spot", "last_spot_ts")

    def __init__(self, inner: TickSink) -> None:
        self._inner = inner
        self.last_spot: float = 0.0
        self.last_spot_ts: float = 0.0

    def on_option_tick(self, tick: Any) -> None:
        self._inner.on_option_tick(tick)

    def on_quote_tick(self, tick: Any) -> None:
        self._inner.on_quote_tick(tick)

    def on_spot_tick(self, tick: SpotTick) -> None:
        self.last_spot = float(tick.price)
        self.last_spot_ts = float(tick.ts)
        self._inner.on_spot_tick(tick)

    def on_status(self, event: StatusEvent) -> None:
        self._inner.on_status(event)
