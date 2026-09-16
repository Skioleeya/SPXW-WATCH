"""
L0 — Tick 与合约的数据传输对象。
=================================
本模块是 L2（采集）与 L3（状态）之间的通信契约，并集中承载本工程的 DTO
词汇表。其中 ``FutureTick`` 属于 **L2 内部**的中间量，不进 ``TickSink``
（理由见其自身文档）；其余类型都是跨层契约。

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

        放在 DTO 上而不是放在 L2，是为了让采集层与离线夹具共用同一套解析规则；
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


@dataclass(frozen=True, slots=True)
class FutureTick:
    """
    一条指数期货报价（按到期月）。

    为什么它**不在** ``TickSink`` 协议里
    ------------------------------------
    ``TickSink`` 是 L2 → L3 的出口；而期货价是 **L2 内部**的中间量 —— 它唯一的
    用途是在 GTH 时段合成现货基准（``acquisition.spot_synthesis``），状态层与
    下游完全不需要知道它。把它塞进 ``TickSink`` 会强迫 ``TickStore`` 实现一个
    自己永远用不上的方法，还会让 L3 无端认识"期货"这个与它无关的概念。

    因此本类型只由 ``acquisition.tick_router`` 产出、由 ``acquisition.spot_source``
    消费，走**显式注入**的 ``future_sink``，而不是主 sink 链。

    ``expiry`` 必须来自 IBKR（``ContractDetails.realExpirationDate``），
    不得由代码推算 —— B2b 的 ``T`` 直接依赖它。
    """

    expiry: str  # "YYYYMMDD"
    price: float
    ts: float


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
class RateLimitStatus:
    """
    出站消息限速桶的可观测状态。

    桶本身住在 ``ib_async`` 的 ``Client`` 里（滑动窗口：每 ``interval_s`` 秒最多
    ``capacity`` 条出站消息）。这里只**观测**，不另建一个桶 —— 库是唯一的限流者；
    本系统若自己再放一个桶，两个桶互相不知情，容量对不上时反而更容易撞上
    IBKR 的 Error 100（3 次违约即终止 API 会话）。

    ``events`` / ``throttled_total_s`` 来自 ``Client.throttleStart`` /
    ``throttleEnd``。它们回答的是同一个问题：当前这个容量到底有没有成为瓶颈。
    全程为 0，就说明订阅/退订根本没被限速拖慢，容量是宽的。
    """

    capacity: int = 0
    interval_s: float = 0.0
    events: int = 0
    throttling: bool = False
    throttled_total_s: float = 0.0


@dataclass(frozen=True, slots=True)
class FeedStatus:
    """
    采集层的整体健康快照。

    这里有两个名字里都带"限流"的读数，含义完全不同，不要混：``rate_limit`` 是
    库层**出站消息桶**（msg/s），``sub_limit_backoff`` 是 IBKR 的 **Error 300
    退避开关**（行情行数超限）。二者此前共用 ``throttled`` 一个名字，排查时
    极易张冠李戴。
    """

    mode: FeedMode = FeedMode.UNKNOWN
    connection: ConnectionState = ConnectionState.DISCONNECTED
    subscribed: int = 0
    subscription_cap: int = 0
    ticks_received: int = 0
    ticks_dropped: int = 0
    rate_limit: RateLimitStatus = field(default_factory=RateLimitStatus)
    sub_limit_backoff: bool = False
    expiry: str = ""
    spot: float = 0.0
    messages: tuple[str, ...] = field(default_factory=tuple)
