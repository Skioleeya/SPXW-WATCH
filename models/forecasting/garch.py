"""
models/forecasting/garch.py
============================
GARCH(1,1) volatility model estimated via Gaussian MLE.

Model
-----
    σ²_t = ω + α * r²_{t-1} + β * σ²_{t-1}

where:
    ω  > 0   (long-run variance floor)
    α  ≥ 0   (ARCH effect — vol reacts to shocks)
    β  ≥ 0   (GARCH effect — vol persists)
    α + β < 1 (stationarity / mean-reversion)

Long-run vol   = sqrt(ω / (1 - α - β)) * sqrt(252)
1-day forecast = sqrt(ω + α*r²_{T} + β*σ²_{T}) * sqrt(252)

Persistence α+β close to 1 means slow mean-reversion (typical in equities).
"""

from typing import Dict, Optional

import numpy as np
from scipy.optimize import minimize


TRADING_DAYS_PER_YEAR = 252
_MIN_HISTORY = 30   # minimum daily observations required


def fit_garch11(log_returns) -> Optional[Dict]:
    """
    Fit GARCH(1,1) to daily log returns via Gaussian MLE.

    Parameters
    ----------
    log_returns : array-like
        Daily log-returns.  Needs >= 30 finite observations.

    Returns
    -------
    dict or None
        {
          'omega'          : float,
          'alpha'          : float,
          'beta'           : float,
          'persistence'    : float,   # alpha + beta
          'long_run_vol'   : float,   # annualized, fraction
          'forecast_vol_1d': float,   # 1-day ahead, annualized, fraction
        }
        None on failure.
    """
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < _MIN_HISTORY:
        return None

    var0 = float(np.var(r, ddof=1))
    if var0 <= 0:
        return None

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
            return 1e10
        sigma2 = np.empty(n)
        sigma2[0] = var0
        for t in range(1, n):
            sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
            if sigma2[t] <= 0:
                return 1e10
        # Gaussian log-likelihood (skip first observation — conditioning)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:] ** 2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    bounds = [(1e-10, var0), (0.0, 0.5), (0.0, 0.9999)]
    constraints = [{"type": "ineq", "fun": lambda p: 0.9999 - p[1] - p[2]}]

    x0s = [
        [var0 * 0.05, 0.10, 0.85],
        [var0 * 0.01, 0.05, 0.90],
        [var0 * 0.10, 0.15, 0.80],
    ]

    best, best_val = None, np.inf
    for x0 in x0s:
        try:
            res = minimize(
                neg_loglik,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-9},
            )
            if res.success and res.fun < best_val:
                best = res
                best_val = res.fun
        except Exception:
            pass

    if best is None:
        return None

    omega, alpha, beta = best.x
    persistence = alpha + beta

    # Propagate sigma2 through all observations to get final in-sample variance
    sigma2 = np.empty(n)
    sigma2[0] = var0
    for t in range(1, n):
        sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]

    # 1-step ahead forecast: σ²_{n} = ω + α*r[n-1]² + β*σ²[n-1]
    forecast_var = float(omega + alpha * r[-1] ** 2 + beta * sigma2[-1])
    forecast_var = max(forecast_var, 1e-12)

    long_run_var = (
        omega / max(1.0 - persistence, 1e-8)
        if persistence < 0.9999
        else var0
    )

    return {
        "omega": float(omega),
        "alpha": float(alpha),
        "beta": float(beta),
        "persistence": float(persistence),
        "long_run_vol": float(np.sqrt(max(long_run_var, 1e-12) * TRADING_DAYS_PER_YEAR)),
        "forecast_vol_1d": float(np.sqrt(forecast_var * TRADING_DAYS_PER_YEAR)),
    }
