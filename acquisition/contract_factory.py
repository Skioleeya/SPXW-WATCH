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


class ContractFactory:
    """按 ``config/app.json`` 的定义构造标的与期权合约。"""

    __slots__ = (
        "_symbol", "_und_sec_type", "_und_exchange", "_currency",
        "_trading_class", "_opt_exchange", "_multiplier",
    )

    def __init__(self, app_cfg: dict) -> None:
        m = _CFG_MODULE
        self._symbol = loader.as_str(app_cfg, "symbol", module=m)
        self._und_sec_type = loader.as_str(app_cfg, "underlying_sec_type", module=m)
        self._und_exchange = loader.as_str(app_cfg, "underlying_exchange", module=m)
        self._currency = loader.as_str(app_cfg, "currency", module=m)
        self._trading_class = loader.as_str(app_cfg, "option_trading_class", module=m)
        self._opt_exchange = loader.as_str(app_cfg, "option_exchange", module=m)
        self._multiplier = loader.as_str(app_cfg, "option_multiplier", module=m)

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
