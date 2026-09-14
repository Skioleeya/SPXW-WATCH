"""
L6 — Skew 三条 IV 曲线的配色回归。
==================================
唯一职责：钉住"哪条 IV 曲线是什么颜色" —— Put25 绿 / Call25 红 / ATM 跨式 黄，
三者互不相同，且图例图标色与曲线色一致。

为什么需要它：2026-09-14 之前三条 IV 曲线复用主序列的分段色（Put25 = theme.hot
红、Call25 = theme.cool 蓝、ATM = theme.textFaint 灰），而主序列 25Δ Skew 按正负
也走 hot/cool ⇒ 图上出现"两条红、两条蓝"，再叠加图例里两个同名的 25Δ Skew，
用户无法分辨哪条是 IV、哪条是 Skew。这类缺陷 ``--check`` / 语法 / 契约全绿都拦不住
—— 只有把语义色钉成判据才行。

三组判据（前缀即分组键）
------------------------
* ``[C1]`` 语义 —— 三条 IV 曲线的颜色 = 指定值。期望值在**检查器里写死**、不从
  config 读回来对拍：只与 config 对拍的话，"把 config 改回红/蓝"会被静默放行
  （断言跟着配置一起变，永远相等）。config 的 ``skew.colors`` 是实现，不是需求。
* ``[C2]`` 可区分 —— 三条颜色互不相同，且至少一条不用 Skew 的分段色
  （修复前 Put/Call 与 Skew 分段色两两撞色）。
* ``[C3]`` 图例一致 —— ``itemStyle.color`` 与 ``lineStyle.color`` 同值：ECharts
  的图例图标读前者、曲线读后者，只改一处会让图例与曲线对不上。

``--selftest``：逐条把修复改回旧行为，要求逐条报出来；守卫自身的非空转
（削掉一组必须被报出来）由 ``tools/group_guard.py`` 负责。

用法:: ``python tools/check_skew_colors.py [--selftest]``
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

#: 三条 IV 曲线的**需求色**（2026-09-14 KAI 指定）：跨式黄 / Put 绿 / Call 红。
#: 键 = series name，必须与 ``web/skew.js`` 里 push 的 name 逐字相同。
IV_COLORS_WANTED: dict[str, str] = {
    "ATM IV": "#ffb020",
    "25Δ Put IV": "#2fd07a",
    "25Δ Call IV": "#ff5a5a",
}

#: 变异表：(名称, 文件, 原文, 替换, 期望被抓住的判据前缀)。
#: 锚点取自 ``web/skew.js`` 的三条 IV 曲线定义；那里的写法一变就要同步这里，
#: 否则 ``--selftest`` 会报"变异点已失效"（2026-09-14 已在 viewport 回归上踩过）。
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("Put IV 退回复用 Skew 的分段色", "skew.js",
     'lineStyle: { width: 1.1, type: "dashed", color: CFG.skew.colors.put25, opacity: .75 },',
     'lineStyle: { width: 1.1, type: "dashed", color: CFG.theme.hot, opacity: .75 },',
     "[C1]"),
    ("ATM 曲线退回旧的淡灰", "skew.js",
     'lineStyle: { width: 1.1, type: "dotted", color: CFG.skew.colors.atm },',
     'lineStyle: { width: 1.1, type: "dotted", color: CFG.theme.textFaint },',
     "[C1]"),
    ("只改曲线色、忘改图例图标色", "skew.js",
     'itemStyle: { color: CFG.skew.colors.call25 },',
     'itemStyle: { color: CFG.skew.colors.atm },',
     "[C3]"),
)


# --------------------------------------------------------------------------- #
# node 驱动体
# --------------------------------------------------------------------------- #

#: 拼在 ``skew_reference.SANDBOX_JS`` 之后。替身不实现渲染，所以从 ``setOption``
#: 收到的 option 上把三条 IV 曲线（``yAxisIndex===1``）的颜色读出来。
DRIVER_BODY = r"""
let lastOption = null;
const panel = new S.SkewPanel({});
panel._chart.setOption = function (opt) { lastOption = opt; };

const full = P.aggregate(F.heatmap, 1);
const aligned = P.alignSkew(F.skew.series, 1, { labels: full.labels, drop: 0 });
panel.update(aligned);

const iv = lastOption.series.filter(function (g) { return g.yAxisIndex === 1; });
out.iv = {
  names: iv.map(function (g) { return g.name; }),
  lineColors: iv.map(function (g) { return g.lineStyle && g.lineStyle.color; }),
  itemColors: iv.map(function (g) { return g.itemStyle && g.itemStyle.color; })
};
out.seg = { hot: CFG.theme.hot, cool: CFG.theme.cool };
process.stdout.write(JSON.stringify(out));
"""

DRIVER = ref.SANDBOX_JS + DRIVER_BODY


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #

def evaluate(result: dict) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    iv = result["iv"]
    names = list(iv["names"])
    line = list(iv["lineColors"])
    item = list(iv["itemColors"])
    seg = set(result["seg"].values())

    # ---- [C1] 语义色 ----
    got = dict(zip(names, line))
    checks.append(("[C1] 三条 IV 曲线都在（缺一条则下面的语义对拍无意义）",
                   len(names) == len(IV_COLORS_WANTED), f"{names}"))
    checks.append(("[C1] 三条 IV 曲线的颜色 = 指定语义（跨式黄 / Put 绿 / Call 红）",
                   got == IV_COLORS_WANTED, f"{got} vs {IV_COLORS_WANTED}"))

    # ---- [C2] 可区分 ----
    checks.append(("[C2] 三条 IV 曲线颜色互不相同",
                   len(set(line)) == len(IV_COLORS_WANTED), f"{line}"))
    checks.append(("[C2] 至少一条不用 Skew 的分段色（否则又回到两红两蓝）",
                   not set(line) <= seg, f"{line} ⊆ {sorted(seg)}"))

    # ---- [C3] 图例与曲线一致 ----
    checks.append(("[C3] itemStyle.color 与 lineStyle.color 同值（图例图标读前者）",
                   line == item, f"line={line} item={item}"))
    checks.append(("[C3] 非空转：取到的是真色串，不是 undefined",
                   all(isinstance(c, str) and c.startswith("#") for c in line),
                   f"{line}"))
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

def _selftest(frame: dict) -> int:
    print("\n[非空转自检] 逐条把修复改回旧行为，检查器必须报出来")
    failures = 0
    files = ref.WEB_SCRIPTS
    sources = {f: (ROOT / "web" / f).read_text("utf-8") for f in files}

    with tempfile.TemporaryDirectory(prefix="swatch-skew-colors-") as tmp:
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
                result = ref.run_node_in(frame, web, driver=DRIVER)
            except RuntimeError as exc:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住（变异后驱动报错）"
                      f"  {str(exc)[:70]}")
                continue

            caught = [label for label, ok, _ in evaluate(result)
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

#: 判据前缀的**唯一来源**。``GROUPS`` 只负责分组与标题，不得自己定义前缀集合 ——
#: 否则删掉一组时守卫跟着失明。守卫见 ``tools/group_guard.py``。
EXPECTED_PREFIXES = ("[C1]", "[C2]", "[C3]")

GROUPS = (
    ("[C1] 语义：哪条 IV 曲线是什么颜色", ("[C1]",)),
    ("[C2] 可区分：三条互不相同、且不退回 Skew 分段色", ("[C2]",)),
    ("[C3] 图例一致：图标色 = 曲线色", ("[C3]",)),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_skew_colors.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("Skew 三条 IV 曲线配色回归（web/skew.js ↔ config.js::skew.colors）")
    print("=" * 72)

    frame, _ = ref.build()
    try:
        result = ref.run_node_in(frame, ROOT / "web", driver=DRIVER)
    except RuntimeError as exc:
        print(f"{RED}无法运行 node 驱动{RESET}  {exc}")
        return 1

    checks = evaluate(result)
    failures = 0

    # 完整性守卫：空集合 / 漏组 / 无人认领的判据都算失败，不是通过。
    problems = guard_problems(checks, GROUPS, EXPECTED_PREFIXES)
    if problems:
        print(f"{RED}判据集合不完整{RESET}  " + "；".join(problems)
              + "  —— 见 tools/group_guard.py")
        return 1

    for title, prefixes in GROUPS:
        failures += _report(title, [c for c in checks if c[0].startswith(prefixes)])

    if args.selftest:
        print("\n[非空转自检] 守卫：削掉一组必须被报出来（否则该组的失败会被静默吞掉）")
        for name, problems in guard_cases(checks, GROUPS, EXPECTED_PREFIXES):
            if problems:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住：{problems[0]}")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：守卫是空转的")
                failures += 1
        failures += _selftest(frame)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
