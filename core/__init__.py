"""
L1 — 通用基元层。

本包提供与业务无关的基础设施：环形缓冲、会话时钟、日志装配、异常分类。
**不 import 项目内任何其他包**（``contracts/`` 除外 —— 它也是 L0/L1 的无逻辑层），
也不读取配置（配置由上层注入）。
"""

from core.clock import SessionClock, WallClock, monotonic, now_ts
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
    SurfaceFitError,
    SurfaceModelError,
    SwatchError,
    TransportError,
)
from core.logging_setup import configure, get_logger
from core.ring_buffer import RingBuffer, Sample
from core.session_grid import build_zones, fmt_hm, minutes_of_day, parse_hm

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
    "SurfaceFitError",
    "SurfaceModelError",
    "SwatchError",
    "TransportError",
    "WallClock",
    "build_zones",
    "configure",
    "fmt_hm",
    "get_logger",
    "minutes_of_day",
    "monotonic",
    "now_ts",
    "parse_hm",
]
