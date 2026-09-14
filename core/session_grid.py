"""
L0 — 会话网格几何。
====================
唯一职责：把 ``config/app.json::sessions`` 的会话定义展开成"会话 / 空档"交替、
首尾相接铺满整个网格的**区段表**。

它只算几何：时刻解析、分钟换算、区段边界是否落在桶边界上。**不含时间源、
不含"现在几点"** —— 那是 ``core.clock.SessionClock`` 的职责。

为什么与 ``SessionClock`` 分开
------------------------------
``clock.py`` 原本把两件事装在一个文件里：一是"现在落在网格哪一格"（依赖时间源、
有缓存、是运行期状态），二是"网格怎么铺"（纯函数、无状态、可离线单测）。两者
职责不同，合在一起还让那个文件长期贴着 400 行上限 —— 2026-09-14 为"按区段选
数据来源"加一个只读查询方法，就把它顶过线了。按职能切开，两边都留出余量。

会话模型（与 ``SessionClock`` 的文档共用）
------------------------------------------
一个交易日由若干**会话**串成，例如 SPXW 的 GTH（20:15 → 次日 09:25）与 RTH
（09:30 → 16:00）。网格锚定在**首个会话的开盘**、可以跨午夜；相邻会话之间那段
不交易的时间自动成为一个"空档"区段（``is_session=False``），前端在「全时段」
视图里整段丢掉它 —— 这就是"隐藏 5 分钟空档"的落点。

依赖：无（L0 最底层的纯函数，连 ``config`` 都不 import）。
"""

from __future__ import annotations

#: 一天多少分钟。区段边界必须落在分钟上，这是算术事实，不是可调参数。
_MINUTES_PER_DAY = 24 * 60


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


def build_zones(
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
