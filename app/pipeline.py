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
from core.clock import SessionClock, WallClock
from core.logging_setup import configure, get_logger

from state.market_state import MarketState
from state.tick_store import TickStore
from features.feature_engine import FeatureEngine
from features.persistence import AsyncPersistenceWriter
from serialization.payload_builder import PayloadBuilder
from transport.server import TransportServer

_APP = "app"
_PIPE = "pipeline"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Pipeline:
    """把各层装配成可运行的系统。"""

    def __init__(self) -> None:
        self._cfg = {
            "app": loader.load("app"),
            "ibkr": loader.load("ibkr"),
            "subscription": loader.load("subscription"),
            "state": loader.load("state"),
            "features": loader.load("features"),
            "serialization": loader.load("serialization"),
            "transport": loader.load("transport"),
            "pipeline": loader.load("pipeline"),
            "persistence": loader.load("persistence"),
        }

        self._log = get_logger("pipeline")
        self._clock = self._build_clock()
        self._store = TickStore(self._cfg["state"], self._clock)
        self._market = MarketState(self._store, self._cfg["state"], self._clock)
        self._writer = AsyncPersistenceWriter(self._cfg["persistence"])
        self._engine = FeatureEngine(
            self._store, self._clock, self._cfg["features"],
            self._cfg["serialization"], self._writer,
        )
        self._builder = PayloadBuilder(self._market, self._cfg["serialization"], self._clock)
        self._server = TransportServer(
            self._cfg["transport"], self._builder, PROJECT_ROOT
        )
        self._feed = self._build_feed()
        # 重连后是否清空特征累积状态。默认 false，即接线只为让这个键可切换，
        # 行为与接线之前完全一致。
        self._reset_on_reconnect = loader.as_bool(
            self._cfg["pipeline"], "reset_feature_state_on_reconnect", module=_PIPE
        )
        self._feed.set_reconnect_hook(self._on_feed_reconnect)
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

        return SessionClock(tz, open_hm, close_hm, bucket, clock=WallClock())

    def _build_feed(self):
        """
        实例化行情源。

        ``ib_async`` 的 import 写在这里（延迟导入）而不是模块顶部：它是本工程
        唯一的重依赖，``run.py --check`` 与 ``tools/`` 下的离线回归都不该被它
        拖住（缺包时自检仍要能跑完）。
        """
        from acquisition.feed_service import IbkrFeed

        self._log.info("行情源: IbkrFeed（IBKR）")
        return IbkrFeed(
            self._cfg["app"], self._cfg["ibkr"], self._cfg["subscription"], self._clock
        )

    def _on_feed_reconnect(self) -> None:
        """
        行情源重连成功后的回调（L1 通过 ``FeedPort.set_reconnect_hook`` 触发）。

        为什么要清空特征状态
        --------------------
        断线期间 IV 序列是断的，重连后的第一笔数据与断线前的最后一点之间隔着
        几分钟。IV 冲量按时间窗做差，这个跨断线的落差会被算成一次**从未发生过
        的剧烈冲量**，在热力图上表现为一整列假信号 —— 而且它看起来和真实行情
        完全一样，前端无法分辨。

        为什么这条链路要绕组装层
        ------------------------
        L1 不认识 L3，直接调用就是反向依赖。所以 L1 只报告"我重连了"，由组装层
        决定要不要清状态 —— 这是本项目唯一允许同时看见两层的角色。

        默认不清（``reset_feature_state_on_reconnect=false``）。清空的代价是
        重连后要重新积累 60/300 秒的数据，前端会有一段空窗；是否划算取决于
        实盘断线频率，所以这是个配置项而不是写死的策略。
        """
        if not self._reset_on_reconnect:
            return
        self._engine.reset()
        self._log.info("已按配置清空特征累积状态（避免跨断线的假冲量）")

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

        await self._writer.start()
        recovered = self._writer.recover()
        if recovered:
            self._engine.restore_heatmap(recovered)
            self._log.info("已从 SQLite 恢复 %d 个历史桶", len(recovered))

        recovered_skew = self._writer.recover_skew()
        if recovered_skew:
            self._engine.restore_skew(recovered_skew)
            self._log.info("已从 SQLite 恢复 %d 个历史 Skew 点", len(recovered_skew))

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
        timeout = loader.as_float(
            self._cfg["pipeline"], "shutdown_timeout_s", module=_PIPE
        )

        pending = [t for t in self._tasks if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            _, stuck = await asyncio.wait(pending, timeout=timeout)
            if stuck:
                self._log.warning(
                    "%d 个后台任务 %.0fs 内未结束，强制继续关闭", len(stuck), timeout
                )
        self._tasks = []

        await self._shutdown_step(self._feed.stop(), "feed 关闭", timeout)
        await self._shutdown_step(self._server.stop(), "server 关闭", timeout)
        await self._shutdown_step(self._writer.stop(), "持久化关闭", timeout)

        self._log.info("已停止")

    async def _shutdown_step(self, coro, what: str, timeout: float) -> None:
        """
        执行一个停机动作，超时就**放弃等待**、继续往下走。

        为什么用 ``asyncio.wait`` 而不是 ``wait_for``
        --------------------------------------------
        ``wait_for`` 超时后会 cancel 目标，然后**继续等它结束**。如果那个协程在
        收到取消之后还要跑很久（卡在一次耗时的网络清理里），``wait_for`` 会跟着
        一起卡住 —— 所谓"超时上限"就是假的。这一点在本轮的非空转验证里被实测
        抓到过：一个普通任务被取消后瞬间结束，``stop()`` 耗时 0.0s，超时分支根本
        没被走到。

        ``asyncio.wait`` 超时后把未完成的任务留在 ``pending`` 里**直接返回**，
        调用方不等它 —— 这才是"保底退出"该有的语义。

        代价：超时后那个任务可能仍在后台跑，进程退出时 asyncio 可能打印
        "Task was destroyed but it is pending"。这是**故意**的取舍 —— 宁可留一行
        警告，也不要让 Ctrl-C 之后程序毫无反应。

        另一个刻意的选择：不再吞 ``CancelledError``。旧写法
        ``except (asyncio.CancelledError, Exception): pass`` 会把取消异常吃掉，
        于是"取消成功"变成假象 —— 任务可能根本没结束，调用方却以为收干净了。
        """
        task = asyncio.ensure_future(coro)
        _, pending = await asyncio.wait({task}, timeout=timeout)
        if pending:
            task.cancel()
            self._log.warning("%s 超时 %.0fs，强制继续关闭", what, timeout)
            return
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._log.warning("%s 异常: %s", what, exc)

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
        # 节奏取自 L2 自己的配置，而不是 pipeline.json —— 裁剪间隔是状态层的
        # 参数，组装层只负责按它驱动循环。
        interval = self._store.prune_interval_s
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
        return str(self._feed.mode)

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
