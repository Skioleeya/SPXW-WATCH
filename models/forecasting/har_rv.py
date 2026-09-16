"""
models/forecasting/har_rv.py
==============================
HAR-RV (Heterogeneous Autoregressive Realized Variance) one-day forecast.

Reference: Corsi (2009), "A simple approximate long-memory model of realized
volatility."

Model
-----
RV^d_{t+1} = c + β_d * RV^d_t + β_w * RV^w_t + β_m * RV^m_t + ε_{t+1}

where:
    RV^d_t  = daily variance proxy (squared log-return)
    RV^w_t  = (1/5)  * Σ_{j=1}^{5}  RV^d_{t-j+1}   (5-day avg)
    RV^m_t  = (1/22) * Σ_{j=1}^{22} RV^d_{t-j+1}   (22-day avg)

Coefficients estimated by OLS over the available history.  Returns the
next-day vol forecast as an annualized fraction (0.20 = 20 %).
"""

from typing import Optional

import numpy as np


TRADING_DAYS_PER_YEAR = 252
_MIN_HISTORY = 23   # 22 lags + 1 target


def har_rv_forecast(log_returns) -> Optional[float]:
    """
    One-day-ahead annualized vol forecast using the HAR-RV model.

    Parameters
    ----------
    log_returns : array-like
        Daily log-returns.  Needs >= 23 finite observations.

    Returns
    -------
    float or None
        Annualized vol forecast (fraction).  None if insufficient data.
    """
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < _MIN_HISTORY:
        return None

    # Daily realized variance proxy (daily units, not annualized)
    rv = r ** 2

    # Build OLS system:  y[t] = c + β_d*rv[t-1] + β_w*rv_w[t-1] + β_m*rv_m[t-1]
    # First valid target index is 22 (so we have 22 lags for monthly component)
    n_obs = n - 22
    if n_obs < 3:
        return None

    X = np.empty((n_obs, 4))   # [const, daily, weekly, monthly]
    y = np.empty(n_obs)

    for i in range(n_obs):
        t = 22 + i
        X[i, 0] = 1.0
        X[i, 1] = rv[t - 1]                     # yesterday's variance
        X[i, 2] = rv[max(t - 5, 0):t].mean()    # 5-day average
        X[i, 3] = rv[t - 22:t].mean()            # 22-day average
        y[i] = rv[t]

    try:
        betas, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except Exception:
        return None

    # Out-of-sample forecast using last available observation
    rv_d_last = rv[-1]
    rv_w_last = rv[-5:].mean()
    rv_m_last = rv[-22:].mean()

    x_next = np.array([1.0, rv_d_last, rv_w_last, rv_m_last])
    forecast_var_daily = float(np.dot(betas, x_next))
    forecast_var_daily = max(forecast_var_daily, 0.0)

    return float(np.sqrt(forecast_var_daily * TRADING_DAYS_PER_YEAR))
