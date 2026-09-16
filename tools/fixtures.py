"""
工具夹具（**不属于任何运行时层**）。
=====================================

唯一职责：为离线检查提供**确定性的替身** —— 可推进的时钟、忠实模拟 ``ib_async``
的 ticker 结构、记录型 sink。

为什么集中在一个文件
--------------------
``[12]``（时钟协议）与 ``[14]``（TickRouter）都要"把真实运行时组件离线跑起来"，
两者需要同一套替身。分开写两份就会分叉 —— 改了一处、另一处还是旧行为，于是
两条检查对同一类对象给出不同结论，而**都不会报错**。

⚠️ 夹具的目标是**忠实**，不是**方便**
------------------------------------
``FakeTicker`` / ``FakeComputation`` 逐字段对齐 ``ib_async`` 的真实结构：

* 四个独立的 computation 槽位（``modelGreeks`` / ``lastGreeks`` / ``bidGreeks``
  / ``askGreeks``）—— 缺一个，``[14]`` 的"拒绝降级"判据就永远测不到；
* ``marketPrice()`` 在无数据时返回 ``nan``（不是 ``None``）—— 这是 ``ib_async``
  的真实行为，夹具若返回 ``None``，就把一条需要覆盖的分支悄悄变成另一条；
* ``__slots__`` 照抄 —— 访问不存在的属性会像真对象一样抛 ``AttributeError``，
  而不是静默返回 ``None``。

同理，``FakeClock`` 冻结在一个**固定的工作日**上。用"当前时间"当基准的夹具
会在跨午夜、周末、以及会话边界上给出不确定的结果（同一个检查今天绿明天红），
那种红既不能归因也不能复现。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from config import loader


def _next_weekday(day: date) -> date:
    """向后找到第一个工作日（网格只定义在周一至周五）。"""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


#: 夹具锚定的交易日。**刻意写死且刻意取远期**，两个理由都不是"随便挑一个"：
#:
#: 1. **确定性** —— 用"今天"当锚，同一个检查会在周末、跨午夜、会话边界上给出
#:    不同结果，那种失败无法复现也无法归因。
#: 2. ⚠️ **必须落在墙钟之后**，否则 ``[12]`` 的裁剪判据会退化成空转：
#:    ``TickStore.prune()`` 若忽略注入的时钟而回落到墙钟，在"锚在过去"的夹具下
#:    算出的 cutoff 依然会切掉样本，判据照旧全绿 —— 两种实现给出相同结论的
#:    判据，等于没判。锚在未来时，墙钟 cutoff 切不到未来样本，判据立刻变红。
ANCHOR_DAY = _next_weekday(date(2030, 1, 1))

#: 锚定时刻：网格起点 + 这个偏移。取 6 小时是为了让"当前时刻"落在 GTH 段中间，
#: 前后都有已走满的桶 —— 落在第 0 桶附近时，任何"跨桶"判据都会退化成空转。
ANCHOR_OFFSET_S = 6 * 3600.0


# --------------------------------------------------------------------------- #
# 时钟
# --------------------------------------------------------------------------- #


class FakeClock:
    """可推进的确定性时钟（实现 ``contracts.ports.ClockPort``）。"""

    __slots__ = ("_ts",)

    def __init__(self, ts: float) -> None:
        self._ts = float(ts)

    def now(self) -> float:
        return self._ts

    def advance(self, seconds: float) -> float:
        """把时钟向前推 ``seconds`` 秒，返回新时刻。"""
        self._ts += float(seconds)
        return self._ts

    def rewind(self, seconds: float) -> float:
        self._ts -= float(seconds)
        return self._ts


def make_session_clock(
    app_cfg: dict,
    serial_cfg: dict,
    *,
    day: date | None = None,
    offset_s: float = ANCHOR_OFFSET_S,
) -> tuple[object, FakeClock]:
    """
    构造一个**冻结在已知时刻**的 ``SessionClock``，连同驱动它的 ``FakeClock``。

    返回 ``(session, fake)``；``session`` 的时间源就是 ``fake``，因此
    ``fake.advance(...)`` 之后 ``session`` 的桶序号、区段、``elapsed_s`` 全部
    跟着走 —— 这正是"把一个交易日压进几毫秒跑完"的落点。

    实现顺序说明：先用墙上时钟建一个**只用来算几何**的实例，读出锚定日的网格
    起点，再用那个时刻建 ``FakeClock`` 并重建。反过来（先建 FakeClock 再问几何）
    会陷入"要先知道起点才能设时钟、要先有时钟才能算起点"的循环。
    """
    from core.clock import SessionClock

    tz_name = loader.as_str(app_cfg, "timezone", module="app")
    sessions = loader.as_list(app_cfg, "sessions", module="app")
    bucket_s = loader.as_int(
        serial_cfg, "heatmap_bucket_seconds", module="serialization"
    )

    probe = SessionClock(tz_name, sessions, bucket_s)
    start = probe.grid_start_dt(day or ANCHOR_DAY)

    fake = FakeClock(start.timestamp() + float(offset_s))
    return SessionClock(tz_name, sessions, bucket_s, clock=fake), fake


# --------------------------------------------------------------------------- #
# ib_async 结构的忠实模拟
# --------------------------------------------------------------------------- #


class FakeComputation:
    """对应 ``ib_async.OptionComputation``（字段名逐字对齐）。"""

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
    """对应 ``ib_async.Option`` / ``Index`` / ``Future``（只留 ``OptionRef`` 需要的字段）。"""

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
        # ib_async 在没有数据时返回 nan，这里保持一致 —— 返回 None 会让
        # "NaN 时回退到盘口中间价"这条分支永远走不到。
        return self._mark if self._mark is not None else math.nan


class ExplodingTicker:
    """访问任何属性都抛异常：验证单条坏数据不会打断整批。"""

    def __getattr__(self, name):
        raise RuntimeError(f"模拟损坏的 ticker，访问 {name} 时炸掉")


def make_option_ticker(strike: float, right: str, expiry: str,
                       con_id: int) -> FakeTicker:
    """造一条期权 ticker（合约字段齐备，greeks 留空由调用方填）。"""
    return FakeTicker(
        FakeContract(con_id=con_id, strike=strike, right=right,
                     expiry=expiry, sec_type="OPT")
    )


def make_index_ticker(con_id: int, mark=None) -> FakeTicker:
    """造一条指数 ticker（标的）。"""
    return FakeTicker(FakeContract(con_id=con_id, sec_type="IND"), mark=mark)


# --------------------------------------------------------------------------- #
# Sink
# --------------------------------------------------------------------------- #


class RecordingSink:
    """记录型 ``TickSink``：把收到的 DTO 分类存下来，供判据逐字段核对。"""

    def __init__(self) -> None:
        self.options: list = []
        self.quotes: list = []
        self.spots: list = []
        self.status: list = []
        self.futures: list = []

    def on_option_tick(self, tick) -> None:
        self.options.append(tick)

    def on_quote_tick(self, tick) -> None:
        self.quotes.append(tick)

    def on_spot_tick(self, tick) -> None:
        self.spots.append(tick)

    def on_status(self, event) -> None:
        self.status.append(event)

    def on_future_tick(self, tick) -> None:
        """``TickRouter`` 的 ``future_sink`` 出口（不在 ``TickSink`` 协议里）。"""
        self.futures.append(tick)

    def clear(self) -> None:
        self.options.clear()
        self.quotes.clear()
        self.spots.clear()
        self.status.clear()
        self.futures.clear()
