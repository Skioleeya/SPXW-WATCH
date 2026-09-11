"""
L6 — 时间周期聚合回归。
========================
唯一职责：证明前端那份周期聚合（``web/period.js``）算出来的东西与后端的定义
一致 —— 尤其是那份**镜像**实现 ``bound()``（对应 ``serialization/numeric.py``
的 ``robust_bound``）没有漂移。

为什么需要它
------------
周期切换把聚合放在前端，代价是色标量程必须在前端按同一规则重算，于是同一个
算法有了 Python 与 JS 两份实现。两份实现最危险的地方在于**它们不会同时出错**：
后端改一次分位规则、前端照旧，图上不会报任何错，只是颜色悄悄不对了 —— 这正是
本项目最怕的"探针全绿但实际是坏的"。参数已由后端随帧下发
（``heatmap.scale_policy``），但**算法本身只能靠对拍钉住**。

五组对照
--------
1. ``options()``    —— 周期列表按基线桶宽过滤后的档位与分组倍数；
2. ``bound()``      —— 与**生产代码** ``serialization.numeric.robust_bound`` 逐值比对；
3. ``aggregate()``  —— 逐格与 Python 参考实现比对（含 null 传播、末组不满）；
4. ``clipTail()``   —— 尾部截断后的列数、标签、``bucket_index``；
5. 跨文件不变量     —— ``maxColumns`` 不得触及 1 分钟视图；基线桶宽整除会话长度。

非空转验证（``--selftest``）
---------------------------
把 ``period.js`` 复制到临时目录并**故意注入**三种缺陷（聚合系数偏移 / 色标漏掉
下限保护 / 组数取整方向反了），要求检查器逐条报出来。三种都能抓住，才说明这组
对照不是空转。造数与参考实现见 ``tools/period_reference.py``。

用法::

    python tools/check_period_aggregation.py
    python tools/check_period_aggregation.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serialization.numeric import robust_bound  # noqa: E402
from tools import period_reference as ref  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

TOLERANCE = 1e-9

#: 变异表：(名称, 原文, 替换)。--selftest 用它证明检查器不是空转。
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    ("聚合系数偏移", "sum += v;", "sum += v + 0.001;"),
    ("色标漏掉下限保护", "return Math.max(picked, floor);", "return picked;"),
    ("组数取整方向反了", "var outCols = Math.ceil(cols / g);",
     "var outCols = Math.floor(cols / g);"),
)


# --------------------------------------------------------------------------- #
# 比较原语
# --------------------------------------------------------------------------- #

def _close(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= TOLERANCE * max(1.0, abs(float(b)))


def _close_matrix(got: list, want: list) -> bool:
    if len(got) != len(want):
        return False
    for got_row, want_row in zip(got, want):
        if len(got_row) != len(want_row):
            return False
        for got_cell, want_cell in zip(got_row, want_row):
            if not _close(got_cell, want_cell):
                return False
    return True


def _flat(values: list) -> list:
    return [v for row in values for v in row if v is not None]


# --------------------------------------------------------------------------- #
# 对照
# --------------------------------------------------------------------------- #

def _option_checks(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    """期望值由 config.js 自己声明的列表推出来，不在这里抄第二份。"""
    declared = result["declared"]
    checks = []
    for key, got in result["options"].items():
        base = int(key)
        want = ([] if base <= 0 else
                [[p["seconds"], p["seconds"] // base, p["label"]]
                 for p in declared if p["seconds"] % base == 0])
        checks.append((f"options(base={base}s) 档位与分组倍数",
                       got == want, f"got={got} want={want}"))
    return checks


def _bound_checks(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    checks = []
    for case in payload["bound"]:
        want = robust_bound(case["values"], case["quantile"], case["floor"])
        got = result["bound"][case["name"]]
        checks.append((f"bound({case['name']}) 与 numeric.robust_bound 一致",
                       _close(got, want), f"js={got} py={want}"))
    return checks


def _aggregate_checks(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    checks = []
    for case in payload["aggregate"]:
        name = case["name"]
        group = case["group"]
        got = result["aggregate"][name]
        want = ref.ref_aggregate(case["block"], group)

        if group <= 1:
            # group=1 是恒等变换：前端刻意原样返回整块，不复制 —— 30 秒视图下
            # 矩阵有 780 列，每帧复制一遍纯属浪费。此时量程就用后端已经按同一
            # 规则算好的那个，**不能**再拿舍入后的值重算（那会与后端差在末几位）。
            want_vmax = case["block"]["vmax"]
        else:
            policy = case["block"]["scale_policy"]
            want_vmax = robust_bound(_flat(want["values"]),
                                     policy["quantile"], policy["floor"])

        checks += [
            (f"aggregate({name}) 列数", got["cols"] == want["cols"],
             f"{got['cols']} vs {want['cols']}"),
            (f"aggregate({name}) 标签", got["labels"] == want["labels"],
             f"首={got['labels'][:1]} 尾={got['labels'][-1:]}"),
            (f"aggregate({name}) 数值逐格一致",
             _close_matrix(got["values"], want["values"]),
             "含 null 传播与末组不满"),
            (f"aggregate({name}) vmax 按后端规则重算",
             _close(got["vmax"], want_vmax),
             f"js={got['vmax']} py={want_vmax}"),
            (f"aggregate({name}) bucket_seconds",
             got["bucket_seconds"] == want["bucket_seconds"],
             str(got["bucket_seconds"])),
            (f"aggregate({name}) bucket_index",
             got["bucket_index"] == want["bucket_index"],
             f"{got['bucket_index']} vs {want['bucket_index']}"),
        ]
    return checks


def _clip_checks(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    clip = payload["clip"]
    got = result["clip"]
    want = ref.ref_clip(clip["block"], clip["maxColumns"])
    return [
        ("clipTail 列数", got["cols"] == want["cols"],
         f"{got['cols']} vs {want['cols']}"),
        ("clipTail 保留最近的一段", got["labels"] == want["labels"],
         f"首={got['labels'][:1]} 尾={got['labels'][-1:]}"),
        ("clipTail 数值切片", _close_matrix(got["values"], want["values"]),
         f"{len(got['values'])} 行"),
        ("clipTail bucket_index 同步回退",
         got["bucket_index"] == want["bucket_index"],
         f"{got['bucket_index']} vs {want['bucket_index']}"),
        ("clipTail 报告被丢弃的列数", got["clipped"] == want["clipped"],
         f"{got['clipped']} vs {want['clipped']}"),
    ]


def _invariant_checks(result: dict) -> list[tuple[str, bool, str]]:
    """跨文件不变量：显示窗口上限与基线桶宽。"""
    app_cfg = json.loads((ROOT / "config" / "app.json").read_text("utf-8"))
    serial_cfg = json.loads(
        (ROOT / "config" / "serialization.json").read_text("utf-8")
    )
    open_min = int(app_cfg["session_open"][:2]) * 60 + int(app_cfg["session_open"][3:])
    close_min = int(app_cfg["session_close"][:2]) * 60 + int(app_cfg["session_close"][3:])
    session_s = (close_min - open_min) * 60
    bucket_s = int(serial_cfg["heatmap_bucket_seconds"])
    max_columns = int(result["maxColumns"] or 0)

    checks = [
        ("基线桶宽整除会话长度（桶恰好铺满会话）",
         session_s % bucket_s == 0, f"会话 {session_s}s ÷ 桶宽 {bucket_s}s"),
        # 这条就是 web/config.js 里 maxColumns 注释所声称的性质：
        # 上限只对最细粒度生效，1 分钟及更粗的周期一个像素都不变。
        ("maxColumns 不触及 1 分钟视图（≥ 会话分钟数）",
         max_columns >= session_s // 60,
         f"maxColumns={max_columns} vs 会话 {session_s // 60} 分钟"),
    ]
    declared = result["declared"]
    if declared:
        finest = min(p["seconds"] for p in declared)
        checks.append(("最细周期不小于基线桶宽（否则凑不出整组）",
                       finest >= bucket_s,
                       f"最细周期 {finest}s vs 基线 {bucket_s}s"))
    return checks


def evaluate(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    """五组对照的全部检查项，(标签, 是否通过, 详情)。"""
    return (_option_checks(result, payload)
            + _bound_checks(result, payload)
            + _aggregate_checks(result, payload)
            + _clip_checks(result, payload)
            + _invariant_checks(result))


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

def _selftest(config_path: Path, payload: dict) -> int:
    print("\n[非空转自检] 往 period.js 注入缺陷，检查器必须逐条抓住")
    source = (ROOT / "web" / "period.js").read_text("utf-8")
    failures = 0

    with tempfile.TemporaryDirectory(prefix="swatch-mutant-") as tmp:
        for name, needle, replacement in MUTATIONS:
            if needle not in source:
                print(f"  {RED}[FAIL]{RESET} 变异点已失效：period.js 里找不到 "
                      f"{needle!r}，请更新 MUTATIONS")
                failures += 1
                continue

            mutant = Path(tmp) / "period.js"
            mutant.write_text(source.replace(needle, replacement, 1), encoding="utf-8")
            try:
                result = ref.run_node(mutant, config_path, payload)
            except RuntimeError as exc:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住（变异后驱动报错）"
                      f"  {str(exc)[:70]}")
                continue

            caught = [label for label, ok, _ in evaluate(result, payload) if not ok]
            if caught:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住"
                      f"（{len(caught)} 项失败，例：{caught[0]}）")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**："
                      "这组对照是空转的")
                failures += 1

    return failures


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

GROUPS = (
    ("[1] 可用周期过滤 options()", "options"),
    ("[2] 色标量程 bound() ↔ numeric.robust_bound", "bound"),
    ("[3] 聚合 aggregate() 逐格对照", "aggregate"),
    ("[4] 显示窗口 clipTail()", "clipTail"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_period_aggregation.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("时间周期聚合回归（web/period.js ↔ 后端定义）")
    print("=" * 72)

    period_path = ROOT / "web" / "period.js"
    config_path = ROOT / "web" / "config.js"
    payload = ref.cases()

    try:
        result = ref.run_node(period_path, config_path, payload)
    except RuntimeError as exc:
        print(f"{RED}无法运行 node 驱动{RESET}  {exc}")
        return 1

    checks = evaluate(result, payload)
    failures = 0
    for title, prefix in GROUPS:
        failures += _report(title, [c for c in checks if c[0].startswith(prefix)])
    failures += _report("[5] 跨文件不变量",
                        [c for c in checks if c[0].startswith(("基线桶宽", "maxColumns",
                                                              "最细周期"))])

    if args.selftest:
        failures += _selftest(config_path, payload)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
