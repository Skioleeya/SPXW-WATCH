"""
L6 — 架构与配置自检（编排器）。
==============================
唯一职责：按顺序调用各检查模块并汇总结果。**本文件不含任何检查逻辑。**

检查项（实现位置见括号）
------------------------
[1]  文件长度：每个 ``.py`` 必须少于 400 行。              （selfcheck_structure）
[2]  依赖方向：第 N 层只能 import 第 0…N 层，禁止反向。      （selfcheck_structure）
[3]  配置文件可读性。                                     （selfcheck_config）
[4]  配置零耦合：配置文件之间不得互相引用。                 （selfcheck_config）
[5]  关键配置项存在。                                     （selfcheck_config）
[6]  订阅容量不超 IBKR 100 条硬上限；显示窗口 ≤ 订阅窗口。   （selfcheck_config）
[7]  配置键归属与接线：一个键只能属于一个模块，且必须被读取。 （selfcheck_config）
[8]  ``__slots__`` 与实例属性赋值一致。                    （selfcheck_slots）
[9]  单一职能：模块不得承载多个职能。                       （selfcheck_duty）
[10] 禁止硬编码：模块级字面量常量必须来自配置。             （selfcheck_hardcode）
[11] 出站限速桶容量与 IBKR 配额（行数÷2）。                 （selfcheck_config）

检查项 [1]–[7] 直接对应项目五条硬性要求；[8] 是踩坑之后加的静态护栏，
[9][10] 把原本只写在 README 里的第 2、3 条变成了可执行检查；
[11] 把"桶容量"从库的隐式默认值变成配置项之后，配上机械校验，
防止它下次改动时悄悄失配。

运行::

    python run.py --check
    python tools/selfcheck.py        # 等价，便于单独调试
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.selfcheck_config import (  # noqa: E402
    check_config_coupling,
    check_config_ownership,
    check_config_readable,
    check_rate_limit_bucket,
    check_required_keys,
    check_subscription_capacity,
)
from tools.selfcheck_core import GREEN, RED, RESET  # noqa: E402
from tools.selfcheck_duty import check_single_duty  # noqa: E402
from tools.selfcheck_hardcode import check_hardcode  # noqa: E402
from tools.selfcheck_slots import check_slots  # noqa: E402
from tools.selfcheck_structure import check_file_sizes, check_layering  # noqa: E402


def run_selfcheck() -> int:
    print("=" * 72)
    print("SPXW SWATCH — 架构与配置自检")
    print("=" * 72)

    failures = 0

    failures += check_file_sizes()
    failures += check_layering()

    loaded, unreadable = check_config_readable()
    failures += unreadable
    failures += check_config_coupling(loaded)
    failures += check_required_keys(loaded)
    failures += check_subscription_capacity(loaded)
    failures += check_rate_limit_bucket(loaded)
    failures += check_config_ownership()

    failures += check_slots()
    failures += check_single_duty()
    failures += check_hardcode()

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
