"""
L6 — 配置自检。
================
唯一职责：校验 ``config/`` 的**结构完整性**：能不能读、彼此是否独立、
必需键是否齐备、容量是否安全、每个键是否归属于唯一的模块并且真的被接线。

检查项
------
[3] 配置文件可读性
[4] 配置零耦合（不得跨文件引用）
[5] 关键配置项存在
[6] 订阅容量与 IBKR 100 条上限；热力图显示窗口不得宽于订阅窗口
[7] 配置键归属与接线 —— 每个键只能被它所属模块读取；且必须真的被读取
[11] 出站限速桶容量与 IBKR 配额

对应项目硬性要求第 3 条（禁止硬编码、必须配置化）与第 5 条
（配置文件彼此独立、一个文件不得含跨层级/跨模块的变量）。

[7] 的判定依据是工程既有的 ``module=`` 约定：每次取键都显式声明"这个键属于哪个
配置文件"。本检查把这个声明与实际配置文件对照 —— 键放错文件、或键没人读，
都会在这里暴露。它不另建一张"键 → 归属"的映射表，避免制造第二份真相。

[11] 的存在理由：``ib_async`` 的 ``Client`` 自带 ``MaxRequests = 45`` 这个**隐式
默认值**。项目把它搬进了 ``config/ibkr.json``，于是"桶到底多大"第一次成为一份
可读的真相 —— 但只有加上这条校验，它才不至于在下次改动里悄悄失配。这里检查的是
四件事：桶容量没超官方上限、滑动窗口长度为正、单批合约确认不会自己撑满桶、以及
本项目的订阅节奏不超过桶容量。这些关系横跨 ``ibkr.json`` 与 ``subscription.json``，
**由检查器读取两个文件**来核对 —— 配置文件之间仍然零引用（要求第 5 条）。
"""

from __future__ import annotations

from tools.selfcheck_core import (
    CONFIG_DIR,
    FORBIDDEN_CONFIG_KEYS,
    REQUIRED_KEYS,
    WHOLE_DICT_MODULES,
    collect_reads,
    config_modules,
    declared_keys,
    fail,
    ok,
    read_config,
    warn,
)

# 未接线键（配置里声明了但没有任何代码读取）一律视为失败。
#
# 这里曾经是 False（只报警告）：一次上线就抓出 7 个死键，而每个都需要产品决策，
# 先留着 warn 免得 ``--check`` 长期变红。那 7 个键已于同日处理完毕（4 个接线、
# 3 个删除），于是收紧为 True —— 从此任何**新出现**的死键会直接让自检失败，
# 而不是静静躺在警告里。这正是检查 [7] 存在的意义：配置项一旦没人读，就是
# 一份过期的真相。
UNWIRED_IS_FAILURE = True

IBKR_SUBSCRIPTION_LIMIT = 100

# IBKR 官方规则：出站消息速率上限 = 已分配行情行数 ÷ 2。
# 默认 100 行 → 50 msg/s。违约错误码 100，累计 3 次会终止 API 会话。
IBKR_MESSAGES_PER_LINE = 2


def check_config_readable() -> tuple[dict[str, dict], int]:
    print("\n[3] 配置文件可读性")
    loaded: dict[str, dict] = {}
    failures = 0

    for name in sorted(REQUIRED_KEYS):
        path = CONFIG_DIR / f"{name}.json"
        if not path.exists():
            fail(f"缺少 config/{name}.json")
            failures += 1
            continue
        try:
            loaded[name] = read_config(name)
        except Exception as exc:  # noqa: BLE001 - 任何读取失败都要报出来
            fail(f"config/{name}.json 无法解析: {exc}")
            failures += 1

    if not failures:
        ok(f"{len(loaded)} 个模块配置全部可读")
    return loaded, failures


def check_config_coupling(loaded: dict[str, dict]) -> int:
    print("\n[4] 配置零耦合（不得跨文件引用）")
    failures = 0
    names = set(REQUIRED_KEYS)

    for name, cfg in loaded.items():
        for key in cfg:
            if key.strip().lower() in FORBIDDEN_CONFIG_KEYS:
                fail(f"config/{name}.json 含跨文件引用键 {key!r}")
                failures += 1

        blob = repr(cfg)
        for other in names:
            if f"{other}.json" in blob:
                warn(f"config/{name}.json 的取值里出现了 {other}.json，请确认不是引用")

    if not failures:
        ok("未发现配置之间的相互引用")
    return failures


def check_required_keys(loaded: dict[str, dict]) -> int:
    print("\n[5] 关键配置项存在")
    missing = 0

    for name, keys in REQUIRED_KEYS.items():
        cfg = loaded.get(name)
        if cfg is None:
            continue
        for key in keys:
            if key not in cfg:
                fail(f"config/{name}.json 缺少必需键 {key!r}")
                missing += 1

    if not missing:
        total = sum(len(v) for v in REQUIRED_KEYS.values())
        ok(f"{total} 个关键配置项齐备")
    return missing


def check_subscription_capacity(loaded: dict[str, dict]) -> int:
    print(f"\n[6] 订阅容量与 IBKR {IBKR_SUBSCRIPTION_LIMIT} 条上限")
    try:
        sub = loaded["subscription"]
        side = int(sub["num_strikes_each_side"])
        cap = int(sub["max_total_subscriptions"])
    except (KeyError, ValueError, TypeError) as exc:
        fail(f"无法核算订阅容量: {exc}")
        return 1

    projected = 4 * side + 1
    if projected > IBKR_SUBSCRIPTION_LIMIT:
        fail(f"档位 ±{side} 需要 {projected} 条行情，超过 IBKR 硬上限 "
             f"{IBKR_SUBSCRIPTION_LIMIT}")
        return 1
    if projected > cap:
        fail(f"档位 ±{side} 需要 {projected} 条，超过自设上限 {cap}")
        return 1

    ok(f"档位 ±{side} → {projected} 条行情（自设上限 {cap}，"
       f"IBKR 上限 {IBKR_SUBSCRIPTION_LIMIT}）")

    # 显示窗口不得宽于订阅窗口：热力图的每一行都取自**已订阅**的合约
    # （``StrikeWindow.rows()`` 只在 ``FeatureEngine._session_refs()`` 里挑），
    # 所以 ``heatmap_rows_each_side`` 一旦大于 ``num_strikes_each_side``，
    # 多出来的档位**永远拿不到数据**，而配置看上去像是生效的 —— 正是本项目
    # 最怕的"配置静默失效"。两个键分属两份配置文件（要求第 5 条禁止跨文件
    # 引用），只能由检查器读两份来核对，手法与 [11] 相同。
    try:
        rows_each_side = int(loaded["features"]["heatmap_rows_each_side"])
    except (KeyError, ValueError, TypeError) as exc:
        fail(f"无法核算热力图显示窗口: {exc}")
        return 1

    if rows_each_side > side:
        fail(f"热力图显示窗口 ±{rows_each_side} 宽于订阅窗口 ±{side}"
             f"（features.json::heatmap_rows_each_side > "
             f"subscription.json::num_strikes_each_side）—— 超出的档位永远没有数据")
        return 1

    ok(f"显示窗口 ±{rows_each_side} ≤ 订阅窗口 ±{side}")
    return 0


def check_config_ownership() -> int:
    print("\n[7] 配置键归属与接线（一个键只能属于一个模块）")
    declared = {m: declared_keys(m) for m in config_modules()}
    resolved, unresolved = collect_reads()
    failures = 0

    misplaced = 0
    for site in resolved:
        if site.module not in declared:
            fail(f"{site.path}:{site.line} 以 module={site.module!r} 取键，"
                 f"但 config/{site.module}.json 不存在")
            misplaced += 1
        elif site.key not in declared[site.module]:
            fail(f"{site.path}:{site.line} 以 module={site.module!r} 读 "
                 f"{site.key!r}，但 config/{site.module}.json 里没有这个键（键与文件错位）")
            misplaced += 1

    failures += misplaced
    if not misplaced:
        ok(f"{len(resolved)} 处取键调用全部落在其声明的配置文件里")

    for site in unresolved:
        warn(f"{site.path}:{site.line} 的 module= 无法静态解析，"
             f"归属未校验（键 {site.key!r}）")

    read = {(site.module, site.key) for site in resolved}
    unread: list[tuple[str, str]] = []
    for module in sorted(declared):
        if module in WHOLE_DICT_MODULES:
            continue
        unread += [(module, k) for k in sorted(declared[module])
                   if (module, k) not in read]

    for module, key in unread:
        msg = f"config/{module}.json 的 {key!r} 没有任何代码读取（未接线/死键）"
        if UNWIRED_IS_FAILURE:
            fail(msg)
        else:
            warn(msg)

    if UNWIRED_IS_FAILURE:
        failures += len(unread)
    elif not unread:
        ok("所有配置键都有代码读取（无死键）")
    else:
        warn(f"共 {len(unread)} 个未接线键，不阻塞通过；"
             f"置 UNWIRED_IS_FAILURE=True 可升级为失败")

    return failures


def check_rate_limit_bucket(loaded: dict[str, dict]) -> int:
    """
    校验出站限速桶容量，以及它与订阅侧配置的关系。

    为什么是这五条
    --------------
    1. 容量 ≥ 1：``0`` 在 ``ib_async`` 里是"关闭限速"的开关值，不是"零容量"。
       写 0 会静默退化成不限速 —— 那不是配置失误，是把保护关掉了。
    2. 窗口 > 0：``RequestsInterval`` 为 0 时滑动窗口永不淘汰，桶会被一次性
       填满且再也排不空。
    3. 容量 ≤ 官方上限（行数 ÷ 2）：超了就是拿 Error 100 换性能，而累计 3 次
       违约 IBKR 会直接终止 API 会话（必须重连）。
    4. 容量 ≥ ``qualify_batch_size``：``qualifyContractsAsync`` 内部是
       ``asyncio.gather`` 的**瞬时并发**，一批就是一个突发。批量大于桶容量，
       等于每次窗口重建都必然触发限速。
    5. 桶速率 ≥ 订阅节奏：``min_request_interval_s`` 反推的每秒请求数若高于桶
       容量，桶会长期满着，这个节奏配置就是一句空话。

    这些关系横跨 ``ibkr.json`` 与 ``subscription.json``。**由检查器读取两个文件**
    来核对 —— 配置文件之间仍然零引用，要求第 5 条不受影响。
    """
    print("\n[11] 出站限速桶容量与 IBKR 配额")
    try:
        ibkr = loaded["ibkr"]
        sub = loaded["subscription"]
        capacity = int(ibkr["rate_limit_max_requests"])
        interval = float(ibkr["rate_limit_interval_s"])
        batch = int(ibkr["qualify_batch_size"])
        pace_s = float(sub["min_request_interval_s"])
    except (KeyError, ValueError, TypeError) as exc:
        fail(f"无法核算限速桶容量: {exc}")
        return 1

    failures = 0
    official = IBKR_SUBSCRIPTION_LIMIT / IBKR_MESSAGES_PER_LINE

    if capacity < 1:
        fail(f"rate_limit_max_requests={capacity} 无效：0 在 ib_async 里是"
             "'关闭限速'的开关值，会静默退化成不限速")
        failures += 1
    if interval <= 0:
        fail(f"rate_limit_interval_s={interval} 必须为正：为 0 时滑动窗口永不"
             "淘汰，桶会被一次填满且再也排不空")
        failures += 1
    if capacity > official:
        fail(f"rate_limit_max_requests={capacity} 超过官方上限 {official:g} "
             f"（行情行数 {IBKR_SUBSCRIPTION_LIMIT} ÷ {IBKR_MESSAGES_PER_LINE}）"
             "—— 会触发 Error 100，累计 3 次被 IBKR 终止 API 会话")
        failures += 1
    if batch > capacity:
        fail(f"qualify_batch_size={batch} 超过桶容量 {capacity}："
             "qualifyContractsAsync 是瞬时并发的一批，每次窗口重建都会撑满桶")
        failures += 1

    if pace_s <= 0:
        fail(f"min_request_interval_s={pace_s} 必须为正")
        failures += 1
    elif capacity / interval < 1.0 / pace_s:
        fail(f"订阅节奏 {1.0 / pace_s:.0f} 条/s（min_request_interval_s="
             f"{pace_s}）高于桶容量 {capacity / interval:.0f} 条/s —— 桶会长期"
             "满着，这个节奏配置等于没生效")
        failures += 1

    if not failures:
        ok(f"桶 {capacity} 条 / {interval:g}s = {capacity / interval:.0f} 条/s"
           f"（官方上限 {official:g}；qualify 单批 {batch} 条；"
           f"订阅节奏 {1.0 / pace_s:.0f} 条/s）")
    return failures
