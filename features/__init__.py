"""
L5 — 特征层。

职责边界
--------
把 L3 的时间序列折算成"交易上可读"的量：IV 冲量、25Δ 偏度、日内动能矩阵、曲面残差。

* 全部是**纯计算**，不做 I/O、不起线程、不持有连接。
* 只通过构造参数拿到 ``TickStore`` 与 ``SessionClock``，因此可以在离线环境下
  用构造出来的假数据完整单测。
* 输出一律是 L0 契约里的不可变对象。
* **本层是 L4 与 L3 之间唯一的接缝**：``surface_engine`` 把存储翻译成
  ``SurfaceInputPort``，除此之外曲面模型层不认识本项目的任何类型。

依赖：L0（config / contracts）、L1（core）、L4（``SurfaceModelPort``），
以及鸭子类型访问的 L3 存储。本层不 import ``state`` —— 它只要求构造器传入的
对象有 ``spot()`` / ``refs()`` / ``option_buffer()`` / ``quote()`` /
``latest_option()`` / ``last_tick_age_s()``。
"""

from features.delta_locator import DeltaLocator, DeltaMatch
from features.feature_engine import FeatureEngine
from features.glitch_filter import GlitchFilter
from features.heatmap_engine import HeatmapEngine
from features.impulse_engine import ImpulseEngine
from features.skew_engine import SkewEngine
from features.strike_window import StrikeWindow
from features.surface_engine import SurfaceEngine, SurfaceSnapshot

__all__ = [
    "DeltaLocator",
    "DeltaMatch",
    "FeatureEngine",
    "GlitchFilter",
    "HeatmapEngine",
    "ImpulseEngine",
    "SkewEngine",
    "StrikeWindow",
    "SurfaceEngine",
    "SurfaceSnapshot",
]
