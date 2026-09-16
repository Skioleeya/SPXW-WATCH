"""
TickRouter 语义检查（**不属于任何运行时层**）。
================================================

唯一职责：把 ``acquisition/`` 那一层**离线跑起来**，验证它只采信券商推送的
IV 与 Greeks，且各类脏值都被正确处置。

为什么必须离线跑它
------------------
``acquisition/`` 是整个工程里**唯一无法在离线回归里被完整执行**的层（真链路要
连 IB Gateway）。因此这一层的缺陷只在实盘暴露 —— 上一轮就漏掉过一个致命问题
（未 qualify 的合约在 ``ib_async`` 里连 hash 都过不了，订阅静默全废）。

本检查用**忠实模拟** ``ib_async`` 结构的替身（见 ``tools/fixtures.py``）把这一层
跑起来，重点守住那条核心约束：

    严禁本地用 BSM 高频重算 —— 只读 tickType 13（MODEL_OPTION）。
    ``use_model_greeks`` 为真时，**必须拒绝**回退到 last/bid/ask 三档 greeks。

这条一旦退化成"拿不到模型值就凑合用别的"，系统的 IV 就不再是券商口径，而是混了
别的东西 —— 且**不会有任何报错**。

覆盖边界（诚实声明）
--------------------
本检查验证的是**归一化语义**（哪些来源被接受、脏值如何处置、ticker 如何分流），
不验证与 IBKR 的真实握手、合约解析、订阅限速 —— 那些需要活链路，见
``tools/selfcheck_connectivity.py`` 与 ``spxw-live-verify``。

运行::

    python tools/selfcheck_router.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from acquisition.tick_router import TickRouter  # noqa: E402
from config import loader  # noqa: E402
from contracts.tick import OptionRef  # noqa: E402
from tools.fixtures import (  # noqa: E402
    ExplodingTicker,
    FakeComputation,
    RecordingSink,
    make_index_ticker,
    make_option_ticker,
)
from tools.selfcheck_core import fail, ok  # noqa: E402

EXPIRY = "20300101"
SPOT_CON_ID = 999001
FUTURE_CON_ID = 888001
FUTURE_EXPIRY = "20300315"

_FAILURES = 0


def _check(label: str, condition: bool, detail: str = "") -> None:
    """记一笔并打印。失败计数与 ``run_*_checks()`` 的契约一致（返回失败条数）。"""
    global _FAILURES
    if not condition:
        _FAILURES += 1
    (ok if condition else fail)(label + (f"  {detail}" if detail else ""))


def _build(use_model: bool, *, with_future: bool = False):
    """按指定 ``use_model_greeks`` 造一个 router + 记录型 sink。"""
    cfg = dict(loader.load("ibkr"))
    cfg["use_model_greeks"] = use_model
    sink = RecordingSink()
    router = TickRouter(sink, cfg, future_sink=sink if with_future else None)
    router.set_spot_con_id(SPOT_CON_ID)
    if with_future:
        router.set_future_contracts({FUTURE_CON_ID: FUTURE_EXPIRY})
    return router, sink


def run_router_checks() -> int:
    """供 ``--check`` 调用的入口。返回**失败条数**。

    ⚠️ **标题必须由本函数打印**（理由见 ``selfcheck_clock.run_clock_checks``）：
    ``--selftest`` 按段落编号定位目标检查项，标题不在这里就切不出那一段，
    变异判据会恒判为抓住。
    """
    global _FAILURES
    _FAILURES = 0
    print("\n[14] TickRouter 语义（L2 唯一被离线执行的一次）")

    max_iv = loader.as_float(loader.load("ibkr"), "max_iv", module="ibkr")
    min_iv = loader.as_float(loader.load("ibkr"), "min_iv", module="ibkr")

    # ------------------------------------------------------------------ #
    # 1. MODEL_OPTION（tick 13）正常路径
    # ------------------------------------------------------------------ #
    router, sink = _build(use_model=True)
    ticker = make_option_ticker(6500.0, "C", EXPIRY, 111)
    ticker.modelGreeks = FakeComputation(
        implied_vol=0.145, delta=0.52, opt_price=12.5,
        gamma=0.0011, vega=3.2, theta=-8.4, und_price=6500.0,
    )
    ticker.bid, ticker.ask, ticker.last = 12.4, 12.6, 12.5
    ticker.bidSize, ticker.askSize, ticker.lastSize = 10, 12, 1

    routed = router.handle_tickers([ticker])
    _check("推送 1 条 tick", routed == 1, f"实际 {routed}")
    _check("产出 OptionTick", len(sink.options) == 1)
    if sink.options:
        tick = sink.options[0]
        _check("IV 取自 modelGreeks", abs(tick.iv - 0.145) < 1e-12, f"{tick.iv}")
        _check("delta 取自 modelGreeks", abs(tick.delta - 0.52) < 1e-12,
               f"{tick.delta}")
        _check("source_tick_type = 13", tick.source_tick_type == 13,
               str(tick.source_tick_type))
        _check("model_greeks = True", tick.model_greeks is True)
        _check("ref 解析正确",
               tick.ref == OptionRef(strike=6500.0, right="C", expiry=EXPIRY),
               tick.ref.label())
    _check("同时产出 QuoteTick（盘口另走一路）", len(sink.quotes) == 1)

    # ------------------------------------------------------------------ #
    # 2. 核心约束：要求模型值时必须拒绝降级来源
    # ------------------------------------------------------------------ #
    for attr in ("lastGreeks", "bidGreeks", "askGreeks"):
        router, sink = _build(use_model=True)
        ticker = make_option_ticker(6500.0, "C", EXPIRY, 111)
        setattr(ticker, attr, FakeComputation(implied_vol=0.145, delta=0.52))
        routed = router.handle_tickers([ticker])
        _check(f"拒绝 {attr}（不降级）",
               routed == 0 and not sink.options and router.rejected == 1,
               f"routed={routed}, rejected={router.rejected}")

    # 模型值存在时，即使同时有 lastGreeks 也优先模型值
    router, sink = _build(use_model=True)
    ticker = make_option_ticker(6500.0, "C", EXPIRY, 111)
    ticker.modelGreeks = FakeComputation(implied_vol=0.150)
    ticker.lastGreeks = FakeComputation(implied_vol=0.999)
    router.handle_tickers([ticker])
    _check("模型值优先于 lastGreeks",
           bool(sink.options) and abs(sink.options[0].iv - 0.150) < 1e-12,
           f"{sink.options[0].iv if sink.options else None}")

    # ------------------------------------------------------------------ #
    # 3. 显式关闭模型值时才允许降级
    # ------------------------------------------------------------------ #
    router, sink = _build(use_model=False)
    ticker = make_option_ticker(6500.0, "C", EXPIRY, 111)
    ticker.lastGreeks = FakeComputation(implied_vol=0.145, delta=0.48)
    routed = router.handle_tickers([ticker])
    _check("允许使用 lastGreeks", routed == 1 and len(sink.options) == 1)
    if sink.options:
        _check("source_tick_type = 12", sink.options[0].source_tick_type == 12,
               str(sink.options[0].source_tick_type))
        _check("model_greeks = False", sink.options[0].model_greeks is False)

    # ------------------------------------------------------------------ #
    # 4. IV 越界与脏值一律拒绝
    # ------------------------------------------------------------------ #
    dirty = [
        ("IV 超过 max_iv", FakeComputation(implied_vol=max_iv + 0.5)),
        ("IV 低于 min_iv", FakeComputation(implied_vol=min_iv / 2.0)),
        ("IV 为 0", FakeComputation(implied_vol=0.0)),
        ("IV 为 None", FakeComputation(implied_vol=None)),
        ("IV 为 NaN", FakeComputation(implied_vol=float("nan"))),
        ("IV 为 inf", FakeComputation(implied_vol=float("inf"))),
    ]
    for label, comp in dirty:
        router, sink = _build(use_model=True)
        ticker = make_option_ticker(6500.0, "C", EXPIRY, 111)
        ticker.modelGreeks = comp
        routed = router.handle_tickers([ticker])
        _check(f"{label} → 拒绝",
               routed == 0 and not sink.options and router.rejected == 1,
               f"routed={routed}")

    # NaN / inf 的 Greeks 归一化成 None，而不是漏进 DTO
    router, sink = _build(use_model=True)
    ticker = make_option_ticker(6500.0, "C", EXPIRY, 111)
    ticker.modelGreeks = FakeComputation(implied_vol=0.145,
                                         delta=float("nan"),
                                         gamma=float("inf"))
    router.handle_tickers([ticker])
    _check("NaN / inf 的 Greeks 归一化为 None",
           bool(sink.options) and sink.options[0].delta is None
           and sink.options[0].gamma is None,
           f"delta={sink.options[0].delta if sink.options else '?'}")

    # ------------------------------------------------------------------ #
    # 5. 三类 ticker 的分流
    # ------------------------------------------------------------------ #
    router, sink = _build(use_model=True)
    router.handle_tickers([make_index_ticker(SPOT_CON_ID, mark=6500.5)])
    _check("指数识别为标的并推送 SpotTick", len(sink.spots) == 1)
    if sink.spots:
        _check("现价取自 marketPrice()",
               abs(sink.spots[0].price - 6500.5) < 1e-12, f"{sink.spots[0].price}")

    router, sink = _build(use_model=True)
    spot = make_index_ticker(SPOT_CON_ID)          # marketPrice() 为 nan
    spot.bid, spot.ask = 6499.5, 6500.5
    router.handle_tickers([spot])
    _check("marketPrice 为 NaN 时回退到盘口中间价",
           bool(sink.spots) and abs(sink.spots[0].price - 6500.0) < 1e-12,
           f"{sink.spots[0].price if sink.spots else '?'}")

    # 期货：**不进** TickSink，只走显式注入的 future_sink
    router, sink = _build(use_model=True, with_future=True)
    future = make_index_ticker(FUTURE_CON_ID, mark=6520.25)
    future.contract.secType = "FUT"
    routed = router.handle_tickers([future])
    _check("期货进 future_sink", routed == 1 and len(sink.futures) == 1,
           f"routed={routed}, futures={len(sink.futures)}")
    _check("期货不进 TickSink（不污染 L3）",
           not sink.options and not sink.spots,
           f"options={len(sink.options)}, spots={len(sink.spots)}")
    if sink.futures:
        _check("期货带 IBKR 给的到期日（不自行推算）",
               sink.futures[0].expiry == FUTURE_EXPIRY, sink.futures[0].expiry)

    # 未注入 future_sink 时，期货被安静忽略（既有回归不传该参数）
    router, sink = _build(use_model=True)
    routed = router.handle_tickers([make_index_ticker(FUTURE_CON_ID, mark=6520.25)])
    _check("未注入 future_sink 时期货被忽略且不计 rejected",
           routed == 0 and not sink.spots and router.rejected == 0,
           f"routed={routed}, rejected={router.rejected}")

    # ------------------------------------------------------------------ #
    # 6. 坏数据不得打断整批
    # ------------------------------------------------------------------ #
    router, sink = _build(use_model=True)
    good_a = make_option_ticker(6495.0, "C", EXPIRY, 201)
    good_a.modelGreeks = FakeComputation(implied_vol=0.14)
    good_b = make_option_ticker(6505.0, "C", EXPIRY, 202)
    good_b.modelGreeks = FakeComputation(implied_vol=0.15)
    routed = router.handle_tickers([good_a, ExplodingTicker(), good_b])
    _check("坏数据被跳过，其余照常推送",
           routed == 2 and len(sink.options) == 2,
           f"routed={routed}, options={len(sink.options)}")
    _check("坏数据计入 rejected", router.rejected == 1, str(router.rejected))

    # ------------------------------------------------------------------ #
    # 7. 无关 ticker 安静忽略（既不是错误，也不该计入 rejected）
    # ------------------------------------------------------------------ #
    router, sink = _build(use_model=True)
    junk = make_index_ticker(555)                  # 未知 conId 的股票
    junk.contract.secType = "STK"
    routed = router.handle_tickers([junk])
    _check("无关 ticker 不推送、不计为 rejected",
           routed == 0 and not sink.options and router.rejected == 0,
           f"routed={routed}, rejected={router.rejected}")

    return _FAILURES


def main() -> int:
    failures = run_router_checks()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
