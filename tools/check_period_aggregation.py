"""
L6 — 时间周期聚合回归。
========================
唯一职责：证明前端那份周期聚合（``web/period.js``）算出来的东西与后端的定义
一致 —— 尤其是那份**镜像**实现 ``bound()``（对应 ``serialization/numeric.py``
的 ``robust_bound``）没有漂移。七组对照见本文件末 ``GROUPS`` 常量。

为什么需要它：周期切换把聚合放在前端，色标量程必须在前端按同一规则重算，于是
同一个算法有了 Python 与 JS 两份实现。后端改一次分位规则、前端照旧，图上不会
报错、只是颜色悄悄不对了 —— 这正是本项目最怕的"探针全绿但实际是坏的"。
参数已由后端随帧下发（``heatmap.scale_policy``），**算法本身只能靠对拍钉住**。

非空转验证（``--selftest``）：把 ``period.js`` 复制到临时目录并**故意注入**五种
缺陷，要求检查器逐条报出来。造数与参考实现见 ``tools/period_reference.py``。

用法::

    python tools/check_period_aggregation.py [--selftest]
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

from core.session_grid import minutes_of_day  # noqa: E402
from serialization.numeric import robust_bound  # noqa: E402
from tools import period_reference as ref  # noqa: E402
from tools.group_guard import guard_cases, guard_problems  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

TOLERANCE = 1e-9

#: 变异表：(名称, 原文, 替换) —— ``--selftest`` 用它证明检查器不是空转。
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    ("聚合系数偏移", "sum += v;", "sum += v + 0.001;"),
    ("色标漏掉下限保护", "return Math.max(picked, floor);", "return picked;"),
    ("组数取整方向反了", "var outCols = Math.ceil(cols / g);",
     "var outCols = Math.floor(cols / g);"),
    ("切列忽略区段过滤（空档被留下）",
     "      if (keep[zones[z].id]) { order.push(zones[z]); }",
     "      order.push(zones[z]);"),
    ("alignSkew 忽略时段映射", "        pos = index[b];", "        pos = b;"),
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


def _slice_checks(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    """时段切列：逐格对照 + 映射表对照。"""
    checks = []
    zones = payload["slice"]["zones"]
    for case in payload["slice"]["cases"]:
        name = case["name"]
        got = result["slice"][name]
        want = ref.ref_slice_zones(case["block"], zones, case["keep"])

        if want is None:
            checks.append((
                f"sliceZones({name}) 无匹配区段时必须返回空（前端据此保留上一帧）",
                got is None, f"js={got!r}"))
            continue
        if got is None:
            checks.append((f"sliceZones({name}) 不应返回空", False, "js=null"))
            continue

        checks += [
            (f"sliceZones({name}) 列数", got["cols"] == want["cols"],
             f"{got['cols']} vs {want['cols']}"),
            (f"sliceZones({name}) 标签序列", got["labels"] == want["labels"],
             f"首={got['labels'][:1]} 尾={got['labels'][-1:]}"),
            (f"sliceZones({name}) 数值逐格一致",
             _close_matrix(got["values"], want["values"]),
             f"{len(got['values'])} 行 × {got['cols']} 列"),
            (f"sliceZones({name}) 映射表（基线列 → 切后列，-1 = 已切掉）",
             got["index"] == want["index"], "逐元素一致"),
            (f"sliceZones({name}) bucket_index 同步平移",
             got["bucket_index"] == want["bucket_index"],
             f"{got['bucket_index']} vs {want['bucket_index']}"),
        ]
    return checks


def _index_checks(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    """时段切列之后，Skew 折线的落列必须跟着同一份映射走。"""
    case = payload["index"]
    got = result["index"]
    cols = len(case["labels"])
    want = ref.ref_align_indexed(
        case["series"], case["group"], cols, case["drop"], case["index"]
    )
    filled = sum(1 for v in (got["withIndex"] or []) if v is not None)
    return [
        ("时段映射下 Skew 落列与参考实现逐值一致",
         got["withIndex"] == want, f"{filled} 个非空列"),
        ("时段映射路径 ≡ 预映射路径（index 只是省一次复制，不该改变任何一格）",
         got["withIndex"] == got["premapped"], "两条路径逐值相同"),
        ("时段切列非空转：忽略映射（拿原始桶号直接落列）必须给出不同结果",
         got["unsliced"] != got["withIndex"], "否则这组对照是空转的"),
    ]


def _invariant_checks(result: dict) -> list[tuple[str, bool, str]]:
    """跨文件不变量：显示窗口上限与基线桶宽，都以**整个交易日网格**为准。"""
    app_cfg = json.loads((ROOT / "config" / "app.json").read_text("utf-8"))
    serial_cfg = json.loads(
        (ROOT / "config" / "serialization.json").read_text("utf-8")
    )
    grid_s = _grid_minutes(app_cfg) * 60
    bucket_s = int(serial_cfg["heatmap_bucket_seconds"])
    max_columns = int(result["maxColumns"] or 0)
    grid_buckets = -(-grid_s // bucket_s)

    checks = [
        ("基线桶宽整除交易日网格（各会话 + 空档恰好铺满）",
         grid_s % bucket_s == 0, f"网格 {grid_s}s ÷ 桶宽 {bucket_s}s"),
        # 上限必须盖住**整个交易日网格**。横轴是时间轴，从尾部截掉历史段在图
        # 上看不出来（只是左边少了几列，没有滚动条也没有提示）—— 于是 GTH
        # 开盘那一段会静默消失，而"能在 GTH 时段完成实盘验证"恰恰要求看得见它。
        ("maxColumns 覆盖整个交易日网格（基线粒度下永不截断）",
         max_columns >= grid_buckets,
         f"maxColumns={max_columns} vs 网格 {grid_buckets} 桶"),
    ]
    declared = result["declared"]
    if declared:
        finest = min(p["seconds"] for p in declared)
        checks.append(("最细周期不小于基线桶宽（否则凑不出整组）",
                       finest >= bucket_s,
                       f"最细周期 {finest}s vs 基线 {bucket_s}s"))
    return checks


def _grid_minutes(app_cfg: dict) -> int:
    """
    交易日网格的总分钟数 = 各会话时长 + 它们之间的空档。只认 ``app.json::sessions``，
    时刻解析交给 ``core.session_grid.minutes_of_day``（这里不重写一份）。
    """
    total = 0
    prev_close: int | None = None
    for item in app_cfg["sessions"]:
        open_min = minutes_of_day(str(item["open"]))
        close_min = minutes_of_day(str(item["close"]))
        if prev_close is not None:
            total += (open_min - prev_close) % (24 * 60)
        total += (close_min - open_min) % (24 * 60)
        prev_close = close_min
    return total


def evaluate(result: dict, payload: dict) -> list[tuple[str, bool, str]]:
    """七组对照的全部检查项，(标签, 是否通过, 详情)。"""
    return (_option_checks(result, payload)
            + _bound_checks(result, payload)
            + _aggregate_checks(result, payload)
            + _clip_checks(result, payload)
            + _slice_checks(result, payload) + _index_checks(result, payload)
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

#: 期望前缀（独立常量，不能由 GROUPS 推出 —— 否则删组时期望集合跟着变小、
#: 守卫失明，那一组的失败被静默吞掉仍 RC=0）。详见 ``tools/group_guard.py``。
EXPECTED_PREFIXES = ("options", "bound", "aggregate", "clipTail", "sliceZones",
                     "时段映射", "时段切列", "基线桶宽", "maxColumns", "最细周期")

GROUPS = (
    ("[1] 可用周期过滤 options()", ("options",)),
    ("[2] 色标量程 bound() ↔ numeric.robust_bound", ("bound",)),
    ("[3] 聚合 aggregate() 逐格对照", ("aggregate",)),
    ("[4] 显示窗口 clipTail()", ("clipTail",)),
    ("[5] 时段切列 sliceZones()", ("sliceZones",)),
    ("[6] 时段映射下的 Skew 落列", ("时段映射", "时段切列")),
    ("[7] 跨文件不变量", ("基线桶宽", "maxColumns", "最细周期")),
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

    # 完整性守卫：空集合 / 漏组 / 无人认领的判据都算失败，不是通过。
    problems = guard_problems(checks, GROUPS, EXPECTED_PREFIXES)
    if problems:
        print(f"{RED}判据集合不完整{RESET}  {'；'.join(problems)}"
              + "  —— 见 tools/group_guard.py")
        return 1

    failures = 0
    for title, prefixes in GROUPS:
        failures += _report(title, [c for c in checks if c[0].startswith(prefixes)])

    if args.selftest:
        print("\n[非空转自检] 守卫：削掉一组必须被报出来（否则该组的失败会被静默吞掉）")
        for name, probs in guard_cases(checks, GROUPS, EXPECTED_PREFIXES):
            if probs:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住：{probs[0]}")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：守卫是空转的")
                failures += 1
        failures += _selftest(config_path, payload)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
