"""
models/svi_reporting.py
========================
SVISurfaceModel 的报告 / 诊断输出（从 svi_surface_model.py 原样拆出）。

拆出原因：单文件 <400 行的机械门禁；"标定"、"模型接口"、"报告输出"是三件事。

本模块只提供 SVIReportingMixin：一组纯输出方法（不修改任何模型状态），
由 SVISurfaceModel 混入。方法签名与返回结构逐字保持原样，因此外部调用点
（dash_surface.py、RV 信号引擎、日报脚本）零改动。
"""

import numpy as np
import pandas as pd

from models.svi_fit import svi_fit_params

# 与原版的差异：原版从 models/svi_fit.py import 三个写死的常量。本项目按第 3 条
# 「禁止硬编码」把它们搬进 ``config/surface.json``，改由 svi_fit_params() 读。
# 每次调用只多一次 frozen dataclass 构造（config.loader 已缓存 JSON），可忽略。


class SVIReportingMixin:
    """
    Reporting / diagnostics half of SVISurfaceModel.

    Mixin: expects the host class to provide
        self._fitted            : bool
        self._fit_diagnostics   : {expiry: fit_result}
        self._params            : {expiry: params}
        self._raw               : RawSurfaceModel
        self.MODEL_NAME         : str
        self._require_fit()     : raise if fit() not called
    """

    def fit_summary(self) -> pd.DataFrame:
        """
        Returns one row per expiry showing SVI calibration quality.

        This is used for diagnostics and future guardrails.
        """
        self._require_fit()
        p = svi_fit_params()

        rows = []

        for expiry, result in (self._fit_diagnostics or {}).items():
            success = bool(result.get("success", False))
            rmse = result.get("rmse")
            num_points = result.get("num_points", 0)
            reason = result.get("reason", "")

            if rmse is None or pd.isna(rmse):
                rmse_vol = np.nan
            else:
                rmse_vol = float(rmse) * 100.0

            if not success:
                status = "FAIL"
            elif rmse_vol <= p.good_rmse_vol_points:
                status = "GOOD"
            elif rmse_vol <= p.warn_rmse_vol_points:
                status = "WARN"
            else:
                status = "BAD"

            cal_arb = bool(result.get("calendar_arb", False))

            rows.append({
                "Expiry": expiry,
                "Success": success,
                "NumPoints": int(num_points),
                "RMSE": rmse,
                "RMSEVol": rmse_vol,
                "Status": status,
                "CalendarArb": cal_arb,
                "Reason": reason,
            })

        if not rows:
            return pd.DataFrame(
                columns=[
                    "Expiry",
                    "Success",
                    "NumPoints",
                    "RMSE",
                    "RMSEVol",
                    "Status",
                    "Reason",
                ]
            )

        return (
            pd.DataFrame(rows)
            .sort_values("Expiry")
            .reset_index(drop=True)
        )

    def _expiry_fit_status(self, expiry) -> str:
        """
        Returns GOOD/WARN/BAD/FAIL/UNKNOWN for one expiry.
        """
        expiry = str(expiry)

        result = (self._fit_diagnostics or {}).get(expiry)

        p = svi_fit_params()

        if not result:
            return "UNKNOWN"

        if not result.get("success", False):
            return "FAIL"

        rmse = result.get("rmse")

        if rmse is None or pd.isna(rmse):
            return "FAIL"

        rmse_vol = float(rmse) * 100.0

        if rmse_vol <= p.good_rmse_vol_points:
            return "GOOD"

        if rmse_vol <= p.warn_rmse_vol_points:
            return "WARN"

        return "BAD"
    
    def expiry_diagnostics(self, expiry) -> dict:
        """
        Returns fit diagnostics for one expiry.

        Used by RV candidates and dashboard panels to show whether
        a signal came from a healthy SVI fit or fallback logic.
        """
        self._require_fit()

        expiry = str(expiry)

        status = self._expiry_fit_status(expiry)
        allowed = svi_fit_params().allowed_statuses

        result = (self._fit_diagnostics or {}).get(expiry, {})

        used_fallback = status not in allowed

        rmse = result.get("rmse")
        rmse_vol = float(rmse) * 100.0 if rmse is not None and not pd.isna(rmse) else np.nan

        return {
            "Expiry": expiry,
            "FitStatus": status,
            "UsedFallback": used_fallback,
            "RMSE": rmse,
            "RMSEVol": rmse_vol,
            "NumPoints": result.get("num_points"),
            "Reason": result.get("reason", ""),
        }

    def residuals(self) -> pd.DataFrame:
        """
        Return per-point (RawIV - SVI_IV) residuals.

        This is where the real value of SVI shows up: residuals measure
        how far each market quote sits from the fitted parametric smile,
        giving cleaner RV signals than the raw model's local-smoothing approach.

        ⚠️ **逐点 = 逐合约**，同一个 ``(Expiry, Strike)`` 上 Put 与 Call 各一行。
        ``pivot_table`` 拟合曲面时对同档两侧取 **mean**，而这里减去的是**单侧**
        的原始行 ⇒ ``ResidualVol`` 报的是"单侧 IV 与该档双侧均值对应的曲面值"之差。
        真实行情下 Put IV ≠ Call IV，于是同档两行常常**一正一负** ——
        所以 ``Right`` 列必须一路带到前端，否则两个相反信号会重叠成一个。
        """
        self._require_fit()

        clean_df = self._raw.clean_df()

        if clean_df.empty:
            return pd.DataFrame(
                columns=["Expiry", "Strike", "Right", "RawIV", "SurfaceIV", "ResidualVol"]
            )

        keep_cols = [
            c for c in [
                "Expiry",
                "Strike",
                "Right",
                "IV",
                "Bid",
                "Ask",
                "Mid",
                "Spread",
                "SpreadPct",
            ]
            if c in clean_df.columns
        ]

        df = clean_df[keep_cols].copy()
        df = df.rename(columns={"IV": "RawIV"})

        df["SurfaceIV"] = df.apply(
            lambda row: self.iv(
                row["Expiry"],
                row["Strike"],
            ),
            axis=1,
        )

        df["ResidualVol"] = (df["RawIV"] - df["SurfaceIV"]) * 100.0

        return df.reset_index(drop=True)

    def diagnostics(self) -> dict:
        self._require_fit()

        s = self._raw.stats()

        fit_results = self._fit_diagnostics or {}

        successful = [
            v for v in fit_results.values()
            if v.get("success")
        ]

        failed = [
            v for v in fit_results.values()
            if not v.get("success")
        ]

        rmse_values = [
            v.get("rmse")
            for v in successful
            if v.get("rmse") is not None
        ]

        if rmse_values:
            avg_rmse = float(np.nanmean(rmse_values))
            max_rmse = float(np.nanmax(rmse_values))
            min_rmse = float(np.nanmin(rmse_values))
        else:
            avg_rmse = None
            max_rmse = None
            min_rmse = None
            
        fit_summary = self.fit_summary()
        svi_fallback_fits = (
            int((~fit_summary["Status"].isin(svi_fit_params().allowed_statuses)).sum())
            if not fit_summary.empty
            else 0
        )

        return {
            "model_name": self.MODEL_NAME,
            "surface_ok": s.get("surface_ok", False),
            "num_expiries": s.get("num_expiries", 0),
            "num_strikes": s.get("num_strikes", 0),
            "clean_count": s.get("clean_count", 0),
            "fit_quality": avg_rmse,
            "avg_rmse": avg_rmse,
            "max_rmse": max_rmse,
            "min_rmse": min_rmse,
            "svi_fits_succeeded": len(successful),
            "svi_fits_failed": len(failed),
            "svi_params": self._params,
            "fit_details": fit_results,
            "fit_summary": fit_summary,
            "svi_good_fits": int((fit_summary["Status"] == "GOOD").sum()) if not fit_summary.empty else 0,
            "svi_warn_fits": int((fit_summary["Status"] == "WARN").sum()) if not fit_summary.empty else 0,
            "svi_bad_fits": int((fit_summary["Status"] == "BAD").sum()) if not fit_summary.empty else 0,
            "svi_failed_fits": int((fit_summary["Status"] == "FAIL").sum()) if not fit_summary.empty else 0,
            "svi_fallback_fits": svi_fallback_fits,
        }
