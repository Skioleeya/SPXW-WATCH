"""
L6 — 周期聚合回归的**非空转自证**。
===================================
唯一职责：往 ``web/`` 的前端脚本里注入已知缺陷，要求 ``check_period_aggregation``
逐条报出来 —— 证明那套对拍不是空转的。

从 ``tools/check_period_aggregation.py`` 拆出（2026-09-15）：那里管"对拍"，这里管
"证明对拍会红"，两件事各自会长。判据函数由调用方传入（``evaluate``），本模块不反向
import 检查器 —— 避免循环依赖，也让"被审计的对象"只有一份。

用法：``python tools/check_period_aggregation.py --selftest``
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent

from tools import period_reference as ref  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

WEB_FILES = ("period.js", "period_align.js")

#: 变异表：(名称, 目标文件, 原文, 替换, 期望被抓住的判据前缀)。
#: **必须带目标文件** —— ``sliceZones`` / ``alignSkew`` 已从 ``period.js`` 拆到
#: ``period_align.js``，而旧表写死"锚点都在 period.js"，于是那两条自检长期打印
#: "变异点已失效"（2026-09-15 发现）。期望前缀同理：不写就只能证明"有东西红了"，
#: 证明不了"该红的那组红了"。
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("聚合系数偏移", "period.js", "sum += v;", "sum += v + 0.001;", "aggregate"),
    ("色标漏掉下限保护", "period.js", "return Math.max(picked, floor);",
     "return picked;", "bound"),
    # 下面两条针对 2026-09-15 定稿的「**周期走满才出列**」语义。
    # 改回旧行为（把未走满的末组也输出）必须被抓住 —— 那正是 KAI 报的
    # 「周期内 IV 仍在变 / 跨周期先渲染 +0」的根因。
    ("未走满的末组也出列（回到旧语义）", "period.js",
     "    var outCols = Math.floor(cols / g);",
     "    var outCols = Math.ceil(cols / g);", "aggregate"),
    # 末组被丢弃后，其起点标签不该再出现在结果里（少一列就是少一列）。
    # 把「整除」改成「+1 列」可以骗过列数以外的字段，但它必须被标签判据抓住。
    ("末组丢弃后标签序列未同步（多报一列的位置）", "period.js",
     "    for (var i = 0; i < outCols; i++) {\n      labels.push(groupLabel(block.labels[i * g], g * baseSeconds));",
     "    for (var i = 0; i <= outCols; i++) {\n      labels.push(groupLabel(block.labels[i * g], g * baseSeconds));",
     "aggregate"),
    ("切列忽略区段过滤（空档被留下）", "period_align.js",
     "      if (keep[zones[z].id]) { order.push(zones[z]); }",
     "      order.push(zones[z]);", "sliceZones"),
    ("alignSkew 忽略时段映射", "period_align.js", "        pos = index[b];",
     "        pos = b;", "时段映射"),
)


def run(config_path: Path, payload: dict,
        evaluate: Callable[[dict, dict], list]) -> int:
    """逐条注入缺陷，返回**未被抓住**的条数（0 = 自证通过）。"""
    print("\n[非空转自检] 往前端脚本注入缺陷，检查器必须逐条抓住")
    failures = 0
    sources = {f: (ROOT / "web" / f).read_text("utf-8") for f in WEB_FILES}

    with tempfile.TemporaryDirectory(prefix="swatch-period-mutant-") as tmp:
        web = Path(tmp) / "web"
        web.mkdir()
        for name, filename, needle, replacement, expect in MUTATIONS:
            if needle not in sources[filename]:
                print(f"  {RED}[FAIL]{RESET} {name} → 变异点已失效：{filename} 里"
                      f"找不到 {needle!r}，请更新 MUTATIONS")
                failures += 1
                continue

            # 每轮把两个文件都重写一遍 —— 上一轮的变异绝不残留，否则后面的
            # "已抓住"可能来自累积的坏文件，自证变成假绿。
            for f in WEB_FILES:
                text = sources[f]
                if f == filename:
                    text = text.replace(needle, replacement, 1)
                (web / f).write_text(text, encoding="utf-8")

            try:
                result = ref.run_node(web / "period.js", config_path, payload,
                                      web / "period_align.js")
            except RuntimeError as exc:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住（变异后驱动报错）"
                      f"  {str(exc)[:70]}")
                continue

            caught = [label for label, ok, _ in evaluate(result, payload)
                      if not ok and label.startswith(expect)]
            if caught:
                print(f"  {GREEN}[ok]{RESET} {name} → 已抓住 {expect}"
                      f"（{len(caught)} 项，例：{caught[0]}）")
            else:
                print(f"  {RED}[FAIL]{RESET} {name} → **未被抓住**：{expect} 全绿，"
                      "这组对照是空转的")
                failures += 1
    return failures
