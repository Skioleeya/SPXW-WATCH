"""
L6 — Skew 周期对齐回归。
=======================
唯一职责：证明前端把 Skew 折线对齐到热力图列网格这件事**真的发生了、且落在
正确的时间上** —— 也就是用户可见的那条要求：

    选 30 秒周期，IV 热力图与 Skew 都是 30 秒一格；
    选 1 分钟周期，两块图都是 1 分钟一格。

为什么需要它
------------
两块图的列网格由热力图产出、Skew 再对齐过去。这条链上任何一环错位都**不会报
错**，只会让上下两块图的横坐标指向不同时刻。三类真实故障模式：

1. 热力图数值块没解码就交给 ``aggregate`` —— 它在 ``!block.values`` 时原样返回，
   聚合悄悄不发生（30 秒视图列数 780、列宽 30s），而所有断言仍通过；
2. ``alignSkew`` 漏掉 ``clipTail`` 的偏移 —— 被裁掉的历史段会盖住左侧列；
3. 并组后取**组内首值**而不是末值 —— 每格画的是该周期开始时的读数，
   曲线整体左移一个周期。

判据为什么必须这样写
--------------------
``alignSkew`` 里 ``out.label = grid.labels.slice()`` 是**直接复制**热力图的标签，
所以"两块图逐列标签相同"这条断言恒为真、抓不到任何东西。真正可失败的判据是：

* **[C1]** 聚合真的发生了（列宽 = 基线 × 组倍数；列数 = 分组后且被 ``clipTail`` 截断后的值）；
* **[C2]** **时间域**一致：每列的 ts 必须落在该列覆盖的时间区间内（只用 ts，
  不碰 bucket 字段，因此与 ``alignSkew`` 的内部算法无关）；
* **[C4]** 末值语义（与独立参考实现逐值对拍），且 group>1 时至少有一列首值≠末值，
  否则这条判据本身是空转；
* **[C6]** 量程**跟着视口走**：全宽时早盘尖峰必须算进量程，把可见列移到尖峰
  之外后必须被排除，只框住尖峰时必须覆盖它 —— 三档全对才算生效。

非空转验证（``--selftest``）
---------------------------
往 ``period.js`` / ``skew.js`` 注入四种缺陷，要求检查器逐条报出来。造数与参考
实现见 ``tools/skew_reference.py``。

用法::

    python tools/check_skew_alignment.py
    python tools/check_skew_alignment.py --selftest
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import skew_reference as ref  # noqa: E402
from tools.group_guard import guard_cases, guard_problems  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: 变异表：(名称, 文件, 原文, 替换, 期望被抓住的判据前缀)。
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("取组内首值而非末值", "period.js",
     "      out.ts[col] = series.ts[i];",
     "      if (out.skew[col] !== null) { continue; }\n      out.ts[col] = series.ts[i];",
     "[C4]"),
    ("aggregate 空转（不聚合）", "period.js",
     "    if (!(g > 1)) { return block; }",
     "    if (true) { return block; }",
     "[C1]"),
    ("alignSkew 漏掉 clipTail 偏移", "period.js",
     "      var col = Math.floor(pos / g) - drop;",
     "      var col = Math.floor(pos / g);",
     "[C2]"),
    ("量程不吃视口（退回全序列极值）", "skew.js",
     "    for (var k = from; k <= to; k++) {",
     "    for (var k = 0; k < values.length; k++) {",
     "[C6]"),
)


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #

def evaluate(result: dict, source: dict, frame: dict) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    base = int(result["base"])
    max_cols = int(result["maxColumns"])
    heat_cols = int(result["heatCols"])
    open_ts = float(source["open_ts"])
    spike = ref.SPIKE_VALUE

    checks.append(("[C0] 帧被 decodeFrame 还原出 values（否则聚合会静默不发生）",
                   bool(result["decoded"]), f"heatCols={heat_cols}"))

    for key in sorted(result["periods"], key=int):
        seconds = int(key)
        got = result["periods"][key]
        group = int(got["group"])
        drop = int(got["drop"])
        cols = int(got["cols"])
        want = ref.ref_align(source, group, cols, drop)
        tag = f"{seconds}s(g={group})"

        exp_cols = min(-(-heat_cols // group), max_cols)
        checks.append((f"[C1] {tag} 列宽 = 基线×组倍数",
                       int(got["bucket_seconds"]) == base * group,
                       f"{got['bucket_seconds']} vs {base * group}"))
        checks.append((f"[C1] {tag} 列数 = 分组后截断（期望 {exp_cols}）",
                       cols == exp_cols, f"{cols}"))

        # [C2] 时间域：只用 ts，不看 bucket 字段
        bad = None
        last_grid = -(-heat_cols // group) - 1
        for c, stamp in enumerate(got["ts"]):
            if stamp is None:
                continue
            lo = open_ts + (c + drop) * group * base
            hi = lo + group * base
            # 末列可能是"正在成形"的那一组，右端放宽到会话末尾
            if stamp < lo or (stamp >= hi and (c + drop) != last_grid):
                bad = (c, stamp, lo, hi)
                break
        checks.append((f"[C2] {tag} 每列 ts 落在本列时间区间内",
                       bad is None,
                       "全部吻合" if bad is None
                       else f"列{bad[0]} ts={bad[1]} 不在 [{bad[2]},{bad[3]})"))

        # [C3] ts 严格单调
        stamps = [s for s in got["ts"] if s is not None]
        checks.append((f"[C3] {tag} ts 严格单调",
                       all(b > a for a, b in zip(stamps, stamps[1:])),
                       f"{len(stamps)} 个非空列"))

        # [C4] 末值语义 + 非空转
        same_ts = got["ts"] == want["ts"]
        same_skew = got["skew"] == want["skew"]
        firsts, lasts, diff_cols = [], [], 0
        for c in range(cols):
            lo, hi = ref.ref_column_span(c, group, drop)
            picked = [source["skew"][i] for i, b in enumerate(source["bucket"])
                      if b is not None and lo <= b < hi]
            if picked:
                firsts.append(picked[0])
                lasts.append(picked[-1])
                if picked[0] != picked[-1]:
                    diff_cols += 1
        checks.append((f"[C4] {tag} 取组内末值（与参考实现逐值一致）",
                       same_skew and same_ts,
                       f"filled={got['filled']} vs {want['filled']}"))
        if group > 1:
            checks.append((f"[C4] {tag} 非空转：存在首值≠末值的列",
                           diff_cols > 0, f"{diff_cols} 列"))
        else:
            checks.append((f"[C4] {tag} group=1 时首值恒等末值，不作非空转断言",
                           True, "结构性说明"))

        # [C5] 首列 ts = 该列桶区间内最后一个点的 ts
        lo, hi = ref.ref_column_span(0, group, drop)
        exp_first = None
        for i, b in enumerate(source["bucket"]):
            if b is not None and lo <= b < hi:
                exp_first = source["ts"][i]
        checks.append((f"[C5] {tag} 首列 ts = 桶区间 [{lo},{hi}) 内最后一点",
                       got["ts"][0] == exp_first, f"{got['ts'][0]} vs {exp_first}"))

        # [C7] 有值列数
        checks.append((f"[C7] {tag} 有值列数（期望 {want['filled']}）",
                       int(got["filled"]) == want["filled"], f"{got['filled']}"))
        checks.append((f"[C7] {tag} 面板读数 points/cols 与网格一致",
                       int(got["points"]) == int(got["filled"]) and
                       int(got["panelCols"]) == cols,
                       f"{got['points']}/{got['panelCols']}"))

    # [C6] 纵轴量程：只认**当前视口**内的极值（见 web/skew.js::axisRange）
    win = result["window"]
    full_hi = float(win["full"][1])
    away_hi = float(win["away"][1])
    on_hi = float(win["on"][1])
    checks.append(("[C6] 序列里能找到尖峰（否则该判据空转）",
                   int(win["spikeCol"]) >= 0, f"第 {win['spikeCol']} 列"))
    checks.append((f"[C6] 全宽时尖峰 {spike} 在可见列内，必须算进量程",
                   full_hi > spike * 0.8, f"上界 {full_hi:.3f}"))
    checks.append((f"[C6] 视口移到尖峰之外时，尖峰必须被排除在量程外",
                   away_hi < spike / 2, f"上界 {away_hi:.3f}"))
    checks.append((f"[C6] 视口只框住尖峰时，量程必须覆盖尖峰",
                   on_hi > spike * 0.8, f"上界 {on_hi:.3f}"))
    checks.append((f"[C6] 视口移开后量程显著收窄（{full_hi / away_hi:.1f}×，"
                   f"证明量程确实跟着视口走）",
                   away_hi < full_hi / 2, f"{full_hi:.3f} → {away_hi:.3f}"))
    return checks


def _report(title: str, checks: list[tuple[str, bool, str]]) -> int:
    print(f"\n{title}")
    failures = 0
    for label, ok, detail in checks:
        if not ok:
            failures += 1
        print(f"  {GREEN if ok else RED}[{'ok' if ok else 'FAIL'}]{RESET} {label}"
              + (f"  {detail}" if detail else ""))
    return failures


# --------------------------------------------------------------------------- #
# 非空转自检
# --------------------------------------------------------------------------- #

def _selftest(frame: dict, source: dict) -> int:
    print("\n[非空转自检] 往前端注入缺陷，检查器必须逐条抓住")
    failures = 0
    files = ("config.js", "matrix_codec.js", "period.js", "skew.js")
    sources = {f: (ROOT / "web" / f).read_text("utf-8") for f in files}

    with tempfile.TemporaryDirectory(prefix="swatch-skew-mutant-") as tmp:
        web = Path(tmp) / "web"
        for name, filename, needle, replacement, expect in MUTATIONS:
            if needle not in sources[filename]:
                print(f"  {RED}[FAIL]{RESET} {name} → 变异点已失效："
                      f"{filename} 里找不到 {needle!r}，请更新 MUTATIONS")
                failures += 1
                continue

            if web.exists():
                shutil.rmtree(web)
            web.mkdir(parents=True)
            for f in files:
                text = sources[f]
                if f == filename:
                    text = text.replace(needle, replacement, 1)
                (web / f).write_text(text, encoding="utf-8")

            try:
                result = ref.run_node_in(frame, web)
            except RuntimeError as exc:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住（变异后驱动报错）"
                      f"  {str(exc)[:70]}")
                continue

            caught = [label for label, ok, _ in evaluate(result, source, frame)
                      if not ok and label.startswith(expect)]
            if caught:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住 {expect}"
                      f"（{len(caught)} 项，例：{caught[0]}）")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**："
                      f"{expect} 全绿，这组对照是空转的")
                failures += 1
    return failures


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

#: 期望前缀（独立常量，不能由 GROUPS 推出 —— 否则删组时期望集合跟着变小、
#: 守卫失明，那一组的失败被静默吞掉仍 RC=0）。详见 ``tools/group_guard.py``。
EXPECTED_PREFIXES = ("[C0]", "[C1]", "[C2]", "[C3]", "[C4]", "[C5]", "[C6]", "[C7]")

GROUPS = (
    ("[C0/C1] 解码与聚合", ("[C0]", "[C1]")),
    ("[C2/C3] 时间轴一致性", ("[C2]", "[C3]")),
    ("[C4/C5/C7] 末值语义与列数", ("[C4]", "[C5]", "[C7]")),
    ("[C6] 纵轴量程（随视口）", ("[C6]",)),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_skew_alignment.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("Skew 周期对齐回归（web/period.js::alignSkew ↔ 热力图列网格）")
    print("=" * 72)

    frame, source = ref.build()
    try:
        result = ref.run_node(frame)
    except RuntimeError as exc:
        print(f"{RED}无法运行 node 驱动{RESET}  {exc}")
        return 1

    checks = evaluate(result, source, frame)

    # 完整性守卫：空集合 / 漏组 / 无人认领的判据都算失败，不是通过。
    problems = guard_problems(checks, GROUPS, EXPECTED_PREFIXES)
    if problems:
        print(f"{RED}判据集合不完整{RESET}  " + "；".join(problems)
              + "  —— 见 tools/group_guard.py")
        return 1

    failures = 0
    for title, prefixes in GROUPS:
        failures += _report(title, [c for c in checks
                                    if c[0].startswith(prefixes)])

    if args.selftest:
        print("\n[非空转自检] 守卫：削掉一组必须被报出来（否则该组的失败会被静默吞掉）")
        for name, probs in guard_cases(checks, GROUPS, EXPECTED_PREFIXES):
            if probs:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住：{probs[0]}")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：守卫是空转的")
                failures += 1
        failures += _selftest(frame, source)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
