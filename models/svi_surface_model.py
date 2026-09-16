"""
models/svi_surface_model.py
============================
SVI (Stochastic Volatility Inspired) parametric surface model.

What is SVI?
------------
SVI (Gatheral 2004) fits each expiry's smile independently with a
five-parameter function in log-moneyness k = ln(K/F) space:

    w(k) = a + b * (ρ(k - m) + sqrt((k - m)² + σ²))

where w(k) is total implied variance (IV² × T), and the parameters are:
    a  – overall level of variance
    b  – angle between put and call wings (slope)
    ρ  – skew (rotation of the smile)
    m  – translation (location of the minimum)
    σ  – curvature of the ATM region

Current implementation
-----------------------
B4 hardened:
    • Fits one SVI smile per expiry using SLSQP with multi-start search
      (1 data-driven + 4 random starts within equity-typical ranges).
    • Vega-weighted objective: ATM options receive the highest weight,
      deep wings are down-weighted via a Gaussian proxy.
    • No-arbitrage constraints: non-negative minimum variance +
      butterfly g(k) >= 0 at 5 check points across the slice.
      Falls back to unconstrained fit if all constrained starts fail.
    • TTE computed from Mon–Fri trading days / 252 (not calendar days).
    • Post-fit calendar-arbitrage check flags expiries where w_atm(T)
      is not non-decreasing in T (does not re-fit, only flags).
    • Falls back to RawSurfaceModel for BAD/FAIL fit status expiries.

Next model: SSVI (Surface SVI) for cross-expiry consistency.

References
-----------
Gatheral (2004): "A Parsimonious Arbitrage-Free Implied Volatility
    Parameterization with Application to the Valuation of Volatility
    Derivatives"
Gatheral & Jacquier (2014): "Arbitrage-Free SVI Volatility Surfaces"

Module layout
-------------
For the <400-line-per-file gate this module was split:
    • models/svi_fit.py        – SLSQP 标定算法（常量 / TTE / fit_svi_slice）
    • models/svi_reporting.py  – fit_summary / expiry_diagnostics / residuals /
                                 diagnostics（SVIReportingMixin）
    • models/svi_surface_model.py（本文件）– SVISurfaceModel 本体
所有原本可从本模块导入的名字都在下面 re-export，调用点零改动。
"""

import time

import numpy as np
import pandas as pd

from models.svi_math import (
    raw_svi_total_variance,
    total_variance_to_iv,
    iv_to_total_variance,
    log_moneyness,
    compute_forward_price,
    initial_svi_guess,
    svi_objective,
    svi_weighted_objective,
    svi_no_arb_constraints,
    vega_weights,
    rmse,
)

from models.base_surface_model import BaseSurfaceModel
from models.raw_surface_model import RawSurfaceModel
from models.market_params import get_market_params

# Re-exported from models/svi_fit.py so that existing imports
# (e.g. `from models.svi_surface_model import year_fraction_from_expiry`)
# keep working unchanged.
#
# 与原版的差异：原版这里还 re-export 了 MIN_POINTS_PER_SVI_SLICE / MIN_SVI_IV /
# MAX_SVI_IV / SVI_OPT_TOL / SVI_MAX_ITER / SVI_*_RMSE_VOL / SVI_ALLOWED_STATUSES /
# SVI_N_MULTISTART / _RNG 十个常量，以及从 svi_math 来的 SVI_BOUNDS /
# SVI_RANDOM_START_RANGES。本项目按第 3 条「禁止硬编码」把它们全部搬进
# ``config/surface.json`` —— 常量既然不再存在于代码里，这组 re-export 也就随之
# 删除（保留它们等于在配置之外再留一份真相）。
from models.svi_fit import (
    svi_allowed_statuses,
    year_fraction_from_expiry,
    fit_svi_slice,
)
from models.surface_params import svi_fit_params

from models.svi_reporting import SVIReportingMixin


class SVISurfaceModel(SVIReportingMixin, BaseSurfaceModel):
    """
    SVI parametric surface model.

    Delegates data cleaning to RawSurfaceModel (reuse the existing pipeline),
    then fits a per-expiry SVI smile on top of the clean data.

    Attributes (after fit())
    -------------------------
    _raw   : RawSurfaceModel  — handles all data cleaning
    _params: dict             — {expiry_str: {"a": .., "b": .., "rho": ..,
                                               "m": .., "sigma": ..}}
    _pivot : pd.DataFrame     — SVI-fitted IV surface (Expiry × Strike)
    _fitted: bool
    """

    MODEL_NAME = "SVI"

    def __init__(self):
        self._raw    = RawSurfaceModel()
        self._params: dict = {}
        self._pivot: pd.DataFrame | None = None
        self._fitted: bool = False
        self._slice_fits = {}
        self._fit_diagnostics = {}
        self._last_fit_log_time = 0.0

    # ------------------------------------------------------------------ #
    # BaseSurfaceModel interface                                           #
    # ------------------------------------------------------------------ #

    def fit(self, app) -> None:
        """
        Step 1: clean data via RawSurfaceModel.
        Step 2: fit SVI per expiry.
        Step 3: build the SVI pivot table.
        """
        self._app = app
        # Always clean first — reuse the existing pipeline.
        self._raw.fit(app)

        clean_df = self._raw.clean_df()
        self._slice_fits = {}
        self._fit_diagnostics = {}

        if clean_df is None or clean_df.empty:
            return
        
        spot = float(getattr(app, "spot_price", 0.0) or 0.0)

        if spot <= 0:
            return

        if not self._raw.stats().get("surface_ok"):
            self._pivot  = None
            self._params = {}
            self._fitted = True
            return

        _mkt = get_market_params()
        for expiry, slice_df in clean_df.groupby("Expiry"):
            t = year_fraction_from_expiry(expiry)

            forward_price = compute_forward_price(
                spot=spot,
                t=t,
                risk_free_rate=_mkt["risk_free_rate"],
                dividend_yield=_mkt["dividend_yield"],
            )

            fit_result = fit_svi_slice(
                expiry=str(expiry),
                slice_df=slice_df,
                forward_price=forward_price,
            )

            self._fit_diagnostics[str(expiry)] = fit_result

            if fit_result["success"]:
                self._slice_fits[str(expiry)] = fit_result["params"]

        self._pivot  = self._raw.surface()
        self._params = self._slice_fits.copy()
        self._fitted = True

        # ── Post-fit: calendar arbitrage check ───────────────────────────
        # For each fitted expiry, verify w(k=0,T) is non-decreasing in T.
        # A violation means the near-term smile has higher ATM total variance
        # than a longer-dated smile — a model artefact that can produce
        # spurious RV signals near the affected expiry.
        expiries_asc = sorted(
            self._params.keys(),
            key=lambda e: year_fraction_from_expiry(e),
        )
        prev_w_atm = -np.inf
        for exp in expiries_asc:
            params = self._params[exp]
            w_atm = float(raw_svi_total_variance(0.0, *params))
            cal_arb = w_atm < prev_w_atm - 1e-6
            self._fit_diagnostics[exp]["calendar_arb"] = cal_arb
            if cal_arb:
                print(
                    f"[SVI] calendar arb: {exp} w_atm={w_atm:.4f} < "
                    f"prev={prev_w_atm:.4f} — treat with caution"
                )
            else:
                prev_w_atm = w_atm

        num_success = len(self._slice_fits)
        num_total = len(self._fit_diagnostics)

        rmse_values = [
            v["rmse"]
            for v in self._fit_diagnostics.values()
            if v.get("success") and v.get("rmse") is not None
        ]

        if rmse_values:
            avg_rmse = float(np.nanmean(rmse_values))
            now = time.time()
            if now - self._last_fit_log_time > 30:
                print(
                    f"[SVI] fitted {num_success}/{num_total} expiries | "
                    f"avg RMSE={avg_rmse:.6f}"
                )
                self._last_fit_log_time = now
        else:
            print(
                f"[SVI] fitted {num_success}/{num_total} expiries | "
                f"no valid RMSE"
            )

    def surface(self) -> pd.DataFrame | None:
        self._require_fit()
        return self._pivot

    def clean_df(self) -> pd.DataFrame:
        self._require_fit()
        return self._raw.clean_df()

    def stats(self) -> dict:
        self._require_fit()
        # Start from raw stats, then add SVI-specific entries.
        s = self._raw.stats().copy()
        s["svi_fits_attempted"] = len(self._raw.clean_df()["Expiry"].unique()) if not self._raw.clean_df().empty else 0
        s["svi_fits_succeeded"] = len(self._params)
        return s

    def iv(self, expiry, strike):
        """
        Returns SVI-fitted IV for one expiry/strike.

        Falls back to RawSurfaceModel if:
            - expiry fit missing
            - invalid parameters
            - numerical issues
        """
        self._require_fit()

        expiry = str(expiry)
        strike = float(strike)

        fit_status = self._expiry_fit_status(expiry)

        if fit_status not in svi_allowed_statuses():
            return self._raw.iv(expiry, strike)

        # Fallback to raw model if expiry was not fitted.
        if expiry not in self._params:
            return self._raw.iv(expiry, strike)

        params = self._params[expiry]

        if params is None or len(params) != 5:
            return self._raw.iv(expiry, strike)

        a, b, rho, m, sigma = params

        spot = getattr(self._app, "spot_price", None)

        if spot is None or spot <= 0:
            return self._raw.iv(expiry, strike)

        try:
            _mkt = get_market_params()
            t = year_fraction_from_expiry(expiry)

            forward_price = compute_forward_price(
                spot=spot,
                t=t,
                risk_free_rate=_mkt["risk_free_rate"],
                dividend_yield=_mkt["dividend_yield"],
            )

            k = log_moneyness(
                strike,
                forward_price,
            )

            w = raw_svi_total_variance(
                k,
                a,
                b,
                rho,
                m,
                sigma,
            )

            iv = total_variance_to_iv(
                w,
                t,
            )

            iv = float(np.asarray(iv).item())

            # Basic sanity filter.
            if not np.isfinite(iv):
                return self._raw.iv(expiry, strike)

            if iv <= 0:
                return self._raw.iv(expiry, strike)

            if iv > 5.0:
                return self._raw.iv(expiry, strike)

            return iv

        except Exception:
            return self._raw.iv(expiry, strike)

    def _require_fit(self) -> None:
        if not self._fitted:
            raise RuntimeError(
                "SVISurfaceModel.fit(app) must be called before reading outputs."
            )
