"""
L0 — 时间与会话时钟。
======================
唯一职责：把"当前时间"和"交易日坐标"（第几个时间桶、当日到期日、当前落在哪个
会话区段）算清楚。**不读配置** —— 参数由调用方注入，本模块因此可以放在 L0。

**为什么要有时间源抽象**：生产下"现在"就是墙上时钟，但离线回归要把一整个交易日
压进几秒钟跑完。两条路径必须共用同一套分桶逻辑，否则热力图横轴对不齐。所以本模块
依赖 ``ClockPort``（见 ``contracts/ports.py``）而不直接调 ``time.time()``：生产注入
``WallClock``，回归注入 ``tools/fixtures.FakeClock``。

**会话模型**：一个交易日由若干**会话**串成，例如 SPXW 的 GTH（20:15 → 次日 09:25）
与 RTH（09:30 → 16:00）。网格锚定在**首个会话的开盘**、可以跨午夜；相邻会话之间
那段不交易的时间自动成为一个"空档"区段。旧行为锚在 RTH 开盘，于是 GTH 时段
``elapsed_s()`` 被钳到 0 —— 隔夜与盘前数据**全落进第 0 桶**，GTH 根本无法验证。

**交易日 = 网格结束的那一天**：0DTE 的到期日就是交易日的身份。网格从 T−1 晚间跨到
T 下午，所以交易日取网格终点的自然日：夜里跑的仍是 T 那张合约。网格只定义在周一至
周五；落在周末（或早于下一个网格开盘）的时刻解析到**下一个**交易日。本模块不含
节假日日历 —— "今天是不是交易日"由 IBKR 的事实决定（拿不到当日到期链就 fail-closed）。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

#: 一个区段在网格里的占位（桶序号区间）由分钟偏移换算而来，因此每个区段边界
#: 都必须落在分钟上。这两条是算术事实，不是可调参数。
_MINUTES_PER_DAY = 24 * 60
_SECONDS_PER_DAY = 24 * 3600


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
    total_minutes = int(total_minutes) % _MINUTES_PER_DAY
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _span_minutes(start: int, end: int) -> int:
    """``start`` 时刻到 ``end`` 时刻的分钟数，跨午夜时绕回来。"""
    return (end - start) % _MINUTES_PER_DAY


def _make_zone(
    zone_id: str,
    label: str,
    is_session: bool,
    offset_min: int,
    span_min: int,
    start_min: int,
    bucket_seconds: int,
) -> dict:
    """把"网格起点后第 offset_min 分钟起、长 span_min 分钟"落成一个区段。"""
    begin_s = offset_min * 60
    end_s = (offset_min + span_min) * 60
    if begin_s % bucket_seconds or end_s % bucket_seconds:
        raise ValueError(
            f"区段 {zone_id!r} 的边界 {fmt_hm((start_min + offset_min) % _MINUTES_PER_DAY)} "
            f"没有落在时间桶边界上（桶宽 {bucket_seconds}s）—— 网格会错位，"
            f"前端按区段切列就会切错"
        )
    return {
        "id": zone_id,
        "label": label,
        "is_session": bool(is_session),
        "first": begin_s // bucket_seconds,
        "last": end_s // bucket_seconds - 1,
        "open": fmt_hm((start_min + offset_min) % _MINUTES_PER_DAY),
        "close": fmt_hm((start_min + offset_min + span_min) % _MINUTES_PER_DAY),
    }


def _build_zones(
    sessions: list[dict], bucket_seconds: int
) -> tuple[int, list[dict], int]:
    """
    把会话定义展开成"会话 / 空档"交替的区段表。

    Returns ``(start_min, zones, total_min)``：网格起点时刻（当日分钟数）、
    区段表（首尾相接铺满网格）、网格总长（分钟）。
    """
    if not sessions:
        raise ValueError("sessions 不能为空 —— 网格没有起点")

    parsed: list[tuple[str, str, int, int]] = []
    for item in sessions:
        parsed.append((
            str(item["id"]),
            str(item["label"]),
            minutes_of_day(str(item["open"])),
            minutes_of_day(str(item["close"])),
        ))

    start_min = parsed[0][2]
    zones: list[dict] = []
    cursor = 0

    for index, (zone_id, label, open_min, close_min) in enumerate(parsed):
        if index > 0:
            gap = _span_minutes(parsed[index - 1][3], open_min)
            if gap > 0:
                zones.append(_make_zone(
                    "gap", "空档", False, cursor, gap, start_min, bucket_seconds
                ))
                cursor += gap
        span = _span_minutes(open_min, close_min)
        if span <= 0:
            raise ValueError(
                f"会话 {zone_id!r} 的时长必须为正："
                f"open={fmt_hm(open_min)} close={fmt_hm(close_min)}"
            )
        zones.append(_make_zone(
            zone_id, label, True, cursor, span, start_min, bucket_seconds
        ))
        cursor += span

    return start_min, zones, cursor


class WallClock:
    """实盘时间源：直接返回系统时钟。"""

    __slots__ = ()

    def now(self) -> float:
        return time.time()


class SessionClock:
    """
    交易日坐标换算。

    ``tz_name`` 是 IANA 时区名；``sessions`` 是会话定义列表（**按时间先后**
    排列，每项含 ``id`` / ``label`` / ``open`` / ``close``，``close`` 早于
    ``open`` 表示跨午夜，相邻会话之间的空档自动成为一个区段）；``bucket_seconds``
    是热力图横轴的时间粒度；``clock`` 是时间源，默认墙上时钟，离线回归可注入
    ``tools/fixtures.FakeClock``。
    """

    __slots__ = (
        "_tz", "_bucket_s", "_clock", "_start_min", "_grid_len_s", "_bucket_count",
        "_zones", "_zone_starts", "_cache_key", "_cache_day", "_cache_start",
    )

    def __init__(
        self,
        tz_name: str,
        sessions: list[dict],
        bucket_seconds: int,
        clock=None,
    ) -> None:
        if bucket_seconds <= 0:
            raise ValueError(f"bucket_seconds 必须为正整数，收到 {bucket_seconds}")
        self._tz = ZoneInfo(tz_name)
        self._bucket_s = int(bucket_seconds)
        self._clock = clock if clock is not None else WallClock()

        start_min, zones, total_min = _build_zones(sessions, self._bucket_s)
        self._start_min = start_min
        self._zones = zones
        self._grid_len_s = total_min * 60
        self._bucket_count = self._grid_len_s // self._bucket_s
        #: 区段起点（不含 0）。它们是一段新序列的起点，差分必须留白。
        self._zone_starts = tuple(z["first"] for z in zones if z["first"] > 0)

        self._cache_key: date | None = None
        self._cache_day: date | None = None
        self._cache_start: datetime | None = None

    # ------------------------------------------------------------------ #
    # 时间源
    # ------------------------------------------------------------------ #

    def now(self) -> float:
        """当前时间（epoch 秒）—— **实现 ``ClockPort``**。

        本类会被当作时间源注入 L2 / L3，因此必须和 ``WallClock`` 一样满足
        ``contracts.ports.ClockPort``。这个接口曾经缺失，后果是 ``TickStore.prune()``
        每 10 秒抛一次异常、被维护循环吞成一行警告 —— 表现是"裁剪从未真正发生"，
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

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    @property
    def bucket_seconds(self) -> int:
        return self._bucket_s

    # ------------------------------------------------------------------ #
    # 交易日网格
    # ------------------------------------------------------------------ #

    def _grid_start_of(self, day: date) -> datetime:
        """交易日 ``day`` 的网格起点时刻。

        网格可能从前一晚开始（GTH 20:15），所以起点按"网格**终点**必须落在 ``day``"
        反推，而不是简单把 ``day`` 当成起点所在的那一天。
        """
        midnight = datetime(day.year, day.month, day.day, tzinfo=self._tz)
        shift = (self._start_min * 60 + self._grid_len_s) // _SECONDS_PER_DAY
        return midnight + timedelta(
            seconds=self._start_min * 60 - shift * _SECONDS_PER_DAY
        )

    def _resolve(self, ts: float) -> tuple[date, datetime]:
        """找出 ``ts`` 落在哪个交易日的网格里。

        网格只定义在周一至周五。找不到（周末，或早于下一个网格开盘）时返回
        **下一个**交易日 —— 调用方据此把 ``elapsed_s`` 钳到 0，表现为"还没开盘"。
        """
        today = self.to_dt(ts).date()
        upcoming: tuple[date, datetime] | None = None

        for step in range(10):
            day = today + timedelta(days=step)
            if day.weekday() >= 5:
                continue
            start = self._grid_start_of(day)
            begin = start.timestamp()
            if begin <= ts < begin + self._grid_len_s:
                return day, start
            if upcoming is None and begin > ts:
                upcoming = (day, start)

        if upcoming is not None:
            return upcoming
        # 十天里有七个工作日，必有候选；走到这里说明参数把网格定义坏了。
        raise ValueError(f"无法把 {ts} 解析到任何交易日网格")

    def _grid(self, ts: float) -> tuple[date, datetime]:
        """带缓存的 ``_resolve``。缓存按自然日失效，因此跨午夜会自动重解。"""
        key = self.to_dt(ts).date()
        if key == self._cache_key and self._cache_day is not None:
            return self._cache_day, self._cache_start
        day, start = self._resolve(ts)
        self._cache_key = key
        self._cache_day = day
        self._cache_start = start
        return day, start

    def session_len_s(self) -> float:
        """整个交易日网格的长度（秒）—— 含各会话与它们之间的空档。"""
        return float(self._grid_len_s)

    def trading_day(self) -> date:
        """当前交易日 —— 网格终点所在的那一天，也是 0DTE 的到期日。"""
        return self._grid(self.now_ts())[0]

    def session_date(self) -> date:
        """会话归属的自然日。等价于 :meth:`trading_day`。"""
        return self.trading_day()

    def expiry_str(self) -> str:
        """当日到期的合约月份串，形如 ``"20260911"``。"""
        return self.trading_day().strftime("%Y%m%d")

    def grid_start_dt(self, day: date | None = None) -> datetime:
        return self._grid_start_of(day or self.trading_day())

    def session_open_dt(self, day: date | None = None) -> datetime:
        """``grid_start_dt`` 的别名，保留给既有调用点。"""
        return self.grid_start_dt(day)

    # ------------------------------------------------------------------ #
    # 会话坐标
    # ------------------------------------------------------------------ #

    def elapsed_s(self) -> float:
        """自网格起点起的秒数，钳制在 ``[0, session_len_s]``。"""
        moment = self.now_ts()
        _, start = self._grid(moment)
        return min(max(moment - start.timestamp(), 0.0), self.session_len_s())

    def seconds_to_close(self) -> float:
        return max(self.session_len_s() - self.elapsed_s(), 0.0)

    def is_open(self) -> bool:
        """当前是否落在某个**会话**里 —— 空档与网格之外都算没开。"""
        moment = self.now_ts()
        _, start = self._grid(moment)
        offset_s = moment - start.timestamp()
        for zone in self._zones:
            if not zone["is_session"]:
                continue
            begin = zone["first"] * self._bucket_s
            end = (zone["last"] + 1) * self._bucket_s
            if begin <= offset_s < end:
                return True
        return False

    # ------------------------------------------------------------------ #
    # 区段（会话 / 空档）
    # ------------------------------------------------------------------ #

    def zone_ranges(self) -> tuple[dict, ...]:
        """区段表：按桶序号升序、首尾相接铺满整个网格。每段含 ``id`` / ``label``
        / ``is_session`` / ``first`` / ``last`` / ``open`` / ``close``。

        会话之间的空档 ``is_session=False``，前端在「全时段」视图里整段丢掉它 ——
        这就是"隐藏 5 分钟空档"的落点。
        """
        return tuple(dict(zone) for zone in self._zones)

    def zone_start_indexes(self) -> tuple[int, ...]:
        """每个区段的起始桶序号（不含 0）。

        这些桶是**一段新序列的起点**：跨过空档后的第一笔 IV 与空档前的最后一笔之间
        隔着整段不交易的时间，做差就是把那段变化压进一个 30 秒桶 —— 与断线恢复是同
        一类假信号。所以它们和断代桶一样要留白。
        """
        return self._zone_starts

    # ------------------------------------------------------------------ #
    # 时间桶（热力图横轴）
    # ------------------------------------------------------------------ #

    def bucket_count(self) -> int:
        return self._bucket_count

    def bucket_index(self) -> int:
        """当前时间落在第几个桶，钳制到 ``[0, bucket_count - 1]``。"""
        raw = int(self.elapsed_s() // self._bucket_s)
        return min(max(raw, 0), self._bucket_count - 1)

    def bucket_label(self, index: int) -> str:
        """某个桶的横轴标签。桶宽是整分钟时输出 ``HH:MM``；**不是**整分钟时（例如
        基线 30 秒）必须带上秒，否则相邻两桶会打印出同一个 ``HH:MM`` —— 前端横轴
        看起来是重复标签，聚合后的分组起点也无从分辨。
        """
        total_s = (self._start_min * 60 + int(index) * self._bucket_s) % _SECONDS_PER_DAY
        hour, rest = divmod(total_s, 3600)
        minute, second = divmod(rest, 60)
        if self._bucket_s % 60 == 0:
            return f"{hour:02d}:{minute:02d}"
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    def bucket_labels(self) -> list[str]:
        return [self.bucket_label(i) for i in range(self._bucket_count)]

    def bucket_index_of_ts(self, ts: float) -> int:
        """把任意时间戳映射到桶序号；越界时钳制。"""
        _, start = self._grid(ts)
        raw = int((float(ts) - start.timestamp()) // self._bucket_s)
        return min(max(raw, 0), self._bucket_count - 1)

    def describe(self) -> dict:
        """给推送帧用的会话摘要。``open`` / ``close`` 是**网格**的起止时刻。"""
        return {
            "date": self.trading_day().isoformat(),
            "expiry": self.expiry_str(),
            "open": fmt_hm(self._start_min),
            "close": fmt_hm(self._start_min + self._grid_len_s // 60),
            "is_open": self.is_open(),
            "elapsed_s": round(self.elapsed_s(), 1),
            "seconds_to_close": round(self.seconds_to_close(), 1),
            "bucket_index": self.bucket_index(),
            "bucket_count": self._bucket_count,
        }
