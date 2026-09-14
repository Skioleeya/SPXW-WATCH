"""
L6 — Skew 视口 / 图例 / 刻度回归。
==================================
唯一职责：把 Skew 面板上三件**用户看得见**的事钉成可失败的判据 —— 图例上两条
同名曲线、纵轴刻度精度读配置、meta 读数随视口收窄。

为什么需要它：这三项此前只有一次性探针（写在工程目录之外，用完即弃）守着 ⇒ 下次
谁改坏了 ``web/skew.js`` 不会有任何东西报红。造数与 node 沙箱见
``tools/skew_reference.py``；判据的设计理由见
``notes/sessions/2026-09-13/web-js-gate-and-probe-governance/project_state.md``。

四组判据（前缀即分组键）
------------------------
* ``[G1]`` 图例 —— ``yAxisIndex===0`` 的两条 series **name 必须不同**（同名会被
  ECharts 按 name 去重：图例只剩一条、只带第一色，实测图例带冷色像素 0 而画布上
  1744px），颜色一暖一冷，显示名由 ``legend.formatter`` 抹成同一个。验的是
  **option 结构**（ECharts 的去重规则），不是像素。
* ``[G2]`` 刻度精度 —— 必须证明 formatter **读配置**：换一个 ``axisDecimals`` 再
  渲染，位数必须跟着变；硬编码 ``toFixed`` 则两次输出相同 ⇒ FAIL。
* ``[G3]`` 读数口径 —— ``points``/``cols`` 按**可见列**算（旧口径按全序列，缩到
  21 列仍报 ``780/780 点``）；期望值由帧里的 bucket 列表独立算出，不读中间量。
* ``[G4]`` 视口回调 —— 缩放**不经过** ``update()``（唯一写 meta 的路径），注册 hook
  后 ``setViewport`` 必须回调、且给的是**收窄后**的读数；未注册时不得报错。

已知覆盖边界：夹具的 skew 序列逐桶无空洞 ⇒ ``points`` 恒等于 ``cols``，本回归钉的
是**窗口**（口径随视口走），不是两者的区分。

``--selftest``：① 逐条把修复改回旧行为，要求逐条报出来；② 守卫自身的非空转 ——
削掉一组必须被报出来（``tools/group_guard.py``）。空判据集合、缺组、无人认领的
判据、探针值与默认值相同，都算失败而非通过。

用法:: ``python tools/check_skew_viewport.py [--selftest]``
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import skew_reference as ref  # noqa: E402
from tools.group_guard import guard_cases, guard_problems  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: 取样视口（列索引，闭区间）。第二个刻意框住夹具的尖峰（``SPIKE_AT``），免得
#: "读数收窄"这条判据只在一个恰好没有特征的窗口上成立。
WINDOWS: tuple[tuple[int, int], ...] = ((10, 30), (95, 105))

#: 刻度精度的探针值。取 1.5 而不是 1.23456：1.5 在二进制里精确，Python 的
#: ``f"{v:.Nf}"`` 与 JS 的 ``toFixed(N)`` 必然给出同一个字符串，判据不会因
#: 两种语言的舍入规则差异而假红。
TICK_VALUE = 1.5

#: 探针小数位。**必须与 config 的默认值不同**，否则 [G2] 是空转的。
PROBE_DECIMALS = 3

#: 变异表：(名称, 文件, 原文, 替换, 期望被抓住的判据前缀)。
#: **文件字段必须跟着代码拆分走**：2026-09-14 `skew.js` 拆出 `skew_helpers.js`
#: （NAME_POS/NAME_NEG）与 `skew_option.js`（图例 formatter、两个纵轴刻度），
#: 四条变异的锚点却仍指向 `skew.js`，`--selftest` 全部报"变异点已失效"。
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("skew 两条曲线改回同名", "skew_helpers.js",
     'var NAME_NEG = NAME_POS + "·负";',
     "var NAME_NEG = NAME_POS;",
     "[G1]"),
    ("图例 formatter 不再抹内部后缀", "skew_option.js",
     "        formatter: H.displayName",
     "        formatter: function (n) { return n; }",
     "[G1]"),
    ("左轴刻度改回硬编码 toFixed(2)", "skew_option.js",
     "            color: CFG.theme.textDim, fontSize: 10,\n"
     "            formatter: function (v) { return v.toFixed(CFG.skew.axisDecimals); }",
     "            color: CFG.theme.textDim, fontSize: 10,\n"
     "            formatter: function (v) { return v.toFixed(2); }",
     "[G2]"),
    ("右轴刻度改回硬编码 toFixed(2)", "skew_option.js",
     "            color: CFG.theme.textFaint, fontSize: 10,\n"
     "            formatter: function (v) { return v.toFixed(CFG.skew.axisDecimals); }",
     "            color: CFG.theme.textFaint, fontSize: 10,\n"
     "            formatter: function (v) { return v.toFixed(2); }",
     "[G2]"),
    ("读数退回全序列计数", "skew.js",
     "    var from = win ? win.from : 0;\n    var to = win ? win.to : n - 1;",
     "    var from = 0;\n    var to = n - 1;",
     "[G3]"),
    ("去掉视口回调", "skew.js",
     "    if (this._viewportHook) { this._viewportHook(this._readout()); }",
     "",
     "[G4]"),
)


# --------------------------------------------------------------------------- #
# node 驱动体
# --------------------------------------------------------------------------- #

#: 拼在 ``skew_reference.SANDBOX_JS`` 之后。``__TICK__`` / ``__WINDOWS__`` 由
#: 下面替换成 Python 侧的常量 —— 窗口与探针值只有一份来源。
VIEWPORT_BODY = r"""
/* 全宽网格（不裁剪）：本回归验的是视口与图例，不涉及 clipTail。 */
const full = P.aggregate(F.heatmap, 1);
const aligned = P.alignSkew(F.skew.series, 1, { labels: full.labels, drop: 0 });

/* 替身不实现渲染，所以把每次 setOption 收到的 option 记下来 —— 图例与刻度
   都从它上面读。面板本身只暴露这一条通路，不需要额外接口。 */
let lastOption = null;
function newPanel() {
  const panel = new S.SkewPanel({});
  panel._chart.setOption = function (opt) { lastOption = opt; };
  return panel;
}

const panel = newPanel();
const fullInfo = panel.update(aligned);

/* ---- [G1] 图例：条目 = 各 series 的 name 去重（ECharts 的规则） ---- */
const graphs = lastOption.series;
const skewGraphs = graphs.filter(function (g) { return g.yAxisIndex === 0; });
const deduped = [];
for (const g of graphs) { if (deduped.indexOf(g.name) < 0) { deduped.push(g.name); } }
const fmt = lastOption.legend.formatter;
out.legend = {
  data: lastOption.legend.data.slice(),
  deduped: deduped,
  skewNames: skewGraphs.map(function (g) { return g.name; }),
  skewColors: skewGraphs.map(function (g) { return g.lineStyle && g.lineStyle.color; }),
  skewShown: skewGraphs.map(function (g) { return fmt(g.name); }),
  hot: CFG.theme.hot,
  cool: CFG.theme.cool
};

/* ---- [G2] 刻度精度：改配置再渲染，位数必须跟着变 ---- */
function tick(opt, axis) {
  return opt.yAxis[axis].axisLabel.formatter(__TICK__);
}
out.axis = { decimals: CFG.skew.axisDecimals, probe: __PROBE__ };
out.axis.before = [tick(lastOption, 0), tick(lastOption, 1)];
CFG.skew.axisDecimals = __PROBE__;
newPanel().update(aligned);
out.axis.after = [tick(lastOption, 0), tick(lastOption, 1)];
CFG.skew.axisDecimals = out.axis.decimals;

/* ---- [G3] 读数按可见列 + [G4] 视口回调 ---- */
out.zoom = {
  full: { points: fullInfo.points, cols: fullInfo.cols },
  windows: [], hooks: 0, hook: null, hooksAfterUnhook: 0
};
panel.setViewportHook(function (info) { out.zoom.hooks += 1; out.zoom.hook = info; });
for (const w of __WINDOWS__) {
  panel.setViewport({ start: w[0], end: w[1], tail: false });
  const info = panel._readout();
  out.zoom.windows.push({ from: w[0], to: w[1], points: info.points, cols: info.cols });
}
/* 宿主可以不注册 hook：此时视口变化不得抛错。 */
panel.setViewportHook(null);
panel.setViewport({ start: 0, end: 99, tail: false });
out.zoom.hooksAfterUnhook = out.zoom.hooks;

process.stdout.write(JSON.stringify(out));
"""

DRIVER = (
    ref.SANDBOX_JS
    + VIEWPORT_BODY
    .replace("__TICK__", repr(float(TICK_VALUE)))
    .replace("__PROBE__", str(int(PROBE_DECIMALS)))
    .replace("__WINDOWS__", json.dumps([list(w) for w in WINDOWS]))
)


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #

def expected_points(source: dict, lo: int, hi: int) -> int:
    """窗口 ``[lo, hi]`` 内有读数的列数 —— 由**帧里的 bucket 列表**独立算出来。

    ``alignSkew`` 在 group=1 / drop=0 / 无时段映射时把桶 ``b`` 落在第 ``b`` 列，
    所以"这一列有没有读数"等价于"有没有哪个桶落在这一列且该点非空"。这里刻意
    不调 ``_readout``，也不复制它的实现 —— 对拍的意义在两侧独立。
    """
    cols: set[int] = set()
    for i, b in enumerate(source["bucket"]):
        if b is None or b < 0 or not (lo <= b <= hi):
            continue
        if source["skew"][i] is not None:
            cols.add(b)
    return len(cols)


def evaluate(result: dict, source: dict) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    leg = result["legend"]
    ax = result["axis"]
    zoom = result["zoom"]

    # ---- [G1] 图例：两条同名曲线各占一条、各带自己的颜色 ----
    names = list(leg["skewNames"])
    checks.append(("[G1] 主序列拆成两条曲线（yAxisIndex=0 恰有 2 条）",
                   len(names) == 2, f"{names}"))
    checks.append(("[G1] 两条曲线的 series name 必须不同（图例按 name 去重）",
                   len(set(names)) == 2, f"{names}"))
    checks.append(("[G1] 图例条目 = 各 series 的 name 去重（不是手写清单）",
                   list(leg["data"]) == list(leg["deduped"]), f"{leg['data']}"))
    checks.append(("[G1] 两条 skew 曲线在图例上各占一条（旧行为只剩 1 条）",
                   all(n in leg["data"] for n in names), f"legend.data={leg['data']}"))
    checks.append(("[G1] 两条曲线的图例显示名相同（formatter 抹掉内部后缀）",
                   len(set(leg["skewShown"])) == 1, f"{leg['skewShown']}"))
    colors = list(leg["skewColors"])
    checks.append(("[G1] 两条曲线的颜色互不相同",
                   len(set(colors)) == 2, f"{colors}"))
    checks.append(("[G1] 两条曲线的颜色 = theme.hot / theme.cool（一暖一冷）",
                   sorted(colors) == sorted([leg["hot"], leg["cool"]]),
                   f"{colors} vs [{leg['hot']}, {leg['cool']}]"))

    # ---- [G2] 纵轴刻度精度读配置 ----
    decimals = int(ax["decimals"])
    probe = int(ax["probe"])
    want_before = [f"{float(TICK_VALUE):.{decimals}f}"] * 2
    want_after = [f"{float(TICK_VALUE):.{probe}f}"] * 2
    checks.append((f"[G2] 默认 axisDecimals={decimals} 时两个轴都按它输出",
                   list(ax["before"]) == want_before,
                   f"{ax['before']} vs {want_before}"))
    checks.append((f"[G2] 非空转：探针位数 {probe} ≠ 默认 {decimals}",
                   probe != decimals, f"{decimals} vs {probe}"))
    checks.append((f"[G2] 改配置为 {probe} 后两个轴位数跟着变（证明读配置，非硬编码）",
                   list(ax["after"]) == want_after,
                   f"{ax['after']} vs {want_after}"))

    # ---- [G3] meta 读数按可见列 ----
    full = zoom["full"]
    heat_cols = int(result["heatCols"])
    checks.append(("[G3] 全宽时读数 = 全序列（无缩放不该被收窄）",
                   int(full["cols"]) == heat_cols,
                   f"{full['points']}/{full['cols']} vs 全宽 {heat_cols} 列"))
    checks.append(("[G3] 非空转：全宽列数远大于取样窗口，否则收窄不可观测",
                   int(full["cols"]) > max(hi for _, hi in WINDOWS),
                   f"{full['cols']} > {max(hi for _, hi in WINDOWS)}"))

    for (lo, hi), got in zip(WINDOWS, zoom["windows"]):
        tag = f"视口[{lo},{hi}]"
        exp_cols = hi - lo + 1
        exp_points = expected_points(source, lo, hi)
        checks.append((f"[G3] {tag} cols = 可见列数（期望 {exp_cols}）",
                       int(got["cols"]) == exp_cols, f"{got['cols']}"))
        checks.append((f"[G3] {tag} points = 窗口内有读数的列数（期望 {exp_points}）",
                       int(got["points"]) == exp_points, f"{got['points']}"))
        checks.append((f"[G3] {tag} 读数确实比全宽收窄（旧口径会停在 {full['points']}）",
                       int(got["points"]) < int(full["points"]),
                       f"{got['points']} < {full['points']}"))

    # ---- [G4] 视口回调 ----
    checks.append((f"[G4] 注册 hook 后 setViewport 必须回调宿主（共 {len(WINDOWS)} 次）",
                   int(zoom["hooks"]) == len(WINDOWS),
                   f"{zoom['hooks']} 次"))
    hook = zoom["hook"]
    last_lo, last_hi = WINDOWS[-1]
    checks.append(("[G4] 回调收到的读数已是收窄后的口径",
                   bool(hook) and int(hook["cols"]) == last_hi - last_lo + 1,
                   f"{hook}"))
    checks.append(("[G4] 未注册 hook 时不得报错（宿主可以不注册）",
                   int(zoom["hooksAfterUnhook"]) == int(zoom["hooks"]),
                   f"{zoom['hooksAfterUnhook']} 次"))
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
    print("\n[非空转自检] 逐条把修复改回旧行为，检查器必须报出来")
    failures = 0
    files = ref.WEB_SCRIPTS
    sources = {f: (ROOT / "web" / f).read_text("utf-8") for f in files}

    with tempfile.TemporaryDirectory(prefix="swatch-skew-viewport-") as tmp:
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

            caught = [label for label, ok, _ in evaluate(result, source)
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

#: 判据前缀的**唯一来源**。``GROUPS`` 只负责分组与标题，**不得**自己定义前缀集合 ——
#: 否则删掉一组时守卫跟着失明（2026-09-13 实测：删掉 ``[G4]`` 后该组 3 条失败被静默
#: 吞掉、退出码仍为 0）。守卫与它的非空转用例见 ``tools/group_guard.py``。
EXPECTED_PREFIXES = ("[G1]", "[G2]", "[G3]", "[G4]")

GROUPS = (
    ("[G1] 图例：两条同名曲线各占一条", ("[G1]",)),
    ("[G2] 纵轴刻度精度（读配置，非硬编码）", ("[G2]",)),
    ("[G3] meta 读数按可见列", ("[G3]",)),
    ("[G4] 视口回调", ("[G4]",)),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_skew_viewport.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("Skew 视口 / 图例 / 刻度回归（web/skew.js）")
    print("=" * 72)

    frame, source = ref.build()
    try:
        result = ref.run_node_in(frame, ROOT / "web", driver=DRIVER)
    except RuntimeError as exc:
        print(f"{RED}无法运行 node 驱动{RESET}  {exc}")
        return 1

    checks = evaluate(result, source)
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
        failures += _selftest(frame, source)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
