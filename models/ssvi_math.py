"""
models/ssvi_math.py
====================
SSVI（Surface SVI）核心数学与全局标定。

从 ssvi_surface_model.py 原样拆出（拆出原因：单文件 <400 行的机械门禁；
"曲面数学 / 标定"与"模型接口"是两件事）。逻辑与注释未改动。

本模块不持有模型状态：SSVISurfaceModel.fit() 依次调用
_extract_atm_theta() → _enforce_calendar_monotonicity() → _calibrate_ssvi()。

SSVI 参数化、日历/蝶式套利保证与参考文献的完整说明见
models/ssvi_surface_model.py 的模块 docstring。
"""

import numpy as np

from scipy.optimize import minimize

from models.svi_math import (
    compute_forward_price,
    iv_to_total_variance,
    total_variance_to_iv,
    log_moneyness,
)
from models.svi_fit import year_fraction_from_expiry
from models.surface_params import ssvi_fit_params

# 与原版的差异：原版把 SSVI_N_STARTS / SSVI_*_RMSE_VOL / MIN_POINTS_FOR_SSVI /
# MIN_EXPIRIES_FOR_SSVI 与 RNG seed 写死在本模块顶部，把随机起点采样区间写死在
# ``_calibrate_ssvi()`` 体内。本项目按第 3 条「禁止硬编码」把它们全部搬进
# ``config/surface.json``。**数值逐字一致。**
#
# 刻意**没有**搬走的两处（它们不是可调参数，是数学事实）：
#   * 蝶式套利约束 η·(1+|ρ|) ≤ 4 —— Gatheral & Jacquier (2014) 的定理常数；
#   * 搜索区间 [(-0.999, 0.999), (1e-4, 3.999)] —— 由 |ρ|<1 与上式在 ρ→0
#     时的上界 η≤4 直接推出。
# 改这两个数等于改 SSVI 的定义，不是调参。

_RNG: np.random.Generator | None = None


def _rng() -> np.random.Generator:
    """
    延迟初始化的随机源（与原版模块级 ``_RNG`` **同一个流语义**）。

    原版在导入时用写死的 seed=0 建流；seed 搬进配置后不能在导入时建，改为首次
    调用时建、之后复用。**必须复用同一个对象**：原版连续多次标定拿到的是流里
    不同的起点；每次重建流会让每轮标定都从同一组起点出发，把多起点搜索悄悄退化。
    """
    global _RNG
    if _RNG is None:
        _RNG = np.random.default_rng(seed=ssvi_fit_params().random_seed)
    return _RNG


# ─── Core SSVI functions ─────────────────────────────────────────────────────

def ssvi_total_variance(k, theta, rho, eta):
    """
    SSVI total variance w(k) for a single expiry with ATM variance theta.

    w(k) = θ/2 * (1 + ρ·φ·k + sqrt((φ·k + ρ)² + (1−ρ²)))
    where φ = η / sqrt(θ)
    """
    k = np.asarray(k, dtype=float)
    phi = eta / np.sqrt(theta)
    psi = phi * k + rho
    return theta / 2.0 * (1.0 + rho * phi * k + np.sqrt(psi ** 2 + (1.0 - rho ** 2)))


def ssvi_iv(k, t, theta, rho, eta):
    """IV from SSVI total variance for log-moneyness k, TTE t."""
    w = ssvi_total_variance(k, theta, rho, eta)
    return total_variance_to_iv(w, t)


def _extract_atm_theta(clean_df, spot, mkt):
    """
    Extracts per-expiry ATM total variance θ_T from clean option data.

    Returns dict {expiry_str: (theta, t)} sorted by T.
    Returns empty dict if data is insufficient.
    """
    theta_map = {}

    for expiry, grp in clean_df.groupby("Expiry"):
        expiry = str(expiry)
        t = year_fraction_from_expiry(expiry)
        if t <= 0:
            continue

        f = compute_forward_price(
            spot=spot,
            t=t,
            risk_free_rate=mkt["risk_free_rate"],
            dividend_yield=mkt["dividend_yield"],
        )

        ks = log_moneyness(grp["Strike"].values, f)
        ws = iv_to_total_variance(grp["IV"].values, t)

        valid = np.isfinite(ks) & np.isfinite(ws) & (ws > 0)
        if valid.sum() < 2:
            continue

        ks_v = ks[valid]
        ws_v = ws[valid]

        # Sort by k then interpolate at k=0 for ATM total variance.
        sort_idx = np.argsort(ks_v)
        ks_s = ks_v[sort_idx]
        ws_s = ws_v[sort_idx]

        if ks_s[0] > 0 or ks_s[-1] < 0:
            # ATM is outside the available strike range — skip.
            continue

        theta = float(np.interp(0.0, ks_s, ws_s))
        if theta <= 0 or not np.isfinite(theta):
            continue

        theta_map[expiry] = (theta, t)

    return theta_map


def _enforce_calendar_monotonicity(theta_map):
    """
    Ensures θ_T is non-decreasing in T (calendar-arbitrage-free condition).

    Returns a new dict with θ_T values replaced by their cummax.
    """
    if not theta_map:
        return {}

    sorted_expiries = sorted(theta_map.keys(), key=lambda e: theta_map[e][1])
    running_max = 0.0
    out = {}
    for exp in sorted_expiries:
        theta, t = theta_map[exp]
        theta_mono = max(theta, running_max)
        running_max = theta_mono
        out[exp] = (theta_mono, t)

    return out


def _calibrate_ssvi(clean_df, spot, theta_map, mkt):
    """
    Calibrates global (ρ, η) by minimizing vega-weighted total-variance MSE.

    Returns {"rho": float, "eta": float, "rmse_vol": float, "success": bool}.
    """
    # Build arrays for all calibration points.
    k_all, w_target, theta_per_pt, t_per_pt = [], [], [], []

    for expiry, (theta, t) in theta_map.items():
        grp = clean_df[clean_df["Expiry"] == expiry]
        if grp.empty:
            continue

        f = compute_forward_price(
            spot=spot,
            t=t,
            risk_free_rate=mkt["risk_free_rate"],
            dividend_yield=mkt["dividend_yield"],
        )

        ks = log_moneyness(grp["Strike"].values, f)
        ws = iv_to_total_variance(grp["IV"].values, t)

        valid = np.isfinite(ks) & np.isfinite(ws) & (ws > 0) & (t > 0)
        k_all.append(ks[valid])
        w_target.append(ws[valid])
        theta_per_pt.append(np.full(valid.sum(), theta))
        t_per_pt.append(np.full(valid.sum(), t))

    if not k_all:
        return {"rho": -0.3, "eta": 0.5, "rmse_vol": None, "success": False}

    k_arr = np.concatenate(k_all)
    w_arr = np.concatenate(w_target)
    theta_arr = np.concatenate(theta_per_pt)
    t_arr = np.concatenate(t_per_pt)

    # Vega-proxy weight: peak at ATM, fall off in wings.
    vega_weight = np.exp(-0.5 * k_arr ** 2 / 0.04)  # σ_k ≈ 0.2

    def objective(params):
        rho, eta = params
        w_fit = ssvi_total_variance(k_arr, theta_arr, rho, eta)
        diff = w_fit - w_arr
        return float(np.sum(vega_weight * diff ** 2))

    # Butterfly-arbitrage constraint: η*(1 + |ρ|) ≤ 4
    constraints = [
        {"type": "ineq", "fun": lambda p: 4.0 - p[1] * (1.0 + abs(p[0]))},
    ]
    bounds = [(-0.999, 0.999), (1e-4, 3.999)]
    p = ssvi_fit_params()

    best_result = None

    # Data-driven starting point: ρ from skew of ATM vol term structure,
    # η from typical market range.
    starts = [tuple(p.data_start)]
    for _ in range(p.n_starts - 1):
        rho0 = _rng().uniform(*p.random_start_ranges[0])
        eta0 = _rng().uniform(*p.random_start_ranges[1])
        starts.append((rho0, eta0))

    for rho0, eta0 in starts:
        try:
            res = minimize(
                objective,
                x0=[rho0, eta0],
                bounds=bounds,
                constraints=constraints,
                method="SLSQP",
                options={"ftol": 1e-10, "maxiter": 1000},
            )
            if best_result is None or res.fun < best_result.fun:
                best_result = res
        except Exception:
            continue

    if best_result is None or not best_result.success:
        # Fallback: unconstrained best from all starts.
        if best_result is None:
            return {"rho": -0.3, "eta": 0.5, "rmse_vol": None, "success": False}

    rho_fit, eta_fit = best_result.x

    # Compute RMSE in vol points for diagnostics.
    w_fit_all = ssvi_total_variance(k_arr, theta_arr, rho_fit, eta_fit)
    iv_fit = total_variance_to_iv(w_fit_all, t_arr)
    iv_raw = total_variance_to_iv(w_arr, t_arr)
    rmse_vol = float(np.sqrt(np.mean((iv_fit - iv_raw) ** 2))) * 100.0

    return {
        "rho": float(rho_fit),
        "eta": float(eta_fit),
        "rmse_vol": rmse_vol,
        "success": True,
    }
