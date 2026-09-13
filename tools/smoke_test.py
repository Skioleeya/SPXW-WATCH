"""L0–L4 全链路离线冒烟测试（不依赖 IBKR）。

行情由 ``tools.fixtures.SyntheticSurface`` 解析生成、时间由
``tools.fixtures.FakeClock`` 推进，因此本测试不连网、不需要行情权限，
每次运行结果完全一致。

用法::

    python tools/smoke_test.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import ConnectionState, FeedMode, OptionRight  # noqa: E402
from contracts.tick import (  # noqa: E402
    FeedStatus,
    OptionRef,
    OptionTick,
    QuoteTick,
    SpotTick,
)
from core.clock import SessionClock  # noqa: E402
from core.logging_setup import configure  # noqa: E402
from features.feature_engine import FeatureEngine  # noqa: E402
from serialization.payload_builder import PayloadBuilder  # noqa: E402
from state.market_state import MarketState  # noqa: E402
from state.tick_store import TickStore  # noqa: E402
from tools.fixtures import FakeClock, SyntheticSurface  # noqa: E402

OK = "  [ok] "
FAIL = "  [FAIL] "

#: 合成曲面参数。回归走的是确定性路径，取值只需保证 IV 为正、Delta 单调、
#: 偏斜为"左高右低"（skew 为正）。
BASE_SPOT = 6500.0
BASE_ATM_IV = 0.14
SURFACE_SLOPE = -1.1
SURFACE_CURVATURE = 1.8
DELTA_SCALE = 0.6
STRIKE_STEP = 5.0


def check(label: str, condition: bool, detail: str = "") -> bool:
    print((OK if condition else FAIL) + label + (f"  {detail}" if detail else ""))
    return condition


def main() -> int:
    app_cfg = loader.load("app")
    sub_cfg = loader.load("subscription")
    state_cfg = loader.load("state")
    feat_cfg = loader.load("features")
    serial_cfg = loader.load("serialization")
    configure(loader.load("logging"))

    passed = True
    print("=" * 72)
    print("L0–L4 离线冒烟测试")
    print("=" * 72)

    # ------------------------------------------------------------------ #
    # 时间与场景
    # ------------------------------------------------------------------ #
    tz = loader.as_str(app_cfg, "timezone", module="app")
    open_hm = loader.as_str(app_cfg, "session_open", module="app")
    close_hm = loader.as_str(app_cfg, "session_close", module="app")
    bucket_s = loader.as_int(
        serial_cfg, "heatmap_bucket_seconds", module="serialization"
    )

    fake = FakeClock(tz, open_hm)
    session = SessionClock(tz, open_hm, close_hm, bucket_s, clock=fake)
    surface = SyntheticSurface(SURFACE_SLOPE, SURFACE_CURVATURE, DELTA_SCALE)

    print(f"\n会话: {session.describe()}")
    # 不写死"= 390"：桶宽是可配的，写死会让这条检查在改桶宽时变成一个假警报，
    # 然后被人顺手改掉。改成校验真正的不变量 —— 桶必须**恰好铺满**会话，
    # 既不留余数（最后一截数据没有桶可落），也不重叠。
    passed &= check(
        "时间桶恰好铺满会话（无余数、无重叠）",
        session.bucket_count() * bucket_s == int(session.session_len_s()),
        f"{session.bucket_count()} 桶 × {bucket_s}s = "
        f"{session.bucket_count() * bucket_s}s / 会话 {int(session.session_len_s())}s",
    )
    passed &= check("到期日格式 YYYYMMDD", len(session.expiry_str()) == 8,
                    session.expiry_str())

    # ------------------------------------------------------------------ #
    # 构建 L2 / L3 / L4
    # ------------------------------------------------------------------ #
    store = TickStore(state_cfg, session)
    market = MarketState(store, state_cfg, session)
    engine = FeatureEngine(store, session, feat_cfg, serial_cfg)
    builder = PayloadBuilder(market, serial_cfg, session)

    expiry = session.expiry_str()
    each_side = loader.as_int(sub_cfg, "num_strikes_each_side", module="subscription")
    step = STRIKE_STEP
    base_spot = BASE_SPOT
    base_atm_iv = BASE_ATM_IV

    # ------------------------------------------------------------------ #
    # 推进 60 个会话分钟，每分钟推进一次完整流水线
    # ------------------------------------------------------------------ #
    print("\n推进 60 个会话分钟（每轮都跑完整流水线）...")
    open_epoch = session.session_open_dt().timestamp()
    bundles = []

    for minute in range(60):
        session_seconds = (minute + 1) * 60.0
        now = open_epoch + session_seconds
        spot = base_spot
        atm_iv = base_atm_iv
        strikes = surface.strike_grid(spot, step, each_side)

        for sub in range(4):
            ts = now + sub * 15.0
            store.on_spot_tick(SpotTick(price=spot, ts=ts))
            for strike in strikes:
                for right in (OptionRight.PUT, OptionRight.CALL):
                    is_put = right is OptionRight.PUT
                    iv = surface.iv_at(strike, spot, atm_iv)
                    # 共模抬升 + 偏斜变陡：模拟"恐慌逐渐积累"的真实形态，
                    # 也让热力图出现非零 ΔIV。
                    iv += 0.0002 * minute
                    iv += 0.00008 * minute * (1.0 if is_put else -1.0)
                    ref = OptionRef(strike=float(strike), right=right, expiry=expiry)
                    store.on_option_tick(
                        OptionTick(
                            ref=ref, iv=iv, ts=ts,
                            delta=surface.delta_for(strike, spot, is_put),
                            opt_price=max(
                                surface.iv_at(strike, spot, atm_iv) * spot * 0.008, 0.5
                            ),
                            und_price=spot, source_tick_type=13, model_greeks=True,
                        )
                    )
                    store.on_quote_tick(
                        QuoteTick(ref=ref, ts=ts, bid=1.0, ask=1.2, last=1.1)
                    )

        bundles.append(engine.compute(now=now + 59.0))

    print(f"  存储: {store.snapshot_meta()}")

    # 首桶没有任何"前值"可差分，但仍然必须产出结构化矩阵（行/列齐全、值为空），
    # 否则前端在第一分钟内会是一整块空白面板。
    first = bundles[0]
    passed &= check(
        "首轮即产出结构化空矩阵（行列齐全 / 0 有值格）",
        first.heatmap is not None
        and first.heatmap.rows() > 0
        and first.heatmap.cols() > 0
        and first.heatmap.filled_cells() == 0,
        f"{first.heatmap.rows() if first.heatmap else 0} 行 × "
        f"{first.heatmap.cols() if first.heatmap else 0} 列 / "
        f"{first.heatmap.filled_cells() if first.heatmap else 0} 有值格",
    )

    bundle = bundles[-1]
    now = open_epoch + 3600.0

    print(f"\n特征产出: spot={bundle.spot:.2f} cells={len(bundle.cells)} "
          f"ok={bundle.quality_ok} flagged={bundle.quality_flagged}")
    passed &= check("产生网格点", len(bundle.cells) > 0, f"{len(bundle.cells)} 个")
    passed &= check("产生热力图矩阵", bundle.heatmap is not None)
    passed &= check("产生 Skew 点", bundle.skew is not None)

    if bundle.heatmap is not None:
        hm = bundle.heatmap
        print(f"  热力图: {hm.rows()} 行 × {hm.cols()} 列, 有值格 {hm.filled_cells()}")
        passed &= check("矩阵有值", hm.filled_cells() > 0, f"{hm.filled_cells()} 格")

    if bundle.skew is not None:
        sk = bundle.skew
        print(f"  Skew: ATM IV={sk.atm_iv and sk.atm_iv * 100:.2f} "
              f"Put25={sk.put25_iv and sk.put25_iv * 100:.2f} "
              f"Call25={sk.call25_iv and sk.call25_iv * 100:.2f} "
              f"Skew25Δ={sk.skew_25d_vol_points}")
        print(f"  25Δ 定位: Put@{sk.put25_strike} Call@{sk.call25_strike} "
              f"(现价 {bundle.spot:.0f})")
        passed &= check("25Δ Skew 有定义", sk.skew_25d_vol_points is not None)
        passed &= check("Skew 为正值（左高右低）",
                        (sk.skew_25d_vol_points or 0) > 0,
                        f"{sk.skew_25d_vol_points}")
        passed &= check(
            "25Δ Put 行权价在现价下方",
            sk.put25_strike is not None and sk.put25_strike < bundle.spot,
            f"{sk.put25_strike} < {bundle.spot:.0f}",
        )
        passed &= check(
            "25Δ Call 行权价在现价上方",
            sk.call25_strike is not None and sk.call25_strike > bundle.spot,
            f"{sk.call25_strike} > {bundle.spot:.0f}",
        )
        passed &= check(
            "Delta 插值落在券商 Delta 上（未本地重算）",
            abs((sk.put25_delta or 0) + 0.25) < 1e-9
            and abs((sk.call25_delta or 0) - 0.25) < 1e-9,
        )

    if bundle.atm is not None:
        print(f"  ATM: 档位={bundle.atm.atm_strike} IV={bundle.atm.atm_iv and bundle.atm.atm_iv * 100:.2f} "
              f"跨式={bundle.atm.straddle_price}")
        passed &= check("ATM IV 已取同档 Put/Call 均值",
                        bundle.atm.atm_iv is not None)

    # ------------------------------------------------------------------ #
    # 回归：compute() 省略 now 时必须取会话时钟，而不是墙上时钟
    # ------------------------------------------------------------------ #
    # 这条曾经真实出过问题：compute() 默认调 core.clock.now_ts()（墙钟）。在
    # 推进过的会话里，墙钟会落在开盘之前，分桶全部钳到第 0 桶，于是热力图恒为
    # null、Skew 序列永远只有一个点。显式传 now 的调用路径掩盖了这个缺陷，
    # 所以这里必须用"不传 now"的方式断言。
    print("\n回归：默认时间源 = 注入的会话时钟")
    probe_store = TickStore(state_cfg, session)
    probe_engine = FeatureEngine(probe_store, session, feat_cfg, serial_cfg)
    probe_advance_s = 1800.0
    fake.advance(probe_advance_s)  # 把会话时间推到开盘后 30 分钟

    probe_ts = session.now_ts()
    probe_spot = base_spot
    probe_atm = base_atm_iv
    probe_store.on_spot_tick(SpotTick(price=probe_spot, ts=probe_ts))
    for strike in surface.strike_grid(probe_spot, step, each_side):
        for right in (OptionRight.PUT, OptionRight.CALL):
            is_put = right is OptionRight.PUT
            probe_ref = OptionRef(strike=float(strike), right=right, expiry=expiry)
            probe_store.on_option_tick(
                OptionTick(
                    ref=probe_ref,
                    iv=surface.iv_at(strike, probe_spot, probe_atm),
                    ts=probe_ts,
                    delta=surface.delta_for(strike, probe_spot, is_put),
                    opt_price=1.0,
                    und_price=probe_spot,
                    source_tick_type=13,
                    model_greeks=True,
                )
            )

    probe_bundle = probe_engine.compute()  # 关键：不传 now
    probe_bucket = probe_bundle.heatmap.bucket_index if probe_bundle.heatmap else None
    # 期望桶号由"推进了多少秒 ÷ 桶宽"推出，不写死 30 —— 桶宽一改，写死的数字
    # 就会变成假警报。墙钟路径给出的桶号与此相差极远，所以这条依然拦得住。
    expect_bucket = int(probe_advance_s // bucket_s)
    passed &= check(
        f"默认时间源取会话时钟（应落在第 {expect_bucket} 桶）",
        probe_bucket == expect_bucket,
        f"bucket_index={probe_bucket}（期望 {expect_bucket} = "
        f"{probe_advance_s / 60:.0f} 分钟 ÷ {bucket_s}s）",
    )
    passed &= check(
        "会话时钟生效后 Skew 写入独立时间桶",
        probe_bundle.skew is not None and probe_bundle.skew.skew_25d_vol_points is not None,
    )

    # ------------------------------------------------------------------ #
    # 回归：被判定为 GLITCH 的点绝不能进入热力图
    # ------------------------------------------------------------------ #
    # 曾经真实出过问题：热力图引擎与 Skew 引擎都只跳过 Quality.MISSING，
    # 于是毛刺过滤器拦下来的分母效应尖峰转头就被写进了矩阵（实测 32 个波动率
    # 点）。这里注入一个 ×10 尖峰，断言它既被标记为 GLITCH，又没进矩阵。
    print("\n回归：GLITCH 点不得进入热力图")
    glitch_store = TickStore(state_cfg, session)
    glitch_engine = FeatureEngine(glitch_store, session, feat_cfg, serial_cfg)

    flat_spot = base_spot
    flat_atm = base_atm_iv
    grid = surface.strike_grid(flat_spot, step, each_side)
    target_strike = grid[3]          # 现价下方，热力图会取它的 Put 一侧
    spike_multiplier = 10.0

    glitch_bundles = []
    for bucket in range(3):
        fake.advance(float(bucket_s))
        ts = session.now_ts()
        glitch_store.on_spot_tick(SpotTick(price=flat_spot, ts=ts))
        for strike in grid:
            for right in (OptionRight.PUT, OptionRight.CALL):
                is_put = right is OptionRight.PUT
                iv = surface.iv_at(strike, flat_spot, flat_atm)
                spiking = bucket == 2 and strike == target_strike and is_put
                if spiking:
                    iv *= spike_multiplier
                ref = OptionRef(strike=float(strike), right=right, expiry=expiry)
                glitch_store.on_option_tick(
                    OptionTick(
                        ref=ref, iv=iv, ts=ts,
                        delta=surface.delta_for(strike, flat_spot, is_put),
                        opt_price=max(iv * flat_spot * 0.008, 0.5),
                        und_price=flat_spot,
                        source_tick_type=13, model_greeks=True,
                    )
                )
        glitch_bundles.append(glitch_engine.compute())

    final = glitch_bundles[-1]
    spiked = [c for c in final.cells
              if c.strike == target_strike and c.right is OptionRight.PUT]
    passed &= check(
        "尖峰被标记为 GLITCH",
        bool(spiked) and spiked[0].quality.value == "glitch",
        f"quality={spiked[0].quality if spiked else '未找到该网格点'}",
    )

    naive_vol_points = abs(spiked[0].iv - flat_atm) * 100.0 if spiked else 0.0
    in_matrix = None
    if final.heatmap is not None:
        strikes_seq = list(final.heatmap.strikes)
        rights_seq = list(final.heatmap.rights)
        for row, (s, r) in enumerate(zip(strikes_seq, rights_seq)):
            if s == target_strike and r is OptionRight.PUT:
                in_matrix = final.heatmap.values[row][-1]
                break
    passed &= check(
        "尖峰未写入矩阵（该格应为 0 或空，而不是尖峰本身）",
        in_matrix is None or abs(in_matrix) < 1e-9,
        f"矩阵值={in_matrix}（若不拦截应约为 {naive_vol_points:.1f} 波动率点）",
    )

    # ------------------------------------------------------------------ #
    # 组装载荷
    # ------------------------------------------------------------------ #
    frame = builder.build(bundle, _status())
    payload = builder.latest_payload()
    passed &= check("载荷已生成", payload is not None)

    if payload is not None:
        text, seq = payload
        print(f"\n  帧 #{seq} JSON 长度 {len(text):,} 字节")
        parsed = json.loads(text)  # 非法 JSON 会在这里抛错
        passed &= check("JSON 可解析", isinstance(parsed, dict))
        passed &= check("含 heatmap 块", parsed.get("heatmap") is not None)
        passed &= check("含 skew 块", "series" in parsed.get("skew", {}))
        passed &= check("含 cells 明细", len(parsed.get("cells", [])) > 0,
                        f"{len(parsed.get('cells', []))} 条")
        passed &= check("无 NaN 字面量", "NaN" not in text)
        print(f"  顶层键: {sorted(parsed.keys())}")

    print()
    print("=" * 72)
    print("结果: " + ("全部通过" if passed else "存在失败项"))
    print("=" * 72)
    return 0 if passed else 1


def _status() -> FeedStatus:
    return FeedStatus(
        mode=FeedMode.LIVE, connection=ConnectionState.CONNECTED,
        subscribed=74, subscription_cap=92,
    )


if __name__ == "__main__":
    raise SystemExit(main())
