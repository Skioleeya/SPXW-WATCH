"""
models/forecasting/
====================
Realized-vol forecasting layer (B5).

Models
------
EWMA   — exponentially weighted moving average variance (simple, robust)
GARCH  — GARCH(1,1) MLE (captures vol clustering / mean reversion)
HAR-RV — Heterogeneous Autoregressive RV (daily / weekly / monthly lags)

All estimators accept an array of daily log-returns and return an annualized
vol forecast (fraction, 0.20 = 20 %).  They return None when there is
insufficient history rather than raising.

Usage
-----
from models.forecasting import ewma_vols, fit_garch11, har_rv_forecast
"""

from models.forecasting.ewma import ewma_vol, ewma_vols
from models.forecasting.garch import fit_garch11
from models.forecasting.har_rv import har_rv_forecast
from models.forecasting.snapshot_history import load_atm_iv_history

__all__ = [
    "ewma_vol",
    "ewma_vols",
    "fit_garch11",
    "har_rv_forecast",
    "load_atm_iv_history",
]
