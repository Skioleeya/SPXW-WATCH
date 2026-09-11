"""
L6 — 合成时钟。
================
唯一职责：实现 L0 的 ``ClockPort``，让"交易日"可以在几分钟内跑完。

为什么需要它
------------
0DTE 的热力图横轴是 390 分钟。用墙上时钟验证一遍要等一整个交易日，开发期
根本不可能迭代。合成时钟把会话时间按 ``session_speedup`` 倍加速：speedup=60
时，1 秒真实时间 = 1 分钟会话时间，6.5 分钟就能跑完全场。

关键在于**下游完全不需要知道时间被加速了**——``SessionClock`` 只是拿到一个
更大的 epoch 数值，分桶、到期日、剩余时间全部照常工作。这正是把时间源抽象成
L0 协议的价值。

依赖：L0。
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from core.clock import minutes_of_day


class SimClock:
    """加速的合成时间源。"""

    __slots__ = ("_tz", "_open_min", "_speedup", "_real_start", "_offset", "_base_day")

    def __init__(
        self,
        tz_name: str,
        session_open: str,
        speedup: float,
        day: datetime | None = None,
    ) -> None:
        if speedup <= 0:
            raise ValueError(f"session_speedup 必须为正数，收到 {speedup}")
        self._tz = ZoneInfo(tz_name)
        self._open_min = minutes_of_day(session_open)
        self._speedup = float(speedup)
        self._real_start = time.monotonic()
        self._offset = 0.0
        self._base_day = (day or datetime.now(self._tz)).date()

    # ------------------------------------------------------------------ #
    # ClockPort
    # ------------------------------------------------------------------ #

    def now(self) -> float:
        elapsed = (time.monotonic() - self._real_start) * self._speedup
        return self._open_epoch() + elapsed + self._offset

    # ------------------------------------------------------------------ #
    # 控制
    # ------------------------------------------------------------------ #

    def advance(self, session_seconds: float) -> None:
        """人为推进会话时间（测试用，立即生效）。"""
        self._offset += float(session_seconds)

    def reset(self) -> None:
        self._real_start = time.monotonic()
        self._offset = 0.0

    def set_day(self, day: datetime) -> None:
        self._base_day = day.date()

    @property
    def speedup(self) -> float:
        return self._speedup

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def _open_epoch(self) -> float:
        return self._epoch_at(self._open_min)

    def _epoch_at(self, minute_of_day: int) -> float:
        dt = datetime(
            self._base_day.year,
            self._base_day.month,
            self._base_day.day,
            minute_of_day // 60,
            minute_of_day % 60,
            tzinfo=self._tz,
        )
        return dt.timestamp()

    def session_seconds(self) -> float:
        """自会话开盘起经过的会话秒数。"""
        return self.now() - self._open_epoch()

    def session_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now(), self._tz)

    def close_epoch(self, session_close: str) -> float:
        """会话收盘时刻的 epoch 时间戳，供模拟器判断何时停手。"""
        return self._epoch_at(minutes_of_day(session_close))

    def describe(self) -> dict:
        return {
            "speedup": self._speedup,
            "session_datetime": self.session_datetime().isoformat(),
            "session_seconds": round(self.session_seconds(), 1),
        }
