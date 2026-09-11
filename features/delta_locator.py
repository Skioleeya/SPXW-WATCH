"""
L3 — Delta 定位器。
===================
唯一职责：在券商推送的 Delta 序列上做插值，定位出"恰好 25 Delta"那个位置对应的
行权价与 IV。

关键合规点：**不做本地 BSM 重算**
----------------------------------
需要 25Δ 合约的 IV 时，常见做法是用 BSM 反解每个行权价的 Delta，再挑最接近 0.25
的那个。本系统明确禁止这条路——Delta 全部来自 IBKR 的 MODEL_OPTION 推送。

这里做的是**对券商给出的 (Delta, Strike, IV) 点列做插值**：Delta 是自变量，
行权价与 IV 是因变量。这不是重新定价，只是把离散的券商报价还原成连续曲线，
和"用市场报价画微笑"是同一类操作。

为什么必须在 Delta 空间插值
---------------------------
0DTE 的行权价间隔是 5 点，而 25Δ 的位置几乎总是落在两档之间。若直接取"最接近
25Δ 的那一档"，得到的可能是 22Δ 或 28Δ，Skew 读数会在相邻档之间反复跳变，
掩盖真实趋势。

依赖：L0。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from config import loader

_CFG = "features"


@dataclass(frozen=True, slots=True)
class DeltaMatch:
    """插值定位的结果。"""

    target_delta: float
    strike: float
    iv: float
    interpolated: bool


class DeltaLocator:
    """在 (Delta, Strike, IV) 点列上做线性插值定位。"""

    __slots__ = ("_tolerance", "_min_points")

    def __init__(self, feat_cfg: dict) -> None:
        self._tolerance = loader.as_float(
            feat_cfg, "skew_delta_tolerance", module=_CFG
        )
        self._min_points = loader.as_int(feat_cfg, "skew_min_points", module=_CFG)

    def locate(
        self,
        samples: Iterable[tuple[float | None, float, float]],
        target: float,
    ) -> DeltaMatch | None:
        """
        定位目标 Delta。

        Parameters
        ----------
        samples
            ``(delta, strike, iv)`` 三元组序列。``delta`` 为 ``None`` 的项会被跳过
            （说明该合约这次没有推送 Greeks）。
        target
            目标 Delta。Put 传负值（如 ``-0.25``），Call 传正值（如 ``+0.25``）。

        Returns
        -------
        DeltaMatch | None
            落在点列范围内时返回插值结果；落在范围外时，只有当最近的样本与目标
            的差距在容差内才返回，否则返回 ``None`` 表示本次不可用。
        """
        valid = sorted(
            (
                (float(delta), float(strike), float(iv))
                for delta, strike, iv in samples
                if delta is not None
            ),
            key=lambda item: item[0],
        )

        if len(valid) < self._min_points:
            return None

        for (d0, s0, v0), (d1, s1, v1) in zip(valid, valid[1:]):
            if d0 <= target <= d1:
                if d1 == d0:
                    return DeltaMatch(target, s0, v0, False)
                weight = (target - d0) / (d1 - d0)
                return DeltaMatch(
                    target_delta=target,
                    strike=s0 + weight * (s1 - s0),
                    iv=v0 + weight * (v1 - v0),
                    interpolated=True,
                )

        # 目标落在样本范围之外：允许用最近的样本，但必须在容差内。
        nearest = min(valid, key=lambda item: abs(item[0] - target))
        if abs(nearest[0] - target) <= self._tolerance:
            return DeltaMatch(target, nearest[1], nearest[2], False)
        return None

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def interpolate_iv_at_strike(
        samples: Iterable[tuple[float, float]],
        strike: float,
    ) -> float | None:
        """
        在 (Strike, IV) 点列上插值出给定行权价的 IV。

        用于求 ATM IV——现价通常落在两档行权价之间，直接取最近档会在整数关口
        产生跳变。
        """
        valid = sorted(
            ((float(s), float(v)) for s, v in samples), key=lambda item: item[0]
        )
        if not valid:
            return None
        if len(valid) == 1:
            return valid[0][1]

        for (s0, v0), (s1, v1) in zip(valid, valid[1:]):
            if s0 <= strike <= s1:
                if s1 == s0:
                    return v0
                weight = (strike - s0) / (s1 - s0)
                return v0 + weight * (v1 - v0)

        # 超出范围：钳制到端点，避免外推出不存在的值。
        return valid[0][1] if strike < valid[0][0] else valid[-1][1]

    @property
    def tolerance(self) -> float:
        return self._tolerance
