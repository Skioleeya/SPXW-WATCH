"""
自检基础设施（**不属于任何运行时层**）。
==========================================

唯一职责：为各检查模块提供**共享的路径常量、输出原语与 AST 扫描工具**。

本文件不含任何检查逻辑 —— 检查项分别在 ``selfcheck_structure``（结构与分层）、
``selfcheck_duty``（单一职能 + 依赖白名单）、``selfcheck_config``（配置）、
``selfcheck_slots`` / ``selfcheck_hardcode``（代码形态）里，由 ``selfcheck`` 汇总。

这里集中放"多个检查都要用"的东西，是为了避免同一份 AST 解析/常量解析逻辑被抄
三遍 —— 抄三遍就会出现"其中一份忘了修"。

⚠️ **为什么没有 ``REQUIRED_KEYS``**
旧项目有一张手工维护的"关键配置项必须存在"清单（11 个模块 × 若干键）。
本项目**刻意不抄**它：`config/loader.py` 已经是 fail-fast（缺键即抛
``ConfigError``，加载器不含业务默认值），而"声明的键必须被读取、读取的键必须被声明"
由 ``selfcheck_config.check_config_ownership`` **双向推导**得出 —— 机制覆盖了那张
清单的全部职能，且新增配置键时**不需要回来改这里**。
手工清单的真实代价是"清单越守越长、且漏一项就静默失守"。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # 支持 `python tools/selfcheck.py` 直接运行
    sys.path.insert(0, str(ROOT))

MAX_LINES = 400
CONFIG_DIR = ROOT / "config"
CONFIG_SUFFIX = ".json"
WEB_DIR = ROOT / "web"

#: 层号越小越底层。同一层之间允许互相 import。
#: **唯一真相在 `notes/memory/ARCHITECTURE.md §3`** —— 改层必须同时改两处。
LAYER_OF: dict[str, int] = {
    "config": 0,
    "contracts": 0,
    "core": 1,
    "acquisition": 2,
    "state": 3,
    "models": 4,
    "features": 5,
    "serialization": 6,
    "transport": 7,
    "app": 8,
}

LAYER_SPAN = f"L0–L{max(LAYER_OF.values())}"

#: 不参与分层/形态检查的目录。tools/ 是开发与验证工具，允许 import 任何层；
#: 反向禁止同样成立 —— **任何层都不得 import tools/**（见 check_layering 的
#: "反向越界"一项）。
EXEMPT_PACKAGES = {"tools"}

#: 只有这一层允许 import 数值库。见 `check_numeric_whitelist`。
NUMERIC_PACKAGES = ("numpy", "pandas", "scipy")
NUMERIC_OWNER = "models"

#: 非源码目录：其中的 ``.py`` 不是产品代码，不进 ``iter_py_files()``。
#: 逐条写明理由 —— 这条边界必须是**显式**的。历史上用 ``ROOT.rglob("*.py")``
#: 一把抓，把归档在 notes/ 下的探针也算成产品代码，让 [1][2][8][9][10] 集体误报。
#:
#: 刻意用"排除表"而不是"只收已知源码包"：排除表漏了目录 → 误报（响，能发现）；
#: 白名单漏了包 → 漏检（静默，发现不了）。方向必须选响的那一侧。
#:
#: ⚠️ 虚拟环境**不在此登记** —— 它由 ``_in_virtualenv()`` 按 ``pyvenv.cfg``
#: 结构识别。目录名（``.venv`` / ``venv`` / ``env`` …）是约定，把它登记进来
#: 等于把补丁当边界：换个名字就再漏一次。
NON_SOURCE_DIRS: dict[str, str] = {
    "notes": "会话证据目录（skill notes-session-records 的落点）；内含探针归档，不是产品代码",
    ".workbuddy-ai": "工作记忆，随会话变动，不是产品代码",
    "logs": "运行日志输出目录",
    "tmp": "临时探针落点（一次性脚本一律写在 <项目根>/tmp/）；不是产品代码。"
           "⚠️ 本条与 .gitignore 的 `tmp/` 是一对，缺一条就会让探针被 [1][2][9][10] 误报",
    "web": "前端静态资源（JS/CSS/HTML），不含 Python —— 故不进任何 AST 类检查。"
           "但**长度与语言无关**：其中的 .js 由 iter_web_scripts() 单独送进 [1] 长度门禁",
}

#: 契约层与工具目录豁免"单一职能"的类数量约束：
#: contracts/ 按定义就是一组不可变数据结构（契约词汇表），tools/ 里是检查器与夹具。
DUTY_EXEMPT_PACKAGES = {"contracts", "tools"}

#: 配置里不允许出现的跨文件引用键。
FORBIDDEN_CONFIG_KEYS = {"$ref", "include", "extends", "import", "ref"}

#: 由 ``configure(整个 dict)`` 消费的配置：键名不会出现在 loader 取键调用里，
#: 因此不参与"未接线键"判定。目前只有 logging.json（由 core.logging_setup 整体消费）。
WHOLE_DICT_MODULES = {"logging"}

#: 键名前缀：以下划线开头的是注释/元信息，不属于可调参数。
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

#: 目录 → 是否含 ``pyvenv.cfg``。跨调用复用，避免对同一批祖先目录反复 stat。
_VENV_MARKERS: dict[Path, bool] = {}


def _in_virtualenv(path: Path) -> bool:
    """``path`` 的任一祖先目录是否为 Python 虚拟环境（含 ``pyvenv.cfg``）。

    为什么按 ``pyvenv.cfg`` 而不是按目录名
    --------------------------------------
    目录名是**约定**：``.venv`` / ``venv`` / ``env`` / ``venv39`` …… 谁都可能用，
    往排除表里补名字就是打补丁 —— 换一个名字再漏一次。

    实测到的正是这个形态：``.gitignore`` 登记了 ``.venv/`` 与 ``venv/``，
    而 ``NON_SOURCE_DIRS`` 没有，于是 ``ROOT.rglob("*.py")`` 把两个虚拟环境的
    site-packages 全收了进来，让 ``[1][2][8][9][10]`` 集体误报 **2582 项**、
    ``--check`` 长期 ``RC=1`` —— 而且没有任何提示指向"是两个 venv 混进来了"。

    ``pyvenv.cfg`` 是 ``venv`` 模块自己写下的**结构性标记**，与目录叫什么无关，
    也不会被误当成源码包。判据与命名解耦，才不会再次漂移。
    """
    for parent in path.parents:
        if parent == parent.parent:  # 盘根，到头了
            break
        hit = _VENV_MARKERS.get(parent)
        if hit is None:
            hit = (parent / "pyvenv.cfg").is_file()
            _VENV_MARKERS[parent] = hit
        if hit:
            return True
    return False


def iter_py_files() -> list[Path]:
    """工程内的**产品源码** ``.py``，按路径排序。

    排除三类：

    * ``__pycache__``（编译产物）；
    * ``NON_SOURCE_DIRS`` 下的任何文件（会话证据、工作记忆、日志、前端资源）；
    * 位于 **Python 虚拟环境**内的任何文件 —— 按 ``pyvenv.cfg`` 识别，
      与目录名解耦（见 ``_in_virtualenv``）。

    根级文件（``run.py``）不受目录排除影响：它没有父目录，一律保留。
    """
    found: list[Path] = []
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        if "__pycache__" in parts:
            continue
        if len(parts) > 1 and parts[0] in NON_SOURCE_DIRS:
            continue
        if _in_virtualenv(path):
            continue
        found.append(path)
    return sorted(found)


def rel_of(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_web_scripts() -> list[Path]:
    """``web/`` 下的前端脚本（``*.js``），按路径排序。

    为什么单独开一支而不是并进 ``iter_py_files()``：``.js`` 进不了 AST 类检查
    （分层、单一职能、硬编码都是按 Python 语法树扫的），但**文件长度与语言无关**
    —— 一个 540 行的 IIFE 同样读不动。所以只把 [1] 这一项扩到前端。

    按**目录枚举**而不是写死名单：名单漏一个就等于漏一个盲区
    （``check_web_syntax`` 曾只覆盖 4 个文件，``skew.js`` 整文件语法错误却全绿）。
    新增前端文件必须自动纳入。
    """
    return sorted(WEB_DIR.glob("*.js"))


def parse_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def package_of(path: Path) -> str:
    """文件所属的顶层包名；根级文件（run.py）返回空串。"""
    parts = path.relative_to(ROOT).parts
    return parts[0] if len(parts) > 1 else ""


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
