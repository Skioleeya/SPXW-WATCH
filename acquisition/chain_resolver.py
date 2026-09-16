"""
L2 — 0DTE 期权链解析。
======================
唯一职责：从 IBKR 返回的期权链参数中挑出**当日到期**的那一片，并把可用行权价
裁剪成以现价为中心的滑动窗口。

纯逻辑，不 import ``ib_async``（只按鸭子类型读 ``.expirations`` / ``.strikes``
等属性），因此可以在离线环境下被完整单测。

依赖：L0（config / contracts）与 L1（core）。
"""

from __future__ import annotations

from typing import Any, Iterable

from config import loader
from contracts.tick import ChainSlice
from core.errors import ChainResolveError

_APP = "app"
_SUB = "subscription"

# 每订阅一个行权价需要 2 条行情（Put + Call），另有 1 条标的现价。
_RIGHTS_PER_STRIKE = 2
_EXTRA_SUBSCRIPTIONS = 1


class ChainResolver:
    """解析 0DTE 切片并计算 ATM 窗口。"""

    __slots__ = (
        "_trading_class", "_preferred_exchange", "_zero_dte_only",
        "_requested_each_side", "_cap",
    )

    def __init__(self, app_cfg: dict, sub_cfg: dict) -> None:
        self._trading_class = loader.as_str(
            app_cfg, "option_trading_class", module=_APP
        )
        self._preferred_exchange = loader.as_str(
            app_cfg, "option_exchange", module=_APP
        )
        self._zero_dte_only = loader.as_bool(app_cfg, "zero_dte_only", module=_APP)
        self._requested_each_side = loader.as_int(
            sub_cfg, "num_strikes_each_side", module=_SUB
        )
        self._cap = loader.as_int(
            sub_cfg, "max_total_subscriptions", module=_SUB
        )

    # ------------------------------------------------------------------ #
    # 订阅容量
    # ------------------------------------------------------------------ #

    def effective_each_side(self) -> int:
        """
        实际可用的"单侧档位数"。

        IBKR 对同时活跃的行情条数有 100 条硬上限，超限会触发 Error 300。
        窗口取上下各 ``side`` 档，共 ``2 × side`` 个行权价，每个行权价订阅
        Put + Call 两条，再加 1 条标的现价：

            总订阅数 = 4 × side + 1

        ⚠️ 这是**容量口径**（含现货那 1 条），用于对上限核算。日志里的
        ``订阅 N/92`` 是**计数口径** ``SubscriptionManager.count`` = ``4 × side``
        —— 现货由 ``subscribe_spot`` 单独管、不进 manager，所以那里**永远不会**
        出现 ``4 × side + 1``。两个口径别混（2026-09-14 踩过），
        见 ``notes/memory/TROUBLESHOOTING.md`` §11。

        这里反解出安全上限再与配置值取小，保证**结构上不可能**超限，而不是
        等报错后再补救。
        """
        max_side = max(
            (self._cap - _EXTRA_SUBSCRIPTIONS) // (_RIGHTS_PER_STRIKE * 2), 1
        )
        return max(min(self._requested_each_side, max_side), 1)

    def projected_subscriptions(self, each_side: int | None = None) -> int:
        side = self.effective_each_side() if each_side is None else each_side
        return _RIGHTS_PER_STRIKE * 2 * side + _EXTRA_SUBSCRIPTIONS

    def is_shrunk(self) -> bool:
        """配置的档位数是否因为限额被压缩了。"""
        return self.effective_each_side() < self._requested_each_side

    # ------------------------------------------------------------------ #
    # 0DTE 切片
    # ------------------------------------------------------------------ #

    def pick_zero_dte(
        self,
        chains: Iterable[Any],
        today: str,
        underlying_con_id: int,
    ) -> ChainSlice:
        """
        选出当日到期、tradingClass 匹配的那一片链。

        Parameters
        ----------
        chains
            ``reqSecDefOptParams`` 的返回值，每项含 ``exchange`` /
            ``tradingClass`` / ``expirations`` / ``strikes`` / ``multiplier``。
        today
            ``"YYYYMMDD"``，通常来自 ``SessionClock.expiry_str()``。
        """
        candidates = [
            chain for chain in chains
            if str(getattr(chain, "tradingClass", "")) == self._trading_class
        ]

        if not candidates:
            available = sorted({
                str(getattr(c, "tradingClass", "?")) for c in chains
            })
            raise ChainResolveError(
                f"期权链里找不到 tradingClass={self._trading_class!r}。"
                f"可用 tradingClass: {available}"
            )

        if self._zero_dte_only:
            dated = [
                c for c in candidates
                if today in set(str(e) for e in getattr(c, "expirations", ()))
            ]
            if not dated:
                sample = sorted(
                    str(e) for e in getattr(candidates[0], "expirations", ())
                )[:5]
                raise ChainResolveError(
                    f"tradingClass={self._trading_class!r} 下没有当日到期（{today}）"
                    f"的合约。最近的到期日: {sample}"
                )
            candidates = dated

        best = self._prefer_exchange(candidates)

        strikes = tuple(sorted(float(s) for s in getattr(best, "strikes", ())))
        if not strikes:
            raise ChainResolveError(
                f"tradingClass={self._trading_class!r} 的 0DTE 切片没有可用行权价"
            )

        return ChainSlice(
            expiry=today,
            trading_class=str(getattr(best, "tradingClass", self._trading_class)),
            strikes=strikes,
            multiplier=str(getattr(best, "multiplier", "100")),
            exchange=str(getattr(best, "exchange", "")),
            underlying_con_id=int(underlying_con_id),
        )

    def _prefer_exchange(self, candidates: list[Any]) -> Any:
        """优先配置里指定的交易所，其次 SMART，最后取行权价最多的那个。"""
        for wanted in (self._preferred_exchange, "SMART"):
            for chain in candidates:
                if str(getattr(chain, "exchange", "")) == wanted:
                    return chain
        return max(candidates, key=lambda c: len(getattr(c, "strikes", ())))

    # ------------------------------------------------------------------ #
    # ATM 滑动窗口
    # ------------------------------------------------------------------ #

    def window(
        self,
        strikes: Iterable[float],
        spot: float,
        each_side: int | None = None,
    ) -> tuple[float, ...]:
        """
        以现价为中心取上下各 ``each_side`` 档。

        返回升序元组。现价恰好落在某个行权价上时，该档计入下方。
        """
        if spot <= 0:
            return ()
        side = self.effective_each_side() if each_side is None else int(each_side)
        ordered = sorted(float(s) for s in strikes)

        below = [s for s in ordered if s <= spot]
        above = [s for s in ordered if s > spot]

        picked = below[-side:] + above[:side]
        return tuple(sorted(picked))

    def centre_strike(self, strikes: Iterable[float], spot: float) -> float | None:
        """最接近现价的行权价。"""
        ordered = sorted(float(s) for s in strikes)
        if not ordered:
            return None
        return min(ordered, key=lambda s: abs(s - spot))

    def centre_moved(
        self,
        previous_centre: float | None,
        strikes: Iterable[float],
        spot: float,
        trigger_strikes: float,
    ) -> bool:
        """
        判断是否需要重建窗口。只有当中心行权价偏移超过
        ``trigger_strikes`` 档时才动，避免现价在整数关口抖动导致反复订阅/退订。
        """
        current = self.centre_strike(strikes, spot)
        if current is None:
            return False
        if previous_centre is None:
            return True
        ordered = sorted(float(s) for s in strikes)
        if len(ordered) < 2:
            return False
        step = min(
            (b - a) for a, b in zip(ordered, ordered[1:]) if b > a
        ) if len(ordered) > 1 else 5.0
        return abs(current - previous_centre) >= (trigger_strikes * step)
