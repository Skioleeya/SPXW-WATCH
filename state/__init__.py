"""
L2 — 状态层。

职责边界
--------
* ``TickStore``：按分片保存 tick 时间序列，实现 L0 的 ``TickSink``，是采集层
  的下游终点。
* ``MarketState``：只读聚合器，把存储内容与采集健康快照拼成可展示读数。

**不包含任何业务计算**（冲量、Skew 属于 L3），**不主动起线程或定时器**
（生命周期由 L6 组装层统一管理）。

只依赖 L0 与 L2 内部。
"""

from state.market_state import MarketState
from state.tick_store import TickStore

__all__ = ["MarketState", "TickStore"]
