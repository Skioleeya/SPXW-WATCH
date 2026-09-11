"""回归：现价穿越行权价导致取边翻转时，热力图行的历史必须保持连续。

背景：热力图每个行权价只取虚值一侧（Put 或 Call）。现价穿越某个行权价时，
这一行的取边会从 Put 翻成 Call。如果时间桶历史按 (行权价, 方向) 分键存储，
那么翻转之后这一行就看不到翻转之前的任何数据——前半段明明采到了，却躺在
另一个键下。表现出来就是图上"现价附近凭空出现一块黑色空洞"。

这个脚本用"现价从 6500 单调跌到 6450"的确定性路径复现并断言它不再发生，
不依赖模拟器，也不依赖行情通道。

用法::

    python tools/repro_side_flip.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import OptionRight  # noqa: E402
from contracts.tick import OptionRef, OptionTick, SpotTick  # noqa: E402
from core.clock import SessionClock  # noqa: E402
from features.feature_engine import FeatureEngine  # noqa: E402
from simulator.scenario import Scenario  # noqa: E402
from simulator.sim_clock import SimClock  # noqa: E402
from state.tick_store import TickStore  # noqa: E402

BUCKETS = 40
STRIKE_STEP = 5.0
EACH_SIDE = 18

#: 允许的启动偏移：前两个时间桶没有"前值"可差分，天然为空。
STARTUP_OFFSET = 2

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def main() -> int:
    app_cfg = loader.load("app")
    sim_cfg = loader.load("simulator")
    sub_cfg = loader.load("subscription")
    state_cfg = loader.load("state")
    feat_cfg = loader.load("features")
    serial_cfg = loader.load("serialization")

    sim_clock = SimClock(
        loader.as_str(app_cfg, "timezone", module="app"),
        loader.as_str(app_cfg, "session_open", module="app"),
        speedup=1.0,
    )
    session = SessionClock(
        loader.as_str(app_cfg, "timezone", module="app"),
        loader.as_str(app_cfg, "session_open", module="app"),
        loader.as_str(app_cfg, "session_close", module="app"),
        loader.as_int(serial_cfg, "heatmap_bucket_seconds", module="serialization"),
        clock=sim_clock,
    )
    scenario = Scenario(sim_cfg)
    store = TickStore(state_cfg, session)
    engine = FeatureEngine(store, session, feat_cfg, serial_cfg)

    expiry = session.expiry_str()
    atm_iv = loader.as_float(sim_cfg, "base_atm_iv", module="simulator")
    open_spot = loader.as_float(sim_cfg, "base_spot", module="simulator")

    # 现价从 6500 线性跌到 6450，跨越 6480 / 6460 等档位
    watched = 6480.0
    side_log: list[str] = []

    for bucket in range(BUCKETS):
        sim_clock.advance(60.0)
        ts = session.now_ts()
        spot = open_spot - (50.0 * bucket / (BUCKETS - 1))
        # 每次都按当前现价重算网格（与 SyntheticFeed 的行为一致）
        grid = scenario.strike_grid(spot, STRIKE_STEP, EACH_SIDE)
        store.on_spot_tick(SpotTick(price=spot, ts=ts))
        for strike in grid:
            for right in (OptionRight.PUT, OptionRight.CALL):
                is_put = right is OptionRight.PUT
                store.on_option_tick(
                    OptionTick(
                        ref=OptionRef(strike=float(strike), right=right, expiry=expiry),
                        iv=scenario.iv_at(strike, spot, atm_iv),
                        ts=ts,
                        delta=scenario.delta_for(strike, spot, is_put),
                        opt_price=max(scenario.iv_at(strike, spot, atm_iv) * spot * 0.008, 0.5),
                        und_price=spot,
                        source_tick_type=13,
                        model_greeks=True,
                    )
                )
        bundle = engine.compute()
        if bundle.heatmap is not None:
            idx = list(bundle.heatmap.strikes).index(watched)
            side_log.append(str(bundle.heatmap.rights[idx]))

    final = engine.compute()
    hm = final.heatmap
    row = list(hm.strikes).index(watched)
    values = hm.values[row]
    filled = [c for c, v in enumerate(values) if v is not None]

    print(f"现价路径: {open_spot:.0f} → {open_spot - 50:.0f}（{BUCKETS} 个时间桶）")
    print(f"观察行权价 {watched:.0f} 的取边变化: {' '.join(side_log)}")
    print(f"当前取边 = {hm.rights[row]}")
    print(f"该行有值列数 = {len(filled)} / {len(values)}")
    print(f"首个有值列 = {filled[0] if filled else None}")
    print()

    flipped = "P" in side_log and "C" in side_log
    if not flipped:
        print(f"{RED}[FAIL]{RESET} 测试前提不成立：该行取边全程未翻转")
        return 1

    continuous = bool(filled) and filled[0] <= STARTUP_OFFSET
    if continuous:
        print(f"{GREEN}[ok]{RESET} 取边翻转后历史保持连续"
              f"（首个有值列 {filled[0]}，允许偏移 ≤ {STARTUP_OFFSET}）")
        return 0

    print(f"{RED}[FAIL]{RESET} 历史在取边翻转处断裂："
          f"前 {filled[0]} 个桶在矩阵里为空，"
          f"而这段数据其实记在翻转前的另一个方向键下")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
