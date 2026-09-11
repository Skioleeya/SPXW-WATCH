"""
L6 — 行情剧本。
================
唯一职责：给定"会话时间"，回答"此刻的现价、平值 IV、以及任意行权价的 IV 与
Delta 应该是多少"。

这是纯函数式的市场模型，不持有任何状态、不产生随机副作用（随机数由调用方
按固定种子注入），因此同一个剧本可以被反复重放并得到一致结果——这对调试
"某个时刻热力图为什么是那个颜色"极其重要。

曲面形状
--------
用最简的二次对数微笑：

::

    x        = (行权价 / 现价 − 1) × 100          # 百分比虚实程度
    IV(x)    = ATM_IV + slope × x + curvature × x² / 10     # 单位：波动率点

``slope`` 为负值即"左高右低"的标准股指偏斜。Delta 用一条 logistic 近似，
斜率参数 ``delta_scale_pct`` 控制 25Δ 离平值有多远（0DTE 上这个距离很窄）。

依赖：L0（配置加载）。
"""

from __future__ import annotations

import math

from config import loader

_CFG = "simulator"

# 现价冲击的方向符号
_DIRECTION_SIGN = {"down": -1.0, "up": 1.0}


class Scenario:
    """一段可复现的行情剧本。"""

    __slots__ = (
        "_base_spot", "_base_atm_iv", "_slope", "_curvature",
        "_delta_scale", "_drift_per_min", "_shock_start",
        "_shock_ramp", "_shock_vol_points", "_shock_spot_points",
        "_shock_sign",
    )

    def __init__(self, sim_cfg: dict) -> None:
        m = _CFG
        self._base_spot = loader.as_float(sim_cfg, "base_spot", module=m)
        self._base_atm_iv = loader.as_float(sim_cfg, "base_atm_iv", module=m)
        self._slope = loader.as_float(sim_cfg, "skew_slope_per_pct", module=m)
        self._curvature = loader.as_float(sim_cfg, "smile_curvature", module=m)
        self._delta_scale = loader.as_float(sim_cfg, "delta_scale_pct", module=m)
        self._drift_per_min = loader.as_float(
            sim_cfg, "spot_drift_points_per_min", module=m
        )
        self._shock_start = loader.as_float(sim_cfg, "shock_start_s", module=m)
        self._shock_ramp = max(loader.as_float(sim_cfg, "shock_ramp_s", module=m), 1e-6)
        self._shock_vol_points = loader.as_float(sim_cfg, "shock_vol_points", module=m)
        self._shock_spot_points = loader.as_float(sim_cfg, "shock_spot_points", module=m)
        direction = loader.as_str(sim_cfg, "shock_direction", module=m).lower()
        self._shock_sign = _DIRECTION_SIGN.get(direction, -1.0)

    # ------------------------------------------------------------------ #
    # 冲击进度
    # ------------------------------------------------------------------ #

    def shock_progress(self, real_elapsed_s: float) -> float:
        """返回 ``[0, 1]`` 的冲击完成度（0 = 未开始，1 = 已完成）。"""
        if real_elapsed_s <= self._shock_start:
            return 0.0
        return min((real_elapsed_s - self._shock_start) / self._shock_ramp, 1.0)

    # ------------------------------------------------------------------ #
    # 现价路径
    # ------------------------------------------------------------------ #

    def spot_at(self, session_seconds: float, real_elapsed_s: float) -> float:
        """会话时间 + 真实经过时间 → 现价。"""
        drift = self._drift_per_min * (session_seconds / 60.0)
        shock = self._shock_sign * self._shock_spot_points * self.shock_progress(real_elapsed_s)
        return self._base_spot + drift + shock

    # ------------------------------------------------------------------ #
    # 波动率曲面
    # ------------------------------------------------------------------ #

    def atm_iv_at(self, real_elapsed_s: float) -> float:
        """平值 IV（小数）。冲击期间整体抬升，且冲击通常伴随偏斜变陡。"""
        progress = self.shock_progress(real_elapsed_s)
        vol_points = self._shock_vol_points * progress
        return self._base_atm_iv + vol_points / 100.0

    def iv_at(self, strike: float, spot: float, atm_iv: float) -> float:
        """给定行权价与现价的 IV（小数）。"""
        if spot <= 0:
            return atm_iv
        x = (strike / spot - 1.0) * 100.0
        vol_points = atm_iv * 100.0 + self._slope * x + self._curvature * (x * x) / 10.0
        return max(vol_points, 1.0) / 100.0

    # ------------------------------------------------------------------ #
    # Delta
    # ------------------------------------------------------------------ #

    def call_delta_at(self, strike: float, spot: float) -> float:
        """看涨 Delta，用 logistic 近似 0DTE 的陡峭 Delta 曲线。"""
        if spot <= 0:
            return 0.5
        x = (strike / spot - 1.0) * 100.0
        return 0.5 + 0.5 * math.tanh(-x / self._delta_scale)

    def put_delta_at(self, strike: float, spot: float) -> float:
        """看跌 Delta = 看涨 Delta − 1（无股息近似）。"""
        return self.call_delta_at(strike, spot) - 1.0

    def delta_for(self, strike: float, spot: float, is_put: bool) -> float:
        return (
            self.put_delta_at(strike, spot)
            if is_put
            else self.call_delta_at(strike, spot)
        )

    # ------------------------------------------------------------------ #
    # 行权价网格
    # ------------------------------------------------------------------ #

    @staticmethod
    def strike_grid(spot: float, step: float, each_side: int) -> tuple[float, ...]:
        """以现价为中心、按固定步长生成行权价格点。"""
        centre = round(spot / step) * step
        return tuple(
            round(centre + offset * step, 2)
            for offset in range(-each_side, each_side + 1)
        )
