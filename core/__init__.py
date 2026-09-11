"""
L0 — 通用基元层。

本包提供与业务无关的基础设施：环形缓冲、会话时钟、日志装配、异常分类。
**不 import 项目内任何其他包**，也不读取配置（配置由上层注入）。
"""

from core.clock import SessionClock, WallClock, minutes_of_day, now_ts, parse_hm
from core.errors import (
    AcquisitionError,
    ChainResolveError,
    ConnectionFailed,
    ContractResolveError,
    FeatureError,
    InsufficientHistory,
    SerializationError,
    SkewUndefined,
    SpotUnavailableError,
    StateError,
    StoreNotReady,
    SubscriptionLimitExceeded,
    SubscriptionThrottled,
    SwatchError,
    TransportError,
)
from core.logging_setup import configure, get_logger
from core.ring_buffer import RingBuffer, Sample

__all__ = [
    "AcquisitionError",
    "ChainResolveError",
    "ConnectionFailed",
    "ContractResolveError",
    "FeatureError",
    "InsufficientHistory",
    "RingBuffer",
    "Sample",
    "SerializationError",
    "SessionClock",
    "SkewUndefined",
    "SpotUnavailableError",
    "StateError",
    "StoreNotReady",
    "SubscriptionLimitExceeded",
    "SubscriptionThrottled",
    "SwatchError",
    "TransportError",
    "WallClock",
    "configure",
    "get_logger",
    "minutes_of_day",
    "now_ts",
    "parse_hm",
]
