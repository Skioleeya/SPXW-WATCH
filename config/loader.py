"""
L0 — 统一配置加载器
====================
唯一职责：把 ``config/<module>.json`` 读成 ``dict`` 并缓存。

设计约束（对应项目硬性要求）
----------------------------
* **禁止硬编码** —— 本文件不定义任何业务默认值。所有可调参数一律来自
  ``config/*.json``；缺少必需键时直接抛错（fail fast），绝不静默兜底。
* **禁止配置耦合** —— 本加载器不认识任何具体模块名，也不知道任何文件里
  有哪些字段。调用方自己决定读哪个文件、取哪些键。配置文件之间禁止互相
  引用（不得出现 ``"$ref"`` 之类的跨文件指针）。
* **不可反向依赖** —— 本模块位于 L0，不 import 项目内任何其他模块，
  连 ``core/`` 也不 import（异常类型自带，避免与 core 形成互相引用）。

用法
----
::

    from config import loader

    cfg  = loader.load("ibkr")                      # 读 config/ibkr.json
    port = loader.as_int(cfg, "port", module="ibkr")
    host = loader.as_str(cfg, "host", module="ibkr")
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent
SUFFIX = ".json"

_lock = threading.RLock()
_cache: dict[str, dict] = {}


class ConfigError(RuntimeError):
    """配置缺失、格式错误或类型不符时抛出。"""


def config_path(module: str) -> Path:
    """返回某个模块配置文件应处的绝对路径（不检查是否存在）。"""
    if not module or not isinstance(module, str):
        raise ConfigError(f"模块名必须是非空字符串，收到 {module!r}")
    return CONFIG_DIR / f"{module}{SUFFIX}"


def load(module: str, *, reload: bool = False) -> dict:
    """
    读取 ``config/<module>.json``。

    Parameters
    ----------
    module
        模块名，不含 ``.json`` 后缀。例如 ``"ibkr"``、``"features"``。
    reload
        为 True 时绕过缓存重新读盘。

    Returns
    -------
    dict
        该模块的配置。返回的是缓存对象的浅拷贝，调用方修改它不会污染缓存。

    Raises
    ------
    ConfigError
        文件不存在、不是合法 JSON、或顶层不是 object。
    """
    with _lock:
        if not reload and module in _cache:
            return dict(_cache[module])

        path = config_path(module)

        if not path.exists():
            raise ConfigError(
                f"缺少配置文件 {path}。本系统禁止硬编码，所有参数必须来自 "
                f"config/{module}{SUFFIX}。"
            )

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"无法读取 {path}: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} 不是合法 JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError(
                f"{path} 顶层必须是 JSON object，收到 {type(data).__name__}"
            )

        _cache[module] = data
        return dict(data)


def clear_cache() -> None:
    """清空缓存（测试或热重载时使用）。"""
    with _lock:
        _cache.clear()


# --------------------------------------------------------------------------- #
# 取键 + 类型校验：缺键或类型不符一律 fail fast，不做静默兜底。
# --------------------------------------------------------------------------- #

def _label(cfg: dict, module: str, key: str) -> str:
    where = module or cfg.get("__module__", "?")
    return f"config/{where}{SUFFIX} 的 {key!r}"


def get(cfg: dict, key: str, *, module: str = "") -> Any:
    """取一个必需键；不存在则抛 ConfigError。"""
    if key not in cfg:
        raise ConfigError(f"缺少必需配置项 {_label(cfg, module, key)}")
    return cfg[key]


def optional(cfg: dict, key: str, default: Any) -> Any:
    """取一个可选键；不存在时返回调用方显式传入的 default。"""
    return cfg[key] if key in cfg else default


def as_str(cfg: dict, key: str, *, module: str = "") -> str:
    value = get(cfg, key, module=module)
    if not isinstance(value, str):
        raise ConfigError(f"{_label(cfg, module, key)} 应为字符串，收到 {value!r}")
    return value


def as_int(cfg: dict, key: str, *, module: str = "") -> int:
    value = get(cfg, key, module=module)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{_label(cfg, module, key)} 应为整数，收到 {value!r}")
    return value


def as_float(cfg: dict, key: str, *, module: str = "") -> float:
    value = get(cfg, key, module=module)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{_label(cfg, module, key)} 应为数值，收到 {value!r}")
    return float(value)


def as_bool(cfg: dict, key: str, *, module: str = "") -> bool:
    value = get(cfg, key, module=module)
    if not isinstance(value, bool):
        raise ConfigError(f"{_label(cfg, module, key)} 应为布尔值，收到 {value!r}")
    return value


def as_list(cfg: dict, key: str, *, module: str = "") -> list:
    value = get(cfg, key, module=module)
    if not isinstance(value, list):
        raise ConfigError(f"{_label(cfg, module, key)} 应为数组，收到 {value!r}")
    return value


def as_float_list(cfg: dict, key: str, *, module: str = "") -> list[float]:
    value = as_list(cfg, key, module=module)
    out: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ConfigError(
                f"{_label(cfg, module, key)} 的元素应全为数值，收到 {item!r}"
            )
        out.append(float(item))
    return out


def as_str_list(cfg: dict, key: str, *, module: str = "") -> list[str]:
    value = as_list(cfg, key, module=module)
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(
                f"{_label(cfg, module, key)} 的元素应全为字符串，收到 {item!r}"
            )
        out.append(item)
    return out


def as_positive(value: float, *, module: str, key: str) -> float:
    """数值必须 > 0，否则抛错。用于端口、间隔、窗口长度这类参数。"""
    if value <= 0:
        raise ConfigError(
            f"config/{module}{SUFFIX} 的 {key!r} 必须为正数，收到 {value!r}"
        )
    return value
