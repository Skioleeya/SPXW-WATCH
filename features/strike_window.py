"""
L5 — 行权价窗口与 OTM 选边。
=============================
唯一职责：在给定的一批合约里，挑出"以现价为中心、每个行权价只取虚值一侧"的
那一组，作为热力图的纵轴行。

为什么每个行权价只取一侧
------------------------
0DTE 的深实值合约几乎不成交、报价宽到无法使用，而 IV 微笑的信息几乎全部集中
在虚值一侧。对每个行权价取 OTM 合约，既能拿到完整的两翼，又省掉一半订阅量。

约定：行权价 < 现价取 Put，行权价 >= 现价取 Call。边界处的选择是任意的，因为
现价附近两侧 IV 几乎相等，且 ATM IV 走的是插值而不是取整档。

⚠️ "两侧几乎相等"在本系统里是**精确成立**的，但成立的原因要写清楚：它依赖
``config/ibkr.json::use_model_greeks = true`` —— IBKR 的 model IV 一个行权价只给
一个波动率，Put 与 Call 同值（2026-09-14 实测差 0.000）。若该开关被关掉，
``tick_router`` 会降级到 last / bid / ask 口径，两侧就不再同值（实测最新成交口径
差 5.5～6.3 波动率点），而热力图每个行权价只留一条时间序列 ⇒ 每次现价穿越行权价
都会打出一个假的 ΔIV 跳变。详见 ``features/heatmap_engine.py`` 模块注释。

依赖：L0（config / contracts）。
"""

from __future__ import annotations

from typing import Iterable

from config import loader
from contracts.enums import OptionRight
from contracts.tick import OptionRef

_CFG = "features"


class StrikeWindow:
    """ATM 居中窗口与 OTM 选边规则。"""

    __slots__ = ("_requested_each_side",)

    def __init__(self, feat_cfg: dict) -> None:
        self._requested_each_side = loader.as_int(
            feat_cfg, "heatmap_rows_each_side", module=_CFG
        )

    # ------------------------------------------------------------------ #
    # 选边
    # ------------------------------------------------------------------ #

    @staticmethod
    def otm_right(strike: float, spot: float) -> OptionRight:
        """行权价在现价下方取 Put，否则取 Call。"""
        return OptionRight.PUT if float(strike) < float(spot) else OptionRight.CALL

    # ------------------------------------------------------------------ #
    # 窗口
    # ------------------------------------------------------------------ #

    def window_strikes(
        self,
        strikes: Iterable[float],
        spot: float,
        each_side: int | None = None,
    ) -> tuple[float, ...]:
        """以现价为中心取上下各 ``each_side`` 档，返回升序行权价。"""
        if spot <= 0:
            return ()
        side = self._requested_each_side if each_side is None else int(each_side)
        if side <= 0:
            return ()

        ordered = sorted({float(s) for s in strikes})
        below = [s for s in ordered if s <= spot]
        above = [s for s in ordered if s > spot]
        return tuple(sorted(below[-side:] + above[:side]))

    def rows(
        self,
        refs: Iterable[OptionRef],
        spot: float,
        each_side: int | None = None,
    ) -> tuple[OptionRef, ...]:
        """
        返回热力图纵轴所需的合约：每个行权价一个 OTM 合约。

        只在 ``refs`` 里确实存在该方向的合约时才收录，避免下游拿到空洞。
        """
        available = {r.key(): r for r in refs}
        strikes = {r.strike for r in refs}
        window = self.window_strikes(strikes, spot, each_side)

        picked: list[OptionRef] = []
        for strike in window:
            right = self.otm_right(strike, spot)
            ref = available.get((strike, str(right)))
            if ref is None:
                # 该方向没订阅到，退回另一侧，至少让这一行有数据。
                ref = available.get((strike, str(right.opposite)))
            if ref is not None:
                picked.append(ref)
        return tuple(picked)

    # ------------------------------------------------------------------ #
    # ATM 定位
    # ------------------------------------------------------------------ #

    @staticmethod
    def nearest_strike(strikes: Iterable[float], spot: float) -> float | None:
        ordered = sorted({float(s) for s in strikes})
        if not ordered:
            return None
        return min(ordered, key=lambda s: abs(s - spot))

    def each_side(self) -> int:
        return self._requested_each_side
