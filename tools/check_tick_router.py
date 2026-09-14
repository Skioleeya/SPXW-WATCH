"""回归：TickRouter 必须只采信券商推送的 IV 与 Greeks。

为什么需要这条检查
------------------
``acquisition/`` 是整个工程里**唯一从未被离线执行过**的层：模拟模式通过延迟
import 彻底绕开它，所以这一层的任何缺陷都只在实盘暴露。上一轮就因此漏掉了一个
致命问题（未 qualify 的合约在 ib_async 里连 hash 都过不了，订阅静默全废）。

本脚本用**忠实模拟** ib_async ``Ticker`` / ``OptionComputation`` 结构的假对象
把这一层跑起来，重点验证那条核心约束：

    严禁本地用 BSM 高频重算 —— 只读 tickType 13（MODEL_OPTION）。
    ``use_model_greeks`` 为真时，**必须拒绝**回退到 last/bid/ask 三档 greeks。

如果这条退化成"拿不到模型值就凑合用别的"，整个系统的 IV 就不再是券商口径，
而是混了别的东西，且不会有任何报错。

用法::

    python tools/check_tick_router.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.tick import OptionRef  # noqa: E402
from acquisition.tick_router import TickRouter  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

EXPIRY = "20260911"
SPOT_CON_ID = 999001


# --------------------------------------------------------------------------- #
# 忠实模拟 ib_async 的结构
# --------------------------------------------------------------------------- #

class FakeComputation:
    """对应 ``ib_async.OptionComputation``。"""

    __slots__ = ("tickAttrib", "impliedVol", "delta", "optPrice",
                 "pvDividend", "gamma", "vega", "theta", "undPrice")

    def __init__(self, implied_vol=None, delta=None, opt_price=None,
                 gamma=None, vega=None, theta=None, und_price=None) -> None:
        self.tickAttrib = 0
        self.impliedVol = implied_vol
        self.delta = delta
        self.optPrice = opt_price
        self.pvDividend = None
        self.gamma = gamma
        self.vega = vega
        self.theta = theta
        self.undPrice = und_price


class FakeContract:
    """对应 ``ib_async.Option`` / ``Index``（只保留 OptionRef 需要的字段）。"""

    __slots__ = ("conId", "symbol", "strike", "right",
                 "lastTradeDateOrContractMonth", "secType")

    def __init__(self, con_id=0, strike=None, right=None,
                 expiry=None, sec_type="OPT") -> None:
        self.conId = con_id
        self.symbol = "SPX"
        self.strike = strike
        self.right = right
        self.lastTradeDateOrContractMonth = expiry
        self.secType = sec_type


class FakeTicker:
    """对应 ``ib_async.Ticker``。"""

    __slots__ = ("contract", "modelGreeks", "lastGreeks", "bidGreeks",
                 "askGreeks", "bid", "ask", "last", "close",
                 "bidSize", "askSize", "lastSize", "_mark")

    def __init__(self, contract, mark=None) -> None:
        self.contract = contract
        self.modelGreeks = None
        self.lastGreeks = None
        self.bidGreeks = None
        self.askGreeks = None
        self.bid = None
        self.ask = None
        self.last = None
        self.close = None
        self.bidSize = None
        self.askSize = None
        self.lastSize = None
        self._mark = mark

    def marketPrice(self):
        # ib_async 在没有数据时返回 nan，这里保持一致。
        return self._mark if self._mark is not None else math.nan


class ExplodingTicker:
    """访问任何属性都抛异常，用于验证单条坏数据不会打断整批。"""

    def __getattr__(self, name):
        raise RuntimeError(f"模拟损坏的 ticker，访问 {name} 时炸掉")


class RecordingSink:
    """记录 TickSink 收到的内容。"""

    def __init__(self) -> None:
        self.options = []
        self.quotes = []
        self.spots = []
        self.status = []

    def on_option_tick(self, tick):
        self.options.append(tick)

    def on_quote_tick(self, tick):
        self.quotes.append(tick)

    def on_spot_tick(self, tick):
        self.spots.append(tick)

    def on_status(self, event):
        self.status.append(event)


# --------------------------------------------------------------------------- #
# 断言
# --------------------------------------------------------------------------- #

FAILURES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    """记一笔并打印。``FAILURES`` 是**失败计数** —— 与 ``run_*_checks()`` 的
    契约一致（返回失败数，供 ``selfcheck`` 累加），不是布尔。"""
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))


def option_ticker(strike=6500.0, right="C", con_id=111) -> FakeTicker:
    return FakeTicker(FakeContract(con_id=con_id, strike=strike,
                                   right=right, expiry=EXPIRY))


def build(use_model: bool):
    cfg = dict(loader.load("ibkr"))
    cfg["use_model_greeks"] = use_model
    sink = RecordingSink()
    router = TickRouter(sink, cfg)
    router.set_spot_con_id(SPOT_CON_ID)
    return router, sink


def run_tick_router_checks() -> int:
    """供 ``run.py --check``（``[14]``）调用的入口。返回**失败数**。

    ``--check`` 的约定：``run_*_checks() -> int`` 返回失败条数，由编排器累加。
    这里不用布尔，因为自检汇总的分母是"多少项不通过"。
    """
    global FAILURES
    FAILURES = 0
    print("=" * 72)
    print("TickRouter 回归（L1 采集层唯一被离线执行的一次）")
    print("=" * 72)

    # ------------------------------------------------------------------ #
    # 1. MODEL_OPTION（tick 13）正常路径
    # ------------------------------------------------------------------ #
    print("\n1.  MODEL_OPTION（tick 13）正常路径")
    router, sink = build(use_model=True)
    t = option_ticker()
    t.modelGreeks = FakeComputation(implied_vol=0.145, delta=0.52,
                                    opt_price=12.5, gamma=0.0011,
                                    vega=3.2, theta=-8.4, und_price=6500.0)
    t.bid, t.ask, t.last = 12.4, 12.6, 12.5
    t.bidSize, t.askSize, t.lastSize = 10, 12, 1

    routed = router.handle_tickers([t])
    check("推送了 1 条 tick", routed == 1, f"实际 {routed}")
    check("产出 OptionTick", len(sink.options) == 1)
    if sink.options:
        tick = sink.options[0]
        check("IV 取自 modelGreeks", abs(tick.iv - 0.145) < 1e-12, f"{tick.iv}")
        check("delta 取自 modelGreeks", abs(tick.delta - 0.52) < 1e-12, f"{tick.delta}")
        check("source_tick_type = 13", tick.source_tick_type == 13,
              str(tick.source_tick_type))
        check("model_greeks = True", tick.model_greeks is True)
        check("ref 解析正确",
              tick.ref == OptionRef(strike=6500.0, right="C", expiry=EXPIRY),
              tick.ref.label())
    check("同时产出 QuoteTick", len(sink.quotes) == 1)

    # ------------------------------------------------------------------ #
    # 2. 核心约束：要求模型值时必须拒绝降级来源
    # ------------------------------------------------------------------ #
    print("\n2.  核心约束：use_model_greeks=true 时拒绝回退")
    router, sink = build(use_model=True)
    t = option_ticker()
    t.lastGreeks = FakeComputation(implied_vol=0.145, delta=0.52)   # 只有非模型值
    routed = router.handle_tickers([t])
    check("拒绝 lastGreeks（不降级）", routed == 0 and not sink.options,
          f"routed={routed}, options={len(sink.options)}")
    check("计入 rejected", router.rejected == 1, str(router.rejected))

    router, sink = build(use_model=True)
    t = option_ticker()
    t.bidGreeks = FakeComputation(implied_vol=0.145)
    routed = router.handle_tickers([t])
    check("拒绝 bidGreeks（不降级）", routed == 0 and not sink.options,
          f"routed={routed}")

    # 模型值存在时，即使同时有 lastGreeks 也优先模型值
    router, sink = build(use_model=True)
    t = option_ticker()
    t.modelGreeks = FakeComputation(implied_vol=0.150)
    t.lastGreeks = FakeComputation(implied_vol=0.999)
    router.handle_tickers([t])
    check("模型值优先于 lastGreeks",
          bool(sink.options) and abs(sink.options[0].iv - 0.150) < 1e-12,
          f"{sink.options[0].iv if sink.options else None}")

    # ------------------------------------------------------------------ #
    # 3. 显式关闭模型值时才允许降级
    # ------------------------------------------------------------------ #
    print("\n3.  use_model_greeks=false 时才允许降级")
    router, sink = build(use_model=False)
    t = option_ticker()
    t.lastGreeks = FakeComputation(implied_vol=0.145, delta=0.48)
    routed = router.handle_tickers([t])
    check("允许使用 lastGreeks", routed == 1 and len(sink.options) == 1)
    if sink.options:
        check("source_tick_type = 12", sink.options[0].source_tick_type == 12,
              str(sink.options[0].source_tick_type))
        check("model_greeks = False", sink.options[0].model_greeks is False)

    # ------------------------------------------------------------------ #
    # 4. IV 越界与脏值一律拒绝
    # ------------------------------------------------------------------ #
    print("\n4.  IV 越界与脏值一律拒绝")
    max_iv = loader.as_float(loader.load("ibkr"), "max_iv", module="ibkr")
    cases = [
        ("IV 超过 max_iv", FakeComputation(implied_vol=max_iv + 0.5)),
        ("IV 低于 min_iv", FakeComputation(implied_vol=0.0001)),
        ("IV 为 0", FakeComputation(implied_vol=0.0)),
        ("IV 为 None", FakeComputation(implied_vol=None)),
        ("IV 为 NaN", FakeComputation(implied_vol=float("nan"))),
        ("IV 为 inf", FakeComputation(implied_vol=float("inf"))),
    ]
    for label, comp in cases:
        router, sink = build(use_model=True)
        t = option_ticker()
        t.modelGreeks = comp
        routed = router.handle_tickers([t])
        check(f"{label} → 拒绝", routed == 0 and not sink.options, f"routed={routed}")

    # NaN 的 delta 应当被归一化成 None，而不是漏进 DTO
    router, sink = build(use_model=True)
    t = option_ticker()
    t.modelGreeks = FakeComputation(implied_vol=0.145, delta=float("nan"),
                                    gamma=float("inf"))
    router.handle_tickers([t])
    check("NaN / inf 的 Greeks 归一化为 None",
          bool(sink.options) and sink.options[0].delta is None
          and sink.options[0].gamma is None,
          f"delta={sink.options[0].delta if sink.options else '?'}")

    # ------------------------------------------------------------------ #
    # 5. 标的 tick 分流
    # ------------------------------------------------------------------ #
    print("\n5.  标的 tick 分流")
    router, sink = build(use_model=True)
    spot = FakeTicker(FakeContract(con_id=SPOT_CON_ID, sec_type="IND"), mark=6500.5)
    router.handle_tickers([spot])
    check("识别为标的并推送 SpotTick", len(sink.spots) == 1)
    if sink.spots:
        check("现价取自 marketPrice()", abs(sink.spots[0].price - 6500.5) < 1e-12,
              f"{sink.spots[0].price}")

    router, sink = build(use_model=True)
    spot = FakeTicker(FakeContract(con_id=SPOT_CON_ID, sec_type="IND"))  # mark=nan
    spot.bid, spot.ask = 6499.5, 6500.5
    router.handle_tickers([spot])
    check("marketPrice 为 NaN 时回退到盘口中间价",
          bool(sink.spots) and abs(sink.spots[0].price - 6500.0) < 1e-12,
          f"{sink.spots[0].price if sink.spots else '?'}")

    # ------------------------------------------------------------------ #
    # 6. 坏数据不能打断整批
    # ------------------------------------------------------------------ #
    print("\n6.  单条坏数据不得打断整批")
    router, sink = build(use_model=True)
    good_a = option_ticker(strike=6495.0, con_id=201)
    good_a.modelGreeks = FakeComputation(implied_vol=0.14)
    good_b = option_ticker(strike=6505.0, con_id=202)
    good_b.modelGreeks = FakeComputation(implied_vol=0.15)

    routed = router.handle_tickers([good_a, ExplodingTicker(), good_b])
    check("坏数据被跳过，其余照常推送", routed == 2 and len(sink.options) == 2,
          f"routed={routed}, options={len(sink.options)}")
    check("坏数据计入 rejected", router.rejected == 1, str(router.rejected))

    # ------------------------------------------------------------------ #
    # 7. 非期权非标的的 ticker 应被安静忽略
    # ------------------------------------------------------------------ #
    print("\n7.  无关 ticker 安静忽略")
    router, sink = build(use_model=True)
    junk = FakeTicker(FakeContract(con_id=555, sec_type="STK"))  # 没有 strike/right
    routed = router.handle_tickers([junk])
    check("无关 ticker 不推送、不计为 rejected",
          routed == 0 and not sink.options and router.rejected == 0,
          f"routed={routed}, rejected={router.rejected}")

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if not FAILURES
          else f"{RED}结果: {FAILURES} 项不通过{RESET}")
    print("=" * 72)
    return FAILURES


def main() -> int:
    """手动单跑：``python tools/check_tick_router.py``。返回进程退出码。"""
    return 1 if run_tick_router_checks() else 0


if __name__ == "__main__":
    raise SystemExit(main())
