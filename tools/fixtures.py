"""
测试夹具：可推进的合成时钟与确定性 IV 曲面。
============================================

本模块**不是产品代码**。它位于 ``tools/``，因此不参与分层方向检查（[2]）、
单一职能检查（[9]）与禁止硬编码检查（[10]）；但仍受文件长度（[1]，< 400 行）
与 ``__slots__`` 一致性（[8]）约束。

它只服务于 ``tools/`` 下的离线回归。那些回归需要两样产品代码里**不存在**、
也不该存在的东西：

1. **可推进的时间源**。0DTE 的热力图横轴是一整个交易日，用墙上时钟验证一遍
   要等到收盘，开发期根本没法迭代。``FakeClock`` 实现 L0 的 ``ClockPort``，
   时间**只随显式 ``advance()`` 前进**，不掺真实时间流逝，因此同一份脚本每次
   运行都落在完全相同的桶号上 —— 这是回归能给出确定性断言的前提。

2. **确定性的行情曲面**。回归要断言"某行权价在某时刻的 ΔIV 应当是多少"，
   就必须先能算出这个"应当"。``SyntheticSurface`` 给出解析式的 IV 微笑与
   Delta 曲线：同参数必然同结果，不含任何随机数。

为什么这些东西从产品代码里搬出来
--------------------------------
它们原本住在 ``simulator/``（``SimClock`` / ``Scenario``），作为**运行时**的
第二数据源存在。2026-09-13 KAI 决定硬切实盘、删除整个模拟盘运行时组件；
回归所依赖的这部分数学与时钟被搬到这里。

搬移时刻意**只保留回归真正用到的部分**：原 ``Scenario`` 里的冲击剧本
（``shock_*``）、现价漂移（``spot_drift_points_per_min``）、以及
``SyntheticFeed`` 的随机噪声与毛刺探针，一律没有搬 —— 回归走的是确定性路径，
那些特性只会给夹具增加不必要的行为面。夹具越小，"测试通过"越能说明产品代码
本身正确。

依赖：L0（``config`` / ``core.clock``）。
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from core.clock import minutes_of_day


class FakeClock:
    """可推进的合成时钟，实现 ``contracts.ports.ClockPort``。

    与墙上时钟的唯一区别：``now()`` 只反映显式 ``advance()`` 累积的偏移，
    不读取 ``time.monotonic()``。于是"推进 3 个时间桶"是精确的、可重放的。

    Parameters
    ----------
    tz_name
        IANA 时区名，与 ``config/app.json`` 的 ``timezone`` 一致。
    session_open
        ``"HH:MM"``，会话开盘时刻；``now()`` 以此为基准零点。
    day
        基准自然日，默认今天（本地时区）。
    """

    __slots__ = ("_tz", "_open_min", "_base_day", "_offset")

    def __init__(
        self,
        tz_name: str,
        session_open: str,
        day: datetime | None = None,
    ) -> None:
        self._tz = ZoneInfo(tz_name)
        self._open_min = minutes_of_day(session_open)
        self._base_day = (day or datetime.now(self._tz)).date()
        self._offset = 0.0

    # ------------------------------------------------------------------ #
    # ClockPort
    # ------------------------------------------------------------------ #

    def now(self) -> float:
        return self._open_epoch() + self._offset

    # ------------------------------------------------------------------ #
    # 控制
    # ------------------------------------------------------------------ #

    def advance(self, session_seconds: float) -> None:
        """把会话时间向前推进指定秒数（立即生效）。"""
        self._offset += float(session_seconds)

    def reset(self) -> None:
        """把偏移归零（不改变基准日）。"""
        self._offset = 0.0

    def set_day(self, day: datetime) -> None:
        """换一个基准自然日，用于复现会话翻篇。"""
        self._base_day = day.date()

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def session_seconds(self) -> float:
        """自开盘起经过的会话秒数。"""
        return self._offset

    def session_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now(), self._tz)

    def _open_epoch(self) -> float:
        dt = datetime(
            self._base_day.year,
            self._base_day.month,
            self._base_day.day,
            self._open_min // 60,
            self._open_min % 60,
            tzinfo=self._tz,
        )
        return dt.timestamp()


class SyntheticSurface:
    """确定性的 IV 微笑与 Delta 曲线。

    曲面形状（单位：波动率点）::

        x      = (行权价 / 现价 − 1) × 100          # 百分比虚实程度
        IV(x)  = ATM_IV + slope × x + curvature × x² / 10

    ``slope`` 取负值即"左高右低"的标准股指偏斜。Delta 用 logistic 近似，
    ``delta_scale`` 控制 25Δ 离平值有多远（0DTE 上这个距离很窄）。

    全部为纯函数，不持有行情状态。
    """

    __slots__ = ("_slope", "_curvature", "_delta_scale")

    def __init__(self, slope: float, curvature: float, delta_scale: float) -> None:
        self._slope = float(slope)
        self._curvature = float(curvature)
        self._delta_scale = float(delta_scale)

    # ------------------------------------------------------------------ #
    # 波动率曲面
    # ------------------------------------------------------------------ #

    def iv_at(self, strike: float, spot: float, atm_iv: float) -> float:
        """给定行权价与现价的 IV（小数）。"""
        if spot <= 0:
            return atm_iv
        x = (strike / spot - 1.0) * 100.0
        vol_points = (
            atm_iv * 100.0 + self._slope * x + self._curvature * (x * x) / 10.0
        )
        return max(vol_points, 1.0) / 100.0

    # ------------------------------------------------------------------ #
    # Delta
    # ------------------------------------------------------------------ #

    def call_delta_at(self, strike: float, spot: float) -> float:
        """看涨 Delta，用 logistic 近似 0DTE 的陡峭 Delta 曲线。"""
        if spot <= 0:
            return 0.5
        x = (strike / spot - 1.0) * 100.0
        return 0.5 + 0.5 * math.tanh(-x / self._delta_scale)

    def put_delta_at(self, strike: float, spot: float) -> float:
        """看跌 Delta = 看涨 Delta − 1（无股息近似）。"""
        return self.call_delta_at(strike, spot) - 1.0

    def delta_for(self, strike: float, spot: float, is_put: bool) -> float:
        return (
            self.put_delta_at(strike, spot)
            if is_put
            else self.call_delta_at(strike, spot)
        )

    # ------------------------------------------------------------------ #
    # 行权价网格
    # ------------------------------------------------------------------ #

    @staticmethod
    def strike_grid(spot: float, step: float, each_side: int) -> tuple[float, ...]:
        """以现价为中心、按固定步长生成行权价格点。"""
        centre = round(spot / step) * step
        return tuple(
            round(centre + offset * step, 2)
            for offset in range(-each_side, each_side + 1)
        )
