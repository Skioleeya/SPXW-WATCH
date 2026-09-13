"""
L6 — 自检基础设施。
====================
唯一职责：为各检查模块提供**共享的路径常量、输出原语与 AST 扫描工具**。

本文件不含任何检查逻辑 —— 检查项分别在 ``selfcheck_structure``（结构与分层）、
``selfcheck_config``（配置）、``selfcheck_slots`` / ``selfcheck_duty`` /
``selfcheck_hardcode``（代码形态）里，由 ``selfcheck`` 汇总执行。

这里集中放"多个检查都要用"的东西，是为了避免同一份 AST 解析/常量解析逻辑被抄
三遍 —— 抄三遍就会出现"其中一份忘了修"的经典问题（本项目在 ``TRUSTWORTHY_QUALITIES``
上已经踩过一次）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # 支持 `python tools/selfcheck.py` 直接运行
    sys.path.insert(0, str(ROOT))

MAX_LINES = 400
CONFIG_DIR = ROOT / "config"
CONFIG_SUFFIX = ".json"

# 层号越小越底层。同一层之间允许互相 import。
LAYER_OF: dict[str, int] = {
    "config": 0,
    "contracts": 0,
    "core": 0,
    "acquisition": 1,
    "state": 2,
    "features": 3,
    "serialization": 4,
    "transport": 5,
    "app": 6,
}

# 不参与分层/形态检查的目录（开发与测试脚本，允许 import 任何层）。
EXEMPT_PACKAGES = {"tools"}

# 非源码目录：其中的 ``.py`` 不是产品代码，不进 ``iter_py_files()``。
# 逐条写明理由 —— 这条边界必须是**显式**的。历史上用 ``ROOT.rglob("*.py")``
# 一把抓，把归档在 notes/ 下的探针也算成产品代码，让 [1][2][8][9][10] 集体误报。
#
# 刻意用"排除表"而不是"只收已知源码包"：排除表漏了目录 → 误报（响，能发现）；
# 白名单漏了包 → 漏检（静默，发现不了）。方向必须选响的那一侧。
NON_SOURCE_DIRS: dict[str, str] = {
    "notes": "会话证据目录（2026-09-13 KAI 决策复活，skill notes-session-records 的落点）；"
             "内含探针归档，不是产品代码",
    ".workbuddy-ai": "工作记忆，随会话变动，不是产品代码",
    "logs": "运行日志输出目录",
    "web": "前端静态资源（JS/CSS/HTML），不含 Python",
}

# 契约层与测试目录豁免"单一职能"的类数量约束：
# contracts/ 按定义就是一组不可变数据结构（契约词汇表），tools/ 里是测试夹具。
DUTY_EXEMPT_PACKAGES = {"contracts", "tools"}

# 各模块配置必须存在的键。
REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "app": ("symbol", "timezone", "sessions",
            "option_trading_class", "option_exchange"),
    "ibkr": ("host", "port", "client_id", "generic_tick_list", "market_data_type",
             "qualify_batch_size", "rate_limit_max_requests", "rate_limit_interval_s"),
    "subscription": ("num_strikes_each_side", "max_total_subscriptions",
                     "reconcile_interval_s"),
    "state": ("option_buffer_seconds", "option_buffer_max_points", "prune_interval_s"),
    "features": ("impulse_windows_seconds", "glitch_min_abs_option_price",
                 "skew_target_delta", "heatmap_rows_each_side"),
    "persistence": ("enabled", "db_path", "queue_maxsize", "write_interval_s"),
    "serialization": ("heatmap_bucket_seconds", "heatmap_color_quantile",
                      "heatmap_color_floor_vol_points", "iv_decimals",
                      "impulse_decimals", "skew_scale_window_seconds"),
    "transport": ("host", "http_port", "ws_path", "push_interval_ms",
                  "client_queue_size"),
    "logging": ("level", "format"),
    "pipeline": ("compute_interval_ms",),
}

# 配置里不允许出现的跨文件引用键。
FORBIDDEN_CONFIG_KEYS = {"$ref", "include", "extends", "import", "ref"}

# 由 ``configure(整个 dict)`` 消费的配置：键名不会出现在 loader 取键调用里，
# 因此不参与"未接线键"判定。目前只有 logging.json（由 core.logging_setup 整体消费）。
WHOLE_DICT_MODULES = {"logging"}

# 键名前缀：以下划线开头的是注释/元信息，不属于可调参数。
META_KEY_PREFIX = "_"

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}  [ok]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}  [FAIL]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}  [warn]{RESET} {msg}")


# --------------------------------------------------------------------------- #
# 文件与 AST
# --------------------------------------------------------------------------- #

def iter_py_files() -> list[Path]:
    """工程内的**产品源码** ``.py``，按路径排序。

    排除两类：``__pycache__``（编译产物）、``NON_SOURCE_DIRS`` 下的任何文件
    （会话证据、工作记忆、日志、前端资源 —— 都不是产品代码）。

    根级文件（``run.py``）不受目录排除影响：它没有父目录，一律保留。
    """
    found: list[Path] = []
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        if "__pycache__" in parts:
            continue
        if len(parts) > 1 and parts[0] in NON_SOURCE_DIRS:
            continue
        found.append(path)
    return sorted(found)


def rel_of(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def package_of(path: Path) -> str:
    """文件所属的顶层包名；根级文件（run.py）返回空串。"""
    parts = path.relative_to(ROOT).parts
    return parts[0] if len(parts) > 1 else ""


def const_strings(tree: ast.Module) -> dict[str, set[str]]:
    """
    收集文件内**所有**赋值语句里能静态确定的字符串值。

    返回 名字 → 可能的取值集合。会解析 ``m = _CFG_MODULE`` 这类别名链，
    因为本项目用 ``module=m`` 把配置模块名传给 loader。

    同名变量在不同作用域被赋成不同值时，集合会有多个元素 —— 调用方据此
    判定"无法静态解析"，而不是猜一个。
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


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

def config_modules() -> set[str]:
    """全部配置文件对应的模块名（不含后缀）。"""
    return {p.stem for p in CONFIG_DIR.glob(f"*{CONFIG_SUFFIX}")}


def read_config(module: str) -> dict:
    path = CONFIG_DIR / f"{module}{CONFIG_SUFFIX}"
    return json.loads(path.read_text(encoding="utf-8"))


def declared_keys(module: str) -> set[str]:
    """某配置文件声明的可调参数键（排除 ``_`` 前缀的注释与元信息）。"""
    cfg = read_config(module)
    return {k for k in cfg if not k.startswith(META_KEY_PREFIX)}


# --------------------------------------------------------------------------- #
# loader 取键调用点
# --------------------------------------------------------------------------- #

LOADER_READERS = frozenset({
    "as_str", "as_int", "as_float", "as_bool",
    "as_list", "as_float_list", "get", "optional",
})


class ReadSite(NamedTuple):
    """一次 ``loader.<reader>(cfg, "<key>", module="<mod>")`` 调用。"""

    path: str
    line: int
    key: str
    module: str | None  # None 表示 module= 无法静态解析


def collect_reads() -> tuple[list[ReadSite], list[ReadSite]]:
    """
    扫描全工程的 loader 取键调用。

    Returns
    -------
    (resolved, unresolved)
        resolved 的 ``module`` 已静态确定；unresolved 的 ``module`` 为 None。
    """
    resolved: list[ReadSite] = []
    unresolved: list[ReadSite] = []

    for path in iter_py_files():
        rel = rel_of(path)
        tree = parse_file(path)
        consts = const_strings(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "loader":
                continue
            if func.attr not in LOADER_READERS or len(node.args) < 2:
                continue

            key_node = node.args[1]
            if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                continue
            key = key_node.value

            module: str | None = None
            kw = next((k for k in node.keywords if k.arg == "module"), None)
            if kw is not None:
                value = kw.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    module = value.value
                elif isinstance(value, ast.Name):
                    candidates = consts.get(value.id, set())
                    if len(candidates) == 1:
                        module = next(iter(candidates))

            site = ReadSite(rel, node.lineno, key, module)
            (resolved if module is not None else unresolved).append(site)

    return resolved, unresolved
