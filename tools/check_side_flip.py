"""回归：现价穿越行权价导致取边翻转时，热力图行的历史必须保持连续。

背景：热力图每个行权价只取虚值一侧（Put 或 Call）。现价穿越某个行权价时，
这一行的取边会从 Put 翻成 Call。如果时间桶历史按 (行权价, 方向) 分键存储，
那么翻转之后这一行就看不到翻转之前的任何数据——前半段明明采到了，却躺在
另一个键下。表现出来就是图上"现价附近凭空出现一块黑色空洞"。

这个脚本用"现价从 6500 单调跌到 6450"的确定性路径复现并断言它不再发生。
行情由 ``tools.fixtures.SyntheticSurface`` 解析生成、时间由
``tools.fixtures.FakeClock`` 推进，因此不依赖 IBKR、不依赖网络，
每次运行结果完全一致。

用法::

    python tools/check_side_flip.py
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
from state.tick_store import TickStore  # noqa: E402
from tools.fixtures import FakeClock, SyntheticSurface  # noqa: E402

BUCKETS = 40
STRIKE_STEP = 5.0
EACH_SIDE = 18

#: 每轮推进的会话秒数。
STEP_SECONDS = 60.0

#: 合成曲面参数。回归走的是确定性路径，取值只需保证 IV 为正、Delta 单调，
#: 不必与任何真实行情对齐。
BASE_SPOT = 6500.0
BASE_ATM_IV = 0.14
SURFACE_SLOPE = -1.1
SURFACE_CURVATURE = 1.8
DELTA_SCALE = 0.6

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def main() -> int:
    app_cfg = loader.load("app")
    state_cfg = loader.load("state")
    feat_cfg = loader.load("features")
    serial_cfg = loader.load("serialization")

    tz = loader.as_str(app_cfg, "timezone", module="app")
    open_hm = loader.as_str(app_cfg, "session_open", module="app")
    close_hm = loader.as_str(app_cfg, "session_close", module="app")
    bucket_s = loader.as_int(
        serial_cfg, "heatmap_bucket_seconds", module="serialization"
    )

    fake = FakeClock(tz, open_hm)
    session = SessionClock(tz, open_hm, close_hm, bucket_s, clock=fake)
    surface = SyntheticSurface(SURFACE_SLOPE, SURFACE_CURVATURE, DELTA_SCALE)
    store = TickStore(state_cfg, session)
    engine = FeatureEngine(store, session, feat_cfg, serial_cfg)

    #: 首个有值列 = 首次写入所在桶 + 1。
    #:
    #: 首次 compute 落在"开盘后 STEP_SECONDS 秒"的那个桶，而那一格没有前值可
    #: 差分，本身也是空的；再往后一格才有值。这个偏移**必须由桶宽推出来**，
    #: 不能写死 —— 桶宽从 60 秒改成 30 秒时，写死的 2 会立刻变成假警报，然后
    #: 被人顺手调大，于是这条检查就不再拦任何东西了。
    startup_offset = int(STEP_SECONDS // bucket_s) + 1

    expiry = session.expiry_str()
    atm_iv = BASE_ATM_IV
    open_spot = BASE_SPOT

    # 现价从 6500 线性跌到 6450，跨越 6480 / 6460 等档位
    watched = 6480.0
    side_log: list[str] = []

    for bucket in range(BUCKETS):
        fake.advance(STEP_SECONDS)
        ts = session.now_ts()
        spot = open_spot - (50.0 * bucket / (BUCKETS - 1))
        # 每次都按当前现价重算网格（与实盘订阅窗口随现价重建的行为一致）
        grid = surface.strike_grid(spot, STRIKE_STEP, EACH_SIDE)
        store.on_spot_tick(SpotTick(price=spot, ts=ts))
        for strike in grid:
            for right in (OptionRight.PUT, OptionRight.CALL):
                is_put = right is OptionRight.PUT
                iv = surface.iv_at(strike, spot, atm_iv)
                store.on_option_tick(
                    OptionTick(
                        ref=OptionRef(strike=float(strike), right=right, expiry=expiry),
                        iv=iv,
                        ts=ts,
                        delta=surface.delta_for(strike, spot, is_put),
                        opt_price=max(iv * spot * 0.008, 0.5),
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

    # 真正的判据是"一旦开始有值就不许再断"。只看首个有值列还不够：翻转处
    # 出现空洞同样会毁掉这条行，而空洞出现在中间时首列位置完全正常。
    interior = [c for c in range(filled[0], len(values)) if values[c] is None]
    passed = True

    continuous = bool(filled) and filled[0] <= startup_offset
    if continuous:
        print(f"{GREEN}[ok]{RESET} 取边翻转后历史保持连续"
              f"（首个有值列 {filled[0]}，允许偏移 ≤ {startup_offset}"
              f" = {int(STEP_SECONDS // bucket_s)} + 1）")
    else:
        print(f"{RED}[FAIL]{RESET} 历史在取边翻转处断裂："
              f"前 {filled[0]} 个桶在矩阵里为空，"
              f"而这段数据其实记在翻转前的另一个方向键下")
        passed = False

    if interior:
        print(f"{RED}[FAIL]{RESET} 行内出现 {len(interior)} 个空洞"
              f"（首个有值列之后仍为空）：{interior[:8]}")
        passed = False
    else:
        print(f"{GREEN}[ok]{RESET} 首个有值列之后无空洞（{len(values) - filled[0]} 列全有值）")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
