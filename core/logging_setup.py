"""
L0 — 日志初始化。
==================
唯一职责：按传入的配置字典装配 root logger。

**本模块不读配置文件** —— ``logging.json`` 由 app 层读取后作为参数注入。
这样 ``core/`` 与 ``config/`` 之间没有任何 import 关系，L0 内部保持零耦合。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def configure(cfg: dict, *, force: bool = False) -> logging.Logger:
    """
    装配 root logger。

    Parameters
    ----------
    cfg
        ``config/logging.json`` 的内容。必需键：``level``、``format``。
        可选键：``date_format``、``console``、``file``、``file_level``。
    force
        为 True 时即使已配置过也重新装配（测试用）。

    Returns
    -------
    logging.Logger
        root logger。
    """
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED and not force:
        return root

    level_name = str(cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = str(cfg.get("format", "%(asctime)s %(levelname)s %(name)s %(message)s"))
    datefmt = cfg.get("date_format")
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    if cfg.get("console", True):
        console = logging.StreamHandler(stream=sys.stderr)
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)

    log_file = cfg.get("file")
    if log_file:
        path = Path(str(log_file))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_level = str(cfg.get("file_level", level_name)).upper()
            file_handler = logging.FileHandler(path, encoding="utf-8")
            file_handler.setLevel(getattr(logging, file_level, level))
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            root.warning("日志文件 %s 无法创建，仅输出到控制台: %s", path, exc)

    root.setLevel(level)

    # 第三方库降噪
    for noisy in ("ib_async", "ib_async.wrapper", "ib_async.client", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    _CONFIGURED = True
    return root


def get_logger(name: str) -> logging.Logger:
    """统一取 logger 的入口，便于日后整体替换日志后端。"""
    return logging.getLogger(name)
