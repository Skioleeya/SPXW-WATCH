"""
models/svi_fit.py
==================
SVI 单到期日切片拟合（从 svi_surface_model.py 原样拆出）。

拆出原因：单文件 <400 行的机械门禁；"标定算法"与"模型接口/报告"是两件事。
本模块只放模块级函数与常量，不持有任何模型状态：
    year_fraction_from_expiry()  — 交易日 / 252 的 TTE
    fit_svi_slice()              — 单个到期日的 SLSQP 多起点 SVI 标定

SVISurfaceModel 通过 models/svi_surface_model.py 引用这些名字（该文件已
re-export，因此原有 import 路径不变）。SVI 参数化与 B4 加固的完整说明见
models/svi_surface_model.py 的模块 docstring。
"""

import numpy as np
import pandas as pd

from scipy.optimize import minimize

from models.svi_math import (
    raw_svi_total_variance,
    total_variance_to_iv,
    iv_to_total_variance,
    log_moneyness,
    initial_svi_guess,
    svi_weighted_objective,
    svi_no_arb_constraints,
    vega_weights,
    rmse,
)
from models.surface_params import svi_fit_params

# 与原版的差异：原版把 MIN_POINTS_PER_SVI_SLICE / MIN_SVI_IV / MAX_SVI_IV /
# SVI_OPT_TOL / SVI_MAX_ITER / SVI_*_RMSE_VOL / SVI_ALLOWED_STATUSES /
# SVI_N_MULTISTART / SVI_BOUNDS / SVI_RANDOM_START_RANGES 与 RNG seed 全部
# 写死在本模块顶部。本项目按第 3 条「禁止硬编码」搬进 ``config/surface.json``，
# 由 ``models/surface_params.py::svi_fit_params()`` 读出。**数值逐字一致。**
# 调用点从全局名改为 ``p.xxx``，其余逻辑与变量名未动。

_RNG: np.random.Generator | None = None


def _rng() -> np.random.Generator:
    """
    延迟初始化的随机源（与原版模块级 ``_RNG`` **同一个流语义**）。

    原版在模块导入时用写死的 seed 建流；这里 seed 来自配置，于是不能在导入时
    建 —— 改为首次调用时建、之后复用同一个生成器对象。

    ⚠️ **必须复用同一个对象**：原版连续两次 fit 从流里拿到的是**不同**的随机
    起点，多起点搜索因此每轮都在探索新的区域。若每次 fit 都按同一个 seed 重建
    流，两次 fit 会拿到完全相同的起点，等价于把多起点退化成固定起点 —— 这是个
    不会报错、只会让拟合悄悄变差的改动。
    """
    global _RNG
    if _RNG is None:
        _RNG = np.random.default_rng(seed=svi_fit_params().random_seed)
    return _RNG


def svi_allowed_statuses() -> frozenset[str]:
    """可接受的 SVI 拟合状态（配置 ``svi_allowed_statuses``）。"""
    return svi_fit_params().allowed_statuses


def year_fraction_from_expiry(expiry_str):
    """
    Converts YYYYMMDD expiry into year fraction using trading days / 252.

    Counts Mon–Fri business days from today to expiry (inclusive of both
    endpoints via pd.bdate_range). Using 252 trading days per year matches
    how market participants quote short-dated options.
    """
    expiry = pd.to_datetime(str(expiry_str), format="%Y%m%d")
    now    = pd.Timestamp.now().normalize()   # strip intra-day time

    bdays = len(pd.bdate_range(start=now, end=expiry.normalize()))
    # Minimum 0.5 trading days so same-day expiry doesn't produce t=0.
    return max(bdays, 0.5) / 252.0

def fit_svi_slice(expiry, slice_df, forward_price):
    """
    Fits raw SVI to ONE expiry slice.

    Parameters
    ----------
    expiry : str
        Expiry YYYYMMDD

    slice_df : DataFrame
        Cleaned options for one expiry.

    forward_price : float
        Approximate forward price.

    Returns
    -------
    dict
        {
            "success": bool,
            "params": ndarray or None,
            "rmse": float or None,
            "num_points": int,
            "expiry": str,
        }
    """
    p = svi_fit_params()

    if slice_df is None or slice_df.empty:
        return {
            "success": False,
            "params": None,
            "rmse": None,
            "num_points": 0,
            "expiry": expiry,
            "reason": "empty_slice",
        }

    df = slice_df.copy()

    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["IV"] = pd.to_numeric(df["IV"], errors="coerce")

    df = df.dropna(subset=["Strike", "IV"])

    df = df[
        (df["IV"] >= p.min_iv)
        & (df["IV"] <= p.max_iv)
    ].copy()

    if len(df) < p.min_points_per_slice:
        return {
            "success": False,
            "params": None,
            "rmse": None,
            "num_points": len(df),
            "expiry": expiry,
            "reason": "too_few_points",
        }

    t = year_fraction_from_expiry(expiry)

    strikes = df["Strike"].astype(float).to_numpy()
    ivs     = df["IV"].astype(float).to_numpy()

    k        = log_moneyness(strikes, forward_price)
    w_market = iv_to_total_variance(ivs, t)
    weights  = vega_weights(k, t)

    # Build starting points: 1 data-driven + (N-1) random within equity-typical range.
    ranges = np.array(p.random_start_ranges, dtype=float)
    lows, highs = ranges[:, 0], ranges[:, 1]
    starts = [initial_svi_guess(k, w_market)]
    for _ in range(p.n_multistart - 1):
        starts.append(_rng().uniform(lows, highs))

    constraints = svi_no_arb_constraints(float(k.min()), float(k.max()))

    best_result = None
    best_value  = np.inf

    # Pass 1: weighted objective + no-arbitrage constraints.
    for x0 in starts:
        try:
            res = minimize(
                svi_weighted_objective,
                x0=x0,
                args=(k, w_market, weights),
                method="SLSQP",
                bounds=list(p.bounds),
                constraints=constraints,
                tol=p.opt_tol,
                options={"maxiter": p.max_iter},
            )
            if res.success and res.fun < best_value:
                best_result = res
                best_value  = res.fun
        except Exception:
            pass

    # Pass 2: weighted objective without constraints (fallback if all constrained runs failed).
    if best_result is None:
        for x0 in starts:
            try:
                res = minimize(
                    svi_weighted_objective,
                    x0=x0,
                    args=(k, w_market, weights),
                    method="SLSQP",
                    bounds=list(p.bounds),
                    tol=p.opt_tol,
                    options={"maxiter": p.max_iter},
                )
                if res.success and res.fun < best_value:
                    best_result = res
                    best_value  = res.fun
            except Exception:
                pass

    if best_result is None:
        return {
            "success": False,
            "params": None,
            "rmse": None,
            "num_points": len(df),
            "expiry": expiry,
            "reason": "all_starts_failed",
        }

    params = best_result.x

    w_fit  = raw_svi_total_variance(k, *params)
    iv_fit = total_variance_to_iv(w_fit, t)
    fit_rmse = rmse(ivs, iv_fit)

    return {
        "success": True,
        "params": params,
        "rmse": fit_rmse,
        "num_points": len(df),
        "expiry": expiry,
        "reason": "",
    }
