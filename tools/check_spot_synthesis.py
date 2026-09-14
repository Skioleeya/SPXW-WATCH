"""
GTH 现货基准合成回归（B2b）。
=============================
验证 ``acquisition.spot_synthesis.SpotSynthesis`` 的三件事：

1. **数值对不对** —— 用 2026-09-14 01:32:55 ET 的**真实** ES 报价复算，并与
   **独立口径**（同到期日期权平价 B3）对拍。B3 走的是完全不同的数据（同一张链
   的 Call/Put），因此这不是自证。
2. **两层闸门真的会拦** —— 各自触发一次；跳变闸门还要证明**不是死锁**
   （拒收一桶之后，下一个正常值必须能恢复）。
3. **输入无效时 fail-closed** —— 不足两个月 / 报价过期 / 价格非法 / T 非法。

判据取自实测，不是猜的：

* 冻结指数 = 7656.98（= 周五官方收盘，恒定，``marketDataType`` 仍报 1）
* 真实 ES 报价：前月 7619.0 / 次月 7686.25（到期 20260918 / 20261218）
* 反解 ``ĉ`` = 0.03524813（探针 20 个样本中位 0.03526）
* B2b = 7616.0575，**B3 = 7616.0**（差 0.06 点）

"选谁当来源"（区段切源、09:25 交班、窗口重建）见 ``tools/check_spot_source.py``。

非空转验证：本回归全绿之后，把 ``spot_synthesis.py`` 里任一闸门的 ``if`` 摘掉，
必须报 FAIL —— 见 ``notes/sessions/2026-09-14/gth-spot-basis-research/handoff.md``
的 COMMAND-EVIDENCE。

运行::

    python tools/check_spot_synthesis.py
"""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acquisition.spot_synthesis import SpotSynthesis  # noqa: E402
from config import loader  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

TZ = "America/New_York"

# ---- 实测锚点（2026-09-14 01:32:55 ET，tmp/gth_probe.csv 第 1 行） ---------- #
FROZEN_INDEX = 7656.98
SAMPLE_F1 = 7619.0
SAMPLE_F2 = 7686.25
SAMPLE_FRONT = "20260918"
SAMPLE_SECOND = "20261218"
SAMPLE_CARRY = 0.03524813340719248
SAMPLE_B2B = 7616.0574940693705
SAMPLE_B3 = 7616.0  # 独立口径：同到期日期权平价
SAMPLE_MOMENT = datetime(2026, 9, 14, 1, 32, 55, tzinfo=ZoneInfo(TZ)).timestamp()

#: SPXW 档距（点）。档位偏移量决定窗口要不要重建。
STRIKE_STEP = 5.0

Case = tuple[str, bool, str]


def _synthesis(spot_cfg: dict) -> SpotSynthesis:
    return SpotSynthesis(spot_cfg)


# --------------------------------------------------------------------------- #
# [1] 数值
# --------------------------------------------------------------------------- #

def case_numbers(spot_cfg: dict) -> list[Case]:
    syn = _synthesis(spot_cfg)
    syn.update(SAMPLE_FRONT, SAMPLE_F1, SAMPLE_MOMENT)
    syn.update(SAMPLE_SECOND, SAMPLE_F2, SAMPLE_MOMENT)

    price = syn.spot(SAMPLE_MOMENT, 60.0)
    carry = syn.carry

    out: list[Case] = [
        (
            "反解 carry 与实测一致（0.03524813）",
            carry is not None and abs(carry - SAMPLE_CARRY) < 1e-9,
            f"got={carry!r}",
        ),
        (
            "合成现货落在合理区间 [7613, 7617]",
            price is not None and 7613.0 <= price <= 7617.0,
            f"got={price!r}",
        ),
    ]
    if price is None:
        return out

    out.append((
        f"与独立口径 B3({SAMPLE_B3}) 差 ≤ 0.5 点（跨数据源对拍）",
        abs(price - SAMPLE_B3) <= 0.5,
        f"got={price:.4f} diff={price - SAMPLE_B3:+.4f}",
    ))
    out.append((
        "与探针 B2b 记录差 ≤ 0.5 点（T 口径差：UTC 00:00 vs 日期差）",
        abs(price - SAMPLE_B2B) <= 0.5,
        f"got={price:.4f} diff={price - SAMPLE_B2B:+.4f}",
    ))
    out.append((
        "冻结指数与合成值差 ≥ 8 档（这就是必须合成的原因）",
        (FROZEN_INDEX - price) / STRIKE_STEP >= 8.0,
        f"gap={FROZEN_INDEX - price:.2f} 点 = "
        f"{(FROZEN_INDEX - price) / STRIKE_STEP:.2f} 档",
    ))
    return out


# --------------------------------------------------------------------------- #
# [2] 闸门一：绝对区间
# --------------------------------------------------------------------------- #

def case_abs_gate(spot_cfg: dict) -> list[Case]:
    limit = float(spot_cfg["max_abs_carry"])
    syn = _synthesis(spot_cfg)

    # ln(8000/7600) / 0.2493 ≈ 0.206 ≫ 15%
    syn.update(SAMPLE_FRONT, 7600.0, SAMPLE_MOMENT)
    syn.update(SAMPLE_SECOND, 8000.0, SAMPLE_MOMENT)
    bad = syn.spot(SAMPLE_MOMENT, 60.0)

    out: list[Case] = [
        (
            f"|ĉ| > {limit:g} 时 fail-closed（不出值）",
            bad is None,
            f"got={bad!r}",
        ),
        (
            "被拦时 rejections 计数增加（不是静默丢弃）",
            syn.rejections >= 1,
            f"rejections={syn.rejections}",
        ),
    ]

    # 同一个实例喂回正常值，必须能产出 —— 闸门不能把实例卡死。
    syn.update(SAMPLE_FRONT, SAMPLE_F1, SAMPLE_MOMENT)
    syn.update(SAMPLE_SECOND, SAMPLE_F2, SAMPLE_MOMENT)
    good = syn.spot(SAMPLE_MOMENT, 60.0)
    out.append((
        "拦下之后喂正常值仍能产出（闸门不粘滞）",
        good is not None,
        f"got={good!r}",
    ))
    return out


# --------------------------------------------------------------------------- #
# [3] 闸门二：跳变
# --------------------------------------------------------------------------- #

def case_jump_gate(spot_cfg: dict) -> list[Case]:
    limit = float(spot_cfg["max_carry_jump"])
    syn = _synthesis(spot_cfg)

    syn.update(SAMPLE_FRONT, SAMPLE_F1, SAMPLE_MOMENT)
    syn.update(SAMPLE_SECOND, SAMPLE_F2, SAMPLE_MOMENT)
    first = syn.spot(SAMPLE_MOMENT, 60.0)

    # 让 ĉ 跳 +60bp（> 50bp 阈值）：F2/F1 = exp(ĉ_target · (T2 − T1))
    span = (
        SpotSynthesis._years_to(SAMPLE_SECOND, SAMPLE_MOMENT)
        - SpotSynthesis._years_to(SAMPLE_FRONT, SAMPLE_MOMENT)
    )
    syn.update(SAMPLE_FRONT, 7600.0, SAMPLE_MOMENT)
    syn.update(SAMPLE_SECOND, 7600.0 * math.exp((SAMPLE_CARRY + 0.006) * span),
               SAMPLE_MOMENT)
    second = syn.spot(SAMPLE_MOMENT, 60.0)
    third = syn.spot(SAMPLE_MOMENT, 60.0)

    return [
        ("基准建立时正常产出", first is not None, f"got={first!r}"),
        (f"|Δĉ| > {limit:g} 时拒收该桶", second is None, f"got={second!r}"),
        ("下一桶恢复正常（基准跟上，不是死锁）", third is not None, f"got={third!r}"),
    ]


# --------------------------------------------------------------------------- #
# [4] 输入有效性
# --------------------------------------------------------------------------- #

def case_inputs(spot_cfg: dict) -> list[Case]:
    def build(pairs: list[tuple[str, float, float]]) -> SpotSynthesis:
        syn = _synthesis(spot_cfg)
        for expiry, price, ts in pairs:
            syn.update(expiry, price, ts)
        return syn

    now = SAMPLE_MOMENT
    one = build([(SAMPLE_FRONT, SAMPLE_F1, now)])
    stale = build([(SAMPLE_FRONT, SAMPLE_F1, now - 100.0),
                   (SAMPLE_SECOND, SAMPLE_F2, now - 100.0)])
    zero = build([(SAMPLE_FRONT, SAMPLE_F1, now), (SAMPLE_SECOND, SAMPLE_F2, now)])
    zero.update(SAMPLE_FRONT, 0.0, now)
    bad_expiry = build([("not-a-date", SAMPLE_F1, now),
                        (SAMPLE_SECOND, SAMPLE_F2, now)])
    same = build([(SAMPLE_FRONT, SAMPLE_F1, now), (SAMPLE_FRONT, SAMPLE_F2, now)])

    return [
        (
            "只有一个月时 fail-closed（B2b 需要两个方程）",
            one.spot(now, 60.0) is None,
            "got=non-None",
        ),
        (
            "报价超过 max_age 时 fail-closed（不吃陈旧价）",
            stale.spot(now, 10.0) is None,
            "got=non-None",
        ),
        (
            "价格 ≤ 0 时删除该月（不保留旧值）",
            zero.spot(now, 60.0) is None,
            f"months={zero.months()}",
        ),
        (
            "到期日无法解析时 fail-closed（T 非法不算）",
            bad_expiry.spot(now, 60.0) is None,
            "got=non-None",
        ),
        (
            "两个报价同一个月时 fail-closed（T2 == T1）",
            same.spot(now, 60.0) is None,
            "got=non-None",
        ),
    ]


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #

def report(title: str, groups: list[tuple[str, list[Case]]]) -> int:
    """统一的回归输出。被 ``tools/check_spot_source.py`` 复用，避免两套风格。"""
    print("=" * 72)
    print(title)
    print("=" * 72)

    failures = 0
    total = 0
    for group_title, cases in groups:
        print(f"\n{group_title}")
        for name, passed, detail in cases:
            total += 1
            if passed:
                print(f"{GREEN}  [ok]{RESET} {name}")
            else:
                print(f"{RED}  [FAIL]{RESET} {name} —— {detail}")
                failures += 1

    print()
    print("=" * 72)
    if failures:
        print(f"{RED}结果: {failures}/{total} 项不通过{RESET}")
    else:
        print(f"{GREEN}结果: 全部通过（{total} 项）{RESET}")
    print("=" * 72)
    return 1 if failures else 0


def main() -> int:
    spot_cfg = loader.load("spot")
    return report("GTH 现货基准合成回归（B2b）", [
        ("[1] 数值：真实报价复算 + 独立口径对拍", case_numbers(spot_cfg)),
        ("[2] 闸门一：绝对区间 |ĉ|", case_abs_gate(spot_cfg)),
        ("[3] 闸门二：跳变 |Δĉ|", case_jump_gate(spot_cfg)),
        ("[4] 输入有效性（fail-closed 条件）", case_inputs(spot_cfg)),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
