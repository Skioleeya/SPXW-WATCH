"""
models/raw_surface_model.py
============================
Cleaned / interpolated surface model — current production behaviour.

This model wraps the exact same logic that previously lived inside
build_clean_surface() in live_surface.py.  The dashboard behaviour is
100% identical to before; the only difference is that the logic now lives
behind the BaseSurfaceModel interface so it can be swapped for SVI later.

Residuals
---------
Because this model's "surface" IS the cleaned raw data (interpolated and
smoothed), residuals are always 0 at the input points — there is no
parametric fit to deviate from.  The residuals() method therefore returns
zeros for all clean_df points.

This will change meaningfully once SVISurfaceModel is used: residuals will
then measure how far each market quote sits from the fitted SVI smile.

When to replace this model
--------------------------
Keep RawSurfaceModel until you have at least two weeks of replay data and
you are confident the RV signal engine is logging correctly.  Then add
SVISurfaceModel and compare residual behaviour between the two models
side-by-side before switching the dashboard over.

Module layout
-------------
The cleaning / interpolation pipeline itself lives in models/raw_cleaning.py
(extracted verbatim for the <400-line-per-file gate).

与原版的差异：原版这里还 re-export 了 raw_cleaning 的 13 个可调常量与
``_max_iv_age``。本项目按第 3 条「禁止硬编码」把它们搬进 ``config/surface.json``
（由 ``models/surface_params.py::cleaning_params()`` 读出）—— 常量不再存在于
代码里，这组 re-export 随之删除（保留等于在配置之外再留一份真相）。
现在只有 ``build_clean_surface`` 被 re-export。
"""

import numpy as np
import pandas as pd

from models.base_surface_model import BaseSurfaceModel

# Re-exported so that `from models.raw_surface_model import build_clean_surface`
# keeps working exactly as before.
from models.raw_cleaning import build_clean_surface


class RawSurfaceModel(BaseSurfaceModel):
    """
    Cleaned, interpolated, and lightly smoothed IV surface.

    This is the original surface logic extracted from build_clean_surface()
    and placed behind the BaseSurfaceModel interface.  No parametric fitting
    is performed — the surface is the data itself after cleaning.

    Attributes (readable after fit())
    ----------------------------------
    _pivot    : pd.DataFrame | None  — the final IV pivot table
    _clean_df : pd.DataFrame         — cleaned point-level data
    _stats    : dict                 — data-quality statistics
    _fitted   : bool                 — True after a successful fit()
    """

    MODEL_NAME = "RawSurface"

    def __init__(self):
        self._pivot: pd.DataFrame | None = None
        self._clean_df: pd.DataFrame = pd.DataFrame()
        self._stats: dict = {}
        self._fitted: bool = False

    # ------------------------------------------------------------------ #
    # BaseSurfaceModel interface                                           #
    # ------------------------------------------------------------------ #

    def fit(self, app) -> None:
        """
        Build the cleaned IV surface from a LiveSurfaceApp instance.

        Reads app.iv_dict, app.id_map, app.quote_dict, app.spot_price,
        and app.is_delayed.  All filtering and smoothing happens here.

        Parameters
        ----------
        app : LiveSurfaceApp
            The running IBKR API application object.
        """
        pivot, clean_df, stats = build_clean_surface(app)
        self._pivot   = pivot
        self._clean_df = clean_df
        self._stats    = stats
        self._fitted   = True

    def surface(self) -> pd.DataFrame | None:
        """Return the fitted IV pivot table (Expiry × Strike → IV)."""
        self._require_fit()
        return self._pivot

    def clean_df(self) -> pd.DataFrame:
        """Return the cleaned point-level DataFrame."""
        self._require_fit()
        return self._clean_df

    def stats(self) -> dict:
        """Return the data-quality stats dict."""
        self._require_fit()
        return self._stats
    
    def expiry_diagnostics(self, expiry) -> dict:
        """
        RawSurfaceModel does not calibrate per-expiry parametric fits,
        so this returns a neutral diagnostics object.
        """
        return {
            "Expiry": str(expiry),
            "FitStatus": "RAW",
            "UsedFallback": False,
            "RMSE": None,
            "RMSEVol": None,
            "NumPoints": None,
            "Reason": "",
        }

    def iv(self, expiry: str, strike: float) -> float | None:
        """
        Return the interpolated IV for a single (expiry, strike) pair.

        Uses the shared bilinear interpolation helper from BaseSurfaceModel.
        """
        self._require_fit()
        return self._interpolate_iv(self._pivot, expiry, strike)

    def residuals(self) -> pd.DataFrame:
        """
        Return per-point residuals.

        For RawSurfaceModel, SurfaceIV equals RawIV at every clean point
        (the surface IS the smoothed data), so ResidualVol is always 0.

        Note: the dashboard's RV signal engine uses a slightly different
        residual definition — it compares each point's IV against the
        *rest* of the smoothed surface, not against itself.  That logic
        lives in dash_surface.py (compute_relative_value_candidates) and
        is unchanged.  This residuals() method is for the replay analyser
        and SVISurfaceModel comparison — it will become meaningful once
        you switch to a parametric model.
        """
        self._require_fit()

        if self._clean_df.empty:
            return pd.DataFrame(
                columns=["Expiry", "Strike", "RawIV", "SurfaceIV", "ResidualVol"]
            )

        df = self._clean_df[["Expiry", "Strike", "IV"]].copy()
        df = df.rename(columns={"IV": "RawIV"})

        # Look up the smoothed surface value for each clean point.
        df["SurfaceIV"] = df.apply(
            lambda row: self._interpolate_iv(self._pivot, row["Expiry"], row["Strike"])
            if self._pivot is not None
            else np.nan,
            axis=1,
        )

        # ResidualVol is in vol points (×100) — same unit as SVISurfaceModel
        # and the dashboard threshold RELVAL_MIN_ABS_VOL (0.75 vol pts).
        df["ResidualVol"] = (df["RawIV"] - df["SurfaceIV"]) * 100.0

        return df.reset_index(drop=True)

    def diagnostics(self) -> dict:
        """Return a human-readable summary dict for logging."""
        self._require_fit()
        s = self._stats
        return {
            "model_name":   self.MODEL_NAME,
            "surface_ok":   s.get("surface_ok", False),
            "num_expiries": s.get("num_expiries", 0),
            "num_strikes":  s.get("num_strikes",  0),
            "clean_count":  s.get("clean_count",  0),
            "fit_quality":  None,   # no parametric fit; SVI will populate this
            "rejected_bad_iv":    s.get("rejected_bad_iv",    0),
            "rejected_outlier":   s.get("rejected_outlier",   0),
            "rejected_wide_quote": s.get("rejected_wide_quote", 0),
            "missing_quote":      s.get("missing_quote",      0),
        }

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _require_fit(self) -> None:
        """Raise if fit() has not been called yet."""
        if not self._fitted:
            raise RuntimeError(
                "RawSurfaceModel.fit(app) must be called before reading outputs."
            )
