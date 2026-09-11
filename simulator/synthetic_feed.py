"""
L6 — 合成行情源。
==================
唯一职责：实现 L0 的 ``FeedPort``，在没有任何 IBKR 连接的情况下产出与实盘
同构的 tick 流。

它的存在让整条链路变得**可验证**
--------------------------------
L1 到 L5 全部通过 L0 契约通信，因此把 ``IbkrFeed`` 换成 ``SyntheticFeed``
之后，状态层、特征层、序列化层、传输层一行都不用改。这既是"依赖倒置"的
收益，也是本项目唯一能在没有 TWS、没有行情权限的情况下跑通端到端的手段。

它还刻意注入两类"脏数据"用于验证防护逻辑：
* 全程叠加高斯噪声 → 检验毛刺过滤不会误杀正常点；
* 定期在最外侧两档注入倍数级 IV 尖峰 → 检验毛刺过滤确实拦得住分母效应。

依赖：L0、L6（Scenario / SimClock）。
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Callable

from config import loader
from contracts.enums import ConnectionState, FeedMode, OptionRight, StatusLevel
from contracts.ports import TickSink
from contracts.tick import (
    FeedStatus,
    OptionRef,
    OptionTick,
    QuoteTick,
    SpotTick,
    StatusEvent,
)

from simulator.scenario import Scenario

_APP = "app"
_SIM = "simulator"
_SUB = "subscription"


class SyntheticFeed:
    """``FeedPort`` 的离线实现。"""

    __slots__ = (
        "_session_clock", "_scenario", "_cfg",
        "_sink", "_rng", "_running", "_task", "_start_real",
        "_tick_interval", "_step", "_each_side", "_cap", "_noise_vol",
        "_spot_noise", "_glitch_interval", "_glitch_mult",
        "_status_interval", "_counts", "_last_status_at", "_last_glitch_at",
        "_expiry", "_subscribed", "_messages", "_mode", "_current_spot",
        "_reconnect_hook",
    )

    def __init__(self, app_cfg: dict, sim_cfg: dict, sub_cfg: dict, session_clock) -> None:
        m = _SIM
        self._session_clock = session_clock
        self._scenario = Scenario(sim_cfg)
        self._cfg = sim_cfg

        rate = loader.as_float(sim_cfg, "tick_rate_hz", module=m)
        self._tick_interval = 1.0 / max(rate, 0.1)
        self._step = loader.as_float(sim_cfg, "strike_step", module=m)

        # 窗口档位与订阅上限取自 subscription.json —— 与实盘用同一份定义，
        # 这样模拟出来的订阅数才真实反映 IBKR 的 100 条约束。
        self._each_side = loader.as_int(
            sub_cfg, "num_strikes_each_side", module=_SUB
        )
        self._cap = loader.as_int(
            sub_cfg, "max_total_subscriptions", module=_SUB
        )
        self._noise_vol = loader.as_float(sim_cfg, "noise_vol_points", module=m)
        self._spot_noise = loader.as_float(sim_cfg, "spot_noise_points", module=m)
        self._glitch_interval = loader.as_float(
            sim_cfg, "glitch_probe_interval_s", module=m
        )
        self._glitch_mult = loader.as_float(
            sim_cfg, "glitch_probe_multiplier", module=m
        )
        self._status_interval = loader.as_float(
            sim_cfg, "publish_status_every_s", module=m
        )

        self._rng = random.Random(loader.as_int(sim_cfg, "seed", module=m))
        self._sink: TickSink | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._start_real = 0.0
        self._counts = {"option": 0, "quote": 0, "spot": 0}
        self._last_status_at = 0.0
        self._last_glitch_at = 0.0
        self._expiry = ""
        self._subscribed = 0
        self._messages: list[str] = []
        self._mode = FeedMode.SIM
        self._current_spot: float = 0.0
        self._reconnect_hook: Callable[[], None] | None = None

    # ------------------------------------------------------------------ #
    # FeedPort
    # ------------------------------------------------------------------ #

    @property
    def mode(self) -> str:
        return str(self._mode)

    def set_sink(self, sink: TickSink) -> None:
        self._sink = sink

    def set_reconnect_hook(self, hook: Callable[[], None]) -> None:
        """
        见 ``contracts.ports.FeedPort.set_reconnect_hook``。

        模拟源不建连接，也就不会重连 —— 这个钩子只记录、永不触发。它存在的
        意义是让 ``SyntheticFeed`` 与 ``IbkrFeed`` 保持同一套接口，组装层才能
        在两种模式下无条件调用，而不必先探测"这个源支不支持重连"。
        """
        self._reconnect_hook = hook

    def status(self) -> FeedStatus:
        return FeedStatus(
            mode=self._mode,
            connection=(
                ConnectionState.CONNECTED if self._running
                else ConnectionState.DISCONNECTED
            ),
            subscribed=self._subscribed,
            subscription_cap=self._cap,
            ticks_received=self._counts["option"] + self._counts["spot"],
            ticks_dropped=0,
            sub_limit_backoff=False,
            expiry=self._expiry,
            spot=self._current_spot,
            messages=tuple(self._messages[-6:]),
        )

    async def start(self) -> None:
        if self._sink is None:
            raise RuntimeError("start() 之前必须先 set_sink()")
        if self._running:
            return

        self._expiry = self._session_clock.expiry_str()
        self._running = True
        self._start_real = time.monotonic()
        self._note(
            f"模拟行情启动：{loader.as_str(self._cfg, 'scenario', module=_SIM)}，"
            f"到期 {self._expiry}，加速 "
            f"{loader.as_float(self._cfg, 'session_speedup', module=_SIM):.0f}×"
        )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._note("模拟行情已停止")

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        close_epoch = self._session_clock.session_close_dt().timestamp()
        while self._running:
            now = self._session_clock.now_ts()
            if now >= close_epoch:
                self._note("会话已收盘，模拟行情结束")
                self._running = False
                break

            real_elapsed = time.monotonic() - self._start_real
            try:
                self._emit_cycle(now, real_elapsed)
            except Exception as exc:  # 单轮失败不能中断整条流
                self._note(f"模拟行情单轮异常: {exc}", StatusLevel.WARN)
            await asyncio.sleep(self._tick_interval)

    def _emit_cycle(self, now: float, real_elapsed: float) -> None:
        session_seconds = self._session_clock.elapsed_s()
        spot = self._scenario.spot_at(session_seconds, real_elapsed)
        spot += self._rng.gauss(0.0, self._spot_noise)
        spot = max(spot, 1.0)
        self._current_spot = spot

        self._sink.on_spot_tick(SpotTick(price=spot, ts=now))
        self._counts["spot"] += 1

        atm_iv = self._scenario.atm_iv_at(real_elapsed)
        strikes = self._scenario.strike_grid(spot, self._step, self._each_side)

        glitching = (
            self._glitch_interval > 0
            and real_elapsed - self._last_glitch_at >= self._glitch_interval
        )
        if glitching:
            self._last_glitch_at = real_elapsed

        outer = {strikes[0], strikes[1], strikes[-2], strikes[-1]}
        self._subscribed = len(strikes) * 2

        for strike in strikes:
            for right in (OptionRight.PUT, OptionRight.CALL):
                self._emit_option(now, strike, right, spot, atm_iv, glitching and strike in outer)

        if self._status_interval > 0 and real_elapsed - self._last_status_at >= self._status_interval:
            self._last_status_at = real_elapsed
            self._note(
                f"模拟进度 {session_seconds / 60.0:.0f} 分钟 | "
                f"现价 {spot:.1f} | ATM IV {atm_iv * 100:.2f}"
            )

    def _emit_option(
        self,
        now: float,
        strike: float,
        right: OptionRight,
        spot: float,
        atm_iv: float,
        glitch: bool,
    ) -> None:
        is_put = right is OptionRight.PUT
        iv = self._scenario.iv_at(strike, spot, atm_iv)
        iv += self._rng.gauss(0.0, self._noise_vol) / 100.0
        iv = max(iv, 0.005)

        if glitch:
            # 模拟下午盘深度虚值合约因分母效应产生的 IV 尖峰。
            iv *= self._glitch_mult

        delta = self._scenario.delta_for(strike, spot, is_put)
        price = self._option_price(strike, spot, iv, is_put)

        ref = OptionRef(strike=float(strike), right=right, expiry=self._expiry)
        self._sink.on_option_tick(
            OptionTick(
                ref=ref,
                iv=iv,
                ts=now,
                delta=delta,
                gamma=0.0,
                vega=0.0,
                theta=0.0,
                opt_price=price,
                und_price=spot,
                source_tick_type=13,
                model_greeks=True,
                con_id=0,
            )
        )
        self._counts["option"] += 1

        half = max(price * 0.02, 0.05)
        self._sink.on_quote_tick(
            QuoteTick(
                ref=ref,
                ts=now,
                bid=round(max(price - half, 0.01), 2),
                ask=round(price + half, 2),
                last=round(price, 2),
                close=round(price, 2),
                bid_size=10,
                ask_size=10,
                last_size=1,
            )
        )
        self._counts["quote"] += 1

    @staticmethod
    def _option_price(strike: float, spot: float, iv: float, is_put: bool) -> float:
        """
        粗略的期权价：内在价值 + 时间价值。

        时间价值用"平值最大、按虚实程度高斯衰减"的形态，量级对齐 0DTE SPX 的
        真实盘口，好让毛刺过滤的价格闸门有真实的东西可判。
        """
        intrinsic = max(0.0, (strike - spot) if is_put else (spot - strike))
        x = abs(strike / spot - 1.0) * 100.0
        decay = math.exp(-((x / 1.2) ** 2))
        time_value = max(spot * iv * 0.008 * decay, 0.05)
        return round(intrinsic + time_value, 2)

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #

    def _note(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        self._messages.append(message)
        if len(self._messages) > 32:
            del self._messages[:-32]
        if self._sink is not None:
            try:
                self._sink.on_status(
                    StatusEvent(
                        level=level,
                        source="sim",
                        message=message,
                        ts=self._session_clock.now_ts(),
                    )
                )
            except Exception:
                pass

    def counts(self) -> dict[str, int]:
        return dict(self._counts)
