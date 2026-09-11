"""
L6 — 单一职能自检。
====================
唯一职责：校验**一个模块只承担一个职能**。

对应项目硬性要求第 2 条（禁止文件内部职能耦合，单一文件单一职能，模块化构建）。

两条判据
--------
1. **顶层公开类数量**：非契约/测试模块不得超过 ``MAX_PUBLIC_CLASSES`` 个。
2. **``__init__.py`` 只做导出**：包入口不得定义类或函数 —— 实现属于具体子模块。

覆盖边界（诚实声明）
--------------------
判据 1 用"顶层公开类数量"作为职能数量的**粗粒度代理指标**。它是有限度的：
一个类也可以塞进三个职能。真正保证单一职能的是目录分层加人评审，这条检查只
负责拦住"一个文件里堆了好几个互不相关的类"这种最明显的违规。

纯词汇表（异常分类、枚举）按定义就是一堆类，是一个职能，因此不计入 —— 判据见
``_vocabulary_classes()``。
"""

from __future__ import annotations

import ast

from tools.selfcheck_core import (
    DUTY_EXEMPT_PACKAGES,
    fail,
    iter_py_files,
    ok,
    package_of,
    parse_file,
    rel_of,
)

MAX_PUBLIC_CLASSES = 2

# 纯词汇表的基类：最终派生自这些名字的类属于"异常分类表 / 枚举表"，
# 是**一个**职能（定义词汇），不是多个职能。
VOCABULARY_BASES = {
    "Exception", "BaseException", "Enum", "StrEnum", "IntEnum", "Flag",
}


def _vocabulary_classes(tree: ast.Module) -> set[str]:
    """
    同文件内**最终派生自 Exception / Enum** 的类名。

    只认同文件内的基类 —— 本工程没有跨文件的异常继承链，所以这里是准确的。
    """
    table: dict[str, list[str]] = {
        node.name: [b.id for b in node.bases if isinstance(b, ast.Name)]
        for node in tree.body if isinstance(node, ast.ClassDef)
    }
    qualified: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, bases in table.items():
            if name in qualified:
                continue
            if any(b in VOCABULARY_BASES or b in qualified for b in bases):
                qualified.add(name)
                changed = True
    return qualified


def check_single_duty() -> int:
    print("\n[9] 单一职能（模块不得承载多个职能）")
    failures = 0

    multi: list[str] = []
    for path in iter_py_files():
        rel = rel_of(path)
        if package_of(path) in DUTY_EXEMPT_PACKAGES:
            continue
        try:
            tree = parse_file(path)
        except SyntaxError:
            continue  # [8] 已报语法错误，这里不重复

        public = [n.name for n in tree.body
                  if isinstance(n, ast.ClassDef) and not n.name.startswith("_")]
        if len(public) <= MAX_PUBLIC_CLASSES:
            continue
        if public and all(n in _vocabulary_classes(tree) for n in public):
            continue  # 纯异常/枚举词汇表
        multi.append(f"{rel} 定义了 {len(public)} 个顶层公开类: {', '.join(public)}")

    for line in multi:
        fail(line)
    failures += len(multi)

    if not multi:
        ok(f"非契约/测试模块的顶层公开类均不超过 {MAX_PUBLIC_CLASSES} 个，"
           f"且无多职能堆叠（豁免: {', '.join(sorted(DUTY_EXEMPT_PACKAGES))}）")

    init_violations = 0
    for path in iter_py_files():
        if path.name != "__init__.py":
            continue
        rel = rel_of(path)
        try:
            tree = parse_file(path)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                fail(f"{rel}:{node.lineno} __init__.py 只能做导出，"
                     f"不得定义 {type(node).__name__} {node.name!r}")
                init_violations += 1

    failures += init_violations
    if not init_violations:
        ok("所有 __init__.py 都只做导出，未承载实现")

    return failures
