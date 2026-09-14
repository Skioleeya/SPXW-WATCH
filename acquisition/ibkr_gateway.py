"""
L1 — IBKR 连接网关。
====================
唯一职责：管理 ``ib_async.IB`` 实例的生命周期——连接、断线重连、行情订阅原语、
以及把 IBKR 的三类事件（行情更新 / 错误 / 断连）转成回调。

本模块是 L1 中仅有的两个 import ``ib_async`` 的文件之一。上层拿到的永远是
原始 ``Ticker`` / 错误码，**不含任何业务判断**——错误码语义（哪些是限流、
哪些需要重订阅）由 ``feed_service`` 翻译。

安全设计
--------
连接一律以 ``readonly=True`` 建立。本系统只做监控，物理上不可能误下单。

出站限速桶不在本模块
--------------------
``Client`` 的滑动窗口限速桶（容量、``throttleStart`` / ``throttleEnd`` 观测）由
``acquisition.rate_limit_watch.RateLimitWatch`` 负责 —— 那是库层概念，与本模块的
"连接生命周期"不是同一个职能。这里只调用它的 ``apply()`` / ``snapshot()``。

依赖：L0、L1（``rate_limit_watch``）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Iterable, Sequence

from ib_async import IB

from config import loader
from contracts.enums import ConnectionState
from contracts.tick import RateLimitStatus
from core.errors import ConnectionFailed
from core.logging_setup import get_logger

from acquisition.rate_limit_watch import RateLimitWatch

_CFG = "ibkr"

TickerCallback = Callable[[Iterable[Any]], None]
ErrorCallback = Callable[[int, int, str, Any], None]
SimpleCallback = Callable[[], None]


class IbkrGateway:
    """``ib_async.IB`` 的薄封装。"""

    __slots__ = (
        "_host", "_port", "_client_id", "_connect_timeout",
        "_backoff_initial", "_backoff_max", "_max_attempts",
        "_generic_ticks", "_qualify_batch", "_qualify_interval", "_log",
        "_rate_limit",
        "_ib", "_state", "_on_tickers", "_on_error",
        "_on_disconnect", "_on_reconnect", "_reconnect_task", "_stop", "_attempts",
    )

    def __init__(self, ibkr_cfg: dict) -> None:
        self._host = loader.as_str(ibkr_cfg, "host", module=_CFG)
        self._port = loader.as_int(ibkr_cfg, "port", module=_CFG)
        self._client_id = loader.as_int(ibkr_cfg, "client_id", module=_CFG)
        self._connect_timeout = loader.as_float(ibkr_cfg, "connect_timeout_s", module=_CFG)
        self._backoff_initial = loader.as_float(
            ibkr_cfg, "reconnect_initial_backoff_s", module=_CFG
        )
        self._backoff_max = loader.as_float(
            ibkr_cfg, "reconnect_max_backoff_s", module=_CFG
        )
        self._max_attempts = loader.as_int(
            ibkr_cfg, "reconnect_max_attempts", module=_CFG
        )
        # generic tick list 里的 "106" 正是让 IBKR 推送 tickOptionComputation 的开关。
        self._generic_ticks = loader.as_str(
            ibkr_cfg, "generic_tick_list", module=_CFG
        )
        self._qualify_batch = loader.as_int(ibkr_cfg, "qualify_batch_size", module=_CFG)
        self._qualify_interval = loader.as_float(
            ibkr_cfg, "qualify_batch_interval_s", module=_CFG
        )
        self._log = get_logger("ibkr.gateway")
        self._rate_limit = RateLimitWatch(ibkr_cfg)
        self._ib: IB | None = None
        self._state = ConnectionState.DISCONNECTED
        self._on_tickers: TickerCallback | None = None
        self._on_error: ErrorCallback | None = None
        self._on_disconnect: SimpleCallback | None = None
        self._on_reconnect: SimpleCallback | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._stop = False
        self._attempts = 0

    # ------------------------------------------------------------------ #
    # 回调注册
    # ------------------------------------------------------------------ #

    def set_callbacks(
        self,
        *,
        on_tickers: TickerCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_disconnect: SimpleCallback | None = None,
        on_reconnect: SimpleCallback | None = None,
    ) -> None:
        self._on_tickers = on_tickers
        self._on_error = on_error
        self._on_disconnect = on_disconnect
        self._on_reconnect = on_reconnect

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return bool(self._ib is not None and self._ib.isConnected() and not self._stop)

    @property
    def ib(self) -> IB | None:
        return self._ib

    @property
    def rate_limit(self) -> RateLimitStatus:
        """
        出站限速桶快照。

        它回答的是"当前桶容量有没有成为瓶颈"：``events`` 全程为 0，说明订阅/退订
        根本没被限速拖慢。注意这与 ``SubscriptionManager`` 的 Error 300 退避是
        两回事 —— 后者是行情**行数**超限，不是消息**速率**超限。
        """
        return self._rate_limit.snapshot()

    def _set_state(self, state: ConnectionState) -> None:
        self._state = state

    # ------------------------------------------------------------------ #
    # 连接 / 断开
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """建立连接。失败抛 ``ConnectionFailed``。"""
        self._stop = False
        self._set_state(ConnectionState.CONNECTING)

        ib = IB()
        self._rate_limit.apply(ib)
        self._wire_events(ib)

        try:
            await ib.connectAsync(
                self._host,
                self._port,
                clientId=self._client_id,
                timeout=self._connect_timeout,
                readonly=True,
            )
        except Exception as exc:
            self._set_state(ConnectionState.DISCONNECTED)
            raise ConnectionFailed(
                f"无法连接 IBKR {self._host}:{self._port} (clientId={self._client_id}): {exc}。"
                "请确认客户端已启动、API 已开启、端口未被占用，并特别注意"
                "端口与客户端类型必须匹配——TWS 与 IB Gateway 使用不同的端口，"
                "对照表见 config/ibkr.json 的 _comment。"
            ) from exc

        if not ib.isConnected():
            self._set_state(ConnectionState.DISCONNECTED)
            raise ConnectionFailed(
                f"套接字已建立但 IBKR 未完成握手（{self._host}:{self._port}）。"
                "请检查客户端的 API 设置（是否允许该 host、是否勾选只读 API）"
                "以及 clientId 是否被其他会话占用。"
            )

        self._ib = ib
        self._attempts = 0
        self._set_state(ConnectionState.CONNECTED)

    async def disconnect(self) -> None:
        """主动断开并停止重连。可重入。"""
        self._stop = True
        task, self._reconnect_task = self._reconnect_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        ib, self._ib = self._ib, None
        if ib is not None:
            try:
                ib.disconnect()
            except Exception:
                pass
        self._rate_limit.close_window()
        self._set_state(ConnectionState.DISCONNECTED)

    # ------------------------------------------------------------------ #
    # 事件接线
    # ------------------------------------------------------------------ #

    def _wire_events(self, ib: IB) -> None:
        ib.pendingTickersEvent += self._handle_tickers
        ib.errorEvent += self._handle_error
        ib.disconnectedEvent += self._handle_disconnect
        # 限速桶的 throttleStart / throttleEnd 不在这里接线：IB.events 不含这两个
        # 事件，必须直接挂 ib.client —— 已由 RateLimitWatch.apply() 完成。

    def _handle_tickers(self, tickers: Iterable[Any]) -> None:
        if self._on_tickers is not None:
            try:
                self._on_tickers(tickers)
            except Exception:
                pass

    def _handle_error(self, reqId: int, errorCode: int, errorString: str, contract: Any) -> None:
        if self._on_error is not None:
            try:
                self._on_error(reqId, errorCode, errorString, contract)
            except Exception:
                pass

    def _handle_disconnect(self) -> None:
        if self._stop:
            return
        self._set_state(ConnectionState.RECONNECTING)
        if self._on_disconnect is not None:
            try:
                self._on_disconnect()
            except Exception:
                pass
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    # ------------------------------------------------------------------ #
    # 重连
    # ------------------------------------------------------------------ #

    async def _reconnect_loop(self) -> None:
        backoff = self._backoff_initial
        while not self._stop:
            if self._max_attempts and self._attempts >= self._max_attempts:
                self._set_state(ConnectionState.DISCONNECTED)
                return
            self._attempts += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, self._backoff_max)

            if self._stop:
                return
            try:
                await self.connect()
            except ConnectionFailed:
                continue

            if self._on_reconnect is not None:
                try:
                    self._on_reconnect()
                except Exception:
                    pass
            return

    # ------------------------------------------------------------------ #
    # 行情订阅原语
    # ------------------------------------------------------------------ #

    async def qualify(self, contract: Any) -> Any:
        """向 IBKR 确认合约，返回带 conId 的合约。"""
        ib = self._require_ib()
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            raise ConnectionFailed(f"合约无法被 IBKR 确认: {contract}")
        return qualified[0]

    async def qualify_many(self, contracts: Sequence[Any]) -> list[Any]:
        """
        批量确认合约。

        为什么必须做这一步
        ------------------
        ``ib_async`` 内部用 ``hash(contract)`` 索引 ticker，而 ``Contract.__hash__``
        在 ``conId == 0`` 时**直接抛 ValueError**（"Qualify contract to populate
        'conId'"）。``reqMktData`` 的第一件事就是 ``wrapper.startTicker`` →
        ``hash(contract)``，所以**未确认的合约根本订阅不了**。

        因此期权合约在订阅前必须经过这里回填 conId。``qualifyContractsAsync``
        会原地更新传入对象，返回值与输入**等长**、失败位为 ``None``。

        按 ``qualify_batch_size`` 分批是必要的：一次性并发几十上百个
        ``reqContractDetails`` 会触发 IBKR 的每秒消息数限流。
        """
        ib = self._require_ib()
        items = list(contracts)
        if not items:
            return []

        batch_size = max(self._qualify_batch, 1)
        interval = self._qualify_interval
        out: list[Any] = []

        for start in range(0, len(items), batch_size):
            chunk = items[start:start + batch_size]
            try:
                results = await ib.qualifyContractsAsync(*chunk)
            except Exception as exc:
                self._log.warning("批量确认合约失败（第 %d 批，%d 条）: %s",
                                  start // batch_size + 1, len(chunk), exc)
                out.extend([None] * len(chunk))
                continue
            # 等长对齐：正常返回时长度一致，异常时补齐，避免与调用方错位。
            results = list(results)
            if len(results) < len(chunk):
                results.extend([None] * (len(chunk) - len(results)))
            out.extend(results[:len(chunk)])
            if interval > 0 and start + batch_size < len(items):
                await asyncio.sleep(interval)

        return out

    def set_market_data_type(self, market_data_type: int) -> None:
        self._require_ib().reqMarketDataType(int(market_data_type))

    async def fetch_chain(
        self,
        symbol: str,
        sec_type: str,
        exchange: str,
        con_id: int,
    ) -> list[Any]:
        """请求期权链参数（``reqSecDefOptParams``）。"""
        ib = self._require_ib()
        return list(
            await ib.reqSecDefOptParamsAsync(symbol, "", sec_type, int(con_id))
        )

    async def fetch_future_months(self, contract: Any, count: int) -> list[Any]:
        """
        枚举期货可交易月份，取**最近**的 ``count`` 个（按到期月升序）。

        返回 ``ContractDetails`` 对象本身，而不是 ``Contract`` —— 调用方要从它
        取 ``realExpirationDate``（精度到日），那是 ``ContractDetails`` 上的字段；
        ``Contract.lastTradeDateOrContractMonth`` 在部分合约上只到月。

        实测（2026-09-14，ES/CME）：不带月份请求会返回**全部**可交易月份
        （21 条，远月到 2028-12），每条都带 conId 与 ``realExpirationDate``。
        因此拿到即可直接订阅，**无需再 qualify**。

        只保留有 conId 的条目：没有 conId 的合约在 ``ib_async`` 里连 ``hash()``
        都过不了，订阅必然失败（见 ``qualify_many`` 的说明）。
        """
        ib = self._require_ib()
        details = list(await ib.reqContractDetailsAsync(contract))
        dated = [
            item for item in details
            if int(getattr(item.contract, "conId", 0) or 0) > 0
        ]
        dated.sort(
            key=lambda item: str(
                getattr(item.contract, "lastTradeDateOrContractMonth", "")
            )
        )
        return dated[: max(int(count), 0)]

    def subscribe_spot(self, contract: Any, generic_ticks: str = "") -> Any:
        """订阅标的现价。"""
        return self._require_ib().reqMktData(contract, generic_ticks, False, False)

    def subscribe_future(self, contract: Any) -> Any:
        """
        订阅一条期货行情。

        与 ``subscribe_spot`` 的差别只在语义与 generic ticks：期货不需要
        ``tickOptionComputation``（那是期权的），传空串即可，省掉无谓的消息量。
        实测（2026-09-14）ES 前月订阅后 ``marketPrice()`` 与 bid/ask 均正常。
        """
        return self._require_ib().reqMktData(contract, "", False, False)

    def subscribe_option(self, contract: Any) -> Any:
        """
        订阅单个期权。

        ``generic_ticks`` 由调用方传入（配置里的 ``"106"``），它正是让 IBKR
        推送 ``tickOptionComputation``（含 MODEL_OPTION）的开关。
        """
        return self._require_ib().reqMktData(
            contract, self._generic_ticks, False, False
        )

    def cancel_option(self, contract: Any) -> None:
        self._require_ib().cancelMktData(contract)

    def _require_ib(self) -> IB:
        if self._ib is None or not self._ib.isConnected():
            raise ConnectionFailed("IBKR 连接不可用，操作被拒绝。")
        return self._ib
