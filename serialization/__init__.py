"""
L4 — 序列化层。

职责边界
--------
把 L3 的不可变结果对象编码成"可以直接发出去的 JSON 文本"。

* 只做**表示**转换（字段命名、精度、结构），不做任何数值计算。
* 不关心谁来发送、发多久一次。
* 输出保证是**合法 JSON**：``allow_nan=False``，绝不让 ``NaN`` 流到前端把
  ``JSON.parse`` 打挂。

只依赖 L0 与 L3 的产出类型。
"""

from serialization.cell_encoder import CellSerializer
from serialization.frame_encoder import FrameEncoder
from serialization.heatmap_matrix import HeatmapSerializer
from serialization.numeric import robust_bound, round_opt, round_req
from serialization.payload_builder import PayloadBuilder
from serialization.skew_series import SkewSerializer

__all__ = [
    "CellSerializer",
    "FrameEncoder",
    "HeatmapSerializer",
    "PayloadBuilder",
    "SkewSerializer",
    "robust_bound",
    "round_opt",
    "round_req",
]
