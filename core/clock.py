"""
L0 — 时间与会话时钟。
======================
唯一职责：把"当前时间"和"交易会话坐标"（第几分钟、第几个时间桶、当日到期日）
算清楚。**不读配置** —— 所有参数由调用方注入，本模块因此可以放在 L0。

为什么需要时间源抽象
--------------------
生产环境下"现在"就是墙上时钟，但**离线回归**需要把一整个交易日压缩进几秒钟
跑完 —— 否则验证一次 0DTE 热力图要等到收盘。两条路径必须共用同一套分桶逻辑，
否则热力图横轴对不齐。因此本模块依赖一个 ``ClockPort``（定义在
``contracts/ports.py``）而不是直接调 ``time.time()``：生产注入 ``WallClock``，
回归注入 ``tools/fixtures.FakeClock``。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def now_ts() -> float:
    """墙上时钟 epoch 秒。"""
    return time.time()


def monotonic() -> float:
    """单调时钟，用于测量间隔（不受系统时间调整影响）。"""
    return time.monotonic()


def parse_hm(value: str) -> tuple[int, int]:
    """把 ``"09:30"`` 解析成 ``(9, 30)``。"""
    if not isinstance(value, str) or ":" not in value:
        raise ValueError(f"时间格式应为 'HH:MM'，收到 {value!r}")
    hh, mm = value.split(":", 1)
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间越界: {value!r}")
    return hour, minute


def minutes_of_day(value: str) -> int:
    hour, minute = parse_hm(value)
    return hour * 60 + minute


def fmt_hm(total_minutes: int) -> str:
    total_minutes = int(total_minutes) % (24 * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


class WallClock:
    """实盘时间源：直接返回系统时钟。"""

    __slots__ = ()

    def now(self) -> float:
        return time.time()


class SessionClock:
    """
    交易会话坐标换算。

    Parameters
    ----------
    tz_name
        IANA 时区名，例如 ``"America/New_York"``。
    session_open, session_close
        ``"HH:MM"`` 格式的本地开收盘时间。
    bucket_seconds
        热力图横轴的时间粒度（秒）。60 表示一分钟一格。
    clock
        时间源，默认墙上时钟。离线回归可注入 ``tools/fixtures.FakeClock``。
    """

    __slots__ = ("_tz", "_open_min", "_close_min", "_bucket_s", "_clock")

    def __init__(
        self,
        tz_name: str,
        session_open: str,
        session_close: str,
        bucket_seconds: int,
        clock=None,
    ) -> None:
        if bucket_seconds <= 0:
            raise ValueError(f"bucket_seconds 必须为正整数，收到 {bucket_seconds}")
        self._tz = ZoneInfo(tz_name)
        self._open_min = minutes_of_day(session_open)
        self._close_min = minutes_of_day(session_close)
        if self._close_min <= self._open_min:
            raise ValueError(
                f"收盘 {session_close} 必须晚于开盘 {session_open}"
            )
        self._bucket_s = int(bucket_seconds)
        self._clock = clock if clock is not None else WallClock()

    # ------------------------------------------------------------------ #
    # 时间源
    # ------------------------------------------------------------------ #

    def now(self) -> float:
        """
        当前时间（epoch 秒）——**实现 ``ClockPort``**。

        本类会被当作时间源直接注入 L2 / L3（``TickStore``、``MarketState``、
        ``FeatureEngine`` 拿到的都是 ``SessionClock``）。因此它必须和
        ``WallClock`` 一样满足 ``contracts.ports.ClockPort``，否则那些模块里
        ``clock.now()`` 的调用会在运行期炸成 ``AttributeError``。

        这个接口曾经缺失，后果是 ``TickStore.prune()`` 每 10 秒抛一次异常、
        被维护循环的 ``except`` 吞成一行警告 —— 表现是"裁剪从未真正发生"，
        而任何探针都看不见。回归见 ``tools/check_clock_protocol.py``。
        """
        return float(self._clock.now())

    def now_ts(self) -> float:
        """``now()`` 的别名，保留给既有的 ``now_ts()`` 调用点。"""
        return self.now()

    def now_dt(self) -> datetime:
        return datetime.fromtimestamp(self.now_ts(), self._tz)

    def to_dt(self, ts: float) -> datetime:
        return datetime.fromtimestamp(float(ts), self._tz)

    # ------------------------------------------------------------------ #
    # 会话坐标
    # ------------------------------------------------------------------ #

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    @property
    def session_open_minutes(self) -> int:
        return self._open_min

    @property
    def session_close_minutes(self) -> int:
        return self._close_min

    def session_len_s(self) -> float:
        return (self._close_min - self._open_min) * 60.0

    def session_date(self) -> date:
        """会话归属的自然日（本地时区）。"""
        return self.now_dt().date()

    def expiry_str(self) -> str:
        """当日到期的合约月份串，形如 ``"20260911"``。"""
        return self.session_date().strftime("%Y%m%d")

    def minutes_since_open(self) -> float:
        dt = self.now_dt()
        return (dt.hour * 60 + dt.minute + dt.second / 60.0) - self._open_min

    def elapsed_s(self) -> float:
        """自开盘起的秒数，钳制在 ``[0, session_len_s]``。"""
        return min(max(self.minutes_since_open() * 60.0, 0.0), self.session_len_s())

    def is_open(self) -> bool:
        return 0.0 <= self.minutes_since_open() <= (self._close_min - self._open_min)

    def is_pre_open(self) -> bool:
        return self.minutes_since_open() < 0.0

    def is_closed(self) -> bool:
        return self.minutes_since_open() > (self._close_min - self._open_min)

    def session_open_dt(self, day: date | None = None) -> datetime:
        target = day or self.session_date()
        return datetime(
            target.year, target.month, target.day,
            self._open_min // 60, self._open_min % 60,
            tzinfo=self._tz,
        )

    def session_close_dt(self, day: date | None = None) -> datetime:
        target = day or self.session_date()
        return datetime(
            target.year, target.month, target.day,
            self._close_min // 60, self._close_min % 60,
            tzinfo=self._tz,
        )

    def seconds_to_close(self) -> float:
        return max(self.session_len_s() - self.elapsed_s(), 0.0)

    # ------------------------------------------------------------------ #
    # 时间桶（热力图横轴）
    # ------------------------------------------------------------------ #

    def bucket_count(self) -> int:
        total = int(self.session_len_s())
        return max(total // self._bucket_s, 1)

    def bucket_index(self) -> int:
        """当前时间落在第几个桶，钳制到 ``[0, bucket_count - 1]``。"""
        raw = int(self.elapsed_s() // self._bucket_s)
        return min(max(raw, 0), self.bucket_count() - 1)

    def bucket_label(self, index: int) -> str:
        """
        某个桶的横轴标签。

        桶宽是整分钟时输出 ``HH:MM``；**不是**整分钟时（例如基线 30 秒）必须
        带上秒，否则相邻两个桶会打印出同一个 ``HH:MM`` —— 前端横轴看起来是
        重复标签，聚合后的分组起点也无从分辨。整分钟这一支刻意保持原样，
        不把 ``:00`` 塞进既有视图。
        """
        total_s = (self._open_min * 60 + int(index) * self._bucket_s) % (24 * 3600)
        hour, rest = divmod(total_s, 3600)
        minute, second = divmod(rest, 60)
        if self._bucket_s % 60 == 0:
            return f"{hour:02d}:{minute:02d}"
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    def bucket_labels(self) -> list[str]:
        return [self.bucket_label(i) for i in range(self.bucket_count())]

    def bucket_index_of_ts(self, ts: float) -> int:
        """把任意时间戳映射到桶序号；越界时钳制。"""
        dt = self.to_dt(ts)
        minutes = (dt.hour * 60 + dt.minute + dt.second / 60.0) - self._open_min
        raw = int((minutes * 60.0) // self._bucket_s)
        return min(max(raw, 0), self.bucket_count() - 1)

    def bucket_start_ts(self, index: int, day: date | None = None) -> float:
        """某个桶的起始时刻（epoch 秒）。"""
        base = self.session_open_dt(day) + timedelta(
            seconds=int(index) * self._bucket_s
        )
        return base.timestamp()

    def describe(self) -> dict:
        """给推送帧用的会话摘要。"""
        return {
            "date": self.session_date().isoformat(),
            "expiry": self.expiry_str(),
            "open": fmt_hm(self._open_min),
            "close": fmt_hm(self._close_min),
            "is_open": self.is_open(),
            "elapsed_s": round(self.elapsed_s(), 1),
            "seconds_to_close": round(self.seconds_to_close(), 1),
            "bucket_index": self.bucket_index(),
            "bucket_count": self.bucket_count(),
        }
