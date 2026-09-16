"""
models/forecasting/ewma.py
===========================
EWMA (Exponentially Weighted Moving Average) realized volatility.

The standard RiskMetrics formulation:
    λ = 1 - 2/(span + 1)   (decay factor)
    σ²_t = λ * σ²_{t-1} + (1-λ) * r²_{t-1}

pandas ewm(span=N, adjust=False) implements this exactly.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252


def ewma_vol(log_returns, span: int = 21) -> Optional[float]:
    """
    EWMA annualized vol from daily log returns.

    Parameters
    ----------
    log_returns : array-like
        Daily log-returns (e.g. log(P_t / P_{t-1})).
    span : int
        EWM span.  Effective decay λ = 1 - 2/(span+1).

    Returns
    -------
    float or None
        Annualized vol (fraction).  None if < 2 finite observations.
    """
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return None

    ewm_var = pd.Series(r).ewm(span=span, adjust=False).var().iloc[-1]
    if not np.isfinite(ewm_var) or ewm_var < 0:
        return None

    return float(np.sqrt(ewm_var * TRADING_DAYS_PER_YEAR))


def ewma_vols(
    log_returns,
    spans: Optional[List[int]] = None,
) -> Dict[int, Optional[float]]:
    """
    EWMA vols for multiple spans in one call.

    Returns
    -------
    dict  {span: annualized_vol_or_None}
    """
    if spans is None:
        spans = [10, 21, 63]
    return {s: ewma_vol(log_returns, s) for s in spans}
