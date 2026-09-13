"""
L6 — 判据分组完整性守卫（共享设施）。
=====================================
唯一职责：给定「判据列表 + 分组表 + 期望前缀集合」，判定这份回归报告是否**完整**。

为什么需要它
------------
`tools/` 下的对照式回归把判据按前缀分组（``[G1]``/``[C1]``/…），报告时按 ``GROUPS``
过滤后再打印。于是有两类"报绿但是假的"，都不报错、退出码为 0：

1. **期望前缀集合由分组表自己推出** ⇒ 删掉一组时期望集合跟着变小、守卫失明，
   而那一组的判据**连报告都进不去** —— 失败的判据一条都不计数。
   2026-09-13 实测（``check_skew_viewport.py``）：删掉 ``[G4]`` 组后，该组 3 条
   失败被静默吞掉，报告照样"全部通过"（``tmp/_probe_guard_hole.py``）。
2. **判据存在但无人认领**（前缀不在任何组里）⇒ 同上，它失败了也不计数。

所以期望前缀必须是**独立常量**，且三条都要查：分组表**恰好**覆盖期望集合、
每条判据都被某个组认领、每个期望前缀都真有判据。缺任何一条都留有静默通过的缝。

``guard_cases`` 是守卫自身的非空转用例 —— 削掉一组必须被报出来；否则这个守卫
自己就是空转的。

用法::

    from tools.group_guard import guard_cases, guard_problems

    # GROUPS 中每个 prefixes 一律是 tuple[str, ...]（不要传 str，否则会被
    # 当成字符序列拆开）；EXPECTED_PREFIXES 是独立常量，**不能**从 GROUPS 推出。
    EXPECTED_PREFIXES = ("[G1]", "[G2]")
    GROUPS = (
        ("[G1] 一组", ("[G1]",)),
        ("[G2] 二组", ("[G2]", "[G3]")),  # 多前缀用 tuple
    )

    problems = guard_problems(checks, GROUPS, EXPECTED_PREFIXES)
    if problems:
        print("判据集合不完整  " + "；".join(problems))
        return 1
"""

from __future__ import annotations


def guard_problems(checks, groups, expected) -> list[str]:
    """
    返回问题列表（空 = 完整）。

    参数形状：
    - ``checks``    —— ``[(label, ok, detail)]``，回归工具的判据列表
    - ``groups``    —— ``((title, prefixes), ...)``，分组表；
      **prefixes 一律为** ``tuple[str, ...]``（不要传 ``str``，否则会被
      当成字符序列拆开）。这是接口约定 —— 不在运行时校验。
    - ``expected``  —— ``tuple[str, ...]``，期望的前缀集合（独立常量，
      不能由 ``groups`` 推出，否则守卫失明）。

    三条都要查（任一不过都算"判据集合不完整"）：
    1. ``groups`` 恰好覆盖 ``expected``（不重不漏）；
    2. 每条 ``checks`` 都至少被一个 ``groups`` 的前缀认领；
    3. 每个 ``expected`` 前缀都至少有一条 ``checks`` 在认领它。
    """
    grouped = [p for _, prefixes in groups for p in prefixes]
    problems: list[str] = []

    if sorted(grouped) != sorted(expected):
        problems.append(f"分组表前缀 {sorted(grouped)} ≠ 期望 {sorted(expected)}")
    if not checks:
        problems.append("判据集合为空")
    problems += [f"判据无人认领：{c[0]}" for c in checks
                 if not any(c[0].startswith(p) for p in grouped)]
    problems += [f"缺少 {p} 的判据" for p in expected
                 if not any(c[0].startswith(p) for c in checks)]
    return problems


def guard_cases(checks, groups, expected) -> list[tuple[str, list[str]]]:
    """
    守卫自身的非空转用例：``[(用例名, 问题列表)]``。**每条都必须非空**，否则守卫
    挡不住那一类静默通过。调用方负责打印与计数。
    """
    last = groups[-1][1][0] if groups else "（无）"
    return [
        ("清空分组表", guard_problems(checks, (), expected)),
        (f"去掉最后一组 {last}", guard_problems(checks, groups[:-1], expected)),
    ]
