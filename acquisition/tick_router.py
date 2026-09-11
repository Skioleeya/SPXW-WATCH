"""
L1 — Tick 归一化路由。
======================
唯一职责：把 IBKR 推来的 ticker 对象翻译成 L0 契约里的不可变 DTO，并推给
``TickSink``。

关键约束：**只采信券商推送的 IV 与 Greeks**
--------------------------------------------
本系统严禁在本地用 BSM 高频重算。因此这里优先读 ``ticker.modelGreeks``
（对应 ``tickOptionComputation`` 的 ``tickType == 13``，即 MODEL_OPTION）。
只有当 ``use_model_greeks`` 为假时，才退一步使用 last / bid / ask 三档
greeks（``tickType`` 12/10/11）作为补充。

本模块不 import ``ib_async``：全部按鸭子类型访问属性。好处是离线模拟器可以
复用同一套归一化规则，且 L1 对第三方库的依赖面被压缩到两个文件。

依赖：L0。
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from config import loader
from contracts.ports import TickSink
from contracts.tick import OptionRef, OptionTick, QuoteTick, SpotTick
from core.clock import now_ts

_CFG = "ibkr"

# (属性名, tickType)。tickType 13 即 MODEL_OPTION。
#
# 注意：ib_async 的 GREEKS_TICK_MAP 把 13（实时模型）与 83（延迟模型）都映射到
# ticker.modelGreeks，把 10/80 映射到 bidGreeks、12/82 映射到 lastGreeks。
# 因此拿到 modelGreeks 就等价于拿到了 MODEL_OPTION，无需区分实时/延迟。
_COMPUTATION_SOURCES: tuple[tuple[str, int], ...] = (
    ("modelGreeks", 13),
    ("lastGreeks", 12),
    ("bidGreeks", 10),
    ("askGreeks", 11),
)


def _finite(value: Any) -> float | None:
    """把 None / NaN / inf 统一成 None，其余转 float。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _finite_int(value: Any) -> int | None:
    number = _finite(value)
    return int(number) if number is not None else None


class TickRouter:
    """ticker → DTO 的转换器。"""

    __slots__ = (
        "_sink", "_max_iv", "_min_iv", "_use_model",
        "_spot_con_id", "_routed", "_rejected",
    )

    def __init__(self, sink: TickSink, ibkr_cfg: dict) -> None:
        self._sink = sink
        self._max_iv = loader.as_float(ibkr_cfg, "max_iv", module=_CFG)
        self._min_iv = loader.as_float(ibkr_cfg, "min_iv", module=_CFG)
        self._use_model = loader.as_bool(ibkr_cfg, "use_model_greeks", module=_CFG)
        self._spot_con_id: int = 0
        self._routed: int = 0
        self._rejected: int = 0

    # ------------------------------------------------------------------ #
    # 配置与计数
    # ------------------------------------------------------------------ #

    def set_spot_con_id(self, con_id: int) -> None:
        """登记标的合约的 conId，用于在批量回调中把它分流出去。"""
        self._spot_con_id = int(con_id or 0)

    @property
    def routed(self) -> int:
        return self._routed

    @property
    def rejected(self) -> int:
        return self._rejected

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #

    def handle_tickers(self, tickers: Iterable[Any]) -> int:
        """
        处理 ``pendingTickersEvent`` 送来的一批 ticker。

        返回成功推送的 tick 条数。异常被就地吞掉——行情回调里抛出未捕获异常
        会破坏 ib_async 事件循环的内部状态。
        """
        count = 0
        for ticker in tickers:
            try:
                if self._is_spot(ticker):
                    if self._emit_spot(ticker):
                        count += 1
                elif self._emit_option(ticker):
                    count += 1
            except Exception:
                self._rejected += 1
        return count

    def _is_spot(self, ticker: Any) -> bool:
        if not self._spot_con_id:
            return False
        contract = getattr(ticker, "contract", None)
        return int(getattr(contract, "conId", 0) or 0) == self._spot_con_id

    # ------------------------------------------------------------------ #
    # 标的
    # ------------------------------------------------------------------ #

    def _emit_spot(self, ticker: Any) -> bool:
        price = self._spot_price(ticker)
        if price is None or price <= 0:
            return False
        self._sink.on_spot_tick(SpotTick(price=price, ts=now_ts()))
        self._routed += 1
        return True

    @staticmethod
    def _spot_price(ticker: Any) -> float | None:
        """依次尝试 markPrice / last / close / 中间价。"""
        try:
            mark = _finite(ticker.marketPrice())
        except Exception:
            mark = None
        if mark is not None and mark > 0:
            return mark

        for attr in ("last", "close"):
            value = _finite(getattr(ticker, attr, None))
            if value is not None and value > 0:
                return value

        bid = _finite(getattr(ticker, "bid", None))
        ask = _finite(getattr(ticker, "ask", None))
        if bid and ask and bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        return None

    # ------------------------------------------------------------------ #
    # 期权
    # ------------------------------------------------------------------ #

    def _emit_option(self, ticker: Any) -> bool:
        contract = getattr(ticker, "contract", None)
        ref = OptionRef.from_contract(contract)
        if ref is None:
            return False

        picked = self._pick_computation(ticker)
        if picked is None:
            self._rejected += 1
            return False
        comp, tick_type = picked

        iv = _finite(getattr(comp, "impliedVol", None))
        if iv is None or iv <= 0 or not (self._min_iv <= iv <= self._max_iv):
            self._rejected += 1
            return False

        ts = now_ts()
        self._sink.on_option_tick(
            OptionTick(
                ref=ref,
                iv=iv,
                ts=ts,
                delta=_finite(getattr(comp, "delta", None)),
                gamma=_finite(getattr(comp, "gamma", None)),
                vega=_finite(getattr(comp, "vega", None)),
                theta=_finite(getattr(comp, "theta", None)),
                opt_price=_finite(getattr(comp, "optPrice", None)),
                und_price=_finite(getattr(comp, "undPrice", None)),
                source_tick_type=tick_type,
                model_greeks=(tick_type == 13),
                con_id=int(getattr(contract, "conId", 0) or 0),
            )
        )

        quote = self._quote_from(ticker, ref, ts)
        if quote is not None:
            self._sink.on_quote_tick(quote)

        self._routed += 1
        return True

    def _pick_computation(self, ticker: Any) -> tuple[Any, int] | None:
        """优先 MODEL_OPTION（tick 13）；配置允许时才回退到 last/bid/ask。"""
        for attr, tick_type in _COMPUTATION_SOURCES:
            comp = getattr(ticker, attr, None)
            if comp is None:
                continue
            if tick_type != 13 and self._use_model:
                # 明确要求只用模型值时不接受降级来源。
                return None
            return comp, tick_type
        return None

    @staticmethod
    def _quote_from(ticker: Any, ref: OptionRef, ts: float) -> QuoteTick | None:
        quote = QuoteTick(
            ref=ref,
            ts=ts,
            bid=_finite(getattr(ticker, "bid", None)),
            ask=_finite(getattr(ticker, "ask", None)),
            last=_finite(getattr(ticker, "last", None)),
            close=_finite(getattr(ticker, "close", None)),
            bid_size=_finite_int(getattr(ticker, "bidSize", None)),
            ask_size=_finite_int(getattr(ticker, "askSize", None)),
            last_size=_finite_int(getattr(ticker, "lastSize", None)),
        )
        has_any = any(
            value is not None
            for value in (quote.bid, quote.ask, quote.last, quote.close)
        )
        return quote if has_any else None
