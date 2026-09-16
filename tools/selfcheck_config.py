"""
配置结构完整性检查（**不属于任何运行时层**）。
================================================

唯一职责：校验 ``config/`` 的**结构** —— 能不能读、彼此是否独立、键本身是否干净、
每个键是否归属于唯一的模块并且真的被接线。

检查项
------
``[3]`` 配置文件可读性（含 **JSON 重复键**）
``[4]`` 配置零耦合（不得跨文件引用）
``[5]`` 键级完整性（空键名 / 空白键名 / null 值）
``[7]`` 配置键归属与接线（读取点 ↔ 声明键**双向推导**）

对应项目硬性要求第 3 条（禁止硬编码、必须配置化）与第 5 条（配置文件彼此独立、
一个文件不得含跨层级 / 跨模块的变量）。

⚠️ 为什么没有 ``REQUIRED_KEYS``
-------------------------------
旧实现有一张手工维护的"关键配置项必须存在"清单（11 个模块 × 若干键），配一个
``[5] 关键配置项存在`` 逐条对照。本项目**刻意不重建它**：

* ``config/loader.py`` 已经是 fail-fast（缺键即抛 ``ConfigError``，加载器不含任何
  业务默认值），"缺键"这件事在**运行期**就已经是响的；
* "声明的键必须被读取、读取的键必须被声明"由 ``[7]`` 的**双向推导**得出 —— 机制
  覆盖了那张清单的全部职能，且新增配置键时**不需要回来改工具**。

手工清单的真实代价是"清单越守越长，且漏一项就静默失守"。旧清单已经腐烂过一次：
``Frame`` 加了 ``surface`` 字段而帧字段清单没跟着长（见 ``selfcheck_connectivity``
的模块注释）。所以 ``[5]`` 改为检查**键本身的形态**，那才是清单覆盖不到的地方。

``[3]`` 为什么要查 JSON 重复键
------------------------------
``json.loads`` 对重复键**静默取最后一个**，不报错、不警告。这意味着配置里同一个键
写了两遍（改配置时忘了删旧的）时，**前一个值被无声丢弃** —— 改了配置却"没生效"，
而没有任何信号。这是本项目头号禁忌（静默错值）的配置版，只能靠逐对扫描拦住。
"""

from __future__ import annotations

import json

from tools.selfcheck_core import (
    CONFIG_DIR,
    CONFIG_SUFFIX,
    FORBIDDEN_CONFIG_KEYS,
    META_KEY_PREFIX,
    WHOLE_DICT_MODULES,
    config_modules,
    declared_keys,
    fail,
    ok,
    warn,
)
from tools.selfcheck_reads import collect_reads


# --------------------------------------------------------------------------- #
# [3] 可读性
# --------------------------------------------------------------------------- #


def _duplicate_keys(path) -> list[str]:
    """
    返回该 JSON 文件里**重复出现的键路径**（含嵌套层级）。

    用 ``object_pairs_hook`` 而不是 ``json.loads`` 的默认行为：默认行为是"后者覆盖
    前者"，重复键在解析结果里完全看不见 —— 只有拿到底层的 pairs 才数得出来。
    """
    duplicates: list[str] = []

    def hook(pairs):
        seen: dict = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen[key] = value
        return seen

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    return duplicates


def check_config_readable() -> int:
    print("\n[3] 配置文件可读性（含 JSON 重复键）")
    failures = 0
    modules = sorted(config_modules())

    if not modules:
        fail(f"{CONFIG_DIR} 下没有任何 {CONFIG_SUFFIX} 文件")
        return 1

    for module in modules:
        path = CONFIG_DIR / f"{module}{CONFIG_SUFFIX}"
        try:
            duplicates = _duplicate_keys(path)
        except (json.JSONDecodeError, OSError) as exc:
            fail(f"config/{module}{CONFIG_SUFFIX} 无法解析: {exc}")
            failures += 1
            continue

        if duplicates:
            fail(f"config/{module}{CONFIG_SUFFIX} 有重复键 {sorted(set(duplicates))}"
                 f" —— json 静默取最后一个，先写的那份**已被无声丢弃**")
            failures += 1

    if not failures:
        ok(f"{len(modules)} 个配置文件全部可解析，且无重复键")

    # 再走一次真实加载路径：loader 的 fail-fast 是运行期唯一的守卫，
    # 这里提前跑一遍，免得把"缺文件 / 顶层不是 object"留到启动时才炸。
    from config import loader

    load_failures = 0
    for module in modules:
        try:
            loader.load(module, reload=True)
        except loader.ConfigError as exc:
            fail(f"loader 无法加载 {module}: {exc}")
            load_failures += 1
    if not load_failures:
        ok(f"{len(modules)} 个配置文件全部能被 loader 加载（fail-fast 路径通畅）")
    return failures + load_failures


# --------------------------------------------------------------------------- #
# [4] 零耦合
# --------------------------------------------------------------------------- #


def _string_leaves(node):
    """递归产出配置里所有的字符串叶子值。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _string_leaves(value)
    elif isinstance(node, list):
        for item in node:
            yield from _string_leaves(item)


def check_config_coupling() -> int:
    print("\n[4] 配置零耦合（不得跨文件引用）")
    failures = 0
    modules = sorted(config_modules())
    names = {f"{m}{CONFIG_SUFFIX}" for m in modules}

    from tools.selfcheck_core import read_config

    for module in modules:
        cfg = read_config(module)

        for key in cfg:
            if key.strip().lower() in FORBIDDEN_CONFIG_KEYS:
                fail(f"config/{module}{CONFIG_SUFFIX} 含跨文件引用键 {key!r}")
                failures += 1

        # 注释里**允许**提到别的配置文件名（本项目大量注释在解释"为什么这个键
        # 不放在另一个文件里"），所以只检查非 ``_`` 前缀的取值。
        for key, value in cfg.items():
            if key.startswith(META_KEY_PREFIX):
                continue
            for leaf in _string_leaves(value):
                hit = sorted(n for n in names if n in leaf)
                if hit:
                    fail(f"config/{module}{CONFIG_SUFFIX} 的 {key!r} 取值里出现 "
                         f"{hit} —— 配置文件之间不得互相引用")
                    failures += 1

    if not failures:
        ok(f"未发现配置之间的相互引用（{len(modules)} 个文件彼此独立）")
    return failures


# --------------------------------------------------------------------------- #
# [5] 键级完整性
# --------------------------------------------------------------------------- #


def check_config_key_hygiene() -> int:
    """
    键**本身**的形态：空键名、带前后空格的键名、``null`` 取值。

    这三类都不在"必需键清单"的覆盖范围里，却都会造成静默失效：

    * ``""`` 空键名 —— 永远取不到，是纯噪音；
    * ``"port "`` 带空格 —— 代码里写 ``cfg["port"]`` 找不到，而肉眼看配置"明明有"；
    * ``null`` 取值 —— 键声明了却没有值；``loader.as_*`` 会抛类型错，但那时已经是
      启动期，且报错信息指向"类型不符"而不是"这个键根本是空的"。
    """
    print("\n[5] 键级完整性（空键名 / 空白键名 / null 值）")
    failures = 0
    modules = sorted(config_modules())

    from tools.selfcheck_core import read_config

    def walk(node, module: str, path: str) -> None:
        nonlocal failures
        if isinstance(node, dict):
            for key, value in node.items():
                where = f"{path}.{key}" if path else key
                if key == "":
                    fail(f"config/{module}{CONFIG_SUFFIX} 有空键名（在 {path or '顶层'}）")
                    failures += 1
                elif key != key.strip():
                    fail(f"config/{module}{CONFIG_SUFFIX} 的键 {key!r} 首尾有空白"
                         f" —— 代码按 {key.strip()!r} 取会取不到")
                    failures += 1
                if value is None:
                    fail(f"config/{module}{CONFIG_SUFFIX} 的 {where!r} 取值为 null"
                         f" —— 键声明了却没有值，启动时会在 loader 类型校验处才炸")
                    failures += 1
                walk(value, module, where)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, module, f"{path}[{i}]")

    for module in modules:
        walk(read_config(module), module, "")

    if not failures:
        ok(f"{len(modules)} 个配置文件无空键名 / 无空白键名 / 无 null 取值")
    return failures


# --------------------------------------------------------------------------- #
# [7] 归属与接线
# --------------------------------------------------------------------------- #


def check_config_ownership() -> int:
    """
    键归属与接线 —— **双向推导**，不依赖任何手工清单。

    正向：每处 ``loader.xxx(cfg, "<key>", module="<mod>")`` 调用，其 ``<key>``
    必须真的在 ``config/<mod>.json`` 里（键放错文件、或键名拼错 ⇒ 失败）。

    反向：``config/<mod>.json`` 里声明的每个键，必须至少有一处代码读取它
    （没人读的键 = 一份过期的真相 ⇒ 失败）。

    判据完全来自工程既有的 ``module=`` 约定，**不另建"键 → 归属"映射表**，
    避免制造第二份真相。
    """
    print("\n[7] 配置键归属与接线（读取点 ↔ 声明键双向推导）")
    declared = {m: declared_keys(m) for m in config_modules()}
    resolved, unresolved = collect_reads()
    failures = 0

    misplaced = 0
    for site in resolved:
        if site.module not in declared:
            fail(f"{site.path}:{site.line} 以 module={site.module!r} 取键，"
                 f"但 config/{site.module}{CONFIG_SUFFIX} 不存在")
            misplaced += 1
        elif site.key not in declared[site.module]:
            fail(f"{site.path}:{site.line} 以 module={site.module!r} 读 "
                 f"{site.key!r}，但 config/{site.module}{CONFIG_SUFFIX} 里没有"
                 f"这个键（键与文件错位）")
            misplaced += 1

    failures += misplaced
    if not misplaced:
        ok(f"{len(resolved)} 处取键调用全部落在其声明的配置文件里")

    for site in unresolved:
        warn(f"{site.path}:{site.line} 的 module= 无法静态解析，归属未校验"
             f"（键 {site.key!r}）")

    read = {(site.module, site.key) for site in resolved}
    unread: list[tuple[str, str]] = []
    for module in sorted(declared):
        if module in WHOLE_DICT_MODULES:
            continue
        unread += [(module, key) for key in sorted(declared[module])
                   if (module, key) not in read]

    for module, key in unread:
        fail(f"config/{module}{CONFIG_SUFFIX} 的 {key!r} 没有任何代码读取"
             f"（未接线 / 死键）—— 配置项一旦没人读，就是一份过期的真相")
    failures += len(unread)

    if not unread:
        ok("所有配置键都有代码读取（无死键）")

    return failures


def run_config_checks() -> int:
    """供 ``--check`` 调用的入口。返回**失败条数**。"""
    return (
        check_config_readable()
        + check_config_coupling()
        + check_config_key_hygiene()
        + check_config_ownership()
    )
