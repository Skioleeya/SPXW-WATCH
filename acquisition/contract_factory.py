"""
L1 — 期权合约工厂。
====================
唯一职责：把"标的 + 到期日 + 行权价 + 方向"翻译成 IBKR 的合约对象。

这是 L1 中**仅有的两个**允许 import ``ib_async`` 的模块之一（另一个是
``ibkr_gateway``）。其余 L1 模块通过鸭子类型与本模块交互，从而在离线模拟
模式下完全不触碰 ``ib_async``。

依赖：L0（config / contracts / core）。
"""

from __future__ import annotations

from typing import Any

from ib_async import Contract, Option

from config import loader
from contracts.enums import OptionRight
from contracts.tick import OptionRef
from core.errors import ContractResolveError

_CFG_MODULE = "app"
_SPOT_MODULE = "spot"


class ContractFactory:
    """按 ``config/app.json`` 与 ``config/spot.json`` 构造标的、期权与期货合约。"""

    __slots__ = (
        "_symbol", "_und_sec_type", "_und_exchange", "_currency",
        "_trading_class", "_opt_exchange", "_multiplier",
        "_future_symbol", "_future_sec_type", "_future_exchange", "_future_currency",
    )

    def __init__(self, app_cfg: dict, spot_cfg: dict) -> None:
        m = _CFG_MODULE
        self._symbol = loader.as_str(app_cfg, "symbol", module=m)
        self._und_sec_type = loader.as_str(app_cfg, "underlying_sec_type", module=m)
        self._und_exchange = loader.as_str(app_cfg, "underlying_exchange", module=m)
        self._currency = loader.as_str(app_cfg, "currency", module=m)
        self._trading_class = loader.as_str(app_cfg, "option_trading_class", module=m)
        self._opt_exchange = loader.as_str(app_cfg, "option_exchange", module=m)
        self._multiplier = loader.as_str(app_cfg, "option_multiplier", module=m)

        s = _SPOT_MODULE
        self._future_symbol = loader.as_str(spot_cfg, "future_symbol", module=s)
        self._future_sec_type = loader.as_str(spot_cfg, "future_sec_type", module=s)
        self._future_exchange = loader.as_str(spot_cfg, "future_exchange", module=s)
        self._future_currency = loader.as_str(spot_cfg, "future_currency", module=s)

    # ------------------------------------------------------------------ #
    # 只读属性
    # ------------------------------------------------------------------ #

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def trading_class(self) -> str:
        return self._trading_class

    @property
    def underlying_exchange(self) -> str:
        return self._und_exchange

    @property
    def option_exchange(self) -> str:
        return self._opt_exchange

    @property
    def currency(self) -> str:
        return self._currency

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #

    def underlying(self) -> Contract:
        """标的合约（SPX 指数为 ``secType=IND``，交易所默认 CBOE）。"""
        contract = Contract()
        contract.symbol = self._symbol
        contract.secType = self._und_sec_type
        contract.exchange = self._und_exchange
        contract.currency = self._currency
        return contract

    def future(self) -> Contract:
        """指数期货合约（**刻意不带月份**）。

        为什么不能在这里算月份
        ----------------------
        合约月与到期日必须由 IBKR 给（见 ``IbkrGateway.fetch_future_months``）。
        硬编码"第三个周五"正是 B1 在换月日静默错值的同族错误 —— 本项目明确禁止。

        实测（2026-09-14，ES/CME）：不带月份的 ``reqContractDetails`` 会返回
        **全部**可交易月份（21 条，远月到 2028-12），每条都带 conId 与
        ``realExpirationDate``（精度到日），因此拿到即可直接订阅，无需再 qualify。
        """
        contract = Contract()
        contract.symbol = self._future_symbol
        contract.secType = self._future_sec_type
        contract.exchange = self._future_exchange
        contract.currency = self._future_currency
        return contract

    def option(self, expiry: str, strike: float, right: OptionRight) -> Option:
        """单个 0DTE 期权合约。``expiry`` 形如 ``"20260911"``。"""
        return Option(
            symbol=self._symbol,
            lastTradeDateOrContractMonth=str(expiry),
            strike=float(strike),
            right=str(right),
            exchange=self._opt_exchange,
            multiplier=self._multiplier,
            currency=self._currency,
            tradingClass=self._trading_class,
        )

    def option_from_ref(self, ref: OptionRef) -> Option:
        return self.option(ref.expiry, ref.strike, ref.right)

    # ------------------------------------------------------------------ #
    # 反向解析
    # ------------------------------------------------------------------ #

    @staticmethod
    def ref_from_contract(contract: Any) -> OptionRef | None:
        """从 IBKR 回传的合约对象还原 ``OptionRef``。"""
        return OptionRef.from_contract(contract)

    @staticmethod
    def assert_qualified(contract: Any) -> Any:
        """校验合约已被 IBKR 确认（有 conId），否则抛错。"""
        if contract is None or not getattr(contract, "conId", 0):
            raise ContractResolveError(
                f"合约未被 IBKR 确认（缺少 conId）: "
                f"{getattr(contract, 'localSymbol', '?')}"
            )
        return contract
