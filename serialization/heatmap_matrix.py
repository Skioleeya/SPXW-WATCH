"""
L4 — 热力图矩阵编码。
=====================
唯一职责：把 ``HeatmapMatrix`` 编码成前端能直接消费的 JSON 结构。

输出结构
--------

::

    {
      "labels":  ["09:30:00", "09:30:30", ...],  # 横轴：基线时间桶
      "strikes": [6485, 6480, ...],         # 纵轴：行权价（降序，高在前）
      "rights":  ["P", "P", "C", ...],      # 每行实际使用的 OTM 方向
      "enc":     "bm16",                    # 数值块编码名（配置给出）
      "scale":   1000,                      # 定标：真实值 = 整数 / scale
      "bm":      "<base64 位图>",            # rows*cols 位，标记哪些格子有值
      "i16":     "<base64 小端 int16>",      # 只存有值的格子，行主序
      "filled":  2170,                      # 有值格数（= 位图置位数）
      "vmax":    3.25,                      # 色标对称量程（基线粒度）
      "rows":    37,
      "cols":    43,
      "bucket_index": 42,
      "bucket_seconds": 30,                 # 基线桶宽（秒）
      "scale_policy": {"quantile": 0.95, "floor": 0.5},
      "spot":    6500.0
    }

数值块为什么不直接发二维数组
----------------------------
矩阵里约 88% 的格子是空的，JSON 每个空格最少 5 字节（``null,``），实测占整帧
71%。改成「位图 + 定标整数」后，在 ``permessage-deflate`` 之上**再省 87%**。
编解码本体与逐位约定在 ``serialization/bitmap_codec.py``，前端镜像在
``web/matrix_codec.js``，两边由 ``tools/check_matrix_codec.py`` 逐值对拍。

``bm`` 里的 0 位表示该格尚无数据（还没到那个时间桶），前端应渲染为透明而不是
0——两者语义与旧版的 ``null`` 完全一致，只是换了表示。

``bucket_seconds`` / ``scale_policy`` / ``scale`` 为什么必须随帧下发
------------------------------------------------------------------
热力图横轴的可选周期由前端聚合得出（ΔIV 可加，见 ``web/period.js``）。前端要
做这件事，必须知道三件**只有后端才知道**的事：基线桶宽是多少（否则算不出该把
几个基线桶并成一组）、色标量程是按什么规则取的（聚合后数值量级会变，``vmax``
必须按同一规则重算，否则一换周期整张图就饱和或发灰）、以及定标整数的分母。

与其让前端抄一份常量（那就是两份真相，改一处忘一处），不如由 L4 在帧里带上。
``scale_policy`` 只是**参数**，规则本体仍在 ``serialization/numeric.robust_bound``；
前端那份实现由 ``tools/check_period_aggregation.py`` 与 Python 版逐值对拍。

依赖：L0、L4（numeric / bitmap_codec）。
"""

from __future__ import annotations

from config import loader
from contracts.feature import HeatmapMatrix

from serialization.bitmap_codec import pack
from serialization.numeric import robust_bound, round_opt

_CFG = "serialization"


class HeatmapSerializer:
    """热力图编码器。"""

    __slots__ = (
        "_decimals", "_quantile", "_floor", "_bucket_seconds",
        "_encoding", "_scale",
    )

    def __init__(self, serial_cfg: dict) -> None:
        self._decimals = loader.as_int(serial_cfg, "impulse_decimals", module=_CFG)
        self._quantile = loader.as_float(
            serial_cfg, "heatmap_color_quantile", module=_CFG
        )
        self._floor = loader.as_float(
            serial_cfg, "heatmap_color_floor_vol_points", module=_CFG
        )
        self._bucket_seconds = loader.as_int(
            serial_cfg, "heatmap_bucket_seconds", module=_CFG
        )
        self._encoding = loader.as_str(serial_cfg, "heatmap_encoding", module=_CFG)
        # 定标直接由精度推导：单设一个键就等于「精度」有两处真相。
        self._scale = 10 ** self._decimals

    def encode(self, matrix: HeatmapMatrix | None) -> dict | None:
        """矩阵为 ``None`` 时返回 ``None``（前端保留上一帧，不闪白）。"""
        if matrix is None:
            return None

        rounded = [
            [round_opt(cell, self._decimals) for cell in row]
            for row in matrix.values
        ]
        bitmap, ints, filled = pack(rounded, self._scale)

        flat = [cell for row in matrix.values for cell in row]

        return {
            "labels": list(matrix.bucket_labels),
            "strikes": list(matrix.strikes),
            "rights": [str(right) for right in matrix.rights],
            "enc": self._encoding,
            "scale": int(self._scale),
            "bm": bitmap,
            "i16": ints,
            "filled": filled,
            "vmax": round(robust_bound(flat, self._quantile, self._floor), 3),
            "rows": matrix.rows(),
            "cols": matrix.cols(),
            "bucket_index": int(matrix.bucket_index),
            "bucket_seconds": int(self._bucket_seconds),
            "scale_policy": {
                "quantile": self._quantile,
                "floor": self._floor,
            },
            "spot": round(float(matrix.spot), 2),
        }
