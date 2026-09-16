"""
L2 — 现货来源选择（按会话区段）。
================================
唯一职责：决定"此刻推给下游的现货价"来自哪里 —— GTH 段用合成值，其余用指数直读。

为什么需要它
------------
指数在 GTH 段是上一交易日收盘的**冻结值**（见 ``acquisition.spot_synthesis``
的实测数据），不能当锚；而 RTH 段指数就是权威，合成的反而多余。同一个系统里
现货因此有两个来源，必须有人按区段选。

它同时是 GTH 段的**闸门**：合成区段里 ``on_spot_tick`` 直接丢弃、不转发指数
—— 否则冻结值会在没有期货 tick 的间隙漏进下游，把窗口锚到 3 天前的价格上。

合成值由**期货 tick 驱动**，而不是由指数 tick 驱动
--------------------------------------------------
这是刻意的：若靠指数 tick 触发改写，一旦 IBKR 停止推送冻结指数（它随时可能），
合成就会静默停摆。改成期货驱动后，"没有期货 = 没有现货"，与
``WindowFollower._spot_stale()`` 的 fail-closed 语义天然对齐。

09:25 交班
----------
``synthesised_zones`` 只含 ``gth``（见 ``config/spot.json``），因此 GTH 段一结束
（09:25）现货源立刻切回指数直读。这次切源会让锚跳变 40+ 点（≈8 档），远超
``subscription.json::recenter_trigger_strikes`` ⇒ 期权订阅窗口由既有的
``WindowFollower`` **自动重建**，不需要额外代码。空档 09:25–09:30 特征层本就
静默（10 桶留白），09:30 一开盘指数即有实时数据。

依赖：L0（config / contracts）与 L1（core）。
"""

from __future__ import annotations

from typing import Any, Callable

from config import loader
from contracts.enums import StatusLevel
from contracts.tick import FutureTick, OptionTick, QuoteTick, SpotTick, StatusEvent

_CFG = "spot"


class SpotSourceSelector:
    """
    按会话区段选现货来源。实现 ``TickSink``，包在真实 sink 外面。

    链上位置：``TickRouter → SpotSourceSelector → SpotTap → store``。
    同时被当作 ``TickRouter`` 的 ``future_sink`` 注入（期货不进 ``TickSink`` 链，
    见 ``contracts.tick.FutureTick``）。
    """

    __slots__ = (
        "_inner", "_synthesis", "_clock", "_zones", "_max_age", "_note",
        "_last_zone", "_forwarded", "_synthesised", "_dropped",
    )

    def __init__(
        self,
        inner: Any,
        synthesis: Any,
        clock: Any,
        spot_cfg: dict,
        max_quote_age_s: float,
        note_callback: Callable[..., None],
    ) -> None:
        self._inner = inner
        self._synthesis = synthesis
        self._clock = clock
        self._zones = frozenset(
            str(zone)
            for zone in loader.as_list(spot_cfg, "synthesised_zones", module=_CFG)
        )
        self._max_age = float(max_quote_age_s)
        self._note = note_callback
        self._last_zone = ""
        self._forwarded = 0
        self._synthesised = 0
        self._dropped = 0

    # ------------------------------------------------------------------ #
    # 只读状态
    # ------------------------------------------------------------------ #

    @property
    def forwarded(self) -> int:
        """原样转发的指数 tick 条数。"""
        return self._forwarded

    @property
    def synthesised(self) -> int:
        """产出的合成现货条数。"""
        return self._synthesised

    @property
    def dropped(self) -> int:
        """在合成区段被丢弃的指数 tick 条数（冻结值，故意不放行）。"""
        return self._dropped

    def synthesising(self) -> bool:
        """当前区段是否用合成值。"""
        return self._clock.current_zone_id() in self._zones

    # ------------------------------------------------------------------ #
    # TickSink
    # ------------------------------------------------------------------ #

    def on_option_tick(self, tick: OptionTick) -> None:
        self._inner.on_option_tick(tick)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._inner.on_quote_tick(tick)

    def on_status(self, event: StatusEvent) -> None:
        self._inner.on_status(event)

    def on_spot_tick(self, tick: SpotTick) -> None:
        """指数 tick：合成区段里**丢弃**（冻结值不能当锚），其余原样转发。"""
        if self._sync_zone():
            self._dropped += 1
            return
        self._forwarded += 1
        self._inner.on_spot_tick(tick)

    def on_future_tick(self, tick: FutureTick) -> None:
        """期货 tick：先登记报价，再（仅合成区段）产出合成现货。"""
        self._synthesis.update(tick.expiry, tick.price, tick.ts)
        if not self._sync_zone():
            return
        price = self._synthesis.spot(tick.ts, self._max_age)
        if price is None:
            return
        self._synthesised += 1
        self._inner.on_spot_tick(SpotTick(price=price, ts=tick.ts))

    # ------------------------------------------------------------------ #
    # 区段
    # ------------------------------------------------------------------ #

    def _sync_zone(self) -> bool:
        """
        返回"当前区段是否用合成值"，并在区段变化时报一条消息。

        区段判定交给 ``SessionClock``（L1）—— 上层自己拿桶序号比区间，等于把
        网格几何抄了第二份。
        """
        zone = self._clock.current_zone_id()
        if zone != self._last_zone:
            self._last_zone = zone
            self._note(
                f"现货源切换：区段 {zone or '?'} → "
                f"{'合成（B2b 期货反解）' if zone in self._zones else '指数直读'}",
                StatusLevel.INFO,
            )
        return zone in self._zones
