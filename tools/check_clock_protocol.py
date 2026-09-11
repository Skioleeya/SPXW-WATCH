"""回归：注入下层的时间源必须满足 L0 的 ClockPort。

背景：``TickStore`` / ``MarketState`` / ``FeatureEngine`` 拿到的"时钟"是组装层
注入的 ``SessionClock``，而不是 ``WallClock``。但 ``SessionClock`` 曾经只提供
``now_ts()``，没有实现 ``contracts.ports.ClockPort`` 要求的 ``now()``。

后果很隐蔽：``TickStore.prune()`` 里那句 ``self._clock.now()`` 每 10 秒抛一次
``AttributeError``，被 L6 维护循环的 ``except Exception`` 吞成一行 warning 日志。
表现出来只是"按时间窗裁剪从未真正发生"——缓冲区只靠 maxlen 兜底，
``option_buffer_seconds`` 这个配置项形同虚设。而所有探针、所有回归都是绿的。

这个脚本做两件事：
  1. 断言三个时间源都满足 ``ClockPort``；
  2. 用真实的 ``SessionClock`` 注入 ``TickStore``，走一遍真实裁剪路径，
     断言过期样本确实被丢掉（而不是抛异常后被吞掉）。

用法::

    python tools/check_clock_protocol.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import OptionRight  # noqa: E402
from contracts.ports import ClockPort  # noqa: E402
from contracts.tick import OptionRef, OptionTick, SpotTick  # noqa: E402
from core.clock import SessionClock, WallClock  # noqa: E402
from simulator.sim_clock import SimClock  # noqa: E402
from state.tick_store import TickStore  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

STRIKE = 6500.0


def main() -> int:
    app_cfg = loader.load("app")
    serial_cfg = loader.load("serialization")
    state_cfg = loader.load("state")

    tz = loader.as_str(app_cfg, "timezone", module="app")
    open_hm = loader.as_str(app_cfg, "session_open", module="app")
    close_hm = loader.as_str(app_cfg, "session_close", module="app")
    bucket_s = loader.as_int(serial_cfg, "heatmap_bucket_seconds", module="serialization")
    option_age = loader.as_float(state_cfg, "option_buffer_seconds", module="state")
    spot_age = loader.as_float(state_cfg, "spot_buffer_seconds", module="state")

    failures = 0

    # ---------------------------------------------------------------- #
    # 1. 三个时间源都必须满足 ClockPort
    # ---------------------------------------------------------------- #
    print("[1] 时间源的协议一致性")
    sim_clock = SimClock(tz, open_hm, speedup=1.0)
    session = SessionClock(tz, open_hm, close_hm, bucket_s, clock=sim_clock)

    for name, source in (
        ("WallClock", WallClock()),
        ("SimClock", sim_clock),
        ("SessionClock", session),
    ):
        if isinstance(source, ClockPort):
            print(f"  {GREEN}[ok]{RESET} {name} 满足 ClockPort")
        else:
            missing = [m for m in ("now",) if not hasattr(source, m)]
            print(f"  {RED}[FAIL]{RESET} {name} 不满足 ClockPort，缺少 {missing}")
            failures += 1

    # ---------------------------------------------------------------- #
    # 2. 真实裁剪路径：SessionClock 注入 TickStore，prune() 必须真的丢掉过期样本
    # ---------------------------------------------------------------- #
    print("\n[2] L2 用注入的时钟裁剪")
    store = TickStore(state_cfg, session)
    expiry = session.expiry_str()
    ref = OptionRef(strike=STRIKE, right=OptionRight.PUT, expiry=expiry)

    ts0 = session.now_ts()
    store.on_spot_tick(SpotTick(price=STRIKE, ts=ts0))
    store.on_option_tick(
        OptionTick(
            ref=ref, iv=0.14, ts=ts0, delta=-0.5, opt_price=10.0,
            und_price=STRIKE, source_tick_type=13, model_greeks=True,
        )
    )
    print(f"  写入 1 个现价样本 + 1 个期权样本（ts={ts0:.1f}）")

    # 推进到远超两个缓冲窗口
    sim_clock.advance(max(option_age, spot_age) + 60.0)
    print(f"  会话时间推进 {max(option_age, spot_age) + 60.0:.0f}s "
          f"（现价窗 {spot_age:.0f}s / 期权窗 {option_age:.0f}s）")

    try:
        dropped = store.prune()
    except AttributeError as exc:
        print(f"  {RED}[FAIL]{RESET} prune() 抛 AttributeError: {exc}")
        print("         —— 注入的时钟没有实现 ClockPort.now()")
        return 1

    remaining = store.snapshot_meta()
    option_points = remaining["option_points"]
    spot_points = remaining["spot_points"]
    print(f"  prune() 丢弃 {dropped} 个样本；剩余 期权 {option_points} / 现价 {spot_points}")

    if dropped <= 0:
        print(f"  {RED}[FAIL]{RESET} 裁剪没有丢弃任何样本，"
              f"说明时间窗没有生效（时钟读数可能不对）")
        failures += 1
    elif option_points or spot_points:
        print(f"  {RED}[FAIL]{RESET} 过期样本仍在缓冲区里"
              f"（期权 {option_points} / 现价 {spot_points}）")
        failures += 1
    else:
        print(f"  {GREEN}[ok]{RESET} 过期样本已按时间窗裁掉，裁剪节奏参数真实生效")

    print()
    if failures:
        print(f"{RED}结果: {failures} 项不通过{RESET}")
        return 1
    print(f"{GREEN}结果: 全部通过{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
