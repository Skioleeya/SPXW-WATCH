"""
L3 — 特征层。

职责边界
--------
把 L2 的时间序列折算成"交易上可读"的量：IV 冲量、25Δ 偏度、日内动能矩阵。

* 全部是**纯计算**，不做 I/O、不起线程、不持有连接。
* 只通过构造参数拿到 ``TickStore`` 与 ``SessionClock``，因此可以在离线环境下
  用构造出来的假数据完整单测。
* 输出一律是 L0 契约里的不可变对象。

只依赖 L0 与 L2。
"""

from features.delta_locator import DeltaLocator, DeltaMatch
from features.feature_engine import FeatureEngine
from features.glitch_filter import GlitchFilter
from features.heatmap_engine import HeatmapEngine
from features.impulse_engine import ImpulseEngine
from features.skew_engine import SkewEngine
from features.strike_window import StrikeWindow

__all__ = [
    "DeltaLocator",
    "DeltaMatch",
    "FeatureEngine",
    "GlitchFilter",
    "HeatmapEngine",
    "ImpulseEngine",
    "SkewEngine",
    "StrikeWindow",
]
