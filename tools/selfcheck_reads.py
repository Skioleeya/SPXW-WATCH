"""
loader 取键调用点收集（**不属于任何运行时层**）。
==================================================

唯一职责：扫全工程，把"**哪段代码读了哪个配置键**"这份事实抽出来，供 ``[7]``
（键归属与接线）做双向推导。

为什么独立成文件而不是并进 ``selfcheck_core``
----------------------------------------------
``selfcheck_core`` 放的是"多个检查都要用的路径常量与输出原语"；本文件是**一个**
检查（``[7]``）专用的分析器，且它自己的逻辑（两遍扫描 + 键转发器追踪）占了相当
篇幅。混在一起会让 ``selfcheck_core`` 逼近 400 行门禁 —— 按"单一文件单一职能"，
分析器应该独立。

⚠️ 为什么需要"键转发器"追踪
----------------------------
只认字面量键名的收集器会**漏掉一整类读取点**：

::

    # models/surface_params.py
    def _param_pairs(cfg, key, *, expected=5):        # ← key 是参数
        raw = loader.get(cfg, key, module=_MODULE)    # ← 键名是变量，不是字面量
        ...

    svi_fit_params():
        bounds=_param_pairs(cfg, "svi_bounds"),       # ← 真正读的是这里

``loader.get(cfg, key, ...)`` 的第二个实参是 ``Name`` 而不是 ``Constant``，字面量
收集器会直接跳过它；于是 ``svi_bounds`` 被判成"没有任何代码读取" ⇒ **假红**。

假红和漏检一样有害：一个满屏误报的门禁会被关掉。所以这里做两遍扫描：

1. **第一遍**找出"键转发器" —— 形如 ``def f(cfg, key)`` 且体内把该参数当作
   ``loader.<reader>(..., key, ...)`` 的键名用的函数，记下参数位置与它声明的
   ``module=``；
2. **第二遍**把所有 ``f(cfg, "某键")`` 调用点也算成读取点，取对应位置的字符串实参。

覆盖边界（诚实声明）
--------------------
* 只追**一层**转发。``f → g → loader`` 这种两级中转不追（本项目没有这种写法，
  真出现时会退化成"该键无人读"的假红，能发现而不是静默漏检）。
* 只认**字符串字面量**实参。键名由变量拼出来的调用点归入 ``unresolved``，
  由调用方打 ``[warn]``，不静默放过。
* 同名转发器出现在多个文件、且声明的 ``module`` 不同 ⇒ 记为该名字无法解析，
  归入 ``unresolved``（宁可不判，也不猜一个）。
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from tools.selfcheck_core import iter_py_files, parse_file, rel_of

#: ``config.loader`` 上"取一个键"的读取器方法名。
LOADER_READERS = frozenset({
    "as_str", "as_int", "as_float", "as_bool",
    "as_list", "as_float_list", "as_str_list", "get", "optional",
})

#: 转发器内部 ``module=`` 无法静态解析时的占位。
_UNRESOLVED = object()


class ReadSite(NamedTuple):
    """一次"读了某个配置键"的事实。"""

    path: str
    line: int
    key: str
    module: str | None  # None 表示 module= 无法静态解析


def const_strings(tree: ast.Module) -> dict[str, set[str]]:
    """
    收集文件内**所有**赋值语句里能静态确定的字符串值。

    返回 名字 → 可能的取值集合。会解析 ``_MODULE = _OTHER`` 这类别名链，因为本
    项目用 ``module=m`` 把配置模块名传给 loader。

    同名变量在不同作用域被赋成不同值时，集合会有多个元素 —— 调用方据此判定
    "无法静态解析"，而不是猜一个。
    """
    direct: dict[str, set[str]] = {}
    aliases: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                direct.setdefault(target.id, set()).add(value.value)
            elif isinstance(value, ast.Name):
                aliases.append((target.id, value.id))

    changed = True
    while changed:
        changed = False
        for name, source in aliases:
            if source not in direct:
                continue
            merged = direct.setdefault(name, set())
            before = len(merged)
            merged |= direct[source]
            if len(merged) != before:
                changed = True

    return direct


def _resolve_module(node: ast.AST, consts: dict[str, set[str]]) -> object:
    """把 ``module=`` 的实参解析成字符串；无法静态解析时返回 ``_UNRESOLVED``。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        candidates = consts.get(node.id, set())
        if len(candidates) == 1:
            return next(iter(candidates))
    return _UNRESOLVED


def _is_loader_reader(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "loader"
        and func.attr in LOADER_READERS
        and len(node.args) >= 2
    )


def _find_forwarders(tree: ast.Module) -> dict[str, tuple[int, object]]:
    """
    找出本文件里的**键转发器**：``{函数名: (键参数位置, module 或 _UNRESOLVED)}``。

    判据：函数体里存在 ``loader.<reader>(<任意>, <本函数的某个参数>, ...)``，
    即第二个位置实参是形参名。
    """
    consts = const_strings(tree)
    found: dict[str, tuple[int, object]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [arg.arg for arg in node.args.args]
        if len(params) < 2:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call) or not _is_loader_reader(sub):
                continue
            key_node = sub.args[1]
            if not (isinstance(key_node, ast.Name) and key_node.id in params):
                continue
            keyword = next((k for k in sub.keywords if k.arg == "module"), None)
            module = _resolve_module(keyword.value, consts) if keyword else _UNRESOLVED
            found[node.name] = (params.index(key_node.id), module)
            break

    return found


def collect_reads() -> tuple[list[ReadSite], list[ReadSite]]:
    """
    扫描全工程的 loader 取键调用（含经**键转发器**的间接调用）。

    Returns
    -------
    (resolved, unresolved)
        ``resolved`` 的 ``module`` 已静态确定；``unresolved`` 的 ``module`` 为 ``None``。
    """
    parsed = []
    for path in iter_py_files():
        rel = rel_of(path)
        tree = parse_file(path)
        parsed.append((rel, tree, const_strings(tree)))

    # ── 第一遍：全局转发器表 ──────────────────────────────────────────
    # 同名转发器若在多个文件里声明了**不同的** module，记为该名字不可解析 ——
    # 宁可不判，也不猜一个。
    forwarders: dict[str, tuple[int, object]] = {}
    conflicting: set[str] = set()
    for _, tree, _ in parsed:
        for name, info in _find_forwarders(tree).items():
            existing = forwarders.get(name)
            if existing is None:
                forwarders[name] = info
            elif existing != info:
                conflicting.add(name)
    for name in conflicting:
        forwarders.pop(name, None)

    # ── 第二遍：直接读取点 + 转发调用点 ──────────────────────────────
    resolved: list[ReadSite] = []
    unresolved: list[ReadSite] = []

    for rel, tree, consts in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if _is_loader_reader(node):
                key_node = node.args[1]
                if not (isinstance(key_node, ast.Constant)
                        and isinstance(key_node.value, str)):
                    continue
                keyword = next((k for k in node.keywords if k.arg == "module"), None)
                module = _resolve_module(keyword.value, consts) if keyword else _UNRESOLVED
                site = ReadSite(rel, node.lineno, key_node.value,
                                module if isinstance(module, str) else None)
                (resolved if site.module is not None else unresolved).append(site)
                continue

            # 经键转发器的间接读取
            func = node.func
            if not isinstance(func, ast.Name):
                continue
            info = forwarders.get(func.id)
            if info is None:
                continue
            position, module = info
            if len(node.args) <= position:
                continue
            key_node = node.args[position]
            if not (isinstance(key_node, ast.Constant)
                    and isinstance(key_node.value, str)):
                continue
            site = ReadSite(rel, node.lineno, key_node.value,
                            module if isinstance(module, str) else None)
            (resolved if site.module is not None else unresolved).append(site)

    return resolved, unresolved
