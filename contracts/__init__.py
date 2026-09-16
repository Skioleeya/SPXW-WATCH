"""
L0 — 层间契约层。

本包只包含**不可变数据结构**与**结构接口（Protocol）**，不含任何逻辑、
不读配置、不 import 项目内其他包。

分层的核心思想
--------------
* ``tick.py``     L2 → L3 的载荷
* ``feature.py``  L5 → L6 的载荷（含曲面模型的输出契约）
* ``frame.py``    L6 → L7 的载荷
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
    SurfaceModelName,
)
from contracts.feature import (
    AtmSnapshot,
    FeatureBundle,
    HeatmapMatrix,
    ImpulseCell,
    SkewPoint,
    SurfaceResidual,
    SurfaceSummary,
    WindowDelta,
)
from contracts.frame import Frame, HealthBlock, SessionBlock, SessionZone
from contracts.ports import (
    ClockPort,
    FeedPort,
    FrameSink,
    FrameSource,
    PayloadSource,
    SurfaceInputPort,
    SurfaceModelPort,
    TickSink,
)
from contracts.tick import (
    ChainSlice,
    FeedStatus,
    FutureTick,
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
    "FutureTick",
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
    "SessionZone",
    "SkewPoint",
    "SpotTick",
    "StatusEvent",
    "StatusLevel",
    "SubscriptionAction",
    "SurfaceInputPort",
    "SurfaceModelName",
    "SurfaceModelPort",
    "SurfaceResidual",
    "SurfaceSummary",
    "TRUSTWORTHY_QUALITIES",
    "TickSink",
    "WindowDelta",
]
