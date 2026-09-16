"""
代码形态检查（**不属于任何运行时层**）。
==========================================

唯一职责：校验源码的**形态** —— ``__slots__`` 与实例属性是否对得上、
模块级字面量常量是否都来自配置。

检查项
------
``[8]``  ``__slots__`` 与实例属性赋值一致
``[10]`` 禁止硬编码（模块级字面量必须来自配置）

对应项目硬性要求第 2 条（单一职能）与第 3 条（禁止硬编码）。

为什么两项合在一个文件
----------------------
两者守的是同一件事 ——"**这个文件里该不该有这些东西**"，且都需要同一份
``iter_py_files()`` + AST 扫描。分开写会把同一套遍历抄两遍，而抄两遍的代价是
"其中一份忘了修"。按 KAI 的"知识库按不变量条数增长，不按错误条数增长"，同族判据
**并入**已有文件。

``[8]`` 为什么需要它
--------------------
定义了 ``__slots__`` 的类没有 ``__dict__``，任何未声明的实例属性赋值都会在
**运行期**抛 ``AttributeError``，而且往往只在某条少见的分支上触发。这个错误在
本项目开发过程中反复出现，每次都只在运行时才暴露，所以用 AST 静态检查堵死。

覆盖边界（诚实声明）
--------------------
``[8]`` 只解析**同文件内**的基类链。跨文件继承的 ``__slots__`` 无法静态求并集
（要解析 import 映射），这类类会被跳过 —— 但**跳过数会打印出来**，不是静默的。
本项目当前所有带 ``__slots__`` 的类都直接继承 ``object`` 或同文件的类。

``[10]`` 只覆盖**模块级**字面量。函数体内的魔法数字不在覆盖范围（那需要更复杂的
数据流分析，且误报率高），靠评审。
"""

from __future__ import annotations

import ast

from tools.selfcheck_core import (
    config_modules,
    fail,
    iter_py_files,
    ok,
    package_of,
    parse_file,
    rel_of,
    warn,
)

# --------------------------------------------------------------------------- #
# [8] __slots__ 一致性
# --------------------------------------------------------------------------- #


def _string_elements(node: ast.AST) -> set[str]:
    """从 ``("a", "b")`` / ``["a"]`` / ``{"a"}`` 里取出字符串元素。"""
    out: set[str] = set()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                out.add(element.value)
    return out


def _declared_slots(node: ast.ClassDef) -> tuple[set[str], list[str]]:
    """提取类里 ``__slots__ = (...)`` 的名字集合与**同文件内**的基类名列表。"""
    slots: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "__slots__":
                    slots |= _string_elements(stmt.value)
    bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
    return slots, bases


def _all_slots(name: str, table: dict[str, tuple[set[str], list[str]]],
               seen: set[str]) -> set[str]:
    """沿同文件基类链求 ``__slots__`` 的并集。"""
    if name in seen or name not in table:
        return set()
    seen.add(name)
    slots, bases = table[name]
    for base in bases:
        slots |= _all_slots(base, table, seen)
    return slots


def _instance_attrs(node: ast.ClassDef) -> dict[str, int]:
    """收集类里所有 ``self.x = ...`` / ``self.x: T = ...`` / ``self.x += ...``。"""
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
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                found.setdefault(target.attr, target.lineno)
    return found


def check_slots() -> int:
    print("\n[8] __slots__ 与实例属性赋值一致")
    failures = 0
    skipped_cross_file = 0

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

        # 全工程已知的类名 —— 用来判断"基类在别的文件里"（跨文件继承 ⇒ 无法求并集）
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            slots, bases = file_slots.get(node.name, (set(), []))

            inherited: set[str] = set()
            unknown_base = False
            for base in bases:
                if base in file_slots:
                    inherited |= _all_slots(base, file_slots, set())
                elif base not in ("object",):
                    unknown_base = True

            if not slots and not inherited:
                continue  # 没有 __slots__，实例有 __dict__，不受约束
            if unknown_base:
                # 基类不在本文件里 ⇒ 无法静态求 __slots__ 并集。**计数并报出来**，
                # 而不是静默跳过 —— 否则"跳过了多少类"这件事本身是隐形的。
                skipped_cross_file += 1
                continue

            allowed = slots | inherited
            for name, lineno in sorted(_instance_attrs(node).items()):
                if name in allowed or name.startswith("__"):
                    continue
                fail(f"{rel}:{lineno} {node.name}.{name} 未在 __slots__ 中声明"
                     f" —— 运行期会在该分支上抛 AttributeError")
                failures += 1

    if not failures:
        msg = "所有 __slots__ 类都未出现未声明的实例属性"
        if skipped_cross_file:
            msg += f"（{skipped_cross_file} 个类因跨文件基类被跳过，无法静态求并集）"
        ok(msg)
    return failures


# --------------------------------------------------------------------------- #
# [10] 禁止硬编码
# --------------------------------------------------------------------------- #

#: 恒等值：写死它们不构成"硬编码业务参数"。
IDENTITY_VALUES = {0, 1, "", True, False, None}

#: 内建容器构造器：``frozenset({...})`` / ``tuple((...))`` 这类写法，值仍然是纯
#: 字面量，不能因为外面包了一层调用就漏检。只认这几个**内建**构造器；任何其它
#: Call（``Quality.OK`` 之类的属性引用、函数调用）一律不算字面量。
LITERAL_CONSTRUCTORS = frozenset({"frozenset", "set", "tuple", "list", "dict"})

#: 豁免的模块级常量：逐条列出是为了让例外**显式可见**，而不是让检查静默放过。
#:
#: 收录纪律：只有"非可调参数"才允许进这张表 —— 外部协议常量、标准映射表、领域
#: 结构不变量。任何"调大调小会改变行为"的东西都不该出现在这里，它应该进
#: ``config/``。条目失效（对应常量已不存在）会报警告，防止表本身腐烂。
EXEMPT_CONSTANTS: dict[str, dict[str, str]] = {
    "acquisition/tick_router.py": {
        "_COMPUTATION_SOURCES":
            "IBKR tickOptionComputation 的 tick ID 与 ticker 属性名对应表"
            "（modelGreeks=13 / lastGreeks=12 / bidGreeks=10 / askGreeks=11）。"
            "这是 ib_async 的协议映射，不是可调参数 —— 改它等于改协议解读方式。",
    },
    "acquisition/chain_resolver.py": {
        "_RIGHTS_PER_STRIKE":
            "领域结构不变量：一个行权价恒有 1 张 call + 1 张 put，不可配置",
    },
    "acquisition/feed_errors.py": {
        "_CODE_SUBSCRIPTION_LIMIT": "IBKR Error 300（行情订阅超限）协议错误码",
        "_CODE_DATA_LOST": "IBKR Error 1101（行情数据丢失）协议错误码",
        "_CODE_NO_SECURITY": "IBKR Error 200（无此合约定义）协议错误码",
        "_IGNORED_CODES":
            "IBKR 环境状态提示码忽略表（连通性、行情农场连接/断开、延迟数据提示、"
            "未订阅权限提示）：这类码是运行环境通知，不是本进程可处置的错误；"
            "忽略它们面板才只显示真正需要动作的问题。协议固定，非可调参数。"
            "包含 2119（行情农场连接状态）和 10090（部分数据未订阅——paper 账户"
            "无实时 OPRA 权限时每次订阅都会刷），去噪后避免淹没真正的错误",
    },
    "serialization/bitmap_codec.py": {
        "_BITS_PER_BYTE":
            "1 字节 = 8 位。位图的位序换算是算术事实，不是可调参数；"
            "改它等于改线格式，而线格式由 web/matrix_codec.js 逐位镜像、"
            "由 check_matrix_codec 对拍守住",
        "_BYTES_PER_I16":
            "int16 占 2 字节。同上，是线格式的固定宽度，不是可调参数",
    },
    "models/surface_params.py": {
        "SVI_PARAM_ORDER":
            "SVI 参数向量的顺序 (a, b, rho, m, sigma)。它与 config/surface.json 的 "
            "svi_bounds / svi_random_start_ranges 一一对应；改这里的顺序等于改标定"
            "语义，不是可调参数",
    },
    "transport/http_static.py": {
        "_CONTENT_TYPES": "静态资源扩展名到标准 MIME 类型的映射表（HTTP 协议标准）",
    },
}

#: **待接线包**：已移植进代码树、但尚未接入运行时的模块。
#:
#: 为什么它们不立刻配置化：这些模块没有接线 ⇒ **没有回归可跑**，改动无法验证。
#: 按本项目的纪律（"没跑过的校验不说通过"），对一个无法验证的模块做配置化改造，
#: 风险大于收益 —— 改错了不会有任何东西报出来。所以选择**显式登记 + 打印 + 计数**，
#: 而不是静默跳过：静默跳过会让"还有一整块没接"这件事从门禁里消失。
#:
#: ⚠️ **到期条件**：任何一条被接线的那一刻，本表对应条目必须删除，并把其中的可调
#: 常量搬进 ``config/``。检查器每次运行都会把这些条目打印出来，就是为了让"还有
#: 一块没接"保持可见。
PENDING_PACKAGES: dict[str, str] = {
    "models/forecasting/":
        "RV 信号引擎（EWMA / GARCH / HAR-RV）已移植但**未接线**"
        "（项目是否需要尚未确定）。接线时必须一并处理："
        "① TRADING_DAYS_PER_YEAR=252（在 ewma/garch/har_rv **三处各写一份**，"
        "是重复真相）② _MIN_HISTORY=30/23（可调）"
        "③ snapshot_history.py::_REQUIRED_COLS（数据列名契约，属真例外、"
        "接线时登记进 EXEMPT_CONSTANTS 而不是搬配置）",
}

#: 跳过整个包：``config/`` 本身就是配置层；``tools/`` 是开发与验证脚本。
SKIP_PACKAGES = {"config", "tools"}


def _literal_repr(node: ast.AST) -> str | None:
    """若节点是纯字面量，返回简短表示；否则返回 ``None``。"""
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _literal_repr(node.operand)
        if inner is None:
            return None
        return ("-" if isinstance(node.op, ast.USub) else "+") + inner
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        parts = [_literal_repr(e) for e in node.elts]
        if any(p is None for p in parts):
            return None
        return "[" + ", ".join(parts) + "]"
    if isinstance(node, ast.Dict):
        keys = [_literal_repr(k) for k in node.keys]
        values = [_literal_repr(v) for v in node.values]
        if any(p is None for p in keys + values):
            return None
        return "{" + ", ".join(f"{k}: {v}" for k, v in zip(keys, values)) + "}"
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        func = node.func
        if isinstance(func, ast.Name) and func.id in LITERAL_CONSTRUCTORS:
            # 剥掉构造器外壳看里面的字面量。元素含非字面量（如 Quality.OK）时
            # 内层返回 None，整条也就不算命中 —— 不误报。
            return _literal_repr(node.args[0])
    return None


def _is_identity(node: ast.AST) -> bool:
    """恒等值或空容器：写死它们不算硬编码业务参数。"""
    if isinstance(node, ast.Constant):
        return node.value in IDENTITY_VALUES
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def check_hardcode() -> int:
    print("\n[10] 禁止硬编码（模块级字面量必须来自配置）")
    failures = 0
    module_names = config_modules()
    hits: list[str] = []
    used: set[tuple[str, str]] = set()
    skipped_pending = 0

    for path in iter_py_files():
        rel = rel_of(path)
        if package_of(path) in SKIP_PACKAGES:
            continue  # config/ 本身就是配置层；tools/ 是开发脚本
        if any(rel.startswith(prefix) for prefix in PENDING_PACKAGES):
            skipped_pending += 1
            continue  # 待接线包，见 PENDING_PACKAGES（会打印出来，不是静默跳过）

        try:
            tree = parse_file(path)
        except SyntaxError:
            continue  # 语法错误由 [8] 报，这里不重复

        exceptions = EXEMPT_CONSTANTS.get(rel, {})
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
                value_node = node.value
            else:
                continue

            if value_node is None or _is_identity(value_node):
                continue
            shown = _literal_repr(value_node)
            if shown is None:
                continue

            for target in targets:
                name = target.id
                if name.startswith("__"):
                    continue  # __all__ 之类的导出声明，不是业务常量
                if (isinstance(value_node, ast.Constant)
                        and value_node.value in module_names):
                    continue  # 配置模块名指针（如 _CFG = "state"）
                if name in exceptions:
                    used.add((rel, name))
                    continue
                hits.append(f"{rel}:{node.lineno} {name} = {shown}")

    for line in hits:
        fail(f"模块级字面量常量: {line}")
    failures += len(hits)

    if not hits:
        total = sum(len(v) for v in EXEMPT_CONSTANTS.values())
        msg = f"未发现模块级硬编码常量（显式例外 {total} 条，逐条登记了理由）"
        if skipped_pending:
            msg += f"；{skipped_pending} 个文件属待接线包，未纳入"
        ok(msg)

    # 待接线包**每次运行都打印**：让"还有一整块没接"这件事保持可见。
    # 静默跳过会让它从门禁视野里消失 —— 那正是本项目最怕的一类缺口。
    for prefix, reason in PENDING_PACKAGES.items():
        warn(f"待接线包 {prefix}：{reason}")

    for rel, table in EXEMPT_CONSTANTS.items():
        for name in table:
            if (rel, name) not in used:
                warn(f"例外表条目已失效：{rel}::{name} 不存在了，"
                     f"请从 EXEMPT_CONSTANTS 中移除")

    return failures


def run_code_checks() -> int:
    """供 ``--check`` 调用的入口。返回**失败条数**。"""
    return check_slots() + check_hardcode()
