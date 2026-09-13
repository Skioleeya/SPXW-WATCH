"""
L6 — 结构自检。
================
唯一职责：校验**代码的组织形态**，即"文件多大、谁可以 import 谁"。

检查项
------
[1] 文件长度：每个 ``.py`` 与 ``web/*.js`` 必须少于 400 行。
[2] 依赖方向：第 N 层的模块只能 import 第 0…N 层的包，禁止反向依赖。

对应项目硬性要求第 1 条（文件 < 400 行）与第 4 条（L0→L1→…→L6 单向）。

[1] 为什么把 ``web/*.js`` 也算进来
--------------------------------
长度约束是**可读性**约束，与语言无关。此前 ``[1]`` 只扫 ``.py``（``web`` 在
``NON_SOURCE_DIRS`` 里），于是 ``--check`` 报"82 个文件全部合规"对
``app.js`` / ``skew.js`` / ``period.js`` **没有任何覆盖** —— 那不是合规，是
门禁缺口。2026-09-13 KAI 定：纳入。纳入后必然暴露既有违规（三个文件均 > 400
行），拆分是独立的一步，**门禁先诚实**。
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.selfcheck_core import (
    EXEMPT_PACKAGES,
    LAYER_OF,
    MAX_LINES,
    ROOT,
    iter_py_files,
    iter_web_scripts,
    ok,
    fail,
    parse_file,
    rel_of,
)


def check_file_sizes() -> int:
    print(f"\n[1] 文件长度（上限 {MAX_LINES} 行）")
    py_files = iter_py_files()
    js_files = iter_web_scripts()
    files = py_files + js_files
    failures = 0

    for path in files:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines >= MAX_LINES:
            fail(f"{rel_of(path)} 共 {lines} 行，超出上限")
            failures += 1

    if not failures:
        longest = max(
            ((len(p.read_text(encoding="utf-8").splitlines()), rel_of(p)) for p in files),
            default=(0, "-"),
        )
        ok(f"{len(py_files)} 个 Python + {len(js_files)} 个前端脚本全部合规，"
           f"最长 {longest[1]} = {longest[0]} 行")
    return failures


def _top_level_imports(path: Path) -> set[str]:
    """文件里 import 的顶层包名（第三方包名也会返回，由调用方过滤）。"""
    tree = parse_file(path)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def check_layering() -> int:
    print("\n[2] 依赖方向（只允许 L0→L1→…→L6 单向）")
    violations: list[str] = []

    for path in iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        parts = rel.split("/")
        if len(parts) == 1:
            continue  # run.py 等根级入口，豁免

        owner = parts[0]
        if owner in EXEMPT_PACKAGES or owner not in LAYER_OF:
            continue

        owner_layer = LAYER_OF[owner]
        for imported in _top_level_imports(path):
            if imported not in LAYER_OF:
                continue
            imported_layer = LAYER_OF[imported]
            if imported_layer > owner_layer:
                violations.append(f"{rel} (L{owner_layer}) → {imported} (L{imported_layer})")

    for violation in violations:
        fail(f"反向依赖: {violation}")

    if not violations:
        ok(f"未发现反向依赖，{len(LAYER_OF)} 个包按 L0–L6 分层")
    return len(violations)
