"""
L6 — ``__slots__`` 一致性自检。
================================
唯一职责：检查 ``__slots__`` 与 ``self.x = ...`` 是否对得上。

对应项目硬性要求第 2 条（单一职能）的静态护栏。

为什么需要它
------------
定义了 ``__slots__`` 的类没有 ``__dict__``，任何未声明的实例属性赋值都会在
**运行期**抛 ``AttributeError``，而且往往只在某条少见的分支上触发。这个错误在
本项目开发过程中反复出现四次，每次都只在运行时才暴露，所以用 AST 静态检查
彻底堵死。

局限：只解析同文件内的基类。本工程所有带 ``__slots__`` 的类都没有带
``__slots__`` 的基类，因此这里是准确的。
"""

from __future__ import annotations

import ast

from tools.selfcheck_core import fail, iter_py_files, ok, parse_file, rel_of


def _string_elements(node: ast.AST) -> set[str]:
    out: set[str] = set()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                out.add(element.value)
    return out


def _declared_slots(node: ast.ClassDef) -> tuple[set[str], list[str]]:
    """提取类里 ``__slots__ = (...)`` 的名字集合与基类名列表。"""
    slots: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "__slots__":
                    slots |= _string_elements(stmt.value)
    bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
    return slots, bases


def _all_slots(
    name: str, table: dict[str, tuple[set[str], list[str]]], seen: set[str]
) -> set[str]:
    if name in seen or name not in table:
        return set()
    seen.add(name)
    slots, bases = table[name]
    for base in bases:
        slots |= _all_slots(base, table, seen)
    return slots


def _instance_attrs(node: ast.ClassDef) -> dict[str, int]:
    """收集类里所有 ``self.x = ...`` / ``self.x: T = ...`` 的属性名。"""
    found: dict[str, int] = {}
    for sub in ast.walk(node):
        targets: list[ast.AST] = []
        if isinstance(sub, ast.Assign):
            targets = list(sub.targets)
        elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
            targets = [sub.target]
        elif isinstance(sub, ast.AugAssign):
            targets = [sub.target]

        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                found.setdefault(target.attr, target.lineno)
    return found


def check_slots() -> int:
    print("\n[8] __slots__ 与实例属性赋值一致")
    failures = 0

    for path in iter_py_files():
        rel = rel_of(path)
        try:
            tree = parse_file(path)
        except SyntaxError as exc:
            fail(f"{rel} 语法错误: {exc}")
            failures += 1
            continue

        file_slots: dict[str, tuple[set[str], list[str]]] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                file_slots[node.name] = _declared_slots(node)

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            slots, bases = file_slots.get(node.name, (set(), []))

            inherited: set[str] = set()
            for base in bases:
                if base in file_slots:
                    inherited |= _all_slots(base, file_slots, set())

            if not slots and not inherited:
                continue  # 没有 __slots__，实例有 __dict__，不受约束

            allowed = slots | inherited
            for name, lineno in sorted(_instance_attrs(node).items()):
                if name in allowed or name.startswith("__"):
                    continue
                fail(f"{rel}:{lineno} {node.name}.{name} 未在 __slots__ 中声明")
                failures += 1

    if not failures:
        ok("所有 __slots__ 类都未出现未声明的实例属性")
    return failures
