"""
单一职能 + 依赖白名单自检（**不属于任何运行时层**）。
=======================================================

唯一职责：校验"一个模块只承担一个职能"，以及"数值库只在允许的层里出现"。

检查项
------
[9]  单一职能：非契约/工具模块的顶层公开类不得超过 ``MAX_PUBLIC_CLASSES`` 个；
     且 ``__init__.py`` 只做导出，不得定义类或函数。
[9b] 依赖白名单：**只有 ``models/`` 允许 import numpy / pandas / scipy**。

对应项目硬性要求第 2 条（单一文件单一职能）。

[9b] 为什么必须机械守
--------------------
"只有 L4 `models/` 能用数值库"是 2026-09-15 的架构决策（KAI 拍板）。它是
**跨层的类型边界**：一旦某个 L5 模块为了省事 `import numpy as np`，numpy 类型
就会顺着返回值和类型标注漏到 L6–L8，而帧里必须只有普通 dataclass
（`contracts/feature.py` 的模块 docstring 明写了这条）。
这种漂移**不会报错**，只会让"配置零耦合 / 严格分层"在一周内无声失效
⇒ 只能靠 AST 级门禁拦住。

为什么放在本文件而不是新建一个 ``selfcheck_numeric.py``：两者守的是同一件事
（"这个文件该不该有这些东西"），且都需要同一份 `iter_py_files()` + AST 扫描。
按 KAI 的"知识库按不变量条数增长，不按错误条数增长"，同族判据**并入**已有文件。

覆盖边界（诚实声明）
--------------------
[9] 用"顶层公开类数量"作为职能数量的**粗粒度代理指标**。它是有限度的：
一个类也可以塞进三个职能。真正保证单一职能的是目录分层加人评审，这条检查只
负责拦住"一个文件里堆了好几个互不相关的类"这种最明显的违规。

**两类豁免**（判据见 ``_vocabulary_classes()``）—— 它们按定义就是"一个职能：
定义词汇/承载数据"，而不是多个职能：

1. **纯词汇表**：最终派生自 ``Exception`` / ``Enum`` 的类（异常分类表、枚举表）。
2. **纯数据载体**：``@dataclass``，且类体里只有字段声明与**纯派生读取器**
   （方法体只有一条 ``return``，且返回表达式里**没有任何调用** —— 没有调用就没有
   副作用/I/O，方法只能是字段的投影）。实例：``models/surface_params.py`` ——
   它的 docstring 写着"**一个文件 = 一张参数表**"，4 个 frozen dataclass 是同一张表
   的四段，是**一个**职能；``CleaningParams.max_iv_age()`` 是两个字段的二选一。
   这不是"调大阈值"：判据是**结构性的**，所以加第 5 张表不会让它悄悄放行一个
   "有行为的第二职能" —— 那种方法必然含调用/赋值/控制流，判据立刻失效。
"""

from __future__ import annotations

import ast

from tools.selfcheck_core import (
    DUTY_EXEMPT_PACKAGES,
    EXEMPT_PACKAGES,
    NUMERIC_OWNER,
    NUMERIC_PACKAGES,
    fail,
    iter_py_files,
    ok,
    package_of,
    parse_file,
    rel_of,
)

MAX_PUBLIC_CLASSES = 2

#: 纯词汇表的基类：最终派生自这些名字的类属于"异常分类表 / 枚举表"，
#: 是**一个**职能（定义词汇），不是多个职能。
VOCABULARY_BASES = {
    "Exception", "BaseException", "Enum", "StrEnum", "IntEnum", "Flag",
}

#: 类体里允许出现的语句类型（纯数据载体的判据）。
#: ``Expr`` 用来放 docstring；``AnnAssign`` 是字段声明；``Pass`` 允许空类。
_FIELD_ONLY_STMTS = (ast.Expr, ast.AnnAssign, ast.Pass)

#: 派生读取器里**禁止**出现的节点 —— 出现任何一个就说明该方法有行为（副作用 /
#: I/O / 控制流），不再是"字段的投影"。
_IMPURE_NODES = (
    ast.Call, ast.Assign, ast.AugAssign, ast.AnnAssign,
    ast.For, ast.AsyncFor, ast.While, ast.If, ast.Try, ast.With, ast.AsyncWith,
    ast.Raise, ast.Assert, ast.Global, ast.Nonlocal, ast.Delete, ast.Yield,
    ast.YieldFrom, ast.Await, ast.Lambda,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)


def _is_derived_reader(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    是否为**纯派生读取器**：方法体只有一条 ``return``，且返回表达式里没有任何调用。

    判据为什么这么写
    ----------------
    只要求"单条 return"不够 —— ``return open("f").read()`` 也是单条 return，却能做
    I/O。所以再加一条：**返回表达式里不得出现任何 ``Call``**。没有调用就没有副作用、
    没有 I/O，方法只能是字段的条件选择/运算，即"字段的投影"。

    实例（本项目）：``CleaningParams.max_iv_age()`` 返回
    ``self.delayed_max_iv_age_s if is_delayed else self.live_max_iv_age_s``
    —— 两个字段的二选一，显然不是"第二个职能"。
    """
    body = [stmt for stmt in node.body if not isinstance(stmt, ast.Expr)]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    if node.args.defaults or node.args.kw_defaults:
        return False
    for sub in ast.walk(body[0]):
        if isinstance(sub, _IMPURE_NODES):
            return False
    return True


def _is_field_only_dataclass(node: ast.ClassDef) -> bool:
    """
    ``@dataclass``，且类体里只有字段声明与**纯派生读取器**。

    这条判据是**结构性的**（"没有调用 ⇒ 没有行为"），不会因为"多加了一张参数表"
    而放宽，也不会放行一个真正有行为的第二职能。
    """
    decorated = any(
        (isinstance(d, ast.Name) and d.id == "dataclass")
        or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
        or (isinstance(d, ast.Call) and (
            (isinstance(d.func, ast.Name) and d.func.id == "dataclass")
            or (isinstance(d.func, ast.Attribute) and d.func.attr == "dataclass")))
        for d in node.decorator_list
    )
    if not decorated:
        return False
    for stmt in node.body:
        if isinstance(stmt, _FIELD_ONLY_STMTS):
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_derived_reader(stmt):
                continue
            return False
        return False
    return True


def _vocabulary_classes(tree: ast.Module) -> set[str]:
    """
    同文件内属于"纯词汇 / 纯数据载体"的类名（两类豁免的并集）。

    异常/枚举只认同文件内的基类 —— 本工程没有跨文件的异常继承链，所以这里是准确的。
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

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_field_only_dataclass(node):
            qualified.add(node.name)

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
            continue  # 语法错误由别处报，这里不重复

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
        ok(f"非契约/工具模块的顶层公开类均不超过 {MAX_PUBLIC_CLASSES} 个，"
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


def _imported_modules(path) -> set[str]:
    """文件里 import 的顶层模块名（含 ``from numpy import x`` 形式）。"""
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


def check_numeric_whitelist() -> int:
    """
    [9b] 只有 ``models/`` 允许 import numpy / pandas / scipy。

    ⚠️ 用 ``ast.walk`` 而不是只看顶层 import：把 ``import pandas`` 藏在函数体里
    是同一件违规，且**更难发现** —— 那种写法往往正是为了绕过检查。
    """
    print(f"\n[9b] 依赖白名单（只有 {NUMERIC_OWNER}/ 可用 "
          f"{' / '.join(NUMERIC_PACKAGES)}）")
    violations: list[str] = []

    for path in iter_py_files():
        owner = package_of(path)
        if owner == NUMERIC_OWNER or owner in EXEMPT_PACKAGES:
            continue  # models/ 是允许方；tools/ 是验证工具（可 import 任何层）
        hits = sorted(_imported_modules(path) & set(NUMERIC_PACKAGES))
        if hits:
            violations.append(f"{rel_of(path)} ({owner or '根级'}) → {', '.join(hits)}")

    for violation in violations:
        fail(f"数值库越界: {violation}")

    if not violations:
        ok(f"{NUMERIC_OWNER}/ 之外的模块均未 import "
           f"{' / '.join(NUMERIC_PACKAGES)}（豁免: {', '.join(sorted(EXEMPT_PACKAGES))}）")
    return len(violations)
