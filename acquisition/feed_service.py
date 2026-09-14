"""
L1 — IBKR 行情服务编排器。
===========================
唯一职责：把网关、合约工厂、链解析、订阅协调、tick 路由串成一条"启动即出数据"
的流水线，并实现 L0 的 ``FeedPort``。

它是 L1 的对外门面：L6 组装层只认识 ``FeedPort``，完全不知道底下有 ``ib_async``。

本模块**不 import 任何 L2 及以上的东西**。它需要知道现价才能算 ATM 窗口，
但这个现价由 ``acquisition.spot_tap.SpotTap`` 就地留存，而不是去读状态层的
存储——否则就构成了 L1 → L2 的反向依赖。

依赖：L0。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from config import loader
from contracts.enums import ConnectionState, FeedMode, StatusLevel
from contracts.ports import TickSink
from contracts.tick import FeedStatus, StatusEvent
from core.clock import now_ts
from core.errors import SpotUnavailableError

from acquisition.chain_resolver import ChainResolver
from acquisition.contract_factory import ContractFactory
from acquisition.feed_errors import FeedErrorHandler
from acquisition.feed_reconcile import WindowFollower
from acquisition.ibkr_gateway import IbkrGateway
from acquisition.spot_source import SpotSourceSelector
from acquisition.spot_synthesis import SpotSynthesis
from acquisition.spot_tap import SpotTap
from acquisition.subscription_manager import SubscriptionManager
from acquisition.tick_router import TickRouter

_APP = "app"
_IBKR = "ibkr"
_SUB = "subscription"
_SPOT = "spot"


class IbkrFeed:
    """``FeedPort`` 的实盘实现。"""

    __slots__ = (
        "_app_cfg", "_ibkr_cfg", "_sub_cfg", "_spot_cfg", "_clock",
        "_sink", "_tap", "_gateway", "_factory", "_resolver",
        "_manager", "_router", "_selector", "_synthesis",
        "_slice", "_window", "_centre",
        "_reconcile_task", "_resubscribe_task", "_running",
        "_messages", "_mode", "_error_handler", "_follower",
        "_reconnect_hook",
    )

    def __init__(
        self,
        app_cfg: dict,
        ibkr_cfg: dict,
        sub_cfg: dict,
        spot_cfg: dict,
        clock: Any,
    ) -> None:
        self._app_cfg = app_cfg
        self._ibkr_cfg = ibkr_cfg
        self._sub_cfg = sub_cfg
        self._spot_cfg = spot_cfg
        self._clock = clock

        self._sink: TickSink | None = None
        self._tap: SpotTap | None = None
        self._gateway = IbkrGateway(ibkr_cfg)
        self._factory = ContractFactory(app_cfg, spot_cfg)
        self._resolver = ChainResolver(app_cfg, sub_cfg)
        self._manager = SubscriptionManager(self._gateway, self._factory, sub_cfg)
        self._router: TickRouter | None = None
        self._selector: SpotSourceSelector | None = None
        self._synthesis: SpotSynthesis | None = None

        self._slice = None
        self._window: tuple[float, ...] = ()
        self._centre: float | None = None
        self._reconcile_task: asyncio.Task | None = None
        self._resubscribe_task: asyncio.Task | None = None
        self._running = False
        self._messages: list[str] = []

        self._error_handler: FeedErrorHandler | None = None
        self._follower: WindowFollower | None = None
        self._reconnect_hook: Callable[[], None] | None = None

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

    def set_reconnect_hook(self, hook: Callable[[], None]) -> None:
        """见 ``contracts.ports.FeedPort.set_reconnect_hook``。"""
        self._reconnect_hook = hook

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
            rate_limit=self._gateway.rate_limit,
            sub_limit_backoff=self._manager.in_backoff,
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

        self._tap = SpotTap(self._sink)
        # 现货来源链：TickRouter → SpotSourceSelector → SpotTap → store。
        # selector 同时被当作 future_sink 注入 —— 期货不进 TickSink 链
        # （理由见 contracts.tick.FutureTick）。
        self._synthesis = SpotSynthesis(self._spot_cfg)
        self._selector = SpotSourceSelector(
            self._tap,
            self._synthesis,
            self._clock,
            self._spot_cfg,
            loader.as_float(self._ibkr_cfg, "max_underlying_age_s", module=_IBKR),
            self._note,
        )
        self._router = TickRouter(
            self._selector, self._ibkr_cfg, future_sink=self._selector
        )

        self._error_handler = FeedErrorHandler(
            self._manager, self._note, self._trigger_resubscribe,
        )
        self._follower = WindowFollower(
            self._manager,
            self._resolver,
            self._tap,
            self._sub_cfg,
            self._note,
            loader.as_float(self._ibkr_cfg, "max_underlying_age_s", module=_IBKR),
            recover_at_ref=lambda: self._error_handler.recover_at
            if self._error_handler is not None else 0.0,
            set_recover_at=lambda v: self._error_handler.set_recover_at(v)
            if self._error_handler is not None else None,
        )

        self._gateway.set_callbacks(
            on_tickers=self._router.handle_tickers,
            on_error=self._on_error,
            on_disconnect=self._on_disconnect,
            on_reconnect=self._on_reconnect,
        )

        self._note(
            f"连接 IBKR {loader.as_str(self._ibkr_cfg, 'host', module=_IBKR)}"
            f":{loader.as_int(self._ibkr_cfg, 'port', module=_IBKR)}"
        )
        await self._gateway.connect()

        mdt = loader.as_int(self._ibkr_cfg, "market_data_type", module=_IBKR)
        self._gateway.set_market_data_type(mdt)
        self._note(f"行情模式 {self._mode}")

        await self._resolve_and_subscribe()

        self._running = True
        self._reconcile_task = asyncio.create_task(
            self._follower.run(
                running_flag=lambda: self._running,
                slice_provider=lambda: self._slice,
            )
        )
        self._note("行情服务已就绪")

    async def _resolve_and_subscribe(self) -> None:
        """解析标的与 0DTE 链，并建立初始订阅。"""
        underlying = await self._gateway.qualify(self._factory.underlying())
        self._gateway.subscribe_spot(underlying)
        self._router.set_spot_con_id(int(getattr(underlying, "conId", 0) or 0))

        await self._subscribe_futures()

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
        if self._follower is not None:
            self._follower.initialize(self._window, self._centre)

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

    async def _subscribe_futures(self) -> None:
        """
        订阅 ES 前月 / 次月 / 次次月，并把 ``conId → 到期日`` 交给 tick 路由。

        为什么是三个月而不是两个月
        --------------------------
        B2b 用**最近两个**未到期月份反解 ĉ。前月到期消失后，需要 (次月, 次次月)
        顶上，所以第三个是**换月余量** —— 缺了它，换月当天会只剩一个月份，
        合成直接 fail-closed 一整个交易日。

        到期日一律取 IBKR 的 ``ContractDetails.realExpirationDate``，
        **代码不推算任何日期**：硬编码"第三个周五"正是 B1 在换月日静默错值
        的同族错误。

        拿不到两个月就直接抛错、拒绝启动 —— 宁可启动失败，也不要拿冻结指数
        顶上一个看起来正常的现货（实测差 8 档）。
        """
        if not loader.as_bool(self._spot_cfg, "enabled", module=_SPOT):
            self._note(
                "现货合成已按配置关闭（config/spot.json::enabled=false）："
                "GTH 段将沿用指数，而该值可能是上一交易日收盘的冻结值",
                StatusLevel.WARN,
            )
            return

        count = loader.as_int(self._spot_cfg, "future_months", module=_SPOT)
        details = await self._gateway.fetch_future_months(
            self._factory.future(), count
        )
        if len(details) < 2:
            raise SpotUnavailableError(
                f"只枚举到 {len(details)} 个期货到期月，B2b 至少需要 2 个"
                "（前月 + 次月联立反解 carry）。GTH 段无法合成现货，"
                "拒绝启动 —— 不拿冻结指数顶上。"
            )

        mapping: dict[int, str] = {}
        for item in details:
            contract = item.contract
            expiry = str(
                getattr(item, "realExpirationDate", "")
                or getattr(contract, "lastTradeDateOrContractMonth", "")
            )
            self._gateway.subscribe_future(contract)
            mapping[int(getattr(contract, "conId", 0) or 0)] = expiry

        self._router.set_future_contracts(mapping)
        self._note(
            f"期货 {len(mapping)} 个月已订阅: "
            + ", ".join(sorted(mapping.values()))
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
    # IBKR 事件翻译
    # ------------------------------------------------------------------ #

    def _on_error(self, req_id: int, code: int, message: str, contract: Any) -> None:
        if self._error_handler is not None:
            self._error_handler.handle(req_id, code, message, contract)

    def _trigger_resubscribe(self) -> None:
        if self._resubscribe_task is None or self._resubscribe_task.done():
            self._resubscribe_task = asyncio.create_task(self._resubscribe())

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
        self._trigger_resubscribe()
        # 通知组装层"连接已重建"。L1 不认识 L3，所以这里只报告事件；
        # 要不要据此清空特征累积状态由 L6 按配置决定。
        if self._reconnect_hook is not None:
            try:
                self._reconnect_hook()
            except Exception as exc:
                self._note(f"重连钩子异常: {exc}", StatusLevel.WARN)

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
