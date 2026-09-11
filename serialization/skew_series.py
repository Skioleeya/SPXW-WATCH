"""
L4 — 25Δ 偏度与平值读数编码。
==============================
唯一职责：把 ``SkewPoint`` 序列与 ``AtmSnapshot`` 编码成前端折线图与顶部读数
所需的 JSON。

为什么用列式（columnar）而不是行式
----------------------------------
折线图有 4 条序列（Skew / ATM / 25Δ Put / 25Δ Call），行式编码会把键名重复
390 遍。列式把每个指标各放一个数组，载荷体积大约只有行式的三分之一，而
ECharts 的 ``dataset`` 原生支持列式输入。

时间轴同时给 ``ts``（epoch 秒）与 ``label``（市场时区 HH:MM）——只用 epoch
的话，前端拿浏览器本地时区去格式化，非美东的用户会看到错位的时间轴。

依赖：L0、L4（numeric）。
"""

from __future__ import annotations

from typing import Iterable

from config import loader
from contracts.feature import AtmSnapshot, SkewPoint

from serialization.numeric import round_opt

_CFG = "serialization"


class SkewSerializer:
    """偏度序列与平值读数编码器。"""

    __slots__ = ("_iv_decimals", "_price_decimals", "_clock")

    def __init__(self, serial_cfg: dict, clock) -> None:
        self._iv_decimals = loader.as_int(serial_cfg, "iv_decimals", module=_CFG)
        self._price_decimals = loader.as_int(
            serial_cfg, "price_decimals", module=_CFG
        )
        self._clock = clock

    # ------------------------------------------------------------------ #
    # 折线序列
    # ------------------------------------------------------------------ #

    def encode_series(self, points: Iterable[SkewPoint]) -> dict:
        """
        编码整条 25Δ 偏度序列。

        同时给出 ``skew_min`` / ``skew_max``，让前端能画一条稳定的纵轴参考线，
        而不是每帧自动缩放导致折线"呼吸"。
        """
        rows = list(points)
        skew_values = [
            p.skew_25d_vol_points for p in rows if p.skew_25d_vol_points is not None
        ]

        return {
            "ts": [round(float(p.ts), 3) for p in rows],
            "label": [self._label(p.ts) for p in rows],
            "skew": [round_opt(p.skew_25d_vol_points, 3) for p in rows],
            "atm": [round_opt(self._as_vol_points(p.atm_iv), 3) for p in rows],
            "put25": [round_opt(self._as_vol_points(p.put25_iv), 3) for p in rows],
            "call25": [round_opt(self._as_vol_points(p.call25_iv), 3) for p in rows],
            "spot": [round(float(p.spot), self._price_decimals) for p in rows],
            "skew_min": round(min(skew_values), 3) if skew_values else None,
            "skew_max": round(max(skew_values), 3) if skew_values else None,
            "count": len(rows),
        }

    def encode_latest(self, point: SkewPoint | None) -> dict | None:
        if point is None:
            return None
        return {
            "ts": round(float(point.ts), 3),
            "label": self._label(point.ts),
            "skew": round_opt(point.skew_25d_vol_points, 3),
            "atm": round_opt(self._as_vol_points(point.atm_iv), 3),
            "put25": round_opt(self._as_vol_points(point.put25_iv), 3),
            "call25": round_opt(self._as_vol_points(point.call25_iv), 3),
            "put25_strike": round_opt(point.put25_strike, self._price_decimals),
            "call25_strike": round_opt(point.call25_strike, self._price_decimals),
            "butterfly": round_opt(point.butterfly_vol_points, 3),
            "quality": str(point.quality),
        }

    # ------------------------------------------------------------------ #
    # 平值读数
    # ------------------------------------------------------------------ #

    def encode_atm(self, atm: AtmSnapshot | None) -> dict | None:
        if atm is None:
            return None
        return {
            "spot": round(float(atm.spot), self._price_decimals),
            "atm_strike": round_opt(atm.atm_strike, self._price_decimals),
            "atm_iv": round_opt(self._as_vol_points(atm.atm_iv), 3),
            "atm_delta": round_opt(atm.atm_delta, 3),
            "straddle": round_opt(atm.straddle_price, self._price_decimals),
            "put25_iv": round_opt(self._as_vol_points(atm.put25_iv), 3),
            "call25_iv": round_opt(self._as_vol_points(atm.call25_iv), 3),
            "skew_25d": round_opt(atm.skew_25d_vol_points, 3),
            "butterfly": round_opt(atm.butterfly_vol_points, 3),
            "ts": round(float(atm.ts), 3),
        }

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _label(self, ts: float) -> str:
        return self._clock.bucket_label(self._clock.bucket_index_of_ts(ts))

    def _as_vol_points(self, iv: float | None) -> float | None:
        """
        IV 小数 → 波动率点。

        内部计算全程用小数（0.14），前端展示与比较一律用波动率点（14.0），
        换算只在这一处发生，避免两头各转一次导致 100 倍错误。
        """
        if iv is None:
            return None
        return float(iv) * 100.0
