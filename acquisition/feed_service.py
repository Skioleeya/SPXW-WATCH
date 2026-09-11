"""
L1 — IBKR 行情服务编排器。
===========================
唯一职责：把网关、合约工厂、链解析、订阅协调、tick 路由串成一条"启动即出数据"
的流水线，并实现 L0 的 ``FeedPort``。

它是 L1 的对外门面：L6 组装层只认识 ``FeedPort``，完全不知道底下有 ``ib_async``。

本模块**不 import 任何 L2 及以上的东西**。它需要知道现价才能算 ATM 窗口，
但这个现价由内部的 ``_SpotTap`` 就地留存，而不是去读状态层的存储——否则就
构成了 L1 → L2 的反向依赖。

依赖：L0。
"""

from __future__ import annotations

import asyncio
from typing import Any

from config import loader
from contracts.enums import ConnectionState, FeedMode, StatusLevel
from contracts.ports import TickSink
from contracts.tick import FeedStatus, SpotTick, StatusEvent
from core.clock import now_ts
from core.errors import SpotUnavailableError

from acquisition.chain_resolver import ChainResolver
from acquisition.contract_factory import ContractFactory
from acquisition.ibkr_gateway import IbkrGateway
from acquisition.subscription_manager import SubscriptionManager
from acquisition.tick_router import TickRouter

_APP = "app"
_IBKR = "ibkr"
_SUB = "subscription"

# IBKR 错误码语义（只在本文件翻译，网关层保持中立）
_CODE_SUBSCRIPTION_LIMIT = 300
_CODE_DATA_LOST = 1101
_CODE_NO_SECURITY = 200
_IGNORED_CODES = frozenset(
    {1100, 1102, 2103, 2104, 2105, 2106, 2108, 2110, 2158, 10167, 10089, 10091}
)


class _SpotTap:
    """
    包在真实 sink 外面的一层薄壳：把现价就地留一份给窗口计算用，其余原样转发。

    这样 L1 既能拿到现价，又不需要去读 L2 的存储，依赖方向保持单向。
    """

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


class IbkrFeed:
    """``FeedPort`` 的实盘实现。"""

    __slots__ = (
        "_app_cfg", "_ibkr_cfg", "_sub_cfg", "_clock",
        "_sink", "_tap", "_gateway", "_factory", "_resolver",
        "_manager", "_router", "_slice", "_window", "_centre",
        "_reconcile_task", "_resubscribe_task", "_running",
        "_messages", "_mode", "_last_error", "_recover_at",
    )

    def __init__(self, app_cfg: dict, ibkr_cfg: dict, sub_cfg: dict, clock: Any) -> None:
        self._app_cfg = app_cfg
        self._ibkr_cfg = ibkr_cfg
        self._sub_cfg = sub_cfg
        self._clock = clock

        self._sink: TickSink | None = None
        self._tap: _SpotTap | None = None
        self._gateway = IbkrGateway(ibkr_cfg)
        self._factory = ContractFactory(app_cfg)
        self._resolver = ChainResolver(app_cfg, sub_cfg)
        self._manager = SubscriptionManager(self._gateway, self._factory, sub_cfg)
        self._router: TickRouter | None = None

        self._slice = None
        self._window: tuple[float, ...] = ()
        self._centre: float | None = None
        self._reconcile_task: asyncio.Task | None = None
        self._resubscribe_task: asyncio.Task | None = None
        self._running = False
        self._messages: list[str] = []
        self._last_error = ""
        self._recover_at = 0.0

        mdt = loader.as_int(ibkr_cfg, "market_data_type", module=_IBKR)
        self._mode = FeedMode.from_market_data_type(mdt)

    # ------------------------------------------------------------------ #
    # FeedPort
    # ------------------------------------------------------------------ #

    @property
    def mode(self) -> str:
        return str(self._mode)

    def set_sink(self, sink: TickSink) -> None:
        self._sink = sink

    def status(self) -> FeedStatus:
        tap = self._tap
        router = self._router
        return FeedStatus(
            mode=self._mode,
            connection=self._gateway.state,
            subscribed=self._manager.count,
            subscription_cap=self._manager.capacity,
            ticks_received=router.routed if router else 0,
            ticks_dropped=router.rejected if router else 0,
            throttled=self._manager.throttled,
            expiry=self._slice.expiry if self._slice else "",
            spot=tap.last_spot if tap else 0.0,
            messages=tuple(self._messages[-6:]),
        )

    # ------------------------------------------------------------------ #
    # 启动
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._sink is None:
            raise RuntimeError("start() 之前必须先 set_sink()")
        if self._running:
            return

        self._tap = _SpotTap(self._sink)
        self._router = TickRouter(self._tap, self._ibkr_cfg)

        self._gateway.set_callbacks(
            on_tickers=self._router.handle_tickers,
            on_error=self._on_error,
            on_disconnect=self._on_disconnect,
            on_reconnect=self._on_reconnect,
        )

        self._note(f"连接 IBKR {loader.as_str(self._ibkr_cfg, 'host', module=_IBKR)}"
                   f":{loader.as_int(self._ibkr_cfg, 'port', module=_IBKR)}")
        await self._gateway.connect()

        mdt = loader.as_int(self._ibkr_cfg, "market_data_type", module=_IBKR)
        self._gateway.set_market_data_type(mdt)
        self._note(f"行情模式 {self._mode}")

        await self._resolve_and_subscribe()

        self._running = True
        self._reconcile_task = asyncio.create_task(self._reconcile_loop())
        self._note("行情服务已就绪")

    async def _resolve_and_subscribe(self) -> None:
        """解析标的与 0DTE 链，并建立初始订阅。"""
        underlying = await self._gateway.qualify(self._factory.underlying())
        self._gateway.subscribe_spot(underlying)
        self._router.set_spot_con_id(int(getattr(underlying, "conId", 0) or 0))

        spot = await self._await_spot()
        self._note(f"标的现价 {spot:.2f}")

        chains = await self._gateway.fetch_chain(
            self._factory.symbol,
            loader.as_str(self._app_cfg, "underlying_sec_type", module=_APP),
            self._factory.underlying_exchange,
            int(getattr(underlying, "conId", 0) or 0),
        )

        # reqSecDefOptParams 是分片返回的，给 IBKR 一点时间补齐其余交易所片段。
        settle = loader.as_float(self._ibkr_cfg, "chain_settle_s", module=_IBKR)
        if settle > 0:
            await asyncio.sleep(settle)

        self._slice = self._resolver.pick_zero_dte(
            chains, self._clock.expiry_str(), int(getattr(underlying, "conId", 0) or 0)
        )

        if self._resolver.is_shrunk():
            self._note(
                f"档位数受订阅上限压缩为 ±{self._resolver.effective_each_side()}",
                StatusLevel.WARN,
            )

        self._note(
            f"0DTE 切片 {self._slice.expiry} {self._slice.trading_class} "
            f"({len(self._slice.strikes)} 个行权价, {self._slice.exchange})"
        )

        self._window = self._resolver.window(self._slice.strikes, spot)
        self._centre = self._resolver.centre_strike(self._window, spot)
        plan = await self._manager.reconcile(self._slice.expiry, self._window)
        self._note(
            f"初始订阅 {plan.projected_total} 条 "
            f"(上限 {self._manager.capacity}, 目标 {len(plan.keep) + len(plan.add)})"
        )
        if plan.failed:
            self._note(
                f"{len(plan.failed)} 条合约未能订阅（合约未确认或接口拒绝），"
                "这些档位不会有数据",
                StatusLevel.ERROR,
            )

    async def _await_spot(self) -> float:
        timeout = loader.as_float(self._ibkr_cfg, "spot_ready_timeout_s", module=_IBKR)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            spot = self._tap.last_spot if self._tap else 0.0
            if spot > 0:
                return spot
            await asyncio.sleep(0.1)
        raise SpotUnavailableError(
            f"{timeout:.0f}s 内未收到标的现价。请确认 TWS 已登录且具备行情权限。"
        )

    # ------------------------------------------------------------------ #
    # 窗口维护循环
    # ------------------------------------------------------------------ #

    async def _reconcile_loop(self) -> None:
        interval = loader.as_float(self._sub_cfg, "reconcile_interval_s", module=_SUB)
        trigger = loader.as_float(
            self._sub_cfg, "recenter_trigger_strikes", module=_SUB
        )
        while self._running:
            await asyncio.sleep(interval)
            if not self._running or self._slice is None or self._tap is None:
                continue

            if self._manager.throttled:
                continue

            if self._recover_at and now_ts() >= self._recover_at:
                self._manager.note_recovered()
                self._recover_at = 0.0
                self._note("订阅配额已恢复", StatusLevel.INFO)

            spot = self._tap.last_spot
            if spot <= 0:
                continue

            if not self._resolver.centre_moved(
                self._centre, self._slice.strikes, spot, trigger
            ):
                continue

            window = self._resolver.window(self._slice.strikes, spot)
            if window == self._window:
                continue

            self._window = window
            self._centre = self._resolver.centre_strike(window, spot)
            try:
                plan = await self._manager.reconcile(self._slice.expiry, window)
            except Exception as exc:
                self._note(f"窗口重建失败: {exc}", StatusLevel.ERROR)
                continue

            if plan.changed:
                self._note(
                    f"窗口跟随现价重建 ±{len(window) // 2} 档 "
                    f"(+{len(plan.add)} / -{len(plan.drop)}, 共 {plan.projected_total})"
                )
            if plan.failed:
                self._note(
                    f"窗口重建时 {len(plan.failed)} 条合约订阅失败",
                    StatusLevel.WARN,
                )

    # ------------------------------------------------------------------ #
    # IBKR 事件翻译
    # ------------------------------------------------------------------ #

    def _on_error(self, req_id: int, code: int, message: str, contract: Any) -> None:
        if code == _CODE_SUBSCRIPTION_LIMIT:
            backoff = self._manager.note_throttled()
            self._recover_at = now_ts() + backoff
            self._note(
                f"触发 IBKR Error 300（行情行数超限），退避 {backoff:.0f}s",
                StatusLevel.ERROR, code,
            )
            return

        if code == _CODE_DATA_LOST:
            self._note("IBKR 1101：行情订阅状态丢失，准备重建", StatusLevel.WARN, code)
            if self._resubscribe_task is None or self._resubscribe_task.done():
                self._resubscribe_task = asyncio.create_task(self._resubscribe())
            return

        if code == _CODE_NO_SECURITY:
            self._note(f"合约无定义 (reqId={req_id}): {message}", StatusLevel.WARN, code)
            return

        if code in _IGNORED_CODES:
            return

        self._last_error = f"{code}: {message}"
        self._note(f"IBKR 错误 {code}: {message}", StatusLevel.WARN, code)

    async def _resubscribe(self) -> None:
        try:
            count = await self._manager.resubscribe_all()
            self._note(f"已重建 {count} 条行情订阅")
        except Exception as exc:
            self._note(f"重建订阅失败: {exc}", StatusLevel.ERROR)

    def _on_disconnect(self) -> None:
        self._note("IBKR 连接断开，进入自动重连", StatusLevel.ERROR)

    def _on_reconnect(self) -> None:
        self._note("IBKR 已重连，正在重建行情", StatusLevel.WARN)
        if self._resubscribe_task is None or self._resubscribe_task.done():
            self._resubscribe_task = asyncio.create_task(self._resubscribe())

    # ------------------------------------------------------------------ #
    # 停机
    # ------------------------------------------------------------------ #

    async def stop(self) -> None:
        self._running = False
        for task in (self._reconcile_task, self._resubscribe_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._reconcile_task = None
        self._resubscribe_task = None

        try:
            await self._manager.clear()
        except Exception:
            pass
        await self._gateway.disconnect()
        self._note("行情服务已停止")

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #

    def _note(self, message: str, level: StatusLevel = StatusLevel.INFO, code: int = 0) -> None:
        self._messages.append(message)
        if len(self._messages) > 32:
            del self._messages[:-32]
        if self._sink is not None:
            try:
                self._sink.on_status(
                    StatusEvent(
                        level=level, source="ibkr", message=message,
                        ts=now_ts(), code=code,
                    )
                )
            except Exception:
                pass
