"""
L1 — 订阅窗口容差回归。
========================
唯一职责：证明「现价在容差带内往返时，热力图显示窗口里的任何一档都不会被退订」。

为什么需要它
------------
热力图的纵轴行来自**显示窗口**（``features`` 配置里的 ``heatmap_rows_each_side``），
行情订阅来自**订阅窗口**（``subscription`` 配置里的 ``num_strikes_each_side``）。
两个半径必须留出余量，而这条余量以前没有任何东西守着。

余量不足会怎样：现价一移动，``WindowFollower`` 就按 ``recenter_trigger_strikes``
重建窗口；``cancel_stale_before_add`` 让滚出窗口的档位**立刻退订**。于是那几档在
现价往返期间收不到任何 tick —— 而 ``HeatmapEngine._prune()`` **只按时间裁剪、
从不按行权价裁剪**，该行不会被删掉，只在中间空一截。图上表现为「行权价轴上的
一条时间空洞」，现价回来之后空洞留在原地，看起来像数据源丢包。

这不是渲染缺陷：前端忠实渲染，错在订阅窗口没留容差。2026-09-14 之前的配置是
两个半径都是 12 —— 容差 0 档，于是这条空洞必然出现。

判据
----
容差（档）必须 ≥ 窗口重建触发步长 ``recenter_trigger_strikes``：

    订阅半径 S − 显示半径 R ≥ 触发步长 T

推导：两次重建之间中心最多滞后 T 档，故现价可探出**已订阅窗口** T 档。此时显示
窗口最低一档 = 现价 − (T + R − 1) × 步长，订阅窗口最低一档 = 中心 − (S − 1) × 步长；
要求前者不低于后者即得 S − R ≥ T。这条判据是**推出来的，不是拿观测拟合的** ——
本回归用容差 = T−1 与 T 两条对照把边界钉死。

本回归怎么跑
------------
纯逻辑、不连网、不依赖 IBKR：``ChainResolver`` 与 ``StrikeWindow`` 都是纯函数，
``WindowFollower`` 的跟随循环在这里被逐点重放（同一套 ``centre_moved`` /
``window`` 调用）。沿三条现价路径（单边下行 / 单边上行 / 先跌后弹）逐点断言
「显示窗口 ⊆ 已订阅集合」。

**并且自证非空转**：把订阅半径压到与显示半径相等，同一条路径必须扫出空洞。
若这条对照也不报红，说明本回归自己失效了 —— 而不是产品变好了。

用法::

    python tools/check_window_tolerance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acquisition.chain_resolver import ChainResolver  # noqa: E402
from config import loader  # noqa: E402
from features.strike_window import StrikeWindow  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: 合成行权价阶梯与现价路径的参数。**只用于夹具** —— 所有产品参数（两个窗口
#: 半径、重建触发）一律从配置读，不在这里重写一份。
CENTRE_STRIKE = 6500.0
STRIKE_STEP = 5.0
LADDER_EACH_SIDE = 200          # 阶梯半径（档）；要盖住整条扫描路径
PATH_SPAN_POINTS = 400.0        # 现价扫描范围（点）
PATH_STEP_POINTS = 1.0          # 扫描步长（点）


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


def _ramp(start: float, end: float, step: float) -> list[float]:
    """从 ``start`` 走到 ``end``（含两端），步长 ``step``。"""
    count = int(round(abs(end - start) / step))
    sign = 1.0 if end >= start else -1.0
    return [start + sign * i * step for i in range(count + 1)]


def _simulate(
    resolver: ChainResolver,
    display: StrikeWindow,
    ladder: tuple[float, ...],
    side_sub: int,
    side_disp: int,
    trigger: float,
    path: list[float],
) -> list[tuple[float, tuple[float, ...]]]:
    """
    沿现价路径重放 ``WindowFollower`` 的窗口跟随，返回空洞清单。

    空洞 = 「显示窗口想要、但当时并未订阅」的档位。返回 ``[(现价, 缺档元组)]``。

    跟随循环与 ``acquisition/feed_reconcile.py::WindowFollower.run()`` 同构：
    初始 ``centre=None`` ⇒ 第一次必然重建；之后只在 ``centre_moved`` 为真时重建。
    """
    subscribed: tuple[float, ...] = ()
    centre: float | None = None
    holes: list[tuple[float, tuple[float, ...]]] = []

    for spot in path:
        if resolver.centre_moved(centre, ladder, spot, trigger):
            subscribed = resolver.window(ladder, spot, side_sub)
            centre = resolver.centre_strike(ladder, spot)
        live = set(subscribed)
        wanted = display.window_strikes(ladder, spot, side_disp)
        missing = tuple(s for s in wanted if s not in live)
        if missing:
            holes.append((spot, missing))
    return holes


def _first(holes: list[tuple[float, tuple[float, ...]]]) -> str:
    if not holes:
        return ""
    spot, missing = holes[0]
    return f"首个：现价 {spot:.0f} 时缺 {', '.join(f'{s:.0f}' for s in missing)}"


def main() -> int:
    app_cfg = loader.load("app")
    sub_cfg = loader.load("subscription")
    feat_cfg = loader.load("features")

    resolver = ChainResolver(app_cfg, sub_cfg)
    display = StrikeWindow(feat_cfg)

    requested = loader.as_int(sub_cfg, "num_strikes_each_side", module="subscription")
    side_sub = resolver.effective_each_side()
    side_disp = display.each_side()
    trigger = loader.as_float(sub_cfg, "recenter_trigger_strikes", module="subscription")
    tolerance = side_sub - side_disp

    ladder = tuple(
        CENTRE_STRIKE + k * STRIKE_STEP
        for k in range(-LADDER_EACH_SIDE, LADDER_EACH_SIDE + 1)
    )

    print("=" * 72)
    print("订阅窗口容差回归（现价往返不得退订显示窗口内的档位）")
    print("=" * 72)
    print(f"  订阅窗口 ±{side_sub} 档（配置 {requested}，容量折算后 "
          f"{side_sub}）· 显示窗口 ±{side_disp} 档 · 重建触发 {trigger} 档")
    print(f"  容差 = {side_sub} − {side_disp} = {tolerance} 档")

    passed = True

    # ------------------------------------------------------------------ #
    # [1] 配置级前置：容差必须为正，且不小于重建触发步长
    # ------------------------------------------------------------------ #
    print("\n[1] 容差判据 S − R ≥ T")
    passed &= _check(
        "容差为正（订阅窗口严格宽于显示窗口）",
        tolerance > 0,
        f"{side_sub} − {side_disp} = {tolerance} 档",
    )
    passed &= _check(
        "容差 ≥ 重建触发步长",
        tolerance >= trigger,
        f"{tolerance} 档 ≥ {trigger} 档",
    )

    # ------------------------------------------------------------------ #
    # [2] 三条现价路径：显示窗口必须始终落在已订阅集合里
    # ------------------------------------------------------------------ #
    paths = {
        "单边下行（现价一路跌）":
            _ramp(CENTRE_STRIKE, CENTRE_STRIKE - PATH_SPAN_POINTS, PATH_STEP_POINTS),
        "单边上行（现价一路涨）":
            _ramp(CENTRE_STRIKE, CENTRE_STRIKE + PATH_SPAN_POINTS, PATH_STEP_POINTS),
        "先跌后弹再回落（往返）":
            _ramp(CENTRE_STRIKE, CENTRE_STRIKE - PATH_SPAN_POINTS, PATH_STEP_POINTS)
            + _ramp(CENTRE_STRIKE - PATH_SPAN_POINTS,
                    CENTRE_STRIKE + PATH_SPAN_POINTS, PATH_STEP_POINTS)
            + _ramp(CENTRE_STRIKE + PATH_SPAN_POINTS, CENTRE_STRIKE, PATH_STEP_POINTS),
    }

    print(f"\n[2] 逐点扫描 {PATH_SPAN_POINTS:.0f} 点行程、步长 "
          f"{PATH_STEP_POINTS:.0f} 点（每步断言 显示窗口 ⊆ 已订阅集合）")
    for name, path in paths.items():
        holes = _simulate(
            resolver, display, ladder, side_sub, side_disp, trigger, path
        )
        passed &= _check(
            f"{name}：无空洞",
            not holes,
            f"{len(path)} 步 / {len(holes)} 个空洞" + (
                f"  {_first(holes)}" if holes else ""),
        )

    # ------------------------------------------------------------------ #
    # [3] 边界：容差 = T−1 必须出洞、= T 必须不出
    # ------------------------------------------------------------------ #
    # 这条把"判据是紧的"钉死 —— 否则上面 [1] 的 `≥ T` 就只是一个人为选的数字。
    # 用单边下行路径（最容易出洞的方向）做对照。
    print("\n[3] 判据边界（证明 ≥ T 是紧的，不是拍出来的数字）")
    down = paths["单边下行（现价一路跌）"]

    for label, sub_side, expect_holes in (
        (f"容差 {int(trigger) - 1} 档（S = R + T − 1）", side_disp + int(trigger) - 1, True),
        (f"容差 {int(trigger)} 档（S = R + T）", side_disp + int(trigger), False),
        ("容差 0 档（S = R，2026-09-14 之前的配置）", side_disp, True),
    ):
        holes = _simulate(
            resolver, display, ladder, sub_side, side_disp, trigger, down
        )
        got_holes = bool(holes)
        passed &= _check(
            f"{label} → {'应出洞' if expect_holes else '应无洞'}",
            got_holes is expect_holes,
            f"{len(holes)} 个空洞" + (f"  {_first(holes)}" if holes else ""),
        )

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if passed
          else f"{RED}结果: 存在失败项{RESET}")
    print("=" * 72)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
