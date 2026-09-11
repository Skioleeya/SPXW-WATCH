"""
L0 — Tick 与合约的数据传输对象。
=================================
本模块是 L1（采集）与 L2（状态）之间**唯一**的通信契约。

为什么单独放一层
----------------
如果 ``state`` 直接 import ``acquisition`` 的类，就出现了跨层耦合；如果
``acquisition`` 反向 import ``state``，就是反向依赖。把双方都要用的结构
下沉到 L0，两边都只依赖 L0，依赖方向天然单向。

所有类型都是 ``frozen + slots`` 的不可变对象：跨线程/跨协程传递时不需要
加锁，也不可能被下游偷偷改写。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.enums import ConnectionState, FeedMode, OptionRight, StatusLevel

# --------------------------------------------------------------------------- #
# 合约标识
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OptionRef:
    """一个期权合约的身份。可哈希，可直接做字典键。"""

    strike: float
    right: OptionRight
    expiry: str

    def key(self) -> tuple[float, str]:
        return (self.strike, str(self.right))

    def label(self) -> str:
        return f"{self.expiry} {self.strike:g}{self.right}"

    @staticmethod
    def from_contract(contract: object) -> "OptionRef | None":
        """
        从 IBKR 合约对象还原 ``OptionRef``（鸭子类型，不需要 import ib_async）。

        放在 DTO 上而不是放在 L1，是为了让采集层与模拟层共用同一套解析规则；
        否则两处各写一份，迟早会分叉。
        """
        try:
            strike = float(getattr(contract, "strike"))
            right_raw = str(getattr(contract, "right")).strip().upper()
            expiry = str(getattr(contract, "lastTradeDateOrContractMonth")).strip()
        except (AttributeError, TypeError, ValueError):
            return None

        if strike <= 0 or not expiry:
            return None

        # 部分合约会把到期日补成带时分秒的完整格式，只取前 8 位。
        if len(expiry) > 8:
            expiry = expiry[:8]

        if right_raw not in ("P", "C"):
            return None

        return OptionRef(strike=strike, right=OptionRight(right_raw), expiry=expiry)


@dataclass(frozen=True, slots=True)
class ChainSlice:
    """解析出来的 0DTE 期权链切片。"""

    expiry: str
    trading_class: str
    strikes: tuple[float, ...]
    multiplier: str
    exchange: str
    underlying_con_id: int


# --------------------------------------------------------------------------- #
# Tick
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OptionTick:
    """
    单个期权的模型隐含波动率与 Greeks。

    来源严格限定为 IBKR 通过 generic tick ``106`` 推送的 ``tickOptionComputation``，
    且 ``source_tick_type == 13``（MODEL_OPTION）。本系统**不在本地用 BSM 重算**。
    """

    ref: OptionRef
    iv: float
    ts: float
    delta: float | None = None
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None
    opt_price: float | None = None
    und_price: float | None = None
    source_tick_type: int = 13
    model_greeks: bool = True
    con_id: int = 0

    @property
    def is_model_tick(self) -> bool:
        return self.source_tick_type == 13 and self.model_greeks


@dataclass(frozen=True, slots=True)
class QuoteTick:
    """期权买卖盘快照，用于盘口质量评估与毛刺过滤。"""

    ref: OptionRef
    ts: float
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    close: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    last_size: int | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    @property
    def is_valid(self) -> bool:
        if self.bid is None or self.ask is None:
            return False
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid


@dataclass(frozen=True, slots=True)
class SpotTick:
    """标的现价。"""

    price: float
    ts: float
    tick_type: int = 0


# --------------------------------------------------------------------------- #
# 状态事件
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """采集层向上层汇报的连接/订阅/限流事件。"""

    level: StatusLevel
    source: str
    message: str
    ts: float
    code: int = 0

    @staticmethod
    def info(source: str, message: str, ts: float, code: int = 0) -> "StatusEvent":
        return StatusEvent(StatusLevel.INFO, source, message, ts, code)

    @staticmethod
    def warn(source: str, message: str, ts: float, code: int = 0) -> "StatusEvent":
        return StatusEvent(StatusLevel.WARN, source, message, ts, code)

    @staticmethod
    def error(source: str, message: str, ts: float, code: int = 0) -> "StatusEvent":
        return StatusEvent(StatusLevel.ERROR, source, message, ts, code)


@dataclass(frozen=True, slots=True)
class FeedStatus:
    """采集层的整体健康快照。"""

    mode: FeedMode = FeedMode.UNKNOWN
    connection: ConnectionState = ConnectionState.DISCONNECTED
    subscribed: int = 0
    subscription_cap: int = 0
    ticks_received: int = 0
    ticks_dropped: int = 0
    throttled: bool = False
    expiry: str = ""
    spot: float = 0.0
    messages: tuple[str, ...] = field(default_factory=tuple)

    def with_message(self, message: str, limit: int = 6) -> "FeedStatus":
        kept = (self.messages + (message,))[-limit:]
        return FeedStatus(
            mode=self.mode,
            connection=self.connection,
            subscribed=self.subscribed,
            subscription_cap=self.subscription_cap,
            ticks_received=self.ticks_received,
            ticks_dropped=self.ticks_dropped,
            throttled=self.throttled,
            expiry=self.expiry,
            spot=self.spot,
            messages=kept,
        )
