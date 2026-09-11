"""
L3 — 会话翻篇回归。
====================
唯一职责：证明跨会话时累积状态被清空，两个交易日的 IV **不会**被当成同一条
序列做差分。

为什么需要它
------------
热力图与 Skew 序列的键都是**会话内**桶序号（``0..389``），它只在一天之内唯一。
引擎本身不带日期，于是跨过会话边界之后，新一天第 1 桶的 IV 会去减上一天第 1 桶
的 IV —— 差出一个**毫无根据的冲量**。这不是"数据缺失"，是凭空造出来的信号，
而且看起来完全正常：颜色、数值量级都对，只是它从来不存在。

这个缺陷曾经真的出现过：``FeatureEngine.reset()`` 一直存在，但**没有任何地方
调用它**。模拟器在收盘后停手，会话时钟继续走到下一个交易日，于是热力图从
"36 档 × 304 桶"塌成 "36 档 × 1 桶 · 0 格"——看起来像渲染坏了，实际是旧数据
被新会话的桶序号重新解释了一遍。

用法::

    python tools/check_session_rollover.py
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import OptionRight  # noqa: E402
from contracts.tick import OptionRef, OptionTick, QuoteTick, SpotTick  # noqa: E402
from core.clock import SessionClock  # noqa: E402
from features.feature_engine import FeatureEngine  # noqa: E402
from simulator.scenario import Scenario  # noqa: E402
from simulator.sim_clock import SimClock  # noqa: E402
from state.tick_store import TickStore  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


def _goto(sim_clock: SimClock, session: SessionClock, offset_s: float) -> None:
    """把会话时间推到开盘后第 ``offset_s`` 秒。"""
    sim_clock.advance(offset_s - session.elapsed_s())


def _row_of(matrix, strike: float):
    """取出矩阵里某个行权价那一行的值序列（不关心取的是 Put 还是 Call）。"""
    if matrix is None:
        return None
    for i, s in enumerate(matrix.strikes):
        if abs(s - strike) < 1e-9:
            return matrix.values[i]
    return None


def main() -> int:
    app_cfg = loader.load("app")
    sim_cfg = loader.load("simulator")
    sub_cfg = loader.load("subscription")
    state_cfg = loader.load("state")
    feat_cfg = loader.load("features")
    serial_cfg = loader.load("serialization")

    tz = loader.as_str(app_cfg, "timezone", module="app")
    open_hm = loader.as_str(app_cfg, "session_open", module="app")
    close_hm = loader.as_str(app_cfg, "session_close", module="app")
    bucket_s = loader.as_int(serial_cfg, "heatmap_bucket_seconds", module="serialization")
    step = loader.as_float(sim_cfg, "strike_step", module="simulator")
    each_side = loader.as_int(sub_cfg, "num_strikes_each_side", module="subscription")

    sim_clock = SimClock(tz, open_hm, speedup=1.0)
    session = SessionClock(tz, open_hm, close_hm, bucket_s, clock=sim_clock)
    scenario = Scenario(sim_cfg)

    store = TickStore(state_cfg, session)
    engine = FeatureEngine(store, session, feat_cfg, serial_cfg)

    spot = scenario.spot_at(0.0, real_elapsed_s=0.0)
    atm_iv = scenario.atm_iv_at(0.0)
    grid = scenario.strike_grid(spot, step, each_side)
    # 取现价下方第 3 档：热力图会取它的 Put 一侧，与取边规则无关地稳定存在。
    watched = float(grid[3])

    def feed(expiry: str, iv_bias: float, ts: float) -> None:
        """喂一整轮网格：现价 + 每档 Put/Call。"""
        store.on_spot_tick(SpotTick(price=spot, ts=ts))
        for strike in grid:
            for right in (OptionRight.PUT, OptionRight.CALL):
                is_put = right is OptionRight.PUT
                ref = OptionRef(strike=float(strike), right=right, expiry=expiry)
                iv = scenario.iv_at(strike, spot, atm_iv) + iv_bias
                store.on_option_tick(
                    OptionTick(
                        ref=ref, iv=iv, ts=ts,
                        delta=scenario.delta_for(strike, spot, is_put),
                        opt_price=max(iv * spot * 0.008, 0.5),
                        und_price=spot,
                        source_tick_type=13, model_greeks=True,
                    )
                )
                store.on_quote_tick(
                    QuoteTick(ref=ref, ts=ts, bid=1.0, ask=1.2, last=1.1)
                )

    print("=" * 72)
    print("会话翻篇回归（跨会话不得共用桶序号）")
    print("=" * 72)

    # ------------------------------------------------------------------ #
    # [1] 会话 A：桶内正常累积（对照组）
    # ------------------------------------------------------------------ #
    print(f"\n[1] 会话 A = {session.expiry_str()}：连续推进 6 个桶")
    session_a = session.expiry_str()
    iv_a = 0.0004          # 每个桶整体抬升，制造稳定的非零 ΔIV
    cols_a: list[int] = []

    for bucket in range(6):
        _goto(sim_clock, session, (bucket + 1) * bucket_s - 1.0)
        ts = session.now_ts()
        feed(session_a, iv_a * bucket, ts)
        bundle = engine.compute(now=ts)
        cols_a.append(bundle.heatmap.cols() if bundle.heatmap else 0)

    last_a = engine.compute(now=session.now_ts())
    row_a = _row_of(last_a.heatmap, watched)
    filled_a = last_a.heatmap.filled_cells() if last_a.heatmap else 0

    passed = True
    passed &= _check("会话内列数单调增长（未误清）",
                     cols_a == sorted(cols_a) and cols_a[-1] == 6,
                     f"cols={cols_a}")
    passed &= _check("会话内有非零 ΔIV", filled_a > 0, f"{filled_a} 有值格")
    passed &= _check("观察行已建立", row_a is not None,
                     f"行权价 {watched:.0f}")
    old_bucket0_iv = None
    if row_a is not None:
        # 反推会话 A 第 0 桶的 IV：第 1 桶的值 = (iv1 - iv0) * 100
        old_bucket0_iv = (scenario.iv_at(watched, spot, atm_iv) + iv_a * 0.0)
        print(f"      会话 A 观察行末列 ΔIV = {row_a[-1]}")

    # ------------------------------------------------------------------ #
    # [2] 翻篇：核心断言
    # ------------------------------------------------------------------ #
    # 把时钟推到下一个自然日（同一个时刻），再喂**只属于新会话第 1 桶**的 tick。
    # 如果桶序号被跨会话复用，新会话第 1 桶的 IV 会去减会话 A 第 0 桶残留的 IV，
    # 差出一个凭空造出来的冲量；正确行为是没有前值 → 该格为空。
    print("\n[2] 翻篇到下一个交易日，只喂新会话第 1 桶")
    sim_clock.set_day(sim_clock.session_datetime() + timedelta(days=1))
    sim_clock.reset()
    session_b = session.expiry_str()
    passed &= _check("到期日已翻篇", session_b != session_a,
                     f"{session_a} → {session_b}")

    iv_b = 0.0200          # 与 A 拉开巨大差距，污染值会非常显眼
    _goto(sim_clock, session, 1 * bucket_s + 1.0)
    ts_b = session.now_ts()
    feed(session_b, iv_b, ts_b)
    bundle_b = engine.compute(now=ts_b)

    row_b = _row_of(bundle_b.heatmap, watched)
    print(f"      会话 B 观察行 = {row_b}")
    passed &= _check("翻篇后仍产出矩阵", row_b is not None)

    # 污染值长这样：(B 的 IV − A 残留的 IV) × 100，量级约 1.6 个波动率点
    contaminant = abs(iv_b - iv_a * 0.0) * 100.0
    if row_b is not None:
        v1 = row_b[1]
        passed &= _check(
            "第 1 桶不得跨会话差分（该格必须为空）",
            v1 is None,
            f"值={v1}" + (f"（若跨会话污染应约为 {contaminant:.2f} 波动率点）"
                          if v1 is not None else ""),
        )

    # ------------------------------------------------------------------ #
    # [3] 翻篇后 Skew 序列必须清零
    # ------------------------------------------------------------------ #
    print("\n[3] 翻篇后 Skew 序列")
    points = len(bundle_b.skew_series)
    passed &= _check("Skew 序列只含新会话的点", points == 1,
                     f"{points} 点（若未清零应约 7 点）")

    # ------------------------------------------------------------------ #
    # [4] 翻篇后无新 tick：不得把旧矩阵挂在新会话名下
    # ------------------------------------------------------------------ #
    # 会话时钟继续走，但没有任何新 tick。此时若不清空，旧矩阵会以新会话的身份
    # 继续被推送出去 —— 画面上是一张"看起来正常"的图，实际全是上一个交易日的。
    print("\n[4] 翻篇后无新 tick（旧数据不得冒充当天）")
    sim_clock.set_day(sim_clock.session_datetime() + timedelta(days=1))
    sim_clock.reset()
    session_c = session.expiry_str()
    _goto(sim_clock, session, 3 * bucket_s)

    bundle_c = engine.compute(now=session.now_ts())
    passed &= _check("到期日再次翻篇", session_c != session_b,
                     f"{session_b} → {session_c}")
    passed &= _check(
        "无新 tick 时不再推送旧矩阵",
        bundle_c.heatmap is None or bundle_c.heatmap.filled_cells() == 0,
        f"有值格={bundle_c.heatmap.filled_cells() if bundle_c.heatmap else 'None'}",
    )
    passed &= _check("Skew 序列已清空", len(bundle_c.skew_series) == 0,
                     f"{len(bundle_c.skew_series)} 点")

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if passed
          else f"{RED}结果: 存在失败项{RESET}")
    print("=" * 72)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
