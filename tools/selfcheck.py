"""
架构与配置自检（编排器，**不属于任何运行时层**）。
====================================================

唯一职责：按顺序调用各检查模块并汇总结果。**本文件不含任何检查逻辑。**

检查矩阵（16 项，实现位置见括号）
--------------------------------
``[1]``  文件长度（每个 ``.py`` 与 ``web/*.js`` 严格少于 400 行；余量 < 5 行警告）
``[2]``  依赖方向（第 N 层只能 import 第 0…N 层）            · ``selfcheck_structure``
``[2b]`` 反向越界（任何运行时层不得 import ``tools/``）        · ``selfcheck_structure``
``[3]``  配置文件可读性（含 JSON 重复键）                     · ``selfcheck_config``
``[4]``  配置零耦合（不得跨文件引用）                        · ``selfcheck_config``
``[5]``  键级完整性（空键名 / 空白键名 / null 值）             · ``selfcheck_config``
``[6]``  订阅容量 / 显示窗口 / 网格容量                      · ``selfcheck_config_invariants``
``[7]``  配置键归属与接线（读取点 ↔ 声明键双向推导）           · ``selfcheck_config``
``[8]``  ``__slots__`` 与实例属性赋值一致                    · ``selfcheck_code``
``[9]``  单一职能                                            · ``selfcheck_duty``
``[9b]`` 依赖白名单（只有 ``models/`` 可用 numpy/pandas/scipy）· ``selfcheck_duty``
``[10]`` 禁止硬编码                                          · ``selfcheck_code``
``[11]`` 出站限速桶容量与 IBKR 配额                          · ``selfcheck_config_invariants``
``[12]`` 时钟协议与裁剪路径                                  · ``selfcheck_clock``
``[13]`` 联通与数据通道（帧契约一致性 + 活链路）              · ``selfcheck_connectivity``
``[14]`` TickRouter 语义                                    · ``selfcheck_router``

``[13]`` 的活链路那一项需要 8060 有服务；无服务时它自己打 ``[warn]`` 跳过，
**离线三项（帧字段覆盖 / 往返 / NaN 守卫）仍然照跑** —— 所以这一项不再是
"非交易日就整条空转"。

运行::

    python run.py --check
    python tools/selfcheck.py                # 等价，便于单独调试
    python tools/selfcheck.py --selftest     # 注入缺陷，证明每一项都不是空转
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.selfcheck_code import check_hardcode, check_slots  # noqa: E402
from tools.selfcheck_config import (  # noqa: E402
    check_config_coupling,
    check_config_key_hygiene,
    check_config_ownership,
    check_config_readable,
)
from tools.selfcheck_config_invariants import (  # noqa: E402
    check_rate_limit_bucket,
    check_subscription_capacity,
)
from tools.selfcheck_connectivity import run_connectivity_checks  # noqa: E402
from tools.selfcheck_core import GREEN, RED, RESET, YELLOW  # noqa: E402
from tools.selfcheck_clock import run_clock_checks  # noqa: E402
from tools.selfcheck_duty import (  # noqa: E402
    check_numeric_whitelist,
    check_single_duty,
)
from tools.selfcheck_router import run_router_checks  # noqa: E402
from tools.selfcheck_structure import (  # noqa: E402
    check_file_sizes,
    check_layering,
    check_tools_not_imported,
)


@dataclass(frozen=True)
class Check:
    """一个检查项。``run`` 返回**失败条数**（0 = 通过）。"""

    number: str
    name: str
    run: Callable[[], int]


CHECKS: tuple[Check, ...] = (
    Check("[1]", "文件长度", check_file_sizes),
    Check("[2]", "依赖方向", check_layering),
    Check("[2b]", "反向越界", check_tools_not_imported),
    Check("[3]", "配置可读性（含重复键）", check_config_readable),
    Check("[4]", "配置零耦合", check_config_coupling),
    Check("[5]", "键级完整性", check_config_key_hygiene),
    Check("[6]", "订阅容量与网格容量", check_subscription_capacity),
    Check("[7]", "配置键归属与接线", check_config_ownership),
    Check("[8]", "__slots__ 一致性", check_slots),
    Check("[9]", "单一职能", check_single_duty),
    Check("[9b]", "依赖白名单", check_numeric_whitelist),
    Check("[10]", "禁止硬编码", check_hardcode),
    Check("[11]", "出站限速桶容量", check_rate_limit_bucket),
    Check("[12]", "时钟协议与裁剪路径", run_clock_checks),
    Check("[13]", "联通与数据通道", run_connectivity_checks),
    Check("[14]", "TickRouter 语义", run_router_checks),
)


def run_selfcheck() -> int:
    print("=" * 72)
    print("SPXW SWATCH — 架构与配置自检")
    print("=" * 72)

    failures = 0
    crashed: list[str] = []

    for check in CHECKS:
        try:
            failures += check.run()
        except Exception as exc:  # noqa: BLE001 - 检查器崩了必须**响**，不能静默
            # 检查器自己抛异常时，若直接让它冒泡，整个 --check 会中断，
            # 后面的检查项一项都不跑 —— 那比"这一项失败"糟得多。
            print(f"\n{RED}  [FAIL]{RESET} {check.number} {check.name} "
                  f"抛异常: {type(exc).__name__}: {exc}")
            failures += 1
            crashed.append(check.number)

    print()
    print("=" * 72)
    if failures:
        detail = f"，其中 {len(crashed)} 项是检查器自身崩溃" if crashed else ""
        print(f"{RED}结果: {failures} 项不通过（覆盖 {len(CHECKS)}/{len(CHECKS)}）"
              f"{detail}{RESET}")
    else:
        print(f"{GREEN}结果: {len(CHECKS)}/{len(CHECKS)} 项全部通过{RESET}")
    print("=" * 72)
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# 非空转自检
# --------------------------------------------------------------------------- #

#: 复制到临时工程里的目录。**不含 venv / tmp / notes**（体积大且不是源码）。
_COPY_DIRS = ("config", "contracts", "core", "acquisition", "state", "models",
              "features", "serialization", "transport", "app", "web", "tools")


@dataclass(frozen=True)
class Mutation:
    """
    一条"静默错值"型缺陷的注入方案。

    每条的挑选标准：**改完之后程序照常启动、照常出图、不报任何错**，只有机械
    门禁能发现它。能被运行期直接炸出来的缺陷不值得放进这里 —— 那种缺陷不需要
    门禁。

    ``replace_from`` 必须**在目标文件里唯一出现**；不唯一时自检会拒绝执行并报错
    （静默地替换到错误的位置，会让"抓住了"这个结论本身不可信）。
    """

    label: str        # 被验的检查项（用于输出与归因）
    path: str         # 相对路径
    append: str = ""  # 追加到文件末尾的内容
    replace_from: str = ""
    replace_to: str = ""


_MUTATIONS: tuple[Mutation, ...] = (
    Mutation("[1]", "contracts/enums.py",
             append="\n# 变异：把文件撑过 400 行\n" * 420),
    Mutation("[2]", "acquisition/feed_errors.py",
             append="\nfrom app import pipeline  # noqa: F401  变异：L2 反向 import L8\n"),
    Mutation("[2b]", "features/glitch_filter.py",
             append="\nimport tools  # noqa: F401  变异：运行时层 import 验证工具\n"),
    Mutation("[3]", "config/app.json",
             replace_from='  "symbol": "SPX",',
             replace_to='  "symbol": "SPX",\n  "symbol": "MUTANT",'),
    Mutation("[4]", "config/app.json",
             replace_from='  "symbol": "SPX",',
             replace_to='  "symbol": "SPX",\n  "$ref": "ibkr.json",'),
    Mutation("[5]", "config/app.json",
             replace_from='  "symbol": "SPX",',
             replace_to='  "symbol": null,'),
    Mutation("[6]", "config/subscription.json",
             replace_from='"num_strikes_each_side": 20,',
             replace_to='"num_strikes_each_side": 30,'),
    # [6] 的三条窗口不变量各要一条变异 —— 只验其中一条，另外两条是空转的。
    # 两条都必须落在"程序照常启动、照常出图"这一类上（否则它们该被运行期炸出来，
    # 不值得放进本表）：
    #   ① 可视半径 > 订阅容差：现价一走就退订**看得见**的档 ⇒ 行权价轴上的时间空洞，
    #      图看着正常，只是某些行中间空一截。
    #   ② 可视半径 > 绘制半径：可视区两端露出**空白行** —— 帧里根本没有那些档。
    Mutation("[6]", "config/features.json",
             replace_from='"heatmap_visible_rows_each_side": 12,',
             replace_to='"heatmap_visible_rows_each_side": 18,'),
    Mutation("[6]", "config/features.json",
             replace_from='"heatmap_visible_rows_each_side": 12,',
             replace_to='"heatmap_visible_rows_each_side": 24,'),
    Mutation("[7]", "state/tick_store.py",
             replace_from='_CFG = "state"',
             replace_to='_CFG = "pipeline"'),
    Mutation("[8]", "core/clock.py",
             replace_from='    def now_ts(self) -> float:\n',
             replace_to='    def now_ts(self) -> float:\n        self.bogus_slot = 1\n'),
    Mutation("[9]", "state/market_state.py", append=(
        "\n\nclass MutA:  # 变异：3 个有行为的顶层公开类\n"
        "    def f(self):\n        return 1\n"
        "\n\nclass MutB:\n    def f(self):\n        return 2\n"
        "\n\nclass MutC:\n    def f(self):\n        return 3\n"
    )),
    Mutation("[9b]", "features/glitch_filter.py",
             append="\nimport numpy  # noqa: F401  变异：L5 越界 import 数值库\n"),
    Mutation("[10]", "features/glitch_filter.py",
             append="\nMUTATION_CONSTANT = 12345  # 变异：模块级硬编码常量\n"),
    Mutation("[11]", "config/ibkr.json",
             replace_from='"rate_limit_max_requests": 45,',
             replace_to='"rate_limit_max_requests": 500,'),
    Mutation("[12]", "core/clock.py", append=(
        "\n\n# 变异：让 SessionClock 不再满足 ClockPort（now 变成不可调用）\n"
        "SessionClock.now = None  # type: ignore[assignment]\n"
    )),
    Mutation("[13]", "serialization/frame_encoder.py",
             replace_from='            "surface": self._surface.encode(frame.surface),\n',
             replace_to=''),
    Mutation("[14]", "acquisition/tick_router.py",
             replace_from="            if tick_type != 13 and self._use_model:\n"
                          "                # 明确要求只用模型值时不接受降级来源。\n"
                          "                return None\n",
             # ⚠️ 变异必须写成 `return comp, tick_type`（**接受**降级），不能写成
             # `continue`。写 `continue` 时循环会继续往下走，而 `_COMPUTATION_SOURCES`
             # 里后面的 bid/ask 槽位通常是空的 ⇒ 最终仍然 `return None` ⇒ **行为与
             # 原代码完全等价**，判据当然不会红。第一版就是这么写的，`--selftest`
             # 报"[14] 没抓住"，查下来是变异没造成缺陷、不是判据空转。
             # **变异必须真的改变行为** —— 否则"抓住了"和"没抓住"两个结论都不可信。
             replace_to="            if tick_type != 13 and self._use_model:\n"
                        "                return comp, tick_type  # 变异：接受降级\n"),
)

#: 输出里一个检查项段落的起头（``[3]`` / ``[9b]`` …）。捕获**含方括号**的编号，
#: 与 ``Mutation.label`` 同形，直接可比。
_SECTION_RE = re.compile(r"^(\[\d+b?\])", re.MULTILINE)


def _copy_project(dst: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in _COPY_DIRS:
        shutil.copytree(_ROOT / name, dst / name, ignore=ignore)
    shutil.copy2(_ROOT / "run.py", dst / "run.py")


def _run_in(project: Path) -> str:
    """在临时工程里跑一次自检，返回**标准输出**（失败时也返回已有输出）。"""
    proc = subprocess.run(
        [sys.executable, "tools/selfcheck.py"],
        cwd=str(project), capture_output=True, text=True, encoding="utf-8",
    )
    return (proc.stdout or "") + (proc.stderr or "")


def _section_failed(output: str, number: str) -> bool:
    """
    目标检查项的**自己那一段**里有没有 ``[FAIL]``。

    ⚠️ 为什么不看退出码就够了
    -------------------------
    ``RC != 0`` 只说明"有某一项失败了"。一个变异若同时触发别的检查项（例如往
    ``config/app.json`` 里塞坏键会连带影响 ``[7]``），那么**即使目标检查项是空转
    的**，退出码照样非 0 —— 于是"抓住了"这个结论是假的。

    所以这里按段落切开输出，只认目标编号那一段。段落切不出来（例如检查器崩了）
    也算失败：那同样是"这一项没有正常报出结论"。
    """
    matches = list(_SECTION_RE.finditer(output))
    for i, match in enumerate(matches):
        if match.group(1) != number:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        return "[FAIL]" in output[match.start():end]
    return True  # 该段没出现 ⇒ 检查没跑到或整体崩了 ⇒ 算抓住


def selftest() -> int:
    """
    对临时工程副本注入缺陷，证明每一项检查**自己**会红。

    ⚠️ **必须先跑一次未变异的对照**：若副本本身就跑不出全绿，那后面所有"变红"
    都不可归因（可能只是副本坏了）。这是"非空转"里最容易被跳过的一步。
    """
    print("=" * 72)
    print("非空转自检：注入缺陷，看各项检查抓不抓得住")
    print("=" * 72)

    failures = 0
    with tempfile.TemporaryDirectory(prefix="swatch-selfcheck-") as tmp:
        tmp_path = Path(tmp)

        # ── 对照：未变异的副本必须全绿 ──────────────────────────────
        control = tmp_path / "control"
        _copy_project(control)
        output = _run_in(control)
        healthy = "项全部通过" in output
        verdict = "全绿" if healthy else "**副本本身就不绿，下面所有结论无效**"
        print(f"  {GREEN if healthy else RED}[{'ok' if healthy else 'FAIL'}]{RESET} "
              f"对照（未变异副本）→ {verdict}")
        if not healthy:
            print(output[-2000:])
            return 1

        # ── 逐条变异（每条用独立副本，保证归因唯一）──────────────────
        for i, mutation in enumerate(_MUTATIONS):
            project = tmp_path / f"mut{i}"
            _copy_project(project)
            target = project / mutation.path

            if mutation.replace_from:
                text = target.read_text(encoding="utf-8")
                count = text.count(mutation.replace_from)
                if count != 1:
                    print(f"  {RED}[FAIL]{RESET} {mutation.label} 变异锚点在 "
                          f"{mutation.path} 里出现 {count} 次（要求恰好 1 次）—— "
                          f"锚点已漂移，请修正 _MUTATIONS")
                    failures += 1
                    continue
                target.write_text(
                    text.replace(mutation.replace_from, mutation.replace_to),
                    encoding="utf-8",
                )
            if mutation.append:
                target.write_text(
                    target.read_text(encoding="utf-8") + mutation.append,
                    encoding="utf-8",
                )

            caught = _section_failed(_run_in(project), mutation.label)
            print(f"  {GREEN if caught else RED}[{'ok' if caught else 'FAIL'}]{RESET} "
                  f"{mutation.label} → "
                  f"{'已抓住' if caught else '**没抓住（该检查是空转的）**'}"
                  f"  (注入 {mutation.path})")
            failures += 0 if caught else 1

    print()
    print("=" * 72)
    if failures:
        print(f"{RED}变异自检: {failures}/{len(_MUTATIONS)} 项未被抓住{RESET}")
    else:
        print(f"{GREEN}变异自检: {len(_MUTATIONS)}/{len(_MUTATIONS)} 项全部被抓到"
              f"（且每一条都验的是**目标检查项自己**报了 FAIL）{RESET}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="selfcheck.py")
    parser.add_argument("--selftest", action="store_true",
                        help="对临时副本注入缺陷，证明各项检查不是空转")
    args = parser.parse_args()
    raise SystemExit(selftest() if args.selftest else run_selfcheck())
