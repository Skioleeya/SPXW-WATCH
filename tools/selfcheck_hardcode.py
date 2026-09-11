"""
L6 — 禁止硬编码自检。
======================
唯一职责：校验**模块级字面量常量**都来自配置，而不是写死在代码里。

对应项目硬性要求第 3 条（禁止硬编码，必须配置化文件）。

判定规则
--------
扫描非 ``config/``、非 ``tools/`` 的源文件，逐个看模块级赋值：

* 值是**字面量**（标量、或由字面量组成的容器）→ 命中；
* 例外（不算硬编码）：恒等值 / 空容器、``__all__`` 之类的 dunder、
  值为**配置模块名**的指针（如 ``_CFG = "state"``）、
  以及 ``EXEMPT_CONSTANTS`` 里逐条登记过的非可调参数。

覆盖边界（诚实声明）
--------------------
只覆盖**模块级**字面量。函数体内的魔法数字不在覆盖范围（那需要更复杂的数据流
分析，且误报率高），靠评审。

例外表的纪律
------------
只有"非可调参数"才允许进 ``EXEMPT_CONSTANTS`` —— 外部协议常量、标准映射表、
领域结构不变量。任何"调大调小会改变行为"的东西都不该出现在这里，它应该进
``config/``。例外表条目失效（对应常量已不存在）也会报警告，防止表本身腐烂。
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

# 恒等值：写死它们不构成"硬编码业务参数"。
IDENTITY_VALUES = {0, 1, "", True, False, None}

# 豁免的模块级常量：逐条列出是为了让例外**显式可见**，而不是让检查静默放过。
EXEMPT_CONSTANTS: dict[str, dict[str, str]] = {
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
    "acquisition/tick_router.py": {
        "_COMPUTATION_SOURCES":
            "IBKR tickOptionComputation 的 tick ID 与字段名对应表（协议固定）",
    },
    "acquisition/chain_resolver.py": {
        "_RIGHTS_PER_STRIKE":
            "领域结构不变量：一个行权价恒有 1 张 call + 1 张 put，不可配置",
    },
    "simulator/scenario.py": {
        "_DIRECTION_SIGN": "配置取值（down/up）到符号的语义映射，非可调参数",
    },
    "transport/http_static.py": {
        "_CONTENT_TYPES": "静态资源扩展名到标准 MIME 类型的映射表",
    },
    "serialization/bitmap_codec.py": {
        "_BITS_PER_BYTE":
            "1 字节 = 8 位。位图的位序换算是算术事实，不是可调参数；"
            "改它等于改线格式，而线格式由 web/matrix_codec.js 逐位镜像、"
            "由 tools/check_matrix_codec.py 对拍守住，不该由配置放开",
        "_BYTES_PER_I16":
            "int16 占 2 字节。同上，是线格式的固定宽度，不是可调参数",
    },
}

SKIP_PACKAGES = {"config", "tools"}

# 内建容器构造器：``frozenset({...})`` / ``tuple((...))`` 这类写法，值仍然是纯
# 字面量，不能因为外面包了一层调用就漏检。只认这几个**内建**构造器；任何其它
# Call（``Quality.OK`` 之类的属性引用、函数调用）一律不算字面量。
LITERAL_CONSTRUCTORS = frozenset({"frozenset", "set", "tuple", "list", "dict"})


def _literal_repr(node: ast.AST) -> str | None:
    """若节点是纯字面量，返回简短表示；否则返回 None。"""
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
            # 剥掉构造器外壳，看里面的字面量。元素含非字面量（如 Quality.OK）
            # 时内层会返回 None，整条也就不算命中 —— 不误报。
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

    for path in iter_py_files():
        rel = rel_of(path)
        if package_of(path) in SKIP_PACKAGES:
            continue  # config/ 本身就是配置层；tools/ 是开发脚本

        try:
            tree = parse_file(path)
        except SyntaxError:
            continue

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
                if isinstance(value_node, ast.Constant) \
                        and value_node.value in module_names:
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
        ok(f"未发现模块级硬编码常量（显式例外 {total} 条，逐条登记了理由）")

    for rel, table in EXEMPT_CONSTANTS.items():
        for name in table:
            if (rel, name) not in used:
                warn(f"例外表条目已失效：{rel}::{name} 不存在了，"
                     f"请从 EXEMPT_CONSTANTS 中移除")

    return failures
