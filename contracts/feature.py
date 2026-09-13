"""
L0 — 特征层输出对象。
======================
L3（特征）算完之后交给 L4（序列化）的东西。放在 L0 的理由同 ``tick.py``：
让 L4 不必 import L3 的实现细节。

单位约定（全系统统一，不允许各处各表）
---------------------------------------
* ``iv`` / ``atm_iv`` / ``put25_iv`` / ``call25_iv`` —— **小数**，0.14 表示 14%。
* 任何带 ``vol_points`` 后缀的字段 —— **波动率点**，1.0 表示 1 个波动率点
  （即 IV 变动 0.01）。
* 任何带 ``impulse`` 的字段 —— **波动率点 / 分钟**。
* ``delta`` —— 券商推送的原始 Delta，不做本地重算。
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.enums import OptionRight, Quality
from contracts.tick import OptionRef

@dataclass(frozen=True, slots=True)
class WindowDelta:
    """
    某个回看窗口上的 IV 变化。

    ``seconds`` 由配置决定（``features.json`` 的 ``impulse_windows_seconds``），
    因此这里用结构而不是 ``iv_1m`` / ``iv_5m`` 这种写死字段名——窗口长度一旦
    调整，字段名就会对不上。
    """

    seconds: int
    iv_ago: float
    delta_vol_points: float     # (当前 IV − 窗口前 IV) × 100
    impulse_per_min: float      # delta_vol_points / (seconds / 60)


@dataclass(frozen=True, slots=True)
class ImpulseCell:
    """一个网格点（行权价 × OTM 方向）的当前 IV 与动能。"""

    ref: OptionRef
    iv: float
    quality: Quality
    age_s: float
    ts: float
    delta: float | None = None
    opt_price: float | None = None
    windows: tuple[WindowDelta, ...] = ()

    @property
    def strike(self) -> float:
        return self.ref.strike

    @property
    def right(self) -> OptionRight:
        return self.ref.right

    def primary_impulse(self) -> float | None:
        """取最短回看窗口的冲量；没有可用窗口时返回 ``None``。"""
        if not self.windows:
            return None
        return min(self.windows, key=lambda w: w.seconds).impulse_per_min

    def impulse_for(self, seconds: int) -> float | None:
        for window in self.windows:
            if window.seconds == seconds:
                return window.impulse_per_min
        return None


@dataclass(frozen=True, slots=True)
class SkewPoint:
    """
    某一时刻的 25Δ 偏度快照。前端折线图的单个点。

    ``skew_25d_vol_points`` 即市场惯称的 25Δ 风险反转（Risk Reversal）：
    25Δ Put IV 减 25Δ Call IV，单位波动率点。正值代表下行保护更贵。
    """

    ts: float
    spot: float
    atm_iv: float | None = None
    put25_iv: float | None = None
    call25_iv: float | None = None
    put25_strike: float | None = None
    call25_strike: float | None = None
    put25_delta: float | None = None
    call25_delta: float | None = None
    skew_25d_vol_points: float | None = None   # put25_iv − call25_iv，单位波动率点
    butterfly_vol_points: float | None = None  # (put25 + call25)/2 − atm
    quality: Quality = Quality.MISSING

    @property
    def is_defined(self) -> bool:
        return self.skew_25d_vol_points is not None


@dataclass(frozen=True, slots=True)
class HeatmapMatrix:
    """
    2D 日内动能矩阵。

    * 纵轴 ``strikes``：以现价为中心的窗口，**降序**（行权价高的在前）。
      行序由 ``HeatmapEngine.build()`` 的产出点保证，不依赖上游窗口的顺序；
      与屏幕自上而下的方向一致（前端 ``yAxis.inverse``）。
    * 横轴 ``bucket_labels``：会话时间桶，从开盘到收盘。
    * ``values[i][j]``：第 i 个行权价、第 j 个时间桶的 ΔIV（波动率点）。
    * ``volumes[i][j]``：同一格的 tick 计数（None 表示无数据）。
      用于前端「成交量加权」视觉层 —— tick 数多 = 圆点大。

    每个行权价只取 OTM 一侧（行权价 < 现价取 Put，否则取 Call），
    这样一张矩阵就能完整呈现 0DTE 微笑的两翼，无需再拆成两张图。
    """

    strikes: tuple[float, ...]
    rights: tuple[OptionRight, ...]
    bucket_labels: tuple[str, ...]
    values: tuple[tuple[float | None, ...], ...]
    bucket_index: int
    spot: float
    volumes: tuple[tuple[int | None, ...], ...] = ()

    def rows(self) -> int:
        return len(self.strikes)

    def cols(self) -> int:
        return len(self.bucket_labels)

    def filled_cells(self) -> int:
        return sum(1 for row in self.values for cell in row if cell is not None)


@dataclass(frozen=True, slots=True)
class AtmSnapshot:
    """现价附近的即时状态，用于前端顶部读数。"""

    spot: float
    atm_strike: float | None = None
    atm_iv: float | None = None
    atm_delta: float | None = None
    straddle_price: float | None = None
    put25_iv: float | None = None
    call25_iv: float | None = None
    skew_25d_vol_points: float | None = None
    butterfly_vol_points: float | None = None
    ts: float = 0.0


@dataclass(frozen=True, slots=True)
class FeatureBundle:
    """
    L3 一轮计算的完整产出。

    L4 拿到它之后只需要加健康信息就能组装成推送帧，不必再回头调用 L3 的任何方法。
    """

    ts: float
    spot: float
    cells: tuple[ImpulseCell, ...] = ()
    heatmap: HeatmapMatrix | None = None
    skew: SkewPoint | None = None
    skew_series: tuple[SkewPoint, ...] = ()
    atm: AtmSnapshot | None = None
    quality_ok: int = 0
    quality_flagged: int = 0

    def is_empty(self) -> bool:
        return not self.cells and self.heatmap is None
