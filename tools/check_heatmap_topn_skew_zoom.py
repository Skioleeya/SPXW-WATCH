"""
L6 — 热力图 Top-N 高亮 与 Skew Y 轴自由缩放的回归。
====================================================
唯一职责：钉住 2026-09-15 新增的两项**只在前端成立**的语义 ——

* ``[T1]`` 成交量 Top-N 高亮：**只有**整个可视区域内成交量最大的 N 格描黑边，
  其余格子**完全不描边**；且 Top-N **内部**宽度不等（第 1 名最粗、第 N 名最细）。
* ``[Y1]`` Y 轴自由缩放：滚轮可无限制放大/缩小量程，锚点在缩放前后不动，
  量程被 ``minSpan``/``maxSpan`` 夹住，退化输入不得产出零宽量程。
  锚点落到量程**之外**时必须退到中心 —— 否则整个视口会被拖到指针处、曲线瞬移。
* ``[Y2]`` 缩放态**锁定** —— 新数据到来不得覆盖用户定的量程。
* ``[Y3]`` **X 轴不受影响** —— ``dataZoom`` 只作用于 ``xAxisIndex``，无 ``yAxisIndex``。

为什么需要这个回归
-------------------
这三件事 ``--check`` / 语法 / 契约全绿都拦不住：
- Top-N 的"只描 3 格"是**计数**语义，类型与结构全对也可能描了 48 格；
- "Top-N 内部宽度不等"更隐蔽 —— 若拿**第 N 名的成交量**当分母，选中集里每个成员的
  比值都 ≥ 1，夹取后宽度**全部相等**（2026-09-15 实测抓到的就是这一条，
  首版实现确实错了）；
- Y 轴缩放是纯前端交互，后端帧里没有任何对应字段。

`scripts` 里没有浏览器，所以用 ``skew_reference.SANDBOX_JS`` 这个共享沙箱
（ECharts 替身）在 node 里求值前端脚本 —— 与 ``check_skew_colors`` /
``check_skew_viewport`` 同一手法。像素级观感仍由人工确认，不在本回归范围。

``--selftest``：逐条把修复改回旧行为，要求逐条报出来。

用法:: ``python tools/check_heatmap_topn_skew_zoom.py [--selftest]``
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
from tools import topn_zoom_driver as drv  # noqa: E402
from tools.group_guard import guard_cases, guard_problems  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: 合成矩阵的形状与 node 驱动都在 ``tools/topn_zoom_driver.py``（IO 与判据分离）。
TOPN_ROWS = drv.TOPN_ROWS
TOPN_COLS = drv.TOPN_COLS
run_node = drv.run_node

#: 变异表：(名称, 文件, 原文, 替换, 期望被抓住的判据前缀)。
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("边框分母退回第 N 名成交量（选中集宽度会全等）", "heatmap.js",
     "    var t = hi > lo ? (vol - lo) / (hi - lo) : 1;",
     "    var t = hi > 0 ? vol / hi : 1;", "[T1]"),
    ("取消只描 N 格（所有非零成交量都描边）", "heatmap.js",
     '        var hit = pick && pick.cells[c + "," + r];',
     "        var hit = volumes && volumes[r] && volumes[r][c] > 0;", "[T1]"),
    ("锚点落到量程外时不再退到中心（视口被拖到指针处）", "skew_helpers.js",
     "    var t = (a - lo) / (hi - lo);",
     "    var t = 0.5;", "[Y1]"),
    ("缩放下限失效（可缩到 0 宽）", "skew_helpers.js",
     "    if (want < floor) { want = floor; }",
     "    if (want < 0) { want = 0; }", "[Y1]"),
    ("锁定量程被自动量程覆盖", "skew_helpers.js",
     "    if (locked && isFinite(locked[0]) && isFinite(locked[1]) && locked[1] > locked[0]) {",
     "    if (false) {", "[Y2]"),
)


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #

def evaluate(result: dict) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    t = result["topn"]
    y = result["yzoom"]
    a = result["axes"]
    cfg = t["cfg"]
    z = y["cfg"]

    # ---- [T1] 成交量 Top-N ----
    want_n = int(cfg["topN"])
    checks.append(("[T1] 配置声明 topN=3", want_n == 3, f"topN={want_n}"))

    checks.append((f"[T1] 只有 {want_n} 格被描边（其余为普通样式）",
                   t["styledCount"] == want_n,
                   f"实际 {t['styledCount']} / 共 {t['total']} 格"))
    checks.append(("[T1] 未选中格一律无边框",
                   t["nonStyledCount"] == t["total"] - want_n,
                   f"无边框 {t['nonStyledCount']}"))

    # 成交量 = r*COLS+c ⇒ 最大的 3 格固定在右下角 (COLS-1,ROWS-1) 起倒数
    want_cells = sorted(
        [(TOPN_COLS - 1 - i % TOPN_COLS, TOPN_ROWS - 1 - i // TOPN_COLS)
         for i in range(want_n)]
    )
    got_cells = sorted([(c["c"], c["r"]) for c in t["styled"]])
    checks.append((f"[T1] 被描边的正是成交量最大的 {want_n} 格",
                   got_cells == want_cells, f"{got_cells} vs {want_cells}"))

    checks.append(("[T1] 未选中格保持裸三元组（不引入多余对象）",
                   t["bareNonStyled"] == t["nonStyledCount"],
                   f"{t['bareNonStyled']}/{t['nonStyledCount']}"))

    # Top-N 内部必须分得出粗细 —— 首版拿"第 N 名成交量"当分母，导致全等。
    # ⚠️ 变异体可能把选中集变成空集（比如"取消只描 N 格"那条反向变异），
    # 此时 max()/min() 会抛 —— 判据必须能**报红**而不是崩，否则 --selftest
    # 变成"驱动报错"、白白通过（本项目最怕的假绿）。
    widths = sorted([c["w"] for c in t["styled"]])
    vols = sorted([c["vol"] for c in t["styled"]])
    if not widths:
        checks.append(("[T1] Top-N 内部描边宽度不等（成交量越大越粗）",
                       False, "选中集为空 —— 没有任何格子被描边"))
        checks.append(("[T1] 宽度随成交量单调不减", False, "选中集为空"))
        checks.append(("[T1] 最粗 = maxRatio × 格短边", False, "选中集为空"))
        checks.append(("[T1] 最细 = minRatio × 格短边", False, "选中集为空"))
    else:
        checks.append(("[T1] Top-N 内部描边宽度不等（成交量越大越粗）",
                       len(set(round(w, 6) for w in widths)) == len(widths),
                       f"成交量 {vols} → 宽度 {[round(w, 2) for w in widths]}"))
        if len(t["styled"]) >= 2:
            by_vol = sorted(t["styled"], key=lambda c: c["vol"])
            increasing = all(by_vol[i]["w"] <= by_vol[i + 1]["w"] + 1e-9
                             for i in range(len(by_vol) - 1))
            checks.append(("[T1] 宽度随成交量单调不减",
                           increasing,
                           "  ".join(f"{c['vol']}→{c['w']:.2f}" for c in by_vol)))

        hi_want = t["cellShort"] * float(cfg["maxRatio"])
        lo_want = t["cellShort"] * float(cfg["minRatio"])
        checks.append(("[T1] 最粗 = maxRatio × 格短边",
                       abs(max(widths) - hi_want) < 0.02,
                       f"{max(widths):.2f} vs {hi_want:.2f}"))
        checks.append(("[T1] 最细 = minRatio × 格短边",
                       abs(min(widths) - lo_want) < 0.02,
                       f"{min(widths):.2f} vs {lo_want:.2f}"))

    # ---- [Y1] 无限制缩放 ----
    checks.append(("[Y1] 滚轮向前 ⇒ 量程收窄（放大）",
                   y["inSpan"] < y["baseSpan"],
                   f"{y['baseSpan']:.3f} → {y['inSpan']:.3f}"))
    checks.append(("[Y1] 滚轮向后 ⇒ 量程变宽（缩小）",
                   y["outSpan"] > y["baseSpan"],
                   f"{y['baseSpan']:.3f} → {y['outSpan']:.3f}"))
    checks.append(("[Y1] 可连续放大到极小刻度（60 次后贴近 minSpan）",
                   abs(y["tinySpan"] - z["minSpan"]) < 1e-6,
                   f"{y['tinySpan']:.4f} vs minSpan {z['minSpan']}"))
    checks.append(("[Y1] 可连续缩小到很大范围（60 次后贴近 maxSpan）",
                   abs(y["hugeSpan"] - z["maxSpan"]) < 1e-6,
                   f"{y['hugeSpan']:.2f} vs maxSpan {z['maxSpan']}"))
    checks.append(("[Y1] 缩放时锚点不动（指针所指的 Y 值保持原位）",
                   abs(y["anchorIn"] - y["anchorBase"]) < 1e-9,
                   f"t: {y['anchorBase']:.6f} → {y['anchorIn']:.6f}"))

    # 退化输入
    checks.append(("[Y1] 从窄于下限的量程继续放大不塌成零宽",
                   y["degNarrowSpan"] >= z["minSpan"] - 1e-9,
                   f"span={y['degNarrowSpan']:.6f}"))
    checks.append(("[Y1] 锚点压在量程边界上不塌成零宽",
                   y["edgeLoSpan"] > 0 and y["edgeHiSpan"] > 0,
                   f"左 {y['edgeLoSpan']:.6f} / 右 {y['edgeHiSpan']:.6f}"))
    checks.append(("[Y1] 锚点落在量程外时退到中心（视口不瞬移）",
                   y["outsideIsCenter"], f"中心 {y['outsideCenter']:.4f}"))
    checks.append((f"[Y1] {y['randomTrials']} 组随机输入全部产出有效量程",
                   y["randomBad"] == 0, f"异常 {y['randomBad']} 组"))

    checks.append(("[Y1] 刻度小数位随量程收窄而增加",
                   y["decimalsNarrow"] > y["decimalsWide"],
                   f"{y['decimalsWide']} → {y['decimalsNarrow']}"))
    checks.append(("[Y1] 刻度小数位有上限（不无限增位）",
                   y["decimalsCapped"] <= 6, f"{y['decimalsCapped']}"))

    # ---- [Y2] 锁定 ----
    checks.append(("[Y2] 无锁定时走自动量程（跟随可见列极值）",
                   y["autoRange"][0] < 0 and y["autoRange"][1] > 0,
                   f"[{y['autoRange'][0]:.2f}, {y['autoRange'][1]:.2f}]"))
    checks.append(("[Y2] 锁定量程原样生效，不被数据覆盖",
                   y["lockedRange"] == [0, 5] and y["lockedStable"],
                   f"{y['lockedRange']}"))

    # ---- [Y3] X 轴不受影响 ----
    checks.append(("[Y3] dataZoom 只作用于 xAxisIndex",
                   list(a["xAxisIndex"]) == [0], f"{a['xAxisIndex']}"))
    checks.append(("[Y3] dataZoom 不含 yAxisIndex（Y 走独立通道）",
                   a["hasYAxisIndex"] is False, "yAxisIndex 未出现"))
    checks.append(("[Y3] 纵轴量程确实落到 option 上",
                   a["y0min"] == -1 and a["y0max"] == 3,
                   f"[{a['y0min']}, {a['y0max']}]"))
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

def _selftest(payload: dict) -> int:
    print("\n[非空转自检] 逐条把修复改回旧行为，检查器必须报出来")
    failures = 0
    files = drv.WEB_FILES
    sources = {f: (ROOT / "web" / f).read_text("utf-8") for f in files}

    with tempfile.TemporaryDirectory(prefix="swatch-topn-mutant-") as tmp:
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
                result = run_node(payload, web)
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
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：{expect} 全绿，"
                      "这组对照是空转的")
                failures += 1
    return failures


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

EXPECTED_PREFIXES = ("[T1]", "[Y1]", "[Y2]", "[Y3]")

GROUPS = (
    ("[T1] 成交量 Top-N 高亮（只描 N 格）", ("[T1]",)),
    ("[Y1] Y 轴自由缩放（无限制 + 锚点 + 边界）", ("[Y1]",)),
    ("[Y2] 缩放态锁定", ("[Y2]",)),
    ("[Y3] X 轴时间范围不受影响", ("[Y3]",)),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_heatmap_topn_skew_zoom.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("热力图 Top-N 高亮 与 Skew Y 轴自由缩放回归")
    print("=" * 72)

    payload, _ = ref.build()
    try:
        result = run_node(payload)
    except RuntimeError as exc:
        print(f"{RED}无法运行 node 驱动{RESET}  {exc}")
        return 1

    checks = evaluate(result)
    problems = guard_problems(checks, GROUPS, EXPECTED_PREFIXES)
    if problems:
        print(f"{RED}判据集合不完整{RESET}  {'；'.join(problems)}"
              + "  —— 见 tools/group_guard.py")
        return 1

    failures = 0
    for title, prefixes in GROUPS:
        failures += _report(title, [c for c in checks if c[0].startswith(prefixes)])

    if args.selftest:
        print("\n[非空转自检] 守卫：削掉一组必须被报出来")
        for name, probs in guard_cases(checks, GROUPS, EXPECTED_PREFIXES):
            if probs:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住：{probs[0]}")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：守卫是空转的")
                failures += 1
        failures += _selftest(payload)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
