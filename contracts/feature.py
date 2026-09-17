"""
L0 — 特征层输出对象。
======================
L5（特征）算完之后交给 L6（序列化）的东西。放在 L0 的理由同 ``tick.py``：
让 L6 不必 import L5 的实现细节。

单位约定（全系统统一，不允许各处各表）
---------------------------------------
* ``iv`` / ``atm_iv`` / ``put25_iv`` / ``call25_iv`` —— **小数**，0.14 表示 14%。
* 任何带 ``vol_points`` 后缀的字段 —— **波动率点**，1.0 表示 1 个波动率点
  （即 IV 变动 0.01）。
* 任何带 ``impulse`` 的字段 —— **波动率点 / 分钟**。
* ``delta`` —— 券商推送的原始 Delta，不做本地重算。

⚠️ **本模块不得出现 numpy / pandas 类型**。曲面模型层（L4）内部用 DataFrame，
但跨层传出的必须是本模块定义的普通 dataclass —— 否则 numpy/pandas 会顺着
类型标注漏到 L5–L8，第 0 节那条"只允许 models/ 用数值库"的决策就废了。
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
    因此这里用结构而不是 ``iv_1m`` / ``iv_5m`` 这种写死字段名 —— 窗口长度一旦
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
      用于前端「成交量加权」视觉层 —— **tick 数越多，该格黑色边框越粗**
      （颜色恒定，粗细是唯一编码维度）。数据源唯一：**30 秒桶**；
      更粗的显示周期由 ``web/period.js::aggregate`` 在组内求和，不另取数据。
      前端消费点在 ``web/heatmap.js::buildOption``，参数在
      ``web/config.js::heatmap.volumeBorder``。

    **列数契约（2026-09-15 重写）**：``cols() == bucket_index``。
    矩阵**只含已走满的桶**（列取 ``0 .. current-1``）—— 正在走的那一桶尚未定稿，
    不得出列。理由与代价见 `notes/memory/ARCHITECTURE.md §8`。

    每个行权价只取 OTM 一侧（行权价 < 现价取 Put，否则取 Call），
    这样一张矩阵就能完整呈现 0DTE 微笑的两翼，无需再拆成两张图。

    **行数契约：画多、看少**（2026-09-16 定）
    ----------------------------------------
    ``strikes`` 有 ``2 × heatmap_draw_rows_each_side`` 行（当前 40），而屏幕上
    只显示其中 ``2 × visible_rows_each_side`` 行（当前 24）。两个半径都是
    **后端**配置（``config/features.json``），随帧一起下发，前端不再抄一份 ——
    抄了就是两份真相。

    为什么"可视半径"必须随帧走、不能放前端配置：它与**订阅**窗口有物理耦合。
    可视档必须始终落在订阅窗口之内（否则现价一走就退订正在看的档，行权价轴上
    留下时间空洞），所以它是一条跨模块约束，必须由后端的门禁守着。
    三条不变量见 ``config/features.json::_heatmap_window_comment``。

    为什么"画 40 只露 24"：现价移动时可视窗口要跟着移。可视区之外若没有**已画好**
    的行，窗口移出去的瞬间那几行是空的（要等下一帧才有数据）；先画满 40 行、只挪
    可视窗口，露出来的就是现成数据。代价是多算 16 行（CPU 与带宽），
    收益是移动时不闪不空。
    """

    strikes: tuple[float, ...]
    rights: tuple[OptionRight, ...]
    bucket_labels: tuple[str, ...]
    values: tuple[tuple[float | None, ...], ...]
    bucket_index: int
    spot: float
    volumes: tuple[tuple[int | None, ...], ...] = ()
    #: 可视窗口半径（档）。0 = 未设定 ⇒ 前端应当**报错并保留上一帧**，
    #: 而不是"画满全部行"顶上 —— 那会让"配置没接线"表现成一个看起来正常的图。
    visible_rows_each_side: int = 0

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


# --------------------------------------------------------------------------- #
# 曲面模型层（L4）的输出契约
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SurfaceResidual:
    """
    单个 (到期日, 行权价, 方向) 上的曲面残差。

    ``residual_vol_points = (raw_iv − model_iv) × 100``。
    正值 = 市场报价比模型贵（"rich"）。``model_iv`` 为 ``None`` 表示该点
    没有可用拟合（不应发生：模型层对坏切片会退回 Raw，见 ``used_fallback``）。

    为什么必须有 ``right``
    ----------------------
    残差是**逐 reqId** 的：同一个 ``(expiry, strike)`` 上 Put 与 Call 是两张
    不同合约，各出一条残差（实测 50 条 / 25 个 strike，恰好 2×）。缺少方向字段时，
    同档两条残差在前端**无法区分** —— 残差图按行权价画，同 strike 的两个点会
    重叠/互相抵消。真实行情下 Put IV ≠ Call IV，这两条的残差常常**一正一负**，
    不区分就等于把两个相反信号画成了一个。

    ⚠️ 注意口径差异（这是原版设计，未改）：``pivot_table`` 求拟合曲面时对同档
    两侧取 **mean**，而残差用的是 ``clean_df`` 里**单侧**的原始行 ⇒
    ``raw_iv`` 是单侧值、``model_iv`` 是双侧均值对应的值。

    刻意**不含报价质量字段**：``models/`` 的 ``clean_df`` 里没有这个列
    （原版 docstring 说"welcome"但从未产出），凭空造一个恒为空字符串的字段
    只会让下游以为"我们有质量信息"。真要加，就得先在配置里定义分档阈值。
    """

    expiry: str
    strike: float
    raw_iv: float
    model_iv: float | None = None
    residual_vol_points: float | None = None
    fit_status: str = ""
    used_fallback: bool = False
    #: 期权方向（``"P"`` / ``"C"``）。取自 ``contracts.enums.OptionRight`` 的值。
    #: 空字符串表示来源未提供方向 —— 用于兼容老的 ``SurfaceInputPort`` 实现，
    #: 本项目自己的 ``features/surface_engine.py`` 恒填。
    right: str = ""


@dataclass(frozen=True, slots=True)
class SurfaceSummary:
    """
    曲面模型一轮拟合的诊断摘要。

    字段名与 `models/` 层 `diagnostics()` 的返回键一一对应（去掉单位后缀），
    但**只保留跨层需要的**：模型层内部的参数向量、逐点拟合细节不上行。
    """

    model_name: str = ""
    fitted_expiries: int = 0
    failed_expiries: int = 0
    good_fits: int = 0
    warn_fits: int = 0
    bad_fits: int = 0
    fallback_expiries: int = 0
    avg_rmse_vol_points: float | None = None
    max_rmse_vol_points: float | None = None
    residuals: tuple[SurfaceResidual, ...] = ()

    @property
    def is_healthy(self) -> bool:
        return self.failed_expiries == 0 and self.fitted_expiries > 0


@dataclass(frozen=True, slots=True)
class FeatureBundle:
    """
    L5 一轮计算的完整产出。

    L6 拿到它之后只需要加健康信息就能组装成推送帧，不必再回头调用 L5 的任何方法。
    """

    ts: float
    spot: float
    cells: tuple[ImpulseCell, ...] = ()
    heatmap: HeatmapMatrix | None = None
    skew: SkewPoint | None = None
    skew_series: tuple[SkewPoint, ...] = ()
    atm: AtmSnapshot | None = None
    surface: SurfaceSummary | None = None
    quality_ok: int = 0
    quality_flagged: int = 0

    def is_empty(self) -> bool:
        return not self.cells and self.heatmap is None
