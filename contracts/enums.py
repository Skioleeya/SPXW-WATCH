"""
L0 — 枚举与常量字面量。
========================
全部使用 ``StrEnum``，保证序列化成 JSON 时得到的是裸字符串（``"P"``）
而不是 ``"OptionRight.PUT"``，避免 L6 层再做一次翻译。
"""

from __future__ import annotations

from enum import StrEnum


class OptionRight(StrEnum):
    """期权方向。值与 IBKR 合约的 ``right`` 字段一致。"""

    PUT = "P"
    CALL = "C"

    @property
    def opposite(self) -> "OptionRight":
        return OptionRight.CALL if self is OptionRight.PUT else OptionRight.PUT


class FeedMode(StrEnum):
    """行情来源模式，用于前端标注与健康面板。

    取值一一对应 IBKR 的 ``marketDataType``，由
    ``from_market_data_type`` 翻译；``UNKNOWN`` 覆盖未知取值。
    """

    LIVE = "live"
    DELAYED = "delayed"
    FROZEN = "frozen"
    DELAYED_FROZEN = "delayed_frozen"
    UNKNOWN = "unknown"

    @staticmethod
    def from_market_data_type(mdt: int) -> "FeedMode":
        return {
            1: FeedMode.LIVE,
            2: FeedMode.FROZEN,
            3: FeedMode.DELAYED,
            4: FeedMode.DELAYED_FROZEN,
        }.get(int(mdt), FeedMode.UNKNOWN)


class ConnectionState(StrEnum):
    """与 TWS / IB Gateway 的会话状态。"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"


class Quality(StrEnum):
    """单个网格点的可信度标签。"""

    OK = "ok"
    STALE = "stale"
    GLITCH = "glitch"
    NO_HISTORY = "no_history"
    MISSING = "missing"


#: 允许写入热力图与参与 Skew 计算的质量标签。
#:
#: 这个判断**必须只有一处定义**。曾经它在特征编排器、热力图引擎、Skew 引擎里
#: 各写了一遍，结果后两者漏掉了 ``GLITCH`` —— 毛刺过滤器辛苦拦下来的分母效应
#: 尖峰，转头就被写进了矩阵（实测能到 32 个波动率点）。语义上：
#:
#: * ``OK``      —— 正常，照写。
#: * ``STALE``   —— 数据旧但仍然真实，写进去只会得到 0 变化，语义诚实。
#: * ``GLITCH``  —— 数值不可信，**必须排除**，否则整张图会出现假信号。
#: * ``MISSING`` / ``NO_HISTORY`` —— 没有可用数值。
TRUSTWORTHY_QUALITIES = frozenset({Quality.OK, Quality.STALE})


class StatusLevel(StrEnum):
    """状态事件严重度。"""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class SubscriptionAction(StrEnum):
    """订阅协调器对单个合约的处置动作。"""

    KEEP = "keep"
    ADD = "add"
    DROP = "drop"


class SurfaceModelName(StrEnum):
    """可用曲面模型。

    值与 ``config/surface.json::active_model`` 一致 —— 配置里写字符串，
    本层负责把它翻译成枚举并 fail fast（写错名字要立刻报错，不能静默退回 Raw）。
    """

    RAW = "RawSurface"
    SVI = "SVI"
    SSVI = "SSVI"

    @staticmethod
    def parse(value: str) -> "SurfaceModelName":
        try:
            return SurfaceModelName(value)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in SurfaceModelName)
            raise ValueError(
                f"未知曲面模型 {value!r}，可选：{allowed}"
            ) from exc
