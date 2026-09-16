"""
L6 — 网格点明细编码。
=====================
唯一职责：把 ``ImpulseCell`` 列表编码成前端悬停提示（tooltip）与明细表所需的
扁平结构。

载荷取舍
--------
热力图矩阵只承载"颜色"，不带任何文字信息。用户把鼠标移到某格上时需要知道
"这是哪个行权价、什么方向、当前 IV 多少、1 分钟冲量多少"，所以网格点的明细
必须单独发一份。行数被窗口档位封顶（默认 37 行），因此这份明细的体积是可控的。

``impulse`` 用字典而不是数组，键就是回看窗口的秒数——窗口长度来自配置，
写死成 ``imp_1m`` / ``imp_5m`` 会在改配置时失配。

依赖：L0、L6（numeric）。
"""

from __future__ import annotations

from config import loader
from contracts.feature import ImpulseCell

from serialization.numeric import round_opt

_CFG = "serialization"


class CellSerializer:
    """网格点明细编码器。"""

    __slots__ = ("_iv_decimals", "_impulse_decimals", "_price_decimals", "_include_raw_iv")

    def __init__(self, serial_cfg: dict) -> None:
        self._iv_decimals = loader.as_int(serial_cfg, "iv_decimals", module=_CFG)
        self._impulse_decimals = loader.as_int(
            serial_cfg, "impulse_decimals", module=_CFG
        )
        self._price_decimals = loader.as_int(
            serial_cfg, "price_decimals", module=_CFG
        )
        self._include_raw_iv = loader.as_bool(
            serial_cfg, "include_raw_iv", module=_CFG
        )

    def encode(self, cells: tuple[ImpulseCell, ...]) -> list[dict]:
        return [self._one(cell) for cell in cells]

    def _one(self, cell: ImpulseCell) -> dict:
        row = {
            "strike": round(float(cell.strike), self._price_decimals),
            "right": str(cell.right),
            "iv": round(float(cell.iv) * 100.0, 3),
            "delta": round_opt(cell.delta, 3),
            "price": round_opt(cell.opt_price, self._price_decimals),
            "quality": str(cell.quality),
            "age": round(float(cell.age_s), 1),
            "impulse": {
                str(window.seconds): round(
                    float(window.impulse_per_min), self._impulse_decimals
                )
                for window in cell.windows
            },
            "delta_iv": {
                str(window.seconds): round(
                    float(window.delta_vol_points), self._impulse_decimals
                )
                for window in cell.windows
            },
            "primary_impulse": round_opt(
                cell.primary_impulse(), self._impulse_decimals
            ),
        }

        if self._include_raw_iv:
            row["iv_raw"] = round(float(cell.iv), self._iv_decimals)
        return row
