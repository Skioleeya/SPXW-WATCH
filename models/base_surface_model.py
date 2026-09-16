"""
models/base_surface_model.py
============================
Abstract base class for all IV surface models.

Every model in this package must subclass BaseSurfaceModel and implement
all abstract methods.  The dashboard only ever calls the methods defined
here, so swapping RawSurfaceModel → SVISurfaceModel → HestonSurfaceModel
requires changing exactly one line in dash_surface.py.

Interface contract
------------------

fit(app)
    Ingest live data from a LiveSurfaceApp instance (or any object that
    exposes the same attributes: iv_dict, id_map, quote_dict, spot_price,
    is_delayed).  Perform whatever cleaning / fitting the model needs.
    Must be called before any other method.

surface() → pd.DataFrame | None
    Return the fitted IV surface as a pivot table:
        index   = Expiry strings (YYYYMMDD), sorted ascending
        columns = Strike floats, sorted ascending
        values  = Implied Volatility (decimal, e.g. 0.18 = 18%)
    Returns None when the surface cannot be built (insufficient data).

clean_df() → pd.DataFrame
    Return the point-level cleaned DataFrame used to build the surface.
    Columns must include at least: Expiry, Strike, IV.
    Additional columns (Bid, Ask, SpreadPct, QuoteQuality, …) are welcome
    and will be used by the RV signal engine.

stats() → dict
    Return a data-quality stats dictionary.  The dashboard reads these
    keys; new models should supply all of them:
        raw_count, fresh_count, clean_count,
        rejected_bad_iv, rejected_outlier,
        max_age, max_age_allowed,
        num_expiries, num_strikes,
        surface_ok,
        missing_quote, rejected_missing_quote,
        rejected_crossed_quote, rejected_low_mid, rejected_wide_quote

iv(expiry: str, strike: float) → float | None
    Return the model IV for a specific expiry / strike cell.
    Uses bilinear interpolation if the exact cell is not in the surface.
    Returns None if the surface is not ready or the point is out of range.

residuals() → pd.DataFrame
    Return per-point residuals:
        Expiry, Strike, RawIV, SurfaceIV, ResidualVol
    For RawSurfaceModel the residuals are always 0 (raw == surface).
    For SVISurfaceModel they measure raw point vs. parametric fit.
    The RV signal engine and replay analyser consume this output.

diagnostics() → dict
    Return a human-readable summary dict for logging / the daily report.
    Required keys:
        model_name  – string name of the model
        surface_ok  – bool
        num_expiries, num_strikes, clean_count
        fit_quality – any model-specific fit metric (e.g. RMSE for SVI);
                      use None for models that have no fitting step.
"""

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class BaseSurfaceModel(ABC):
    """Abstract base class for IV surface models."""

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def fit(self, app) -> None:
        """
        Build the surface from a LiveSurfaceApp instance.

        Parameters
        ----------
        app : LiveSurfaceApp
            The live IBKR app object.  The model must read from:
                app.iv_dict   – {req_id: {"iv": float, "time": float, ...}}
                app.id_map    – {req_id: (expiry_str, strike_float)}
                app.quote_dict – {req_id: {"bid": float, "ask": float, ...}}
                app.spot_price – float
                app.is_delayed – bool

        After fit() returns, surface(), clean_df(), stats(), iv(),
        residuals(), and diagnostics() must all be safe to call.
        """

    # ------------------------------------------------------------------ #
    # Primary outputs                                                      #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def surface(self) -> pd.DataFrame | None:
        """
        Return the fitted surface pivot table, or None if unavailable.

        Returns
        -------
        pd.DataFrame | None
            index   = Expiry (str, YYYYMMDD)
            columns = Strike (float)
            values  = IV (float, decimal)
        """

    @abstractmethod
    def clean_df(self) -> pd.DataFrame:
        """
        Return the point-level cleaned/filtered DataFrame.

        Returns
        -------
        pd.DataFrame
            Must contain at least: Expiry (str), Strike (float), IV (float).
            RV engine also uses: Bid, Ask, SpreadPct, QuoteQuality.
        """

    @abstractmethod
    def stats(self) -> dict:
        """
        Return a data-quality stats dictionary consumed by the dashboard.
        See module docstring for required keys.
        """

    # ------------------------------------------------------------------ #
    # Secondary outputs                                                    #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def iv(self, expiry: str, strike: float) -> float | None:
        """
        Return the model IV for a single (expiry, strike) pair.

        Parameters
        ----------
        expiry : str   e.g. "20261219"
        strike : float e.g. 480.0

        Returns
        -------
        float | None
            Interpolated model IV, or None if unavailable.
        """

    @abstractmethod
    def residuals(self) -> pd.DataFrame:
        """
        Return per-point residuals between raw IVs and the model surface.

        Returns
        -------
        pd.DataFrame with columns:
            Expiry       (str)
            Strike       (float)
            RawIV        (float)  – the cleaned market IV
            SurfaceIV    (float)  – the model's fitted IV at this point
            ResidualVol  (float)  – (RawIV - SurfaceIV) * 100  [vol points]
                                    positive = option is rich vs the model

        IMPORTANT: ResidualVol MUST be in vol points (×100) for all
        subclasses.  The RV engine threshold RELVAL_MIN_ABS_VOL and all
        downstream display/logging code assume this unit.
        """

    @abstractmethod
    def diagnostics(self) -> dict:
        """
        Return a human-readable diagnostic summary for logging.
        See module docstring for required keys.
        """

    # ------------------------------------------------------------------ #
    # Shared helpers (available to all subclasses)                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _interpolate_iv(pivot: pd.DataFrame, expiry: str, strike: float) -> float | None:
        """
        Bilinear-style interpolation: first interpolate across the strike axis
        for the two bracketing expiries, then interpolate across expiry index.

        This is the default implementation used by iv().  Subclasses that have
        a closed-form parametric model should override iv() instead.
        """
        if pivot is None or pivot.empty:
            return None

        strikes = pivot.columns.astype(float).to_numpy()
        expiries = pivot.index.tolist()

        # ---- Strike-axis lookup for a single expiry row -----------------
        def interp_strike(row):
            ivs = row.astype(float).to_numpy()
            valid = ~np.isnan(ivs)
            if valid.sum() == 0:
                return np.nan
            return float(np.interp(strike, strikes[valid], ivs[valid]))

        # ---- Case 1: expiry is an exact row in the pivot ----------------
        if expiry in expiries:
            val = interp_strike(pivot.loc[expiry])
            return val if not np.isnan(val) else None

        # ---- Case 2: interpolate between two bracketing expiries --------
        expiries_sorted = sorted(expiries)
        before = [e for e in expiries_sorted if e <= expiry]
        after  = [e for e in expiries_sorted if e >  expiry]

        if not before:
            val = interp_strike(pivot.loc[expiries_sorted[0]])
            return val if not np.isnan(val) else None

        if not after:
            val = interp_strike(pivot.loc[expiries_sorted[-1]])
            return val if not np.isnan(val) else None

        e0, e1 = before[-1], after[0]
        v0 = interp_strike(pivot.loc[e0])
        v1 = interp_strike(pivot.loc[e1])

        if np.isnan(v0) or np.isnan(v1):
            return None

        # Linear interpolation in expiry-string space (ordinal, good enough
        # for now; SVI model will use time-to-expiry in years instead).
        t0, t1, tq = int(e0), int(e1), int(expiry)
        w = (tq - t0) / (t1 - t0) if t1 != t0 else 0.5
        return float(v0 * (1 - w) + v1 * w)
