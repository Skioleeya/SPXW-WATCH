"""
L0 — 层间契约层。

本包只包含**不可变数据结构**与**结构接口（Protocol）**，不含任何逻辑、
不读配置、不 import 项目内其他包。

分层的核心思想
--------------
* ``tick.py``     L1 → L2 的载荷
* ``feature.py``  L3 → L4 的载荷
* ``frame.py``    L4 → L5 的载荷
* ``ports.py``    各层之间互相通信所用的接口

只要层与层之间只通过本包通信，依赖方向就永远是单向的，也不可能出现循环引用。
"""

from contracts.enums import (
    TRUSTWORTHY_QUALITIES,
    ConnectionState,
    FeedMode,
    OptionRight,
    Quality,
    StatusLevel,
    SubscriptionAction,
)
from contracts.feature import (
    AtmSnapshot,
    FeatureBundle,
    HeatmapMatrix,
    ImpulseCell,
    SkewPoint,
    WindowDelta,
)
from contracts.frame import Frame, HealthBlock, SessionBlock
from contracts.ports import (
    ClockPort,
    FeedPort,
    FrameSink,
    FrameSource,
    PayloadSource,
    TickSink,
)
from contracts.tick import (
    ChainSlice,
    FeedStatus,
    OptionRef,
    OptionTick,
    QuoteTick,
    RateLimitStatus,
    SpotTick,
    StatusEvent,
)

__all__ = [
    "AtmSnapshot",
    "ChainSlice",
    "ClockPort",
    "ConnectionState",
    "FeatureBundle",
    "FeedMode",
    "FeedPort",
    "FeedStatus",
    "Frame",
    "FrameSink",
    "FrameSource",
    "HealthBlock",
    "HeatmapMatrix",
    "ImpulseCell",
    "OptionRef",
    "OptionRight",
    "OptionTick",
    "PayloadSource",
    "Quality",
    "QuoteTick",
    "RateLimitStatus",
    "SessionBlock",
    "SkewPoint",
    "SpotTick",
    "StatusEvent",
    "StatusLevel",
    "SubscriptionAction",
    "TRUSTWORTHY_QUALITIES",
    "TickSink",
    "WindowDelta",
]
