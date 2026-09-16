"""
L5 — ATM 读数汇总。
====================
唯一职责：把逐档的 ``ImpulseCell`` 与 Skew 点折叠成一个 ``AtmSnapshot``。

从 ``feature_engine.py`` 原样拆出（拆出原因：单文件 <400 行的机械门禁，
且"编排流水线"与"汇总平值读数"是两件事）。逻辑、变量名、注释均未改动。

为什么平值读数要回存储取**另一侧**
----------------------------------
热力图每档只保留虚值一侧（那是展示选择）。如果直接从 ``cells`` 里凑平值 IV 或
跨式价，会得到"平值档恰好是 Call 时只能看到 Call"的偏差 —— 偏斜陡时能到
1 个波动率点以上。所以这里按 ``(atm_strike, right, expiry)`` 回到存储取两侧。

依赖：L0（contracts）、L5 内部（``StrikeWindow``）。
"""

from __future__ import annotations

from contracts.enums import OptionRight
from contracts.feature import AtmSnapshot, ImpulseCell
from contracts.tick import OptionRef

from features.strike_window import StrikeWindow


def build_atm(
    store,
    cells: tuple[ImpulseCell, ...],
    spot: float,
    skew_point,
    now: float,
) -> AtmSnapshot:
    """
    汇总平值读数。

    ``store`` 是鸭子类型的 tick 存储，只用 ``latest_option(ref)``。
    """
    atm_strike = StrikeWindow.nearest_strike((c.strike for c in cells), spot)

    atm_delta = None
    if atm_strike is not None:
        for cell in cells:
            if cell.strike == atm_strike and cell.delta is not None:
                atm_delta = cell.delta
                break

    return AtmSnapshot(
        spot=spot,
        atm_strike=atm_strike,
        atm_iv=_atm_iv(store, cells, atm_strike, skew_point),
        atm_delta=atm_delta,
        straddle_price=_straddle(store, cells, atm_strike),
        put25_iv=skew_point.put25_iv if skew_point else None,
        call25_iv=skew_point.call25_iv if skew_point else None,
        skew_25d_vol_points=(
            skew_point.skew_25d_vol_points if skew_point else None
        ),
        butterfly_vol_points=(
            skew_point.butterfly_vol_points if skew_point else None
        ),
        ts=now,
    )


def _atm_iv(
    store,
    cells: tuple[ImpulseCell, ...],
    atm_strike: float | None,
    skew_point,
) -> float | None:
    """
    平值 IV。

    优先取平值档 Put 与 Call 的均值——热力图每档只保留虚值一侧，直接用它
    会得到"平值档恰好是 Call 时只能看到 Call IV"的偏差，在偏斜较陡时这个
    偏差可以到 1 个波动率点以上。两侧都拿不到时才退回微笑插值。
    """
    if atm_strike is not None and cells:
        expiry = cells[0].ref.expiry
        sides: list[float] = []
        for right in (OptionRight.PUT, OptionRight.CALL):
            ref = OptionRef(strike=float(atm_strike), right=right, expiry=expiry)
            tick = store.latest_option(ref)
            if tick is not None:
                sides.append(float(tick.iv))
        if len(sides) == 2:
            return sum(sides) / 2.0
        if len(sides) == 1:
            return sides[0]

    return skew_point.atm_iv if skew_point else None


def _straddle(
    store,
    cells: tuple[ImpulseCell, ...],
    atm_strike: float | None,
) -> float | None:
    """
    平值跨式价格 = 同档 Put + Call 的期权价之和。

    热力图每档只保留 OTM 一侧，所以这里必须回到存储里把另一侧也取出来。
    """
    if atm_strike is None or not cells:
        return None
    expiry = cells[0].ref.expiry

    total = 0.0
    for right in (OptionRight.PUT, OptionRight.CALL):
        ref = OptionRef(strike=float(atm_strike), right=right, expiry=expiry)
        tick = store.latest_option(ref)
        if tick is None or tick.opt_price is None:
            return None
        total += float(tick.opt_price)
    return total
