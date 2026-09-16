"""
L7 — 推送循环。
================
唯一职责：按固定节奏检查"是否产出了新帧"，有则广播。

为什么按"帧序号变化"而不是"定时无条件推"
----------------------------------------
行情不动的时候（比如午后死水），特征循环仍然在跑，但产出内容完全相同。无条件
推送只会白烧带宽和前端重绘。这里只在 ``seq`` 变化时推，另外用
``heartbeat_interval_s`` 兜底重发一次，让长时间无行情的前端也能确认链路还活着。

依赖：L0。
"""

from __future__ import annotations

import asyncio
from typing import Any

from config import loader
from contracts.ports import PayloadSource
from core.clock import now_ts

_CFG = "transport"


class PushLoop:
    """把最新帧按节奏广播出去。"""

    __slots__ = (
        "_source", "_broadcaster", "_interval", "_heartbeat",
        "_running", "_task", "_last_seq", "_last_push_at",
        "_pushed", "_skipped", "_heartbeats",
    )

    def __init__(
        self,
        source: PayloadSource,
        broadcaster: Any,
        transport_cfg: dict,
    ) -> None:
        self._source = source
        self._broadcaster = broadcaster
        self._interval = (
            loader.as_int(transport_cfg, "push_interval_ms", module=_CFG) / 1000.0
        )
        self._heartbeat = loader.as_float(
            transport_cfg, "heartbeat_interval_s", module=_CFG
        )
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_seq = -1
        self._last_push_at = 0.0
        self._pushed = 0
        self._skipped = 0
        self._heartbeats = 0

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            if not self._running:
                break
            try:
                self.tick()
            except Exception:
                # 单次推送失败不能打断循环，否则前端会永久静默。
                continue

    # ------------------------------------------------------------------ #
    # 单次
    # ------------------------------------------------------------------ #

    def tick(self) -> int:
        """检查一次并广播，返回送达的客户端数。"""
        payload = self._source.latest_payload()
        if payload is None:
            self._skipped += 1
            return 0

        text, seq = payload
        # 这里刻意用墙钟而不是会话时钟：心跳间隔是**真实时间**概念（"20 秒没推
        # 就补发一次"），用被加速的会话时钟会让心跳在离线夹具下快 60 倍。
        moment = now_ts()
        fresh = seq != self._last_seq
        stale_but_alive = (moment - self._last_push_at) >= self._heartbeat

        if not fresh and not stale_but_alive:
            self._skipped += 1
            return 0

        if not fresh:
            self._heartbeats += 1

        delivered = self._broadcaster.broadcast(text)
        self._last_seq = seq
        self._last_push_at = moment
        self._pushed += 1
        return delivered

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #

    @property
    def interval_s(self) -> float:
        return self._interval

    def stats(self) -> dict[str, Any]:
        return {
            "interval_ms": round(self._interval * 1000.0, 1),
            "pushed": self._pushed,
            "skipped": self._skipped,
            "heartbeats": self._heartbeats,
            "last_seq": self._last_seq,
        }
