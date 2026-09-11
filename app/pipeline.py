"""
L6 — 组装根（Composition Root）。
==================================
唯一职责：读配置、按 L0 → L5 的顺序把各层实例化并接线，然后驱动两条循环
（特征计算、内存裁剪）。

本文件是整个工程里**唯一**允许同时 import 所有层的模块。其它任何文件出现
"跨层 import" 都是架构违规。它本身不含业务逻辑：所有决策（窗口多大、几秒
算一次、毛刺怎么判）都在配置与各层内部，这里只负责把它们串起来。

数据流（严格单向）
------------------
::

    feed (L1)  ──tick──▶  store (L2)  ──series──▶  engine (L3)
                                                        │
                                                      bundle
                                                        ▼
                              server (L5)  ◀──json──  builder (L4)

反向没有任何一条路径：传输层拿不到 store，特征层拿不到 socket，行情层不知道
特征层的存在。这正是"前端卡顿不影响行情连接"的结构保证。

依赖：全部。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from config import loader
from contracts.enums import FeedMode
from core.clock import SessionClock, WallClock
from core.logging_setup import configure, get_logger

from state.market_state import MarketState
from state.tick_store import TickStore
from features.feature_engine import FeatureEngine
from serialization.payload_builder import PayloadBuilder
from transport.server import TransportServer

_APP = "app"
_PIPE = "pipeline"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Pipeline:
    """把各层装配成可运行的系统。"""

    def __init__(self, *, simulate: bool | None = None) -> None:
        self._cfg = {
            "app": loader.load("app"),
            "ibkr": loader.load("ibkr"),
            "subscription": loader.load("subscription"),
            "state": loader.load("state"),
            "features": loader.load("features"),
            "serialization": loader.load("serialization"),
            "transport": loader.load("transport"),
            "simulator": loader.load("simulator"),
            "pipeline": loader.load("pipeline"),
        }

        if simulate is None:
            simulate = loader.as_bool(self._cfg["simulator"], "enabled", module="simulator")
        self._simulate = bool(simulate)

        self._log = get_logger("pipeline")
        self._clock = self._build_clock()
        self._store = TickStore(self._cfg["state"], self._clock)
        self._market = MarketState(self._store, self._cfg["state"], self._clock)
        self._engine = FeatureEngine(
            self._store, self._clock, self._cfg["features"], self._cfg["serialization"]
        )
        self._builder = PayloadBuilder(self._market, self._cfg["serialization"], self._clock)
        self._server = TransportServer(
            self._cfg["transport"], self._builder, PROJECT_ROOT
        )
        self._feed = self._build_feed()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._frames_built = 0

    # ------------------------------------------------------------------ #
    # 装配
    # ------------------------------------------------------------------ #

    def _build_clock(self) -> SessionClock:
        app = self._cfg["app"]
        serial = self._cfg["serialization"]
        tz = loader.as_str(app, "timezone", module=_APP)
        open_hm = loader.as_str(app, "session_open", module=_APP)
        close_hm = loader.as_str(app, "session_close", module=_APP)
        bucket = loader.as_int(serial, "heatmap_bucket_seconds", module="serialization")

        if self._simulate:
            from simulator.sim_clock import SimClock

            source = SimClock(
                tz,
                open_hm,
                loader.as_float(self._cfg["simulator"], "session_speedup", module="simulator"),
            )
        else:
            source = WallClock()

        return SessionClock(tz, open_hm, close_hm, bucket, clock=source)

    def _build_feed(self):
        """
        按模式实例化行情源。

        两个分支的 import 都写在这里（延迟导入）：离线模式下永远不会去加载
        ``ib_async``，实盘模式下也不会加载模拟器。
        """
        if self._simulate:
            from simulator.synthetic_feed import SyntheticFeed

            self._log.info("行情源: SyntheticFeed（离线模拟）")
            return SyntheticFeed(
                self._cfg["app"], self._cfg["simulator"],
                self._cfg["subscription"], self._clock,
            )

        from acquisition.feed_service import IbkrFeed

        self._log.info("行情源: IbkrFeed（IBKR 实盘/延迟）")
        return IbkrFeed(
            self._cfg["app"], self._cfg["ibkr"], self._cfg["subscription"], self._clock
        )

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._running:
            return

        configure(loader.load("logging"))
        self._log.info("启动 %s | 到期 %s | 会话 %s",
                       self.mode, self._clock.expiry_str(), self._clock.describe())

        await self._server.start()
        if not self._server.static_enabled:
            self._log.warning(
                "前端静态目录缺失，浏览器将打不开页面：%s", self._server.static_root
            )
        self._log.info("界面地址 %s | 行情通道 %s", self._server.url, self._server.ws_url)

        self._feed.set_sink(self._store)
        self._running = True

        grace = loader.as_float(self._cfg["pipeline"], "startup_grace_s", module=_PIPE)
        await asyncio.sleep(grace)

        await self._feed.start()

        self._tasks = [
            asyncio.create_task(self._compute_loop(), name="compute"),
            asyncio.create_task(self._prune_loop(), name="prune"),
            asyncio.create_task(self._stats_loop(), name="stats"),
        ]
        self._log.info("流水线已就绪")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []

        for closer, name in ((self._feed.stop, "feed"), (self._server.stop, "server")):
            try:
                await closer()
            except Exception as exc:
                self._log.warning("%s 关闭异常: %s", name, exc)

        self._log.info("已停止")

    async def run_until_cancelled(self) -> None:
        """阻塞直到被外部取消（Ctrl-C 或信号）。"""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        finally:
            await self.stop()

    # ------------------------------------------------------------------ #
    # 循环
    # ------------------------------------------------------------------ #

    async def _compute_loop(self) -> None:
        """
        特征计算循环。

        它是"生产者"，只做一件事：算一轮 → 交给 L4 编码。传输层是否有人在听、
        前端是否卡住，在这里完全不可见。
        """
        interval = (
            loader.as_int(self._cfg["pipeline"], "compute_interval_ms", module=_PIPE)
            / 1000.0
        )
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                bundle = self._engine.compute()
                self._builder.build(bundle, self._feed.status())
                self._frames_built += 1
            except Exception as exc:
                self._log.exception("特征计算异常: %s", exc)

    async def _prune_loop(self) -> None:
        interval = loader.as_float(self._cfg["pipeline"], "prune_interval_s", module=_PIPE)
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                self._store.prune()
            except Exception as exc:
                self._log.warning("裁剪异常: %s", exc)

    async def _stats_loop(self) -> None:
        interval = loader.as_float(
            self._cfg["pipeline"], "log_stats_every_s", module=_PIPE
        )
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            stats = self.stats()
            self._log.info(
                "帧 %d | 客户端 %d | 分片 %d | 现价 %.2f | 订阅 %d/%d",
                stats["frames"], stats["clients"], stats["store"]["cells"],
                stats["spot"], stats["subscribed"], stats["subscription_cap"],
            )

    # ------------------------------------------------------------------ #
    # 只读信息
    # ------------------------------------------------------------------ #

    @property
    def mode(self) -> str:
        return str(FeedMode.SIM) if self._simulate else str(self._feed.mode)

    @property
    def url(self) -> str:
        return self._server.url

    @property
    def running(self) -> bool:
        return self._running

    def stats(self) -> dict[str, Any]:
        status = self._feed.status()
        return {
            "mode": self.mode,
            "frames": self._frames_built,
            "clients": self._server.client_count,
            "spot": self._market.spot_with_fallback(status),
            "subscribed": status.subscribed,
            "subscription_cap": status.subscription_cap,
            "expiry": self._clock.expiry_str(),
            "session": self._clock.describe(),
            "store": self._store.snapshot_meta(),
            "transport": self._server.stats(),
        }
