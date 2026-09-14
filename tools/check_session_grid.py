"""
L6 — 交易日网格回归（多会话 / 空档 / 区段留白）。
================================================

唯一职责：证明 ``config/app.json`` 的 ``sessions`` 真被展开成一张**铺满整个交易日、
可跨午夜**的时间桶网格，而且会话之间的空档被当作一段独立的、必须留白的区段。

2026-09-13 之前网格锚在 RTH 开盘（09:30），GTH 时段 ``elapsed_s()`` 被钳到 0，隔夜与
盘前的数据**全部落进第 0 桶** —— GTH 根本无法验证。改成多会话网格后有四处会**静默**
出错、都不报异常：

1. 网格没铺满（会话时长 + 空档不能被桶宽整除）⇒ 最后一截数据没有桶可落；
2. 区段表有缝或重叠 ⇒ 前端切列时漏列或把同一列复制两份；
3. **区段起点桶不留白** ⇒ 跨过 09:25–09:30 空档的第一笔 IV 与空档前最后一笔做差，
   整段空档的变化被压进一个 30 秒桶，画出一堵与真冲量无法区分的假墙（与断线恢复
   是同一类假信号，见 ``features/heatmap_engine.py``）；
4. 桶容量没跟着网格放大 ⇒ 最早的桶被环形缓冲悄悄裁掉，GTH 开盘那段凭空消失。

判据刻意**不写死** 20:15 / 09:25 / 2370：全从 ``config`` 推出来，写死就是第二份真相。

``--selftest`` 把同一套判据跑在三个**故意做坏**的网格上（单会话 / 把空档并进首个会话
/ 抹掉区段边界），要求各自变红 —— 三个都抓住才说明这组判据不是空转。用法::

    python tools/check_session_grid.py [--selftest]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import OptionRight, Quality  # noqa: E402
from contracts.feature import ImpulseCell  # noqa: E402
from contracts.tick import OptionRef  # noqa: E402
from core.clock import SessionClock  # noqa: E402
from core.session_grid import minutes_of_day  # noqa: E402
from features.heatmap_engine import HeatmapEngine  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

STRIKE = 6500.0

#: 区段留白用例里三个时刻的 IV。跨度刻意大：若不留白，那一格会画出整整 5 个波动率
#: 点的假冲量，肉眼与真信号无法区分。
IV_BEFORE = 0.2000
IV_IN_GAP = 0.2500
IV_AFTER = 0.3000


class _FixedClock:
    """只提供 ``now()`` 的桩：把会话时钟钉在某个时刻。"""

    __slots__ = ("_moment",)

    def __init__(self, moment: float) -> None:
        self._moment = float(moment)

    def now(self) -> float:
        return self._moment


class _NoZoneStarts:
    """包住真实时钟、把区段边界抹成空 —— **只用于 --selftest 造变异**。

    它复刻的正是"区段起点不留白"这个缺陷：网格几何完全正确，只有边界不生效。
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def zone_start_indexes(self) -> tuple[int, ...]:
        return ()


def _check(label: str, condition: bool, detail: str = "") -> tuple[str, bool, str]:
    return label, bool(condition), detail


def _local(tz: str, year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz))


def _clock_at(tz: str, sessions: list, bucket_s: int, day, hour: int, minute: int):
    moment = _local(tz, day.year, day.month, day.day, hour, minute)
    return SessionClock(tz, sessions, bucket_s, clock=_FixedClock(moment.timestamp()))


def _cell(ref: OptionRef, iv: float, ts: float) -> ImpulseCell:
    return ImpulseCell(ref=ref, iv=iv, quality=Quality.OK, age_s=0.0, ts=ts)


def _gap_exit_boundary(clock: SessionClock) -> int | None:
    """"走出空档、回到会话"的那一桶 —— 也就是 09:30：左边是 GTH 最后一笔（09:25 前），
    右边是 RTH 第一笔（09:30 后），中间隔着 5 分钟不交易的时间。跨过它做差，整段空档
    的变化就被压进一个 30 秒桶。判据只钉这一个边界，因为它是用户实际会看到的那一处。
    """
    zones = clock.zone_ranges()
    for index, zone in enumerate(zones):
        if index and zone["is_session"] and not zones[index - 1]["is_session"]:
            return int(zone["first"])
    return None


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #

def _grid_shape(clock: SessionClock, sessions: list, bucket_s: int) -> list:
    zones = clock.zone_ranges()
    grid_s = int(clock.session_len_s())

    expected_s = 0
    prev_close: int | None = None
    for item in sessions:
        open_min = minutes_of_day(str(item["open"]))
        close_min = minutes_of_day(str(item["close"]))
        if prev_close is not None:
            expected_s += ((open_min - prev_close) % (24 * 60)) * 60
        expected_s += ((close_min - open_min) % (24 * 60)) * 60
        prev_close = close_min

    cursor = 0
    tiled = True
    for zone in zones:
        if int(zone["first"]) != cursor:
            tiled = False
            break
        cursor = int(zone["last"]) + 1

    spans_ok = all(
        (int(z["last"]) - int(z["first"]) + 1) * bucket_s
        == ((minutes_of_day(str(z["close"])) - minutes_of_day(str(z["open"])))
            % (24 * 60)) * 60
        for z in zones
    )

    day = clock.trading_day()
    midnight = datetime(day.year, day.month, day.day, tzinfo=clock.tz)
    return [
        _check("网格长度 = 各会话时长 + 它们之间的空档",
               grid_s == expected_s, f"时钟 {grid_s}s vs 配置 {expected_s}s"),
        _check("时间桶恰好铺满网格（无余数、无重叠）",
               clock.bucket_count() * bucket_s == grid_s,
               f"{clock.bucket_count()} 桶 × {bucket_s}s"),
        _check("区段表首尾相接铺满网格（无缝隙、无重叠）",
               tiled and cursor == clock.bucket_count(),
               f"覆盖到第 {cursor} 桶 / 共 {clock.bucket_count()} 桶"),
        _check("区段表含至少一个非会话空档（会话之间的不交易时段）",
               any(not z["is_session"] for z in zones),
               f"{len(zones)} 个区段 / {sum(1 for z in zones if z['is_session'])} 个会话"),
        _check("每个区段的桶数与其 open/close 跨度一致",
               spans_ok, "区段边界必须落在桶边界上"),
        _check("区段起点数 = 区段数 - 1（每个边界都是一段新序列的起点）",
               len(clock.zone_start_indexes()) == max(len(zones) - 1, 0),
               f"{len(clock.zone_start_indexes())} 个边界 / {len(zones)} 个区段"),
        _check("网格跨午夜（起点落在交易日的前一自然日）",
               clock.grid_start_dt() < midnight,
               f"{clock.grid_start_dt().date()} → {day}"),
    ]


def _bucket_checks(clock: SessionClock, sessions: list) -> list:
    zones = clock.zone_ranges()
    first, last = zones[0], zones[-1]
    checks = [
        _check("首桶标签 = 首个会话开盘时刻",
               clock.bucket_label(0).startswith(str(sessions[0]["open"])),
               f"{clock.bucket_label(0)} vs {sessions[0]['open']}"),
        _check("末桶落在最后一个会话内",
               int(last["first"]) <= clock.bucket_count() - 1 <= int(last["last"]),
               f"末桶 {clock.bucket_label(clock.bucket_count() - 1)}"),
        _check("首区段就是首个会话（网格从会话开盘起算）",
               bool(first["is_session"]) and int(first["first"]) == 0,
               f"{first['id']} [{first['first']},{first['last']}]"),
    ]
    gap = next((z for z in zones if not z["is_session"]), None)
    if gap is not None:
        lo, hi = int(gap["first"]), int(gap["last"]) + 1
        checks.append(_check(
            "空档两侧的桶标签与空档的 open/close 一致",
            clock.bucket_label(lo).startswith(str(gap["open"]))
            and clock.bucket_label(hi).startswith(str(gap["close"])),
            f"{clock.bucket_label(lo)} → {clock.bucket_label(hi)}",
        ))
    return checks


def _is_open_checks(tz: str, sessions: list, bucket_s: int, day) -> list:
    """``is_open()`` 只认**真实会话**：空档与网格之外都必须算没开。"""
    checks = []
    for zone in _clock_at(tz, sessions, bucket_s, day, 12, 0).zone_ranges():
        hour, minute = int(zone["open"][:2]), int(zone["open"][3:])
        probe = _clock_at(tz, sessions, bucket_s, day, hour, minute)
        checks.append(_check(
            f"{zone['id']} 开盘时刻 is_open={bool(zone['is_session'])}",
            probe.is_open() is bool(zone["is_session"]),
            f"@{zone['open']} → {probe.is_open()}",
        ))
    return checks


def _trading_day_checks(tz: str, sessions: list, bucket_s: int, monday) -> list:
    """交易日 = 网格**终点**那一天，夜里跑的仍是终点日那张 0DTE 合约。只认周一至周五；
    周末与"早于下一个网格开盘"的时刻解析到**下一个**交易日。
    """
    friday = monday - timedelta(days=3)
    saturday = monday - timedelta(days=2)
    sunday = monday - timedelta(days=1)
    probes = [
        ("周一盘中（RTH）", monday, 10, 0, monday),
        ("周一盘前（GTH 段）", monday, 8, 0, monday),
        ("周一空档（09:27）", monday, 9, 27, monday),
        ("周日晚（GTH 开盘后）", sunday, 21, 0, monday),
        ("周日白天（网格之外）", sunday, 12, 0, monday),
        ("周六白天（周末）", saturday, 12, 0, monday),
        ("周五收盘后（16:00 之后）", friday, 18, 0, monday),
        ("周五晚（GTH 开盘后）", friday, 21, 0, monday),
    ]
    checks = []
    for label, day, hour, minute, want in probes:
        probe = _clock_at(tz, sessions, bucket_s, day, hour, minute)
        checks.append(_check(f"交易日推导 · {label} → {want}",
                             probe.trading_day() == want, str(probe.trading_day())))

    gap_probe = _clock_at(tz, sessions, bucket_s, monday, 9, 27)
    checks.append(_check("空档内 is_open 必须为 False", not gap_probe.is_open(),
                         f"第 {gap_probe.bucket_index()} 桶"))
    return checks


def _capacity_checks(clock: SessionClock, serial_cfg: dict) -> list:
    """桶容量必须覆盖整个网格，否则最早的桶会被环形缓冲**静默**裁掉。"""
    buckets = clock.bucket_count()
    return [
        _check("热力图容量覆盖整个交易日网格",
               int(serial_cfg["heatmap_max_buckets"]) >= buckets,
               f"{serial_cfg['heatmap_max_buckets']} vs {buckets} 桶"),
        _check("Skew 序列容量覆盖整个交易日网格",
               int(serial_cfg["skew_series_max_points"]) >= buckets,
               f"{serial_cfg['skew_series_max_points']} vs {buckets} 桶"),
    ]


def _blanking_check(tz: str, sessions: list, bucket_s: int, serial_cfg: dict,
                    day, clock: SessionClock | None = None) -> list:
    """区段起点桶必须留白。

    在空档里最后一笔 IV 之前写 IV_BEFORE、在 RTH 首桶写 IV_IN_GAP：若边界不留白，
    那一格会输出 ``(IV_IN_GAP − IV_BEFORE) × 100`` —— 一个凭空造出来的冲量。
    """
    base = clock or _clock_at(tz, sessions, bucket_s, day, 12, 0)
    boundary = _gap_exit_boundary(base)
    if boundary is None:
        return [_check("存在'空档之后的首个会话'边界（否则本判据无从谈起）",
                       False, "区段表里没有 gap → session 的接缝")]

    origin = base.grid_start_dt().timestamp()
    ref = OptionRef(strike=STRIKE, right=OptionRight.PUT, expiry=base.expiry_str())
    engine = HeatmapEngine(base, serial_cfg)

    def observe(iv: float, offset_buckets: int) -> float:
        ts = origin + offset_buckets * bucket_s + 5.0
        engine.observe((_cell(ref, iv, ts),), ts)
        return ts

    observe(IV_BEFORE, boundary - 1)
    observe(IV_IN_GAP, boundary)
    ts_after = observe(IV_AFTER, boundary + 2)

    matrix = engine.build((ref,), STRIKE, ts_after)
    if matrix is None:
        return [_check("区段留白用例能产出矩阵", False, "build() 返回 None")]
    row = matrix.values[0]
    fake = (IV_IN_GAP - IV_BEFORE) * 100.0
    return [
        _check("区段起点桶留白（不跨空档做差）", row[boundary] is None,
               f"值={row[boundary]}"
               + (f"（若不留白应约为 {fake:.2f} 波动率点）"
                  if row[boundary] is not None else "")),
        _check("区段起点之后的第一笔差值正常（只跳过边界那一桶）",
               row[boundary + 2] is not None
               and abs(row[boundary + 2] - (IV_AFTER - IV_IN_GAP) * 100.0) < 1e-9,
               f"值={row[boundary + 2]}"),
    ]


# --------------------------------------------------------------------------- #
# 组装与运行
# --------------------------------------------------------------------------- #

def battery(tz: str, sessions: list, bucket_s: int, serial_cfg: dict,
            clock: SessionClock, day) -> list[tuple[str, bool, str]]:
    return (_grid_shape(clock, sessions, bucket_s)
            + _bucket_checks(clock, sessions)
            + _is_open_checks(tz, sessions, bucket_s, day)
            + _trading_day_checks(tz, sessions, bucket_s, day)
            + _capacity_checks(clock, serial_cfg)
            + _blanking_check(tz, sessions, bucket_s, serial_cfg, day, clock))


# --------------------------------------------------------------------------- #
# 非空转自检
# --------------------------------------------------------------------------- #

def _selftest(tz: str, sessions: list, bucket_s: int, serial_cfg: dict, day) -> int:
    print("\n[非空转自检] 把同一套判据跑在故意做坏的网格上，必须逐条变红")
    failures = 0

    single = [dict(s) for s in sessions if str(s["id"]) == "rth"] or [dict(sessions[-1])]
    merged = [dict(s) for s in sessions]
    merged[0]["close"] = merged[-1]["open"] if len(merged) > 1 else merged[0]["close"]
    variants = (
        ("退回单会话锚点（改动前的行为）", single,
         _clock_at(tz, single, bucket_s, day, 12, 0),
         ("网格跨午夜", "区段表含至少一个非会话空档")),
        ("把空档并进首个会话", merged,
         _clock_at(tz, merged, bucket_s, day, 12, 0),
         ("区段表含至少一个非会话空档",)),
        ("抹掉区段边界（留白不生效）", sessions,
         _NoZoneStarts(_clock_at(tz, sessions, bucket_s, day, 12, 0)),
         ("区段起点桶留白",)),
    )
    for name, variant_sessions, clock, expect in variants:
        rows = battery(tz, variant_sessions, bucket_s, serial_cfg, clock, day)
        caught = [label for label, ok, _ in rows
                  if not ok and label.startswith(expect)]
        if caught:
            print(f"  {GREEN}[ok]{RESET} {name} → 已抓住"
                  f"（{len(caught)} 项，例：{caught[0]}）")
        else:
            print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：这组判据是空转的")
            failures += 1

    return failures


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_session_grid.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("交易日网格回归（多会话 / 空档 / 区段留白）")
    print("=" * 72)

    app_cfg = loader.load("app")
    serial_cfg = loader.load("serialization")
    tz = str(app_cfg["timezone"])
    sessions = list(app_cfg["sessions"])
    bucket_s = int(serial_cfg["heatmap_bucket_seconds"])

    clock = SessionClock(tz, sessions, bucket_s)
    day = clock.trading_day()
    print(f"\n网格 {clock.grid_start_dt().isoformat()} → {day} · "
          f"{clock.bucket_count()} 桶 × {bucket_s}s")
    for zone in clock.zone_ranges():
        print(f"  {zone['id']:>4s} [{zone['first']:>4d},{zone['last']:>4d}] "
              f"{zone['open']}–{zone['close']}"
              + ("" if zone["is_session"] else "   ← 不交易"))

    print("\n[1] 网格几何与会话结构")
    failures = 0
    for label, ok, detail in battery(tz, sessions, bucket_s, serial_cfg, clock, day):
        if not ok:
            failures += 1
        print(f"  {GREEN if ok else RED}[{'ok' if ok else 'FAIL'}]{RESET} {label}"
              + (f"  {detail}" if detail else ""))

    if args.selftest:
        failures += _selftest(tz, sessions, bucket_s, serial_cfg, day)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
