"""
时钟协议与裁剪路径检查（**不属于任何运行时层**）。
====================================================

唯一职责：校验**注入的时间源**这条链真的通 —— 时间源满足 ``ClockPort``，
且状态层的裁剪真的按注入的时钟走。

对应项目硬性要求第 4 条（严格分层单向依赖）的运行时侧：L3 拿到的"现在"必须
是**组装层注入**的那个时间源，而不是它自己去调 ``time.time()``。

为什么要单独一条检查
--------------------
``SessionClock`` 曾经只提供 ``now_ts()``、没有实现 ``ClockPort.now()``。后果
极其隐蔽：``TickStore.prune()`` 里那句 ``self._clock.now()`` 每 10 秒抛一次
``AttributeError``，被维护循环的 ``except Exception`` 吞成一行 warning。表现出
来只是"按时间窗裁剪从未真正发生" —— 缓冲区只靠 ``maxlen`` 兜底，
``option_buffer_seconds`` 这个配置项形同虚设。**而当时所有探针、所有回归都是绿的。**

这类缺陷的形状是"两套实现给出同一个可观测结果"，所以判据必须能**区分**它们：

* 用注入的时钟（锚在未来）⇒ 推进后样本过期 ⇒ ``prune()`` 丢弃；
* 用墙钟（锚在未来）⇒ 墙钟 cutoff 切不到未来样本 ⇒ ``prune()`` 丢弃 0 条。

本检查**内建这两条对照**（而不是只靠 ``--selftest`` 的变异）：判据若不能区分
两种实现，它就不是判据。这也是"非空转"的最直接证据 —— 直接印在输出里。

运行::

    python tools/selfcheck_clock.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import loader  # noqa: E402
from contracts.enums import OptionRight  # noqa: E402
from contracts.ports import ClockPort  # noqa: E402
from contracts.tick import OptionRef, OptionTick, SpotTick  # noqa: E402
from core.clock import SessionClock, WallClock  # noqa: E402
from state.tick_store import TickStore  # noqa: E402
from tools.fixtures import FakeClock, make_session_clock  # noqa: E402
from tools.selfcheck_core import fail, ok  # noqa: E402

STRIKE = 6500.0


def _feed_one_sample(store: TickStore, expiry: str, ts: float) -> None:
    """往 store 里推一组最小可用的样本（现价 + 一个期权）。"""
    store.on_spot_tick(SpotTick(price=STRIKE, ts=ts))
    store.on_option_tick(
        OptionTick(
            ref=OptionRef(strike=STRIKE, right=OptionRight.PUT, expiry=expiry),
            iv=0.14, ts=ts, delta=-0.5, opt_price=10.0,
            und_price=STRIKE, source_tick_type=13, model_greeks=True,
        )
    )


def run_clock_checks() -> int:
    """供 ``--check`` 调用的入口。返回**失败条数**。

    ⚠️ **标题必须由本函数打印，不能只在 ``main()`` 里打**：``--selftest`` 按段落
    编号定位"目标检查项自己那一段"来判断是否变红（见 ``selfcheck.py`` 的
    ``_section_failed``）。标题不在这里，那一段就切不出来，变异判据会**恒判为
    抓住** —— 即这条检查的非空转证明是假的。
    """
    print("\n[12] 时钟协议与裁剪路径")
    app_cfg = loader.load("app")
    serial_cfg = loader.load("serialization")
    state_cfg = loader.load("state")

    option_age = loader.as_float(state_cfg, "option_buffer_seconds", module="state")
    spot_age = loader.as_float(state_cfg, "spot_buffer_seconds", module="state")
    stale_s = max(option_age, spot_age) + 60.0

    failures = 0
    session, fake = make_session_clock(app_cfg, serial_cfg)
    print(f"  锚定交易日 {session.trading_day().isoformat()} · "
          f"{session.bucket_count()} 桶 × {session.bucket_seconds}s · "
          f"到期日 {session.expiry_str()}")

    # ------------------------------------------------------------------ #
    # 1. 三个时间源都必须满足 ClockPort
    # ------------------------------------------------------------------ #
    for name, source in (
        ("WallClock", WallClock()),
        ("FakeClock", fake),
        ("SessionClock", session),
    ):
        # ⚠️ 不用 isinstance 单判：``runtime_checkable`` 的 Protocol 只检查
        # **方法是否存在**，一个把 now() 改名成 now_broken() 的类会干净地通过
        # 类型检查、然后在运行期炸。所以显式再核一次可调用性。
        if isinstance(source, ClockPort) and callable(getattr(source, "now", None)):
            ok(f"{name} 满足 ClockPort")
        else:
            fail(f"{name} 不满足 ClockPort（缺少可调用的 now()）"
                 f"—— 注入它之后 prune() 会抛 AttributeError")
            failures += 1

    # ------------------------------------------------------------------ #
    # 2. 真实裁剪路径：注入的时钟必须真的驱动 prune()
    # ------------------------------------------------------------------ #
    store = TickStore(state_cfg, session)
    ts0 = session.now_ts()
    _feed_one_sample(store, session.expiry_str(), ts0)

    fake.advance(stale_s)
    try:
        dropped = store.prune()
    except AttributeError as exc:
        fail(f"prune() 抛 AttributeError: {exc} —— 注入的时钟没实现 ClockPort.now()")
        return failures + 1

    remaining = store.snapshot_meta()
    left = remaining["option_points"] + remaining["spot_points"]
    if dropped <= 0:
        fail("裁剪没有丢弃任何样本 —— 时间窗没有生效（时钟读数可能不对）")
        failures += 1
    elif left:
        fail(f"过期样本仍在缓冲区里（期权 {remaining['option_points']} / "
             f"现价 {remaining['spot_points']}）")
        failures += 1
    else:
        ok(f"注入时钟驱动裁剪：推进 {stale_s:.0f}s 后丢弃 {dropped} 条，"
           f"缓冲区已空 ⇒ option_buffer_seconds 真实生效")

    # ------------------------------------------------------------------ #
    # 3. 内建反证：判据必须能区分"注入时钟"与"墙钟回落"
    # ------------------------------------------------------------------ #
    # 同样喂一组**未来时刻**的样本，但把墙钟当时间源。墙钟的 cutoff 落在当下，
    # 切不到未来样本 ⇒ dropped 必为 0。若这一条也丢样本，说明上面那条判据其实
    # 区分不出两种实现（即它是空的）。
    control = TickStore(state_cfg, WallClock())
    _feed_one_sample(control, session.expiry_str(), session.now_ts())
    control_dropped = control.prune()
    if control_dropped == 0:
        ok("反证：同一组未来样本用墙钟裁剪 ⇒ 丢弃 0 条 ⇒ 上一条判据确实在验"
           "「注入的时钟」而非「墙钟」")
    else:
        fail(f"反证失败：墙钟也丢弃了 {control_dropped} 条 —— 上一条判据无法区分"
             f"两种实现，等于空转（夹具锚定日可能落在过去）")
        failures += 1

    # ------------------------------------------------------------------ #
    # 4. L8 依赖的裁剪节奏属性
    # ------------------------------------------------------------------ #
    pace = store.prune_interval_s
    if isinstance(pace, float) and pace > 0:
        ok(f"prune_interval_s = {pace:g}s（L8 维护循环按它驱动裁剪）")
    else:
        fail(f"prune_interval_s 不是正数（收到 {pace!r}）—— 维护循环无法定节奏")
        failures += 1

    # ------------------------------------------------------------------ #
    # 5. 网格契约：桶序号与区段表必须自洽（前端横轴与 L8 都依赖）
    # ------------------------------------------------------------------ #
    zones = session.zone_ranges()
    index = session.bucket_index()
    if not zones:
        fail("区段表为空 —— 前端无法切 GTH/RTH，热力图横轴也没有区段信息")
        failures += 1
    elif not (0 <= index < session.bucket_count()):
        fail(f"bucket_index() = {index} 越界（bucket_count = "
             f"{session.bucket_count()}）")
        failures += 1
    else:
        first, last = zones[0]["first"], zones[-1]["last"]
        if first != 0 or last != session.bucket_count() - 1:
            fail(f"区段表没有铺满网格：首桶 {first} / 末桶 {last}，"
                 f"应为 0 / {session.bucket_count() - 1}")
            failures += 1
        else:
            ok(f"{len(zones)} 个区段首尾相接铺满 {session.bucket_count()} 桶，"
               f"当前落在 {session.current_zone_id()!r}（桶 {index}）")

    return failures


def main() -> int:
    failures = run_clock_checks()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
