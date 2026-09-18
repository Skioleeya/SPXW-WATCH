"""
L2 — 期货合约的到期**时刻**（不是到期日）。
==========================================
唯一职责：把 IBKR ``ContractDetails`` 上的 ``realExpirationDate`` /
``lastTradeTime`` / ``timeZoneId`` 合成一个 epoch 秒，并把它与 ``conId`` /
到期日一起编成两张登记表。

为什么必须精确到时刻（而不是取当日 00:00 UTC）
----------------------------------------------
ES 的真实到期时刻是到期日 **08:30 US/Central**（= 13:30 UTC = 09:30 ET，SOQ 结算），
而"到期日 00:00 UTC"比它**早 13.5 小时**。这个误差在 ``T2 − T1`` 里会抵消，
但在**绝对 T1** 上不会 —— 2026-09-18（ES 季月到期日）实测：从 00:00 UTC 起
``T1 = -0.000970`` 为负 ⇒ ``spot()`` 命中 ``t1 <= 0`` 的闸门 ⇒
**GTH 段一点现货都合成不出来、服务起不来**（`run.py` 两次同样
``SpotUnavailableError``，而日志里一条告警都没有）。

两个独立来源，不一致就拒绝启动
------------------------------
主来源 = ``lastTradeTime`` + ``timeZoneId``。
独立来源 = ``tradingHours`` 里"**止于**到期日"那一段的结束时刻
（实测 ESU6：``20260917:1700-20260918:0830``）。
两者不一致时抛 ``SpotUnavailableError``：不知道该信谁的时候，猜一个 T 出来
比拒绝启动危险得多 —— T 偏了不会报错，只会让整个 GTH 段的窗口静默订偏。

⚠️ 独立来源**不一定存在**：``tradingHours`` 是 IBKR 给的有限窗口
（实测 ESZ6/ESH7 只列了 6 天），窗口不覆盖到期日时无从交叉校验 —— 那时只用
主来源。这是"**缺少校验**"，与"**校验失败**"是两件事，必须分开处理。

依赖：L0（core.errors）。无 IO、不读配置、不看时钟。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from core.errors import SpotUnavailableError


def _parse_day(text: Any) -> tuple[int, int, int] | None:
    """``"YYYYMMDD"`` → ``(年, 月, 日)``；不合法返回 ``None``。"""
    value = str(text or "").strip()
    if len(value) < 8:
        return None
    try:
        return int(value[:4]), int(value[4:6]), int(value[6:8])
    except ValueError:
        return None


def _parse_clock(text: Any) -> tuple[int, int, int] | None:
    """``"HH:MM:SS"``（秒可缺）→ ``(时, 分, 秒)``；不合法返回 ``None``。"""
    parts = str(text or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        values = [int(part) for part in parts[:3]]
    except ValueError:
        return None
    while len(values) < 3:
        values.append(0)
    return values[0], values[1], values[2]


def _hours_end_on(trading_hours: Any, day: str) -> str | None:
    """
    ``tradingHours`` 里"**止于** ``day``"那一段的结束时刻，形如 ``"0830"``。

    分段格式（实测）::

        20260917:1700-20260918:0830;20260919:CLOSED;20260920:CLOSED

    以 ``;`` 分隔，每段是 ``起日:起时-止日:止时`` 或 ``某日:CLOSED``。
    只认**止日 == day** 的段；返回 ``None`` 表示窗口里没有这样的段
    （≠ 校验失败，见模块 docstring）。
    """
    for segment in str(trading_hours or "").split(";"):
        end = segment.strip().split("-")[-1]
        end_day, separator, end_clock = end.partition(":")
        if separator and end_day.strip() == day:
            return end_clock.strip()
    return None


def instant_of(details: Any) -> tuple[str, float]:
    """
    一条 ``ContractDetails`` → ``(到期日 "YYYYMMDD", 到期时刻 epoch 秒)``。

    两者**一起返回**：调用方用前者做键、后者算 T，同源就不会错配。
    任一必需字段缺失或不可解析 ⇒ 抛 ``SpotUnavailableError``（fail-closed），
    绝不回落到"当日 00:00 UTC"那个被实测证伪的假设。
    """
    day = str(getattr(details, "realExpirationDate", "") or "").strip()
    parsed = _parse_day(day)
    if parsed is None:
        raise SpotUnavailableError(
            f"期货合约缺少可解析的 realExpirationDate（收到 {day!r}）。"
            "B2b 的 T 直接依赖它 —— 拒绝启动，不猜一个到期日出来。"
        )

    clock = _parse_clock(getattr(details, "lastTradeTime", ""))
    zone_name = str(getattr(details, "timeZoneId", "") or "").strip()
    if clock is None or not zone_name:
        raise SpotUnavailableError(
            f"期货 {day} 缺少 lastTradeTime / timeZoneId（收到 "
            f"{getattr(details, 'lastTradeTime', '')!r} / {zone_name!r}）。"
            "到期**时刻**算不出来时 T 会偏十几小时 ⇒ 拒绝启动。"
        )

    try:
        zone = ZoneInfo(zone_name)
        moment = datetime(
            parsed[0], parsed[1], parsed[2], clock[0], clock[1], clock[2], tzinfo=zone
        )
    except Exception as exc:  # noqa: BLE001 - 时区/日期不可用都必须**响**
        raise SpotUnavailableError(
            f"期货 {day} 的到期时刻无法解析（时区 {zone_name!r}，时刻 "
            f"{getattr(details, 'lastTradeTime', '')!r}）：{type(exc).__name__}: {exc}"
        ) from exc

    # 独立来源交叉校验（只在 tradingHours 窗口覆盖到期日时可用）。
    hours_end = _hours_end_on(getattr(details, "tradingHours", ""), day)
    if hours_end is not None:
        expected = f"{clock[0]:02d}{clock[1]:02d}"
        if hours_end != expected:
            raise SpotUnavailableError(
                f"期货 {day} 的两个到期时刻来源不一致：lastTradeTime={expected} "
                f"vs tradingHours 止于当日的段={hours_end}。不知道该信谁 ⇒ 拒绝启动"
                "（猜一个 T 会让整个 GTH 段的窗口静默订偏）。"
            )
    return day, moment.timestamp()


def build_map(details: Iterable[Any]) -> tuple[dict[int, str], dict[str, float]]:
    """
    ``[ContractDetails]`` → ``(conId → 到期日, 到期日 → 到期时刻)``。

    两张表同源同批生成，调用方分别交给 tick 路由（认合约）与现货合成器（算 T）。
    **先整批解析、再订阅** —— 中途抛错时不会留下"订了一半"的副作用。
    """
    by_con_id: dict[int, str] = {}
    by_expiry: dict[str, float] = {}
    for item in details:
        expiry, instant = instant_of(item)
        con_id = int(getattr(getattr(item, "contract", None), "conId", 0) or 0)
        by_con_id[con_id] = expiry
        by_expiry[expiry] = instant
    return by_con_id, by_expiry
