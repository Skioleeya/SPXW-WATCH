"""
L4 — 热力图矩阵编码。
=====================
唯一职责：把 ``HeatmapMatrix`` 编码成前端 ECharts 能直接消费的 JSON 结构。

输出结构
--------
::

    {
      "labels":  ["09:30", "09:31", ...],   # 横轴：时间桶
      "strikes": [6480, 6485, ...],         # 纵轴：行权价（升序）
      "rights":  ["P", "P", "C", ...],      # 每行实际使用的 OTM 方向
      "values":  [[...], ...],              # values[row][col] = ΔIV 波动率点
      "vmax":    3.25,                      # 色标对称量程
      "rows":    37,
      "cols":    43,
      "bucket_index": 42,
      "spot":    6500.0
    }

``values`` 里的 ``null`` 表示该格尚无数据（还没到那个时间桶），前端应渲染为
透明而不是 0——两者语义完全不同。

依赖：L0、L4（numeric）。
"""

from __future__ import annotations

from config import loader
from contracts.feature import HeatmapMatrix

from serialization.numeric import robust_bound, round_opt

_CFG = "serialization"


class HeatmapSerializer:
    """热力图编码器。"""

    __slots__ = ("_decimals", "_quantile", "_floor")

    def __init__(self, serial_cfg: dict) -> None:
        self._decimals = loader.as_int(serial_cfg, "impulse_decimals", module=_CFG)
        self._quantile = loader.as_float(
            serial_cfg, "heatmap_color_quantile", module=_CFG
        )
        self._floor = loader.as_float(
            serial_cfg, "heatmap_color_floor_vol_points", module=_CFG
        )

    def encode(self, matrix: HeatmapMatrix | None) -> dict | None:
        """矩阵为 ``None`` 时返回 ``None``（前端保留上一帧，不闪白）。"""
        if matrix is None:
            return None

        values = [
            [round_opt(cell, self._decimals) for cell in row]
            for row in matrix.values
        ]

        flat = [cell for row in matrix.values for cell in row]

        return {
            "labels": list(matrix.bucket_labels),
            "strikes": list(matrix.strikes),
            "rights": [str(right) for right in matrix.rights],
            "values": values,
            "vmax": round(robust_bound(flat, self._quantile, self._floor), 3),
            "rows": matrix.rows(),
            "cols": matrix.cols(),
            "bucket_index": int(matrix.bucket_index),
            "spot": round(float(matrix.spot), 2),
        }
