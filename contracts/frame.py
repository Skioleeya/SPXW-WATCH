"""
L0 — 推送帧结构。
==================
L4（序列化）产出、L5（传输）广播、前端消费的顶层对象。

这一层刻意做成"自包含的只读快照"：一旦构造完成，内容不再变化。传输层可以
随便拿去排队、丢弃、重发，都不会影响 L1–L3 的实时计算——这正是需求里
"图形渲染或前端卡顿绝不影响后台底层连接稳定性"（fail-closed）的结构基础。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.enums import ConnectionState, FeedMode
from contracts.feature import AtmSnapshot, HeatmapMatrix, ImpulseCell, SkewPoint
from contracts.tick import RateLimitStatus


@dataclass(frozen=True, slots=True)
class SessionBlock:
    """会话坐标。"""

    date: str = ""
    expiry: str = ""
    open: str = ""
    close: str = ""
    is_open: bool = False
    elapsed_s: float = 0.0
    seconds_to_close: float = 0.0
    bucket_index: int = 0
    bucket_count: int = 0


@dataclass(frozen=True, slots=True)
class HealthBlock:
    """
    系统健康读数，前端顶栏直接显示。

    ``rate_limit`` 与 ``sub_limit_backoff`` 是两个不同层面的限流读数，命名刻意
    不共用 "throttled" —— 前者是 ``ib_async`` 出站消息桶（msg/s），后者是 IBKR
    Error 300（行情行数超限）的退避开关。
    """

    mode: FeedMode = FeedMode.UNKNOWN
    connection: ConnectionState = ConnectionState.DISCONNECTED
    subscribed: int = 0
    subscription_cap: int = 0
    ticks_received: int = 0
    ticks_dropped: int = 0
    store_cells: int = 0
    last_tick_age_s: float | None = None
    rate_limit: RateLimitStatus = field(default_factory=RateLimitStatus)
    sub_limit_backoff: bool = False
    messages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Frame:
    """
    一次推送的完整载荷。

    ``seq`` 单调递增，前端可据此检测丢帧；``ts`` 是产出该帧的时间戳。
    """

    seq: int
    ts: float
    spot: float
    session: SessionBlock
    health: HealthBlock
    heatmap: HeatmapMatrix | None = None
    skew_series: tuple[SkewPoint, ...] = ()
    cells: tuple[ImpulseCell, ...] = ()
    atm: AtmSnapshot | None = None

    def summary(self) -> str:
        cells = len(self.cells)
        rows = self.heatmap.rows() if self.heatmap else 0
        return (
            f"seq={self.seq} spot={self.spot:.2f} cells={cells} "
            f"heatmap={rows}x{self.heatmap.cols() if self.heatmap else 0} "
            f"skew_pts={len(self.skew_series)}"
        )
