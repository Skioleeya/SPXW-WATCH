"""
L2 — 市场状态聚合。
===================
唯一职责：把「存储里的时序数据」与「采集层上报的健康快照」拼成下游可以直接
消费的读数（现价、健康块、会话块）。

本模块是**只读聚合器**：没有任何 setter，不持有可变的业务状态，也不起线程。
这样 L4 组装推送帧时，看到的永远是一个自洽的视图。

注意它接收的是 L0 的 ``FeedStatus`` 而不是 ``IbkrFeed`` 对象——如果这里 import
了采集层，就形成了 L2 → L1 的反向依赖。

依赖：L0、L2（TickStore）。
"""

from __future__ import annotations

from typing import Any

from config import loader
from contracts.enums import ConnectionState
from contracts.frame import HealthBlock, SessionBlock, SessionZone
from contracts.tick import FeedStatus

from state.tick_store import TickStore

_CFG = "state"


class MarketState:
    """存储 + 采集健康 → 可展示读数。"""

    __slots__ = ("_store", "_clock", "_stale_s", "_degraded_s")

    def __init__(self, store: TickStore, state_cfg: dict, clock: Any) -> None:
        self._store = store
        self._clock = clock
        self._stale_s = loader.as_float(state_cfg, "health_stale_tick_s", module=_CFG)
        self._degraded_s = loader.as_float(
            state_cfg, "health_degraded_tick_s", module=_CFG
        )

    # ------------------------------------------------------------------ #
    # 读数
    # ------------------------------------------------------------------ #

    def spot(self) -> float:
        """现价。优先用存储里的最新标的 tick，缺失时退回采集层上报值。"""
        price = self._store.spot()
        return price

    def spot_with_fallback(self, feed_status: FeedStatus) -> float:
        price = self._store.spot()
        if price > 0:
            return price
        return float(feed_status.spot)

    def session_block(self) -> SessionBlock:
        described = self._clock.describe()
        return SessionBlock(
            date=described["date"],
            expiry=described["expiry"],
            open=described["open"],
            close=described["close"],
            is_open=bool(described["is_open"]),
            elapsed_s=float(described["elapsed_s"]),
            seconds_to_close=float(described["seconds_to_close"]),
            bucket_index=int(described["bucket_index"]),
            bucket_count=int(described["bucket_count"]),
            zones=self.session_zones(),
        )

    def session_zones(self) -> tuple[SessionZone, ...]:
        """
        网格的区段表（会话 + 它们之间的空档），升序、首尾相接。

        ``SessionClock`` 是 L0，**不 import ``contracts``**，所以它给的是普通
        dict；在这里升格成契约对象，跨层边界才算干净。前端按 ``first``/``last``
        切列，自己不推算时刻。
        """
        return tuple(
            SessionZone(
                id=str(zone["id"]),
                label=str(zone["label"]),
                is_session=bool(zone["is_session"]),
                first=int(zone["first"]),
                last=int(zone["last"]),
                open=str(zone["open"]),
                close=str(zone["close"]),
            )
            for zone in self._clock.zone_ranges()
        )

    def health(self, feed_status: FeedStatus, now: float | None = None) -> HealthBlock:
        """汇总健康块。连接状态由 tick 新鲜度进一步降级，避免"连着但没数据"。"""
        moment = now if now is not None else self._clock.now_ts()
        age = self._store.last_tick_age_s(moment)
        connection = feed_status.connection

        if connection is ConnectionState.CONNECTED and age is not None:
            if age > self._stale_s:
                connection = ConnectionState.DEGRADED

        return HealthBlock(
            mode=feed_status.mode,
            connection=connection,
            subscribed=feed_status.subscribed,
            subscription_cap=feed_status.subscription_cap,
            ticks_received=feed_status.ticks_received,
            ticks_dropped=feed_status.ticks_dropped,
            store_cells=self._store.cell_count(),
            last_tick_age_s=age,
            rate_limit=feed_status.rate_limit,
            sub_limit_backoff=feed_status.sub_limit_backoff,
            messages=self.recent_messages(limit=6),
        )

    def recent_messages(self, limit: int = 6) -> tuple[str, ...]:
        """把状态事件渲染成前端可直接显示的一行行文本。"""
        events = self._store.status_events(limit=limit)
        return tuple(
            f"{event.level.upper():5s} {event.source}: {event.message}"
            for event in events
        )

    def is_data_healthy(self, feed_status: FeedStatus, now: float | None = None) -> bool:
        """数据是否足够新鲜，可用于产出有效帧。"""
        moment = now if now is not None else self._clock.now_ts()
        age = self._store.last_tick_age_s(moment)
        if age is None:
            return False
        return age <= self._degraded_s and feed_status.connection is not ConnectionState.DISCONNECTED

    def stale_threshold_s(self) -> float:
        return self._stale_s

    def degraded_threshold_s(self) -> float:
        return self._degraded_s
