"""
L2 — 动态 ATM 订阅协调器。
==========================
唯一职责：让"当前活跃的行情订阅集合"始终等于"以现价为中心的 0DTE 窗口"，
且**结构上不可能**突破 IBKR 的 100 条上限。

三重保护（对应需求里的"防限流核心"）
------------------------------------
1. **容量反推**：窗口档位数由 ``ChainResolver.effective_each_side()`` 反推，
   配置写大了也只会被压缩，不会真的超限。
2. **先退后订**：``cancel_stale_before_add`` 打开时，先取消滑出窗口的合约，
   再订阅新进窗口的，峰值订阅数不会瞬时冲高。
3. **Error 300 退避**：一旦 IBKR 返回"行情行数超限"，进入指数退避并停止一切
   订阅动作，等行情配额回收后再恢复。

命名纪律：本模块管的是 **Error 300（行情行数超限）**，不是**消息速率**。
消息速率那个桶在 ``ib_async`` 的 ``Client`` 里，由
``acquisition.rate_limit_watch.RateLimitWatch`` 观测。两者语义不同，因此这里
一律用 ``backoff`` / ``limit_events`` 命名，**刻意不出现** ``throttle*`` —— 历史上
二者共用 ``throttled`` 一个名字，排查时极易张冠李戴。

订阅前必须先确认合约（qualify）
-------------------------------
``ib_async`` 用 ``hash(contract)`` 索引 ticker，而 ``Contract.__hash__`` 在
``conId == 0`` 时**直接抛 ValueError**。``reqMktData`` 的第一件事就是
``hash(contract)``，所以**未确认的合约根本订阅不了**。

这一点极其容易踩：异常如果被静默吞掉，系统会"启动成功、报告就绪、然后永远
收不到任何期权数据"，而且没有任何报错。因此这里订阅前一律先批量 qualify，
并且订阅失败会记进 ``SubscriptionPlan.failed`` 向上暴露，绝不静默。

依赖：L0 / L1。通过注入的 ``gateway`` / ``factory`` 访问外部能力（鸭子类型），
因此本模块不 import ``ib_async``。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from config import loader
from contracts.enums import OptionRight
from contracts.tick import OptionRef
from core.errors import ContractResolveError, SubscriptionLimitExceeded
from core.logging_setup import get_logger

_CFG = "subscription"


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    """一次协调的决策结果，便于日志与自检。"""

    keep: tuple[OptionRef, ...] = ()
    add: tuple[OptionRef, ...] = ()
    drop: tuple[OptionRef, ...] = ()
    failed: tuple[OptionRef, ...] = ()
    blocked_by_backoff: bool = False
    projected_total: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.add or self.drop)


@dataclass(slots=True)
class _State:
    contracts: dict[OptionRef, Any] = field(default_factory=dict)
    backoff_until: float = 0.0
    backoff_current: float = 0.0
    limit_events: int = 0


class SubscriptionManager:
    """维护活跃订阅集合与窗口的一致性。"""

    __slots__ = (
        "_gateway", "_factory", "_min_interval", "_cancel_first",
        "_backoff_base", "_backoff_mult", "_backoff_max", "_max_retries",
        "_cap", "_log", "_state",
    )

    def __init__(self, gateway: Any, factory: Any, sub_cfg: dict) -> None:
        self._gateway = gateway
        self._factory = factory
        self._min_interval = loader.as_float(sub_cfg, "min_request_interval_s", module=_CFG)
        self._cancel_first = loader.as_bool(sub_cfg, "cancel_stale_before_add", module=_CFG)
        self._backoff_base = loader.as_float(sub_cfg, "error300_backoff_s", module=_CFG)
        self._backoff_mult = loader.as_float(sub_cfg, "error300_backoff_multiplier", module=_CFG)
        self._backoff_max = loader.as_float(sub_cfg, "error300_max_backoff_s", module=_CFG)
        self._max_retries = loader.as_int(sub_cfg, "error300_max_retries", module=_CFG)
        self._cap = loader.as_int(sub_cfg, "max_total_subscriptions", module=_CFG)
        self._log = get_logger("subscription")
        self._state = _State()

    # ------------------------------------------------------------------ #
    # 只读状态
    # ------------------------------------------------------------------ #

    @property
    def count(self) -> int:
        return len(self._state.contracts)

    @property
    def capacity(self) -> int:
        return self._cap

    @property
    def in_backoff(self) -> bool:
        """是否处于 Error 300（行情行数超限）退避期。"""
        return time.monotonic() < self._state.backoff_until

    @property
    def limit_events(self) -> int:
        """累计收到的 Error 300 次数。"""
        return self._state.limit_events

    def active_refs(self) -> tuple[OptionRef, ...]:
        return tuple(self._state.contracts.keys())

    def active_contract(self, ref: OptionRef) -> Any | None:
        return self._state.contracts.get(ref)

    def backoff_remaining_s(self) -> float:
        return max(self._state.backoff_until - time.monotonic(), 0.0)

    # ------------------------------------------------------------------ #
    # 目标集合
    # ------------------------------------------------------------------ #

    @staticmethod
    def desired_refs(expiry: str, strikes: Iterable[float]) -> tuple[OptionRef, ...]:
        """窗口内每个行权价的 Put 与 Call 都要订阅。"""
        refs: list[OptionRef] = []
        for strike in strikes:
            for right in (OptionRight.PUT, OptionRight.CALL):
                refs.append(OptionRef(strike=float(strike), right=right, expiry=str(expiry)))
        return tuple(refs)

    def guard_capacity(self, desired: Iterable[OptionRef]) -> tuple[OptionRef, ...]:
        """
        硬闸门：目标集合超过上限时截断并抛错。

        正常情况下 ``effective_each_side()`` 已经把窗口压到安全范围，
        走到这里说明上游逻辑出了问题——宁可报错也不要真的去触发 Error 300。
        """
        refs = tuple(desired)
        if len(refs) > self._cap:
            raise SubscriptionLimitExceeded(
                f"目标订阅 {len(refs)} 条超过上限 {self._cap} 条，已拒绝执行。"
                "请调小 subscription.json 的 num_strikes_each_side。"
            )
        return refs

    # ------------------------------------------------------------------ #
    # 协调
    # ------------------------------------------------------------------ #

    async def reconcile(
        self,
        expiry: str,
        strikes: Iterable[float],
    ) -> SubscriptionPlan:
        """
        把活跃订阅对齐到目标窗口。

        返回本次的增删明细。处于退避期时不做任何动作，只回报
        ``blocked_by_backoff=True``。
        """
        desired = self.guard_capacity(self.desired_refs(expiry, strikes))

        if self.in_backoff:
            return SubscriptionPlan(
                keep=self.active_refs(),
                blocked_by_backoff=True,
                projected_total=self.count,
            )

        desired_set = set(desired)
        active = self._state.contracts
        to_add = tuple(r for r in desired if r not in active)
        to_drop = tuple(r for r in tuple(active.keys()) if r not in desired_set)
        to_keep = tuple(r for r in desired if r in active)

        # 先退后订：滑出窗口的合约先取消，避免峰值订阅数瞬时冲高。
        if self._cancel_first and to_drop:
            await self._drop(to_drop)

        # 订阅前必须确认合约——未确认（conId=0）的合约在 ib_async 里连
        # hash 都过不了，根本订阅不上。一次批量确认，避免逐条往返。
        qualified = await self._qualify(to_add)

        added: list[OptionRef] = []
        failed: list[OptionRef] = []
        for ref in to_add:
            if self.count >= self._cap:
                break
            contract = qualified.get(ref)
            if contract is None:
                failed.append(ref)
                continue
            if await self._subscribe(ref, contract):
                added.append(ref)
            else:
                failed.append(ref)

        # 未开启"先退后订"时，退订放在订阅之后，保证同一时刻只增不减的错觉不会发生。
        if not self._cancel_first and to_drop:
            await self._drop(to_drop)

        if failed:
            self._log.warning("有 %d 条合约未能建立订阅（前 3 条: %s）",
                              len(failed),
                              ", ".join(r.label() for r in failed[:3]))

        return SubscriptionPlan(
            keep=to_keep,
            add=tuple(added),
            drop=to_drop,
            failed=tuple(failed),
            projected_total=self.count,
        )

    # ------------------------------------------------------------------ #
    # 合约确认
    # ------------------------------------------------------------------ #

    async def _qualify(
        self, refs: Iterable[OptionRef]
    ) -> dict[OptionRef, Any]:
        """
        批量向 IBKR 确认合约，返回 ``{ref: 已确认合约}``。

        确认失败的（歧义、无此合约、接口异常）不会出现在结果里，调用方据此
        把它们记入 ``failed``，而不是让一个空合约一路走到订阅阶段再静默失败。

        "什么叫已确认"由工厂判定（``assert_qualified``）——那是 ``ib_async``
        的知识，本模块刻意不 import 它，所以不在这里判断 conId。
        """
        pairs = [(ref, self._factory.option_from_ref(ref)) for ref in refs]
        if not pairs:
            return {}

        contracts = [contract for _, contract in pairs]
        try:
            results = await self._gateway.qualify_many(contracts)
        except Exception as exc:
            self._log.error("批量确认合约失败: %s", exc)
            return {}

        out: dict[OptionRef, Any] = {}
        for (ref, contract), result in zip(pairs, results):
            # qualifyContractsAsync 会原地回填 conId，因此 result 与 contract
            # 通常是同一个对象；result 为 None 表示确认失败。
            target = result if result is not None else contract
            try:
                out[ref] = self._factory.assert_qualified(target)
            except ContractResolveError:
                self._log.debug("合约未确认: %s", ref.label())
        return out

    # ------------------------------------------------------------------ #
    # 订阅 / 退订
    # ------------------------------------------------------------------ #

    async def _subscribe(self, ref: OptionRef, contract: Any) -> bool:
        """
        建立一条订阅。

        失败时**记录日志并返回 False**，不再静默吞掉——这个异常以前被无声吞掉，
        导致实盘整场收不到任何期权数据却显示"就绪"。
        """
        try:
            self._gateway.subscribe_option(contract)
        except Exception as exc:
            self._log.error("订阅失败 %s: %s", ref.label(), exc)
            return False
        self._state.contracts[ref] = contract
        await asyncio.sleep(self._min_interval)
        return True

    async def _drop(self, refs: Iterable[OptionRef]) -> None:
        for ref in refs:
            contract = self._state.contracts.pop(ref, None)
            if contract is None:
                continue
            try:
                self._gateway.cancel_option(contract)
            except Exception as exc:
                self._log.warning("退订失败 %s: %s", ref.label(), exc)
            await asyncio.sleep(self._min_interval)

    async def resubscribe_all(self) -> int:
        """
        IBKR 报 1101（行情订阅状态丢失）后重建全部订阅。

        返回**成功重建**的条数。``_state.contracts`` 里存的是已确认的合约对象，
        直接复用即可，无需重新解析链或重新确认。
        """
        pairs = tuple(self._state.contracts.items())
        self._state.contracts.clear()
        restored = 0
        for ref, contract in pairs:
            if await self._subscribe(ref, contract):
                restored += 1
        return restored

    async def clear(self) -> None:
        """取消所有订阅（停机时调用）。"""
        await self._drop(tuple(self._state.contracts.keys()))

    # ------------------------------------------------------------------ #
    # Error 300 退避反馈（由 feed_service 从 IBKR 错误回调转发进来）
    # ------------------------------------------------------------------ #

    def note_limit_hit(self) -> float:
        """记录一次 Error 300，返回本次退避秒数。"""
        self._state.limit_events += 1
        current = self._state.backoff_current or self._backoff_base
        self._state.backoff_current = min(current * self._backoff_mult, self._backoff_max)
        self._state.backoff_until = time.monotonic() + current
        return current

    def note_recovered(self) -> None:
        """连续成功一段时间后复位退避。"""
        self._state.backoff_current = 0.0
        self._state.backoff_until = 0.0

    def exhausted(self) -> bool:
        return (
            self._max_retries > 0
            and self._state.limit_events > self._max_retries
        )
