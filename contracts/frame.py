"""
L0 — 推送帧结构。
==================
L6（序列化）产出、L7（传输）广播、前端消费的顶层对象。

这一层刻意做成"自包含的只读快照"：一旦构造完成，内容不再变化。传输层可以
随便拿去排队、丢弃、重发，都不会影响 L2–L5 的实时计算 —— 这正是需求里
"图形渲染或前端卡顿绝不影响后台底层连接稳定性"（fail-closed）的结构基础。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.enums import ConnectionState, FeedMode
from contracts.feature import (
    AtmSnapshot,
    HeatmapMatrix,
    ImpulseCell,
    SkewPoint,
    SurfaceSummary,
)
from contracts.tick import RateLimitStatus


@dataclass(frozen=True, slots=True)
class SessionZone:
    """
    交易日网格里的一个区段。

    ``is_session=True`` 是一个真实会话（GTH / RTH），``False`` 是两个会话之间的
    **空档**（例如 GTH 收盘 09:25 → RTH 开盘 09:30）。空档里没有任何行情，
    前端在「全时段」视图里把它整段丢掉 —— 这就是"隐藏 5 分钟空档"的落点。

    ``first`` / ``last`` 是区段覆盖的桶序号区间（含两端），由 L1 的
    ``SessionClock`` 按会话定义算出。前端只按这两个数切列，**不自己推算时刻**：
    让它自己算就等于把网格几何抄了第二份。
    """

    id: str = ""
    label: str = ""
    is_session: bool = True
    first: int = 0
    last: int = 0
    open: str = ""
    close: str = ""


@dataclass(frozen=True, slots=True)
class SessionBlock:
    """
    会话坐标。

    ⚠️ ``bucket_index`` 是**时间读数**（``bucket_index_of_ts(now)``），
    不是矩阵列数。重写后的契约里两者恰好相等（矩阵只含已走满的桶，
    列数 = ``bucket_index``），但**不要依赖这个巧合** —— 进度条读的是这个字段。
    """

    date: str = ""
    expiry: str = ""
    open: str = ""
    close: str = ""
    is_open: bool = False
    elapsed_s: float = 0.0
    seconds_to_close: float = 0.0
    bucket_index: int = 0
    bucket_count: int = 0
    zones: tuple[SessionZone, ...] = ()


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

    ``skew`` 与 ``skew_series`` 的区别（**别合并，也别用序列末项代替前者**）
    ------------------------------------------------------------------
    * ``skew`` 是**实时**读数（本轮 ``compute()`` 刚算出来的那一个点）。
    * ``skew_series`` 只含**已走满的桶**（见 ``ARCHITECTURE.md §8``），
      因此它的末项最多可能比 ``skew`` 旧一整个桶（30 s）。

    折线图必须画序列（已走满的桶才定稿，否则最后一个点在桶内持续抖动）；
    顶部读数必须用 ``skew``（否则现价一动、读数要等半分钟才跟上）。
    两者是**不同的语义**，不是"同一个东西的两种取法"。
    """

    seq: int
    ts: float
    spot: float
    session: SessionBlock
    health: HealthBlock
    heatmap: HeatmapMatrix | None = None
    skew: SkewPoint | None = None
    skew_series: tuple[SkewPoint, ...] = ()
    cells: tuple[ImpulseCell, ...] = ()
    atm: AtmSnapshot | None = None
    surface: SurfaceSummary | None = None

    def summary(self) -> str:
        cells = len(self.cells)
        rows = self.heatmap.rows() if self.heatmap else 0
        surface = self.surface.model_name if self.surface else "-"
        return (
            f"seq={self.seq} spot={self.spot:.2f} cells={cells} "
            f"heatmap={rows}x{self.heatmap.cols() if self.heatmap else 0} "
            f"skew_pts={len(self.skew_series)} surface={surface}"
        )
