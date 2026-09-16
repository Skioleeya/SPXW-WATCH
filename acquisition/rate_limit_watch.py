"""
L2 — 出站消息限速桶的显式配置与观测。
======================================
唯一职责：把 ``ib_async.Client`` 的滑动窗口限速桶（``MaxRequests`` /
``RequestsInterval``）**显式**写进配置值，并观测 ``throttleStart`` /
``throttleEnd``，产出一份可上报的 ``RateLimitStatus``。

为什么单独成文件
----------------
1. 桶是**库层**概念，与"连接生命周期"（``ibkr_gateway``）不是同一个职能。
2. ``IB.events`` 元组里没有 ``throttleStart`` / ``throttleEnd``，``IB`` 类也不
   转发它们 —— 必须直接挂 ``ib.client``。把这个易踩的细节收在一个文件里，
   比散在网关的接线函数里更容易被读到。
3. 本项目还有另一个名字带 "throttle" 的东西：IBKR **Error 300** 退避（行情行数
   超限，见 ``subscription_manager``）。二者语义完全不同，分文件存放是最彻底的
   消歧。

官方配额（2026-09 核实）
------------------------
* 出站消息速率上限 = **已分配行情行数 ÷ 2**；默认 100 行 → 50 msg/s。
* ``ib_async`` 自带默认 45 / 1s（官方上限的 90%）。本模块**不依赖它** —— 容量
  由 ``config/ibkr.json`` 显式给出，缺键时 ``loader`` 直接抛 ``ConfigError``。
* 违约错误码 100；累计 3 次违规，IBKR 会**终止 API 会话**（必须重连）。

本模块只**观测**桶，不实现第二个桶：库是唯一的限流者。若本系统自己再放一个桶，
两个桶互相不知情，容量对不上时反而更容易撞上 Error 100。

依赖：L0（config / contracts）与 L1（core）。
"""

from __future__ import annotations

import time
from typing import Any

from config import loader
from contracts.tick import RateLimitStatus
from core.logging_setup import get_logger

_CFG = "ibkr"


class RateLimitWatch:
    """显式设置桶容量，并累计 ``throttleStart`` / ``throttleEnd`` 的观测值。"""

    __slots__ = ("_capacity", "_interval", "_events", "_since", "_total", "_log")

    def __init__(self, ibkr_cfg: dict) -> None:
        self._capacity = loader.as_int(
            ibkr_cfg, "rate_limit_max_requests", module=_CFG
        )
        self._interval = loader.as_float(
            ibkr_cfg, "rate_limit_interval_s", module=_CFG
        )
        self._events = 0
        self._since = 0.0
        self._total = 0.0
        self._log = get_logger("ibkr.rate_limit")

    # ------------------------------------------------------------------ #
    # 只读
    # ------------------------------------------------------------------ #

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def events(self) -> int:
        return self._events

    def snapshot(self) -> RateLimitStatus:
        """当前快照。正在被限速时，时长按"到现在为止"累计。"""
        total = self._total
        if self._since > 0:
            total += time.monotonic() - self._since
        return RateLimitStatus(
            capacity=self._capacity,
            interval_s=self._interval,
            events=self._events,
            throttling=self._since > 0,
            throttled_total_s=total,
        )

    # ------------------------------------------------------------------ #
    # 接线
    # ------------------------------------------------------------------ #

    def apply(self, ib: Any) -> None:
        """
        把桶容量写进 ``Client``，并挂上节流事件。

        每次 ``connect()`` 都会造一个新的 ``IB`` / ``Client``，所以这里先把上一个
        连接的限速窗口结算掉 —— 否则连接中途掉线时，"正在被限速"会永远挂着。

        ``MaxRequests`` / ``RequestsInterval`` 是**类属性**（库默认 45 / 1s）。
        这里写成实例属性；``Client.reset()`` 只清消息队列与节流标志，不会把它清掉，
        所以一次 ``apply()`` 足以覆盖该连接的全部生命周期。
        """
        self.close_window()
        ib.client.MaxRequests = int(self._capacity)
        ib.client.RequestsInterval = float(self._interval)
        ib.client.throttleStart += self._on_start
        ib.client.throttleEnd += self._on_end
        # 用 INFO 而不是 DEBUG：这是"桶确实是按配置设的、没落回库的隐式默认值"的
        # 唯一运行期证据。每次连接只打一行。
        self._log.info(
            "出站限速桶显式设为 %d 条 / %.3gs（不依赖 ib_async 的类属性默认值）",
            self._capacity, self._interval,
        )

    def close_window(self) -> None:
        """结算"正在被限速"的这段时长。可重入；未在限速时为 no-op。"""
        if self._since <= 0:
            return
        self._total += time.monotonic() - self._since
        self._since = 0.0

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #

    def _on_start(self) -> None:
        self._events += 1
        self._since = time.monotonic()
        self._log.warning(
            "出站限速桶已满（%d 条 / %.3gs），超出部分转入延迟队列；累计第 %d 次",
            self._capacity, self._interval, self._events,
        )

    def _on_end(self) -> None:
        self.close_window()
        self._log.info(
            "出站限速桶已排空，累计被限速 %.2fs（共 %d 次）",
            self._total, self._events,
        )
