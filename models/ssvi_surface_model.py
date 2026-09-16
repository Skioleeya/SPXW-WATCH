"""
models/ssvi_surface_model.py
============================
SSVI (Surface SVI) — globally calendar-arbitrage-free implied-vol surface.

What is SSVI?
-------------
Per-expiry SVI fits each smile independently, which can produce calendar
arbitrage (near-term total variance exceeding back-dated variance for some k).
SSVI avoids this by parameterizing the *whole surface* jointly:

    w(k, T) = θ_T/2 * (1 + ρ·φ_T·k + sqrt((φ_T·k + ρ)² + (1−ρ²)))

where:
    θ_T = ATM total implied variance for expiry T  (per-expiry, extracted
          from data, then monotone-enforced so θ_T is non-decreasing in T)
    φ_T = η / sqrt(θ_T)   (simplified Heston-like wing function)
    ρ   = global skew parameter ∈ (−1, 1)
    η   = global wing-slope parameter > 0

Global calibration
------------------
Only (ρ, η) are calibrated jointly across all expiry/strike pairs by
minimizing the vega-weighted mean-squared total-variance residual.

Arbitrage guarantees
--------------------
1. Calendar arbitrage: θ_T is monotone-enforced (cummax over sorted T),
   so ∂w/∂T ≥ 0 is satisfied by construction.
2. Butterfly arbitrage: the Gatheral-Jacquier condition η·(1 + |ρ|) ≤ 4
   is enforced as a calibration constraint.

References
----------
Gatheral & Jacquier (2014): "Arbitrage-free SVI volatility surfaces"
    https://doi.org/10.1080/14697688.2013.819986

Module layout
-------------
For the <400-line-per-file gate the math / calibration half was split into
models/ssvi_math.py (ssvi_total_variance / ssvi_iv / _extract_atm_theta /
_enforce_calendar_monotonicity / _calibrate_ssvi + 常量).  本文件只保留
SSVISurfaceModel 本体；原本可从本模块导入的名字全部在下面 re-export。
"""

import numpy as np
import pandas as pd
import time

from models.base_surface_model import BaseSurfaceModel
from models.raw_surface_model import RawSurfaceModel
from models.svi_math import (
    compute_forward_price,
    iv_to_total_variance,
    total_variance_to_iv,
    log_moneyness,
)
from models.svi_surface_model import year_fraction_from_expiry
from models.market_params import get_market_params

# Re-exported from models/ssvi_math.py so that existing imports
# (e.g. `from models.ssvi_surface_model import ssvi_total_variance`)
# keep working unchanged.
#
# 与原版的差异：原版这里还 re-export 了 SSVI_N_STARTS / SSVI_*_RMSE_VOL /
# MIN_POINTS_FOR_SSVI / MIN_EXPIRIES_FOR_SSVI 五个常量。本项目按第 3 条
# 「禁止硬编码」把它们搬进 ``config/surface.json`` —— 常量不再存在于代码里，
# 这组 re-export 随之删除（保留等于在配置之外再留一份真相）。
from models.ssvi_math import (
    ssvi_total_variance,
    ssvi_iv,
    _extract_atm_theta,
    _enforce_calendar_monotonicity,
    _calibrate_ssvi,
)
from models.surface_params import ssvi_fit_params


class SSVISurfaceModel(BaseSurfaceModel):
    """
    SSVI surface model — globally calendar-arbitrage-free.

    Calibrates two global parameters (ρ, η) against all expiry/strike
    pairs simultaneously. Per-expiry ATM variances θ_T are extracted from
    data and monotone-enforced before calibration.
    """

    def __init__(self):
        self._raw = RawSurfaceModel()
        self._rho: float | None = None
        self._eta: float | None = None
        self._theta_map: dict = {}   # {expiry: (theta, t)}
        self._pivot: pd.DataFrame | None = None
        self._cal_result: dict = {}
        self._fitted = False
        self._last_fit_log_time = 0.0
        self._spot: float = 0.0
        self._mkt: dict = {}

    def _require_fit(self):
        if not self._fitted:
            raise RuntimeError("SSVISurfaceModel: call fit() before accessing results.")

    # ── fit ──────────────────────────────────────────────────────────────

    def fit(self, app) -> None:
        self._raw.fit(app)
        self._fitted = True

        clean_df = self._raw.clean_df()
        self._rho = None
        self._eta = None
        self._theta_map = {}
        self._pivot = None
        self._cal_result = {}

        if clean_df is None or clean_df.empty:
            return

        if not self._raw.stats().get("surface_ok"):
            return

        spot = float(getattr(app, "spot_price", 0.0) or 0.0)
        if spot <= 0:
            return

        p = ssvi_fit_params()

        n_expiries = clean_df["Expiry"].nunique()
        if n_expiries < p.min_expiries or len(clean_df) < p.min_points:
            return

        self._spot = spot
        self._mkt = get_market_params()

        # Step 1: extract per-expiry ATM total variance.
        raw_theta = _extract_atm_theta(clean_df, spot, self._mkt)
        if len(raw_theta) < p.min_expiries:
            return

        # Step 2: enforce calendar monotonicity.
        self._theta_map = _enforce_calendar_monotonicity(raw_theta)

        # Step 3: calibrate global (ρ, η).
        self._cal_result = _calibrate_ssvi(clean_df, spot, self._theta_map, self._mkt)

        if not self._cal_result.get("success"):
            return

        self._rho = self._cal_result["rho"]
        self._eta = self._cal_result["eta"]

        # Step 4: build IV pivot using SSVI where calibration succeeded,
        # falling back to the raw smoothed surface where SSVI produces
        # non-finite/non-positive values.
        raw_pivot = self._raw.surface()
        if raw_pivot is None:
            return

        ssvi_pivot = self._build_ssvi_pivot(raw_pivot, clean_df)
        self._pivot = ssvi_pivot

        rmse_vol = self._cal_result.get("rmse_vol")
        now = time.time()
        if now - self._last_fit_log_time > 30:
            rmse_str = f"{rmse_vol:.4f}" if rmse_vol is not None else "n/a"
            print(
                f"[SSVI] fitted {len(self._theta_map)} expiries | "
                f"ρ={self._rho:.3f} η={self._eta:.3f} | "
                f"RMSE={rmse_str} vol pts"
            )
            self._last_fit_log_time = now

    def _build_ssvi_pivot(self, raw_pivot, clean_df) -> pd.DataFrame:
        """
        Replaces raw smoothed surface values with SSVI-fitted IVs.
        Falls back to raw value for any point that produces non-finite IV.
        """
        pivot = raw_pivot.copy()

        for expiry in pivot.index:
            expiry_str = str(expiry)
            if expiry_str not in self._theta_map:
                continue

            theta, t = self._theta_map[expiry_str]
            f = compute_forward_price(
                spot=self._spot,
                t=t,
                risk_free_rate=self._mkt["risk_free_rate"],
                dividend_yield=self._mkt["dividend_yield"],
            )

            strikes = pivot.columns.astype(float).to_numpy()
            ks = log_moneyness(strikes, f)

            ivs_ssvi = ssvi_iv(ks, t, theta, self._rho, self._eta)

            # Replace only finite, positive, sensible values.
            for j, (iv_s, iv_raw) in enumerate(zip(ivs_ssvi, pivot.loc[expiry].values)):
                if np.isfinite(iv_s) and 0.001 < iv_s < 5.0:
                    pivot.iloc[pivot.index.get_loc(expiry), j] = float(iv_s)

        return pivot

    # ── BaseSurfaceModel interface ────────────────────────────────────────

    def surface(self) -> pd.DataFrame | None:
        self._require_fit()
        return self._pivot

    def clean_df(self) -> pd.DataFrame:
        self._require_fit()
        return self._raw.clean_df()

    def stats(self) -> dict:
        self._require_fit()
        s = self._raw.stats().copy()
        s["ssvi_calibrated"] = self._rho is not None
        s["ssvi_rho"] = self._rho
        s["ssvi_eta"] = self._eta
        s["ssvi_n_expiries"] = len(self._theta_map)
        return s

    def iv(self, expiry: str, strike: float) -> float | None:
        self._require_fit()

        if self._rho is None or expiry not in self._theta_map:
            return self._raw.iv(expiry, strike)

        theta, t = self._theta_map[expiry]
        f = compute_forward_price(
            spot=self._spot,
            t=t,
            risk_free_rate=self._mkt["risk_free_rate"],
            dividend_yield=self._mkt["dividend_yield"],
        )
        k = float(log_moneyness(strike, f))
        iv_val = float(ssvi_iv(k, t, theta, self._rho, self._eta))

        if not np.isfinite(iv_val) or iv_val <= 0 or iv_val > 5.0:
            return self._raw.iv(expiry, strike)

        return iv_val

    def residuals(self) -> pd.DataFrame:
        self._require_fit()

        clean_df = self._raw.clean_df()
        if clean_df.empty:
            return pd.DataFrame(
                columns=["Expiry", "Strike", "RawIV", "SurfaceIV", "ResidualVol"]
            )

        keep_cols = [
            c for c in ["Expiry", "Strike", "IV", "Bid", "Ask", "Mid", "Spread", "SpreadPct"]
            if c in clean_df.columns
        ]
        df = clean_df[keep_cols].copy().rename(columns={"IV": "RawIV"})

        df["SurfaceIV"] = df.apply(
            lambda row: self.iv(row["Expiry"], row["Strike"]),
            axis=1,
        )
        df["ResidualVol"] = (df["RawIV"] - df["SurfaceIV"]) * 100.0

        return df.reset_index(drop=True)

    def diagnostics(self) -> dict:
        self._require_fit()

        s = self._raw.stats()
        p = ssvi_fit_params()

        rmse_vol = self._cal_result.get("rmse_vol")

        if rmse_vol is None:
            fit_quality = None
            fit_status = "FAIL"
        elif rmse_vol <= p.good_rmse_vol_points:
            fit_quality = rmse_vol
            fit_status = "GOOD"
        elif rmse_vol <= p.warn_rmse_vol_points:
            fit_quality = rmse_vol
            fit_status = "WARN"
        else:
            fit_quality = rmse_vol
            fit_status = "BAD"

        return {
            "model_name": "SSVI",
            "surface_ok": s.get("surface_ok", False) and self._rho is not None,
            "num_expiries": s.get("num_expiries", 0),
            "num_strikes": s.get("num_strikes", 0),
            "clean_count": s.get("clean_count", 0),
            "fit_quality": fit_quality,
            "fit_status": fit_status,
            "ssvi_rho": self._rho,
            "ssvi_eta": self._eta,
            "ssvi_n_expiries_calibrated": len(self._theta_map),
            "cal_success": self._cal_result.get("success", False),
        }
