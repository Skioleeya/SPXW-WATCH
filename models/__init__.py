"""
models/  —— L4 曲面模型层
=========================
Raw / SVI / SSVI 三个 IV 曲面模型（原版 ``live-volatility-surface/models/``
移植），外加一层把 pandas 输出翻译成 L0 契约的适配器。

对上层（L5）唯一有意义的入口是 ``SurfaceModelAdapter``：

    from models import SurfaceModelAdapter

    adapter = SurfaceModelAdapter()   # 模型名取自 config/surface.json
    adapter.fit(surface_input)        # surface_input 实现 SurfaceInputPort
    summary = adapter.summary()       # L0 的 SurfaceSummary，不含 pandas 对象

本层是**全项目唯一允许 import numpy / pandas / scipy 的层**，由
``tools/selfcheck_duty.py`` 机械守住。L0–L3 仍是纯标准库。

模型名 → 类
-----------
RawSurfaceModel  —— 清洗 + 插值（无参数拟合，残差恒为 0）
SVISurfaceModel  —— 逐到期日 SVI 微笑拟合
SSVISurfaceModel —— 跨到期日全局拟合，calendar-arbitrage-free

三者都实现 ``BaseSurfaceModel``，可互换；换模型只改 ``config/surface.json``
的 ``active_model``，不动代码。

模块清单
--------
base_surface_model   抽象基类（接口契约，逐字移植）
raw_surface_model    Raw 模型本体
raw_cleaning         清洗 / 插值流水线（从 raw_surface_model 拆出）
svi_math             SVI 参数化数学（纯函数）
svi_fit              单到期日 SLSQP 标定（从 svi_surface_model 拆出）
svi_reporting        拟合质量报告 / 诊断（从 svi_surface_model 拆出）
svi_surface_model    SVI 模型本体
ssvi_math            SSVI 全局标定数学（从 ssvi_surface_model 拆出）
ssvi_surface_model   SSVI 模型本体
market_params        市场假设（r / q）读取
surface_params       config/surface.json → 参数对象（本层唯一读该文件的地方）
surface_adapter      SurfaceModelPort 实现（对 L5 的出口）

拆分成多文件的原因：单文件 < 400 行的机械门禁，且"数学"、"标定"、"模型接口"、
"报告输出"是四件事。接口逐字保持，原有 import 路径由各模块 re-export 兜住。
"""

from models.base_surface_model import BaseSurfaceModel
from models.market_params import get_market_params
from models.raw_surface_model import RawSurfaceModel
from models.ssvi_surface_model import SSVISurfaceModel
from models.surface_adapter import SurfaceModelAdapter
from models.surface_params import (
    CleaningParams,
    PricingParams,
    SsviFitParams,
    SviFitParams,
    active_model_name,
    cleaning_params,
    pricing_params,
    ssvi_fit_params,
    svi_fit_params,
)
from models.svi_math import compute_forward_price
from models.svi_surface_model import SVISurfaceModel

__all__ = [
    "BaseSurfaceModel",
    "CleaningParams",
    "PricingParams",
    "RawSurfaceModel",
    "SSVISurfaceModel",
    "SVISurfaceModel",
    "SsviFitParams",
    "SviFitParams",
    "SurfaceModelAdapter",
    "active_model_name",
    "cleaning_params",
    "compute_forward_price",
    "get_market_params",
    "pricing_params",
    "ssvi_fit_params",
    "svi_fit_params",
]
