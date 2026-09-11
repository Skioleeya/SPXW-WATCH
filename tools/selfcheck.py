"""
L6 — 架构与配置自检。
======================
唯一职责：把"架构约束"变成可执行的检查，而不是靠人记住。

检查项
------
1. **文件长度**：每个 ``.py`` 必须少于 400 行。
2. **依赖方向**：第 N 层的模块只能 import 第 0…N 层的包，禁止反向依赖。
3. **配置文件完整性**：每个模块的 JSON 都能读出来。
4. **配置零耦合**：配置文件之间不得互相引用（不得出现 ``$ref`` / ``include``
   之类的跨文件指针），也不得出现别的配置文件名。
5. **关键配置项存在**：防止有人改了键名导致运行时才炸。

运行::

    python run.py --check
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MAX_LINES = 400

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
    "simulator": 6,
    "app": 6,
}

# 不参与分层检查的目录（开发/测试脚本，允许 import 任何层）。
EXEMPT_PACKAGES = {"tools"}

# 各模块配置必须存在的键。
REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "app": ("symbol", "timezone", "session_open", "session_close",
            "option_trading_class", "option_exchange"),
    "ibkr": ("host", "port", "client_id", "generic_tick_list", "market_data_type",
             "qualify_batch_size"),
    "subscription": ("num_strikes_each_side", "max_total_subscriptions",
                     "reconcile_interval_s"),
    "state": ("option_buffer_seconds", "option_buffer_max_points", "prune_interval_s"),
    "features": ("impulse_windows_seconds", "glitch_min_abs_option_price",
                 "skew_target_delta", "heatmap_rows_each_side"),
    "serialization": ("heatmap_bucket_seconds", "heatmap_color_quantile",
                      "heatmap_color_floor_vol_points", "iv_decimals",
                      "impulse_decimals"),
    "transport": ("host", "http_port", "ws_path", "push_interval_ms",
                  "client_queue_size"),
    "logging": ("level", "format"),
    "simulator": ("enabled", "scenario", "tick_rate_hz", "session_speedup"),
    "pipeline": ("compute_interval_ms", "prune_interval_s"),
}

# 配置里不允许出现的跨文件引用键。
FORBIDDEN_CONFIG_KEYS = {"$ref", "include", "extends", "import", "ref"}

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _ok(msg: str) -> None:
    print(f"{GREEN}  [ok]{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"{RED}  [FAIL]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}  [warn]{RESET} {msg}")


# --------------------------------------------------------------------------- #
# 1. 文件长度
# --------------------------------------------------------------------------- #

def check_file_sizes() -> int:
    print(f"\n[1] 文件长度（上限 {MAX_LINES} 行）")
    failures = 0
    files = sorted(
        p for p in ROOT.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    for path in files:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        rel = path.relative_to(ROOT).as_posix()
        if lines >= MAX_LINES:
            _fail(f"{rel} 共 {lines} 行，超出上限")
            failures += 1
    if not failures:
        longest = max(
            ((len(p.read_text(encoding='utf-8').splitlines()),
              p.relative_to(ROOT).as_posix()) for p in files),
            default=(0, "-"),
        )
        _ok(f"{len(files)} 个文件全部合规，最长 {longest[1]} = {longest[0]} 行")
    return failures


# --------------------------------------------------------------------------- #
# 2. 依赖方向
# --------------------------------------------------------------------------- #

def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
    print("\n[2] 依赖方向（只允许 L0→L1→…→L6 单向）")
    failures = 0
    violations: list[str] = []

    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        if len(rel.parts) == 1:
            continue  # run.py 等根级入口，豁免
        owner = rel.parts[0]
        if owner in EXEMPT_PACKAGES or owner not in LAYER_OF:
            continue
        owner_layer = LAYER_OF[owner]

        for imported in _top_level_imports(path):
            if imported not in LAYER_OF:
                continue
            imported_layer = LAYER_OF[imported]
            if imported_layer > owner_layer:
                violations.append(
                    f"{rel.as_posix()} (L{owner_layer}) → {imported} (L{imported_layer})"
                )

    for violation in violations:
        _fail(f"反向依赖: {violation}")
        failures += 1

    if not failures:
        _ok(f"未发现反向依赖，{len(LAYER_OF)} 个包按 L0–L6 分层")
    return failures


# --------------------------------------------------------------------------- #
# 3 / 4 / 5. 配置
# --------------------------------------------------------------------------- #

def check_configs() -> int:
    print("\n[3] 配置文件可读性")
    failures = 0
    config_dir = ROOT / "config"
    loaded: dict[str, dict] = {}

    for name in sorted(REQUIRED_KEYS):
        path = config_dir / f"{name}.json"
        if not path.exists():
            _fail(f"缺少 config/{name}.json")
            failures += 1
            continue
        try:
            loaded[name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"config/{name}.json 不是合法 JSON: {exc}")
            failures += 1
    if not failures:
        _ok(f"{len(loaded)} 个模块配置全部可读")

    print("\n[4] 配置零耦合（不得跨文件引用）")
    coupling = 0
    all_names = {f"{n}.json" for n in REQUIRED_KEYS} | {f'"{n}"' for n in REQUIRED_KEYS}
    for name, cfg in loaded.items():
        for key in cfg:
            if key.strip().lower() in FORBIDDEN_CONFIG_KEYS:
                _fail(f"config/{name}.json 含跨文件引用键 {key!r}")
                coupling += 1
        blob = json.dumps(cfg, ensure_ascii=False)
        for other in all_names:
            if other in blob:
                _warn(f"config/{name}.json 的取值里出现了 {other}，请确认不是引用")
    if not coupling:
        _ok("未发现配置之间的相互引用")
    failures += coupling

    print("\n[5] 关键配置项存在")
    missing = 0
    for name, keys in REQUIRED_KEYS.items():
        cfg = loaded.get(name)
        if cfg is None:
            continue
        for key in keys:
            if key not in cfg:
                _fail(f"config/{name}.json 缺少必需键 {key!r}")
                missing += 1
    if not missing:
        total = sum(len(v) for v in REQUIRED_KEYS.values())
        _ok(f"{total} 个关键配置项齐备")
    failures += missing

    print("\n[6] 订阅容量与 IBKR 100 条上限")
    try:
        sub = loaded["subscription"]
        side = int(sub["num_strikes_each_side"])
        cap = int(sub["max_total_subscriptions"])
        projected = 4 * side + 1
        if projected > 100:
            _fail(f"档位 ±{side} 需要 {projected} 条行情，超过 IBKR 硬上限 100")
            failures += 1
        elif projected > cap:
            _fail(f"档位 ±{side} 需要 {projected} 条，超过自设上限 {cap}")
            failures += 1
        else:
            _ok(f"档位 ±{side} → {projected} 条行情（自设上限 {cap}，IBKR 上限 100）")
    except (KeyError, ValueError) as exc:
        _fail(f"无法核算订阅容量: {exc}")
        failures += 1

    return failures


def check_slots() -> int:
    """
    检查 ``__slots__`` 与 ``self.x = ...`` 是否对得上。

    定义了 ``__slots__`` 的类没有 ``__dict__``，任何未声明的实例属性赋值都会在
    运行期抛 ``AttributeError``，而且往往只在某条少见的分支上触发。这个坑在开发
    过程中反复出现，值得用静态检查彻底堵死。

    局限：只解析同文件内的基类。本工程所有带 ``__slots__`` 的类都没有带
    ``__slots__`` 的基类，因此这里是准确的。
    """
    print("\n[7] __slots__ 与实例属性赋值一致")
    failures = 0

    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            _fail(f"{rel} 语法错误: {exc}")
            failures += 1
            continue

        # 先收集同文件内每个类声明的 slots，供子类继承解析
        file_slots: dict[str, tuple[set[str], list[str]]] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                slots, bases = _declared_slots(node)
                file_slots[node.name] = (slots, bases)

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            slots, bases = file_slots.get(node.name, (set(), []))

            # 合并基类 slots
            inherited: set[str] = set()
            for base in bases:
                if base in file_slots:
                    inherited |= _all_slots(base, file_slots, set())

            if not slots and not inherited:
                continue  # 该类没有 __slots__，实例有 __dict__，不受约束

            allowed = slots | inherited
            assigned = _instance_attrs(node)

            for name, lineno in sorted(assigned.items()):
                if name in allowed:
                    continue
                if name.startswith("__"):
                    continue
                _fail(f"{rel}:{lineno} {node.name}.{name} 未在 __slots__ 中声明")
                failures += 1

    if not failures:
        _ok("所有 __slots__ 类都未出现未声明的实例属性")
    return failures


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


def _string_elements(node: ast.AST) -> set[str]:
    out: set[str] = set()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                out.add(element.value)
    return out


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


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #

def run_selfcheck() -> int:
    print("=" * 72)
    print("SPXW SWATCH — 架构与配置自检")
    print("=" * 72)

    failures = 0
    failures += check_file_sizes()
    failures += check_layering()
    failures += check_configs()
    failures += check_slots()

    print()
    print("=" * 72)
    if failures:
        print(f"{RED}结果: {failures} 项不通过{RESET}")
    else:
        print(f"{GREEN}结果: 全部通过{RESET}")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_selfcheck())
