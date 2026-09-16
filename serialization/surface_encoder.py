"""
L6 — 曲面摘要编码。
===================
唯一职责：把 ``SurfaceSummary`` 编码成前端残差图与模型诊断所需的 JSON。

为什么必须有上线条数
--------------------
``residuals`` 是**逐点**残差（当前单到期日实测 **50 点/模型**），而帧每 400 ms
推一次。多到期日扩展后点数按到期日数线性增长 —— 几百个点 × 每点 7 个字段，
体积会压过热力图位图本身（那是整帧最贵的部分）。

上限用**等间隔抽样**，不是"取残差最大的 N 个"
--------------------------------------------
残差图是**按行权价画的**（横轴 strike、纵轴残差）。取绝对值最大的 N 个，点会
全堆在两端 —— 曲面在翼部本来就拟合最差 —— 中间空掉，图上看不出拟合形状。
等间隔抽样保住空间分布，且结果确定（同一个输入永远给同一个子集，前端不会
两帧之间看到点的集合跳变）。

``limit >= len(residuals)`` 时 stride = 1 ⇒ 全量，不抽样。

IV 一律转波动率点
-----------------
与 ``SkewSerializer`` 同口径：内部计算全程用小数（0.14），出帧一律 ×100
（14.0）。换算只在这一处发生，避免两头各转一次导致 100 倍错误。

依赖：L0、L6（numeric）。
"""

from __future__ import annotations

from config import loader
from contracts.feature import SurfaceResidual, SurfaceSummary

from serialization.numeric import round_opt

_CFG = "serialization"


class SurfaceSerializer:
    """曲面摘要编码器。"""

    __slots__ = ("_residuals_limit", "_iv_decimals", "_price_decimals")

    def __init__(self, serial_cfg: dict) -> None:
        # as_positive 保证 >= 1：0 或负数会让 _pick() 的 stride 失去意义。
        self._residuals_limit = int(
            loader.as_positive(
                loader.as_int(serial_cfg, "surface_residuals_limit", module=_CFG),
                module=_CFG,
                key="surface_residuals_limit",
            )
        )
        self._iv_decimals = loader.as_int(serial_cfg, "iv_decimals", module=_CFG)
        self._price_decimals = loader.as_int(serial_cfg, "price_decimals", module=_CFG)

    # ------------------------------------------------------------------ #
    # 出口
    # ------------------------------------------------------------------ #

    def encode(self, summary: SurfaceSummary | None) -> dict | None:
        if summary is None:
            return None
        picked = self._pick(summary.residuals)
        return {
            "model": summary.model_name,
            "fitted": int(summary.fitted_expiries),
            "failed": int(summary.failed_expiries),
            "good": int(summary.good_fits),
            "warn": int(summary.warn_fits),
            "bad": int(summary.bad_fits),
            "fallback": int(summary.fallback_expiries),
            "avg_rmse": round_opt(summary.avg_rmse_vol_points, 3),
            "max_rmse": round_opt(summary.max_rmse_vol_points, 3),
            "healthy": bool(summary.is_healthy),
            "residuals": [self._residual(r) for r in picked],
            "residual_count": len(summary.residuals),
            "residual_shown": len(picked),
        }

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _residual(self, r: SurfaceResidual) -> dict:
        return {
            "expiry": r.expiry,
            "strike": round(float(r.strike), self._price_decimals),
            # 方向（"P" / "C"）。同一 (expiry, strike) 上 Put 与 Call 各出一条残差，
            # 真实行情下常一正一负 —— 前端按 (strike, right) 才能把两点分开画。
            # 空串表示来源未提供（老实现），不是错误。
            "right": r.right,
            "raw_iv": round(float(r.raw_iv) * 100.0, self._iv_decimals),
            "model_iv": round_opt(self._vol_points(r.model_iv), self._iv_decimals),
            "residual": round_opt(r.residual_vol_points, 3),
            "status": r.fit_status,
            "fallback": bool(r.used_fallback),
        }

    def _pick(self, residuals: tuple[SurfaceResidual, ...]) -> tuple[SurfaceResidual, ...]:
        """等间隔抽样到 ``_residuals_limit`` 条以内（保序，确定性）。"""
        n = len(residuals)
        limit = self._residuals_limit
        if n <= limit:
            return residuals
        stride = -(-n // limit)  # ceil，避免 math.ceil 引入浮点
        return residuals[::stride]

    @staticmethod
    def _vol_points(iv: float | None) -> float | None:
        """IV 小数 → 波动率点。``None`` 原样透传。"""
        if iv is None:
            return None
        return float(iv) * 100.0
