"""
L6 — 断流恢复的「断代留白」回归。
==================================
守住一件事：**IBKR 断流恢复后的第一桶，热力图必须留白。**

为什么需要它
------------
断线期间最后一笔 tick 会一直是 ``STALE``，而 ``STALE`` 属于
``TRUSTWORTHY_QUALITIES``（会话内前向填充语义）⇒ 它被逐桶写进矩阵，断线看起来
只是"IV 没动"。重连后第一笔新 IV 一进来，就与断线前的值做差 —— **整段断线的
变化被压进单个 30 秒桶**，画出一堵与真冲量无法区分的假墙。色标下限只有
±0.5 波动率点，几个点的跳变就打满，肉眼分不出来。

毛刺过滤器拦不住这件事：``glitch_max_jump_vol_points``（25 波动率点）与 MAD
两道闸门是为**逐笔错价**标定的，而普通断线的跳变远小于 25 点；更要紧的是，
断线超过 ``state.option_buffer_seconds``（900s）后旧 tick 被裁光，两道闸门都会
因"样本不足"返回 ``False`` —— 长断线时它们**双双失效**。

本回归的判别力
--------------
用例 2 是**对照**：同一串数据、不打断代标记，必须复现出 +2.5 波动率点的尖峰。
它证明用例 1 的断言不是恒真的。

另一条同族判据（2026-09-14 加）：**长空洞不能拉出「假 0 带」**。前向填充的假定
只对短跨度成立；进程重启后 ``recover()`` 捞回的孤立旧桶若被一路沿用，图上会
出现横跨整段会话的 ΔIV=0 亮黄绿带，与真"IV 没变"无法区分。用例 4 走真实恢复
入口 ``load_snapshot()``，钉住"上限内沿用、上限外留白、恢复首桶不做差"。

``--selftest`` 注入两处缺陷 —— ① 把 ``HeatmapEngine.observe`` 换成"吞掉
break_now 参数"的版本（用例 1 必须 FAIL）；② 把 ``_row_values`` 里的前向填充
上限推到无穷（用例 4 必须 FAIL）。两者都复现不出失败 ⇒ 回归是空转的。

用法::

    python tools/check_reconnect_gap.py
    python tools/check_reconnect_gap.py --selftest
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import OptionRight, Quality  # noqa: E402
from contracts.feature import ImpulseCell  # noqa: E402
from contracts.tick import OptionRef  # noqa: E402
from core.clock import SessionClock  # noqa: E402
from features.heatmap_engine import HeatmapEngine  # noqa: E402

TZ = "America/New_York"
STRIKE = 7675.0
QUIET_STRIKE = 7700.0
EXPIRY = "20260911"

IV_BEFORE = 0.2000
IV_AFTER = 0.2250            # +2.5 波动率点
EXPECTED_SPIKE = 2.5

BUCKET_S = 30
#: 单会话定义：本回归只关心"断代留白"，不需要 GTH 与空档。
SESSIONS: list[dict] = [
    {"id": "rth", "label": "RTH", "open": "09:30", "close": "16:00"},
]
GAP_START = 9                # 断线从第 9 桶开始
GAP_END = 17                 # 第 17 桶是断线中最后一桶
RESUME = 18                  # 第 18 桶 = 恢复后的第一桶
LAST = 20

# 断流判定阈值（秒）—— 与 config/serialization.json 的 heatmap_feed_gap_s 同量级
GAP_S = 300.0


class StubClock:
    """可控的墙钟：只提供 ``now()``，供 SessionClock 包装。"""

    def __init__(self, moment: float) -> None:
        self.moment = moment

    def now(self) -> float:
        return self.moment


class StubStore:
    """只提供 ``last_tick_age_s`` 的桩，用于单测断流状态机。"""

    def __init__(self) -> None:
        self.age: float | None = None

    def last_tick_age_s(self, now: float | None = None) -> float | None:
        return self.age


def grid_start_epoch() -> float:
    """网格起点（本回归只用一个 RTH 会话，起点即 09:30）。

    刻意自造一个**单会话**定义而不是读 ``config/app.json``：本回归要证明的是
    "断流恢复留白"这一条，会话定义越简单越不容易把别的机制混进来。真实的多会话
    网格（GTH + 空档 + RTH）由 ``tools/check_session_grid.py`` 覆盖。
    """
    return datetime(2026, 9, 11, 9, 30, tzinfo=ZoneInfo(TZ)).timestamp()


def make_clock() -> tuple[SessionClock, StubClock]:
    source = StubClock(grid_start_epoch())
    clock = SessionClock(TZ, SESSIONS, BUCKET_S, clock=source)
    return clock, source


def ts_of(bucket: int) -> float:
    """第 ``bucket`` 桶内 1 秒处的 epoch。"""
    return grid_start_epoch() + bucket * BUCKET_S + 1.0


def cell(strike: float, iv: float, ts: float) -> ImpulseCell:
    return ImpulseCell(
        ref=OptionRef(strike=strike, right=OptionRight.CALL, expiry=EXPIRY),
        iv=iv,
        quality=Quality.OK,
        age_s=0.0,
        ts=ts,
    )


def feed(engine: HeatmapEngine, iv: float, bucket: int, break_now: bool = False) -> None:
    ts = ts_of(bucket)
    engine.observe((cell(STRIKE, iv, ts),), ts, break_now=break_now)


def row_of(engine: HeatmapEngine, strike: float, upto: int) -> tuple:
    clock, _ = make_clock()
    ref = OptionRef(strike=strike, right=OptionRight.CALL, expiry=EXPIRY)
    matrix = engine.build((ref,), 7670.0, ts_of(upto))
    assert matrix is not None, "矩阵为空，说明引擎没记下任何桶"
    return matrix.values[0]


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #


def case_gap_is_blanked(use_break: bool) -> tuple[bool, str]:
    """断流恢复的第一桶必须留白（``use_break=False`` 时用来复现缺陷）。"""
    clock, _ = make_clock()
    engine = HeatmapEngine(clock, loader.load("serialization"))

    for bucket in range(0, GAP_START):
        feed(engine, IV_BEFORE, bucket)
    for bucket in range(GAP_START, RESUME):
        # 断线期间 STALE 仍属可信质量 ⇒ 同一笔 IV 被继续写进每个桶
        feed(engine, IV_BEFORE, bucket)
    feed(engine, IV_AFTER, RESUME, break_now=use_break)
    for bucket in range(RESUME + 1, LAST + 1):
        feed(engine, IV_AFTER, bucket)

    row = row_of(engine, STRIKE, LAST)
    value = row[RESUME]
    if use_break:
        ok = value is None
        return ok, f"恢复桶 ΔIV = {value!r}（期望 None = 留白）"
    ok = value is not None and abs(value - EXPECTED_SPIKE) < 1e-9
    return ok, f"不打断代时恢复桶 ΔIV = {value!r}（期望 {EXPECTED_SPIKE}，复现假墙）"


def case_break_is_one_bucket_only() -> tuple[bool, str]:
    """断代只抹掉那一桶；之后必须恢复正常差分。"""
    clock, _ = make_clock()
    engine = HeatmapEngine(clock, loader.load("serialization"))

    for bucket in range(0, GAP_START):
        feed(engine, IV_BEFORE, bucket)
    for bucket in range(GAP_START, RESUME):
        feed(engine, IV_BEFORE, bucket)
    feed(engine, IV_AFTER, RESUME, break_now=True)
    for bucket in range(RESUME + 1, LAST + 1):
        feed(engine, IV_AFTER, bucket)

    row = row_of(engine, STRIKE, LAST)
    tail = [row[b] for b in range(RESUME + 1, LAST + 1)]
    ok = all(v == 0.0 for v in tail)
    return ok, f"断代后各桶 ΔIV = {tail}（期望全 0，说明只留白了一桶）"


def case_quiet_strike_keeps_zero() -> tuple[bool, str]:
    """无断代时，安静档位（长时间没有新 IV）必须前向填充成 0，而不是留白。"""
    clock, _ = make_clock()
    engine = HeatmapEngine(clock, loader.load("serialization"))

    for bucket in range(0, LAST + 1):
        ts = ts_of(bucket)
        cells = (cell(STRIKE, IV_BEFORE, ts),)
        if bucket in (0, LAST):
            cells = cells + (cell(QUIET_STRIKE, 0.18, ts),)
        engine.observe(cells, ts)

    row = row_of(engine, QUIET_STRIKE, LAST)
    middle = [row[b] for b in range(1, LAST)]
    ok = all(v == 0.0 for v in middle)
    return ok, f"安静档位中间各桶 ΔIV = {middle}（期望全 0，前向填充未被打断）"


def case_long_gap_is_blanked() -> tuple[bool, str]:
    """孤立旧桶 + 长空洞：**超出前向填充上限**的桶必须留白，不能拉出「假 0 带」。

    2026-09-14 实测来源：进程重启后 ``recover()`` 捞回上一存活期写在 20:15 的
    单个桶，而 ``load_snapshot()`` 照单全收；若前向填充没有上限，该桶会被一路
    沿用到当前，图上出现一条横跨整段会话的 ΔIV=0 亮黄绿带 —— 与真"IV 没变"
    肉眼无法区分，且在首次真观测处与陈旧值做差、凭空造出一个冲量。

    上限值不写死，从 ``config/serialization.json::heatmap_max_ffill_buckets`` 读，
    这样调阈值不会让本用例变成假警报。
    """
    cfg = loader.load("serialization")
    limit = int(cfg["heatmap_max_ffill_buckets"])
    far = limit + 5                       # 明确越过上限
    clock, _ = make_clock()
    engine = HeatmapEngine(clock, cfg)

    # 走真实恢复入口（app/pipeline.py 就是这么喂的），而不是直接摸 _buckets
    engine.load_snapshot([
        {"bucket_index": 0, "ivs": {STRIKE: IV_BEFORE}, "break": False},
        {"bucket_index": far, "ivs": {STRIKE: IV_AFTER}, "break": False},
    ])
    row = row_of(engine, STRIKE, far)

    inside = row[limit]        # 上限之内：沿用上一个已知 IV ⇒ 0
    beyond = row[limit + 1]    # 上限之外：必须留白
    resume = row[far]          # 恢复首桶：不与陈旧值做差
    ok = inside == 0.0 and beyond is None and resume is None
    return ok, (
        f"上限内 ΔIV={inside!r}（期望 0.0）· 上限外 ΔIV={beyond!r}（期望 None）"
        f"· 恢复桶 ΔIV={resume!r}（期望 None）[上限 {limit} 桶]"
    )


def case_gap_state_machine() -> tuple[bool, str]:
    """``FeatureEngine._note_feed_gap`` 每次断流只报一次 True，且只在恢复那刻。"""
    from features.feature_engine import FeatureEngine

    store = StubStore()
    engine = FeatureEngine(
        store, make_clock()[0], loader.load("features"), loader.load("serialization")
    )

    store.age = 0.5
    steps = [engine._note_feed_gap(0.0) for _ in range(3)]
    store.age = GAP_S + 1.0
    during = [engine._note_feed_gap(0.0) for _ in range(3)]
    store.age = 0.5
    after = [engine._note_feed_gap(0.0) for _ in range(3)]

    ok = (
        steps == [False, False, False]
        and during == [False, False, False]
        and after == [True, False, False]
    )
    return ok, f"健康={steps} 断流中={during} 恢复后={after}（期望末组 [True, False, False]）"


# --------------------------------------------------------------------------- #
# 驱动
# --------------------------------------------------------------------------- #


def run_suite(use_break: bool) -> tuple[bool, list[str]]:
    checks = [
        ("断流恢复的第一桶留白", case_gap_is_blanked(use_break)),
        ("断代只影响那一桶", case_break_is_one_bucket_only()),
        ("安静档位不被误伤", case_quiet_strike_keeps_zero()),
        ("长空洞不拉出假 0 带", case_long_gap_is_blanked()),
        ("断流状态机只报一次", case_gap_state_machine()),
    ]
    lines: list[str] = []
    all_ok = True
    for name, (ok, detail) in checks:
        all_ok = all_ok and ok
        lines.append(f"  [{'ok' if ok else 'FAIL'}] {name} —— {detail}")
    return all_ok, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_reconnect_gap.py")
    parser.add_argument(
        "--selftest", action="store_true",
        help="注入『引擎吞掉 break_now』缺陷，断言回归会 FAIL（非空转验证）",
    )
    args = parser.parse_args(argv)

    print("=" * 72)
    print("断流恢复的「断代留白」回归")
    print("=" * 72)

    if args.selftest:
        original_observe = HeatmapEngine.observe
        original_row_values = HeatmapEngine._row_values

        def broken_observe(self, cells, now, break_now=False):  # noqa: ANN001
            return original_observe(self, cells, now, break_now=False)

        def broken_row_values(self, bucket, current):  # noqa: ANN001
            """把前向填充上限推到无穷 —— 复现 2026-09-14 的「假 0 带」。"""
            saved = self._max_ffill
            self._max_ffill = 10 ** 9
            try:
                return original_row_values(self, bucket, current)
            finally:
                self._max_ffill = saved

        HeatmapEngine.observe = broken_observe
        HeatmapEngine._row_values = broken_row_values
        print(
            "\n[--selftest] 已注入两处缺陷："
            "① observe 吞掉 break_now；② 前向填充上限推到无穷\n"
        )
        try:
            ok, lines = run_suite(use_break=True)
        finally:
            HeatmapEngine.observe = original_observe
            HeatmapEngine._row_values = original_row_values
        print("\n".join(lines))
        red = [
            ln.split("] ", 1)[1].split(" ——")[0]
            for ln in lines if "[FAIL]" in ln
        ]
        print()
        if ok:
            print("结果: --selftest 未复现失败 —— 回归是空转的，必须修")
            return 1
        print(f"结果: --selftest 已复现失败（变红: {red}）—— 回归有判别力")
        return 0

    ok, lines = run_suite(use_break=True)
    print("\n".join(lines))
    print()
    print("对照：不打断代标记时必须复现假墙（证明用例 1 不是恒真）")
    control_ok, control_lines = run_suite(use_break=False)
    print(control_lines[0])
    print()
    if not control_ok:
        print("结果: 对照组未复现尖峰 —— 用例 1 失去判别力，必须修")
        return 1
    print("结果: " + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
