"""
结构自检（**不属于任何运行时层**）。
=====================================

唯一职责：校验**代码的组织形态**，即"文件多大、谁可以 import 谁"。

检查项
------
[1]  文件长度：每个 ``.py`` 与 ``web/*.js`` 必须**严格少于** 400 行。
     附：余量 < 5 行的文件报 ``[warn]``（不是失败，但下次加两行注释就会违规）。
[2]  依赖方向：第 N 层的模块只能 import 第 0…N 层的包，禁止反向依赖。
[2b] 反向越界：**任何运行时层都不得 import ``tools/``** —— tools/ 是验证工具，
     不属于 L0–L8 链。它若被产品代码 import，产品行为就依赖了测试代码。
     这一条与 ``EXEMPT_PACKAGES`` 是同一枚硬币的两面，必须成对存在。

对应项目硬性要求第 1 条（文件 < 400 行）与第 4 条（严格分层单向依赖）。

[1] 为什么把 ``web/*.js`` 也算进来
--------------------------------
长度约束是**可读性**约束，与语言无关。此前 [1] 只扫 ``.py``（``web`` 在
``NON_SOURCE_DIRS`` 里），于是 ``--check`` 报"82 个文件全部合规"对
``app.js`` / ``skew.js`` / ``period.js`` **没有任何覆盖** —— 那不是合规，是
门禁缺口。纳入后必然暴露既有违规，拆分是独立的一步，**门禁先诚实**。
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.selfcheck_core import (
    EXEMPT_PACKAGES,
    LAYER_OF,
    LAYER_SPAN,
    MAX_LINES,
    ROOT,
    fail,
    iter_py_files,
    iter_web_scripts,
    ok,
    parse_file,
    rel_of,
    warn,
)

#: 余量低于这个行数就报警告。理由见 open_tasks：「`ibkr_gateway.py` = 399 行，
#: 距门禁只剩 1 行 —— 下一个会话只要加两行（哪怕只是注释）就会违规」。
MARGIN_WARN = 5

#: 不属于任何运行时层、且**产品代码不得 import** 的顶层目录。
FORBIDDEN_IMPORTS = ("tools",)


def check_file_sizes() -> int:
    print(f"\n[1] 文件长度（上限 {MAX_LINES} 行，严格小于）")
    py_files = iter_py_files()
    js_files = iter_web_scripts()
    files = py_files + js_files
    failures = 0
    tight: list[tuple[int, str]] = []

    for path in files:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines >= MAX_LINES:
            fail(f"{rel_of(path)} 共 {lines} 行，超出上限")
            failures += 1
        elif lines >= MAX_LINES - MARGIN_WARN:
            tight.append((lines, rel_of(path)))

    if not failures:
        longest = max(
            ((len(p.read_text(encoding="utf-8").splitlines()), rel_of(p)) for p in files),
            default=(0, "-"),
        )
        ok(f"{len(py_files)} 个 Python + {len(js_files)} 个前端脚本全部合规，"
           f"最长 {longest[1]} = {longest[0]} 行")

    # 余量警告：不是失败，但必须**看得见** —— 否则下次加两行注释就撞门禁。
    for lines, rel in sorted(tight, reverse=True):
        warn(f"{rel} = {lines} 行，距上限只剩 {MAX_LINES - lines} 行")

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
    print(f"\n[2] 依赖方向（只允许 {LAYER_SPAN} 单向）")
    violations: list[str] = []

    # ⚠️ 先核对**层表覆盖**：树里出现的每个顶层包都必须在 LAYER_OF 里。
    # 不查这一条的后果是**静默漏洞** —— 新增一个包（例如 `forecasting/`）时，
    # 下面的循环会因 `owner not in LAYER_OF` 直接 continue，该包的跨层 import
    # 一行都不检查，而输出照旧是"未发现反向依赖"。新包必须显式登记层号。
    present = {rel_of(p).split("/")[0] for p in iter_py_files()
               if len(rel_of(p).split("/")) > 1}
    unregistered = sorted(present - set(LAYER_OF) - EXEMPT_PACKAGES)
    for owner in unregistered:
        fail(f"{owner}/ 未在 LAYER_OF 登记层号 ⇒ 该包的跨层 import **完全未被检查**")
    violations.extend(unregistered)

    for path in iter_py_files():
        rel = rel_of(path)
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
        if "未在 LAYER_OF" in violation:
            continue  # 上面已经逐条打过
        fail(f"反向依赖: {violation}")

    if not violations:
        ok(f"未发现反向依赖，{len(LAYER_OF)} 个包按 {LAYER_SPAN} 分层，"
           f"树里 {len(present)} 个包全部已登记")
    return len(violations)


def check_tools_not_imported() -> int:
    print("\n[2b] 反向越界（运行时层不得 import tools/）")
    violations: list[str] = []

    for path in iter_py_files():
        parts = rel_of(path).split("/")
        if len(parts) == 1:
            continue  # 根级入口（run.py）—— 它 `--check` 时 import tools，是设计
        if parts[0] in EXEMPT_PACKAGES:
            continue
        for imported in _top_level_imports(path):
            if imported in FORBIDDEN_IMPORTS:
                violations.append(f"{rel_of(path)} import 了 {imported}/")

    for violation in violations:
        fail(f"产品代码依赖了验证工具: {violation}")

    if not violations:
        ok(f"没有任何运行时层 import {', '.join(FORBIDDEN_IMPORTS)}/")
    return len(violations)
