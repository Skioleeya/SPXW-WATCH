"""
L6 — 离线模拟层。

职责边界
--------
提供 ``FeedPort`` 的第二个实现（``SyntheticFeed``）与配套的加速时钟
（``SimClock``）、行情剧本（``Scenario``），使整条链路在没有 TWS、没有行情
权限的情况下也能端到端跑通并验证。

它不是"测试代码"——模拟器是一等公民的运行时组件，由配置开关切换，因此
它的输出必须与实盘同构（同样的 DTO、同样的 tick 语义）。

只依赖 L0。
"""

from simulator.scenario import Scenario
from simulator.sim_clock import SimClock
from simulator.synthetic_feed import SyntheticFeed

__all__ = ["Scenario", "SimClock", "SyntheticFeed"]
