"""
L5 — WebSocket 广播器。
=======================
唯一职责：把成品 JSON 文本推给所有已连接的前端，并保证**慢客户端只伤害它自己**。

Fail-Closed 的实现方式
----------------------
需求原文是"保证图形渲染或前端卡顿绝不影响后台底层连接的稳定性"。做法不是加
重试、也不是加超时，而是**结构上让生产者永远不等待消费者**：

* 每个客户端一条独立队列，容量由 ``client_queue_size`` 决定（默认 1）。
* 广播时用 ``put_nowait``；队列满就直接丢掉最旧的一帧，绝不 ``await``。
* 每客户端一个独立发送协程负责真正写 socket，写不动是它自己的事。

于是"前端卡住"最多导致该前端自己掉帧，行情通道、特征计算、其他前端全部不受
影响。丢帧数会被统计并展示在健康面板上——静默丢帧是不可接受的。

依赖：L0。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

from config import loader
from contracts.ports import PayloadSource
from core.clock import now_ts

_CFG = "transport"


@dataclass(slots=True)
class ClientStats:
    """单个客户端的运行统计。"""

    peer: str = ""
    sent: int = 0
    dropped: int = 0
    connected_at: float = 0.0


@dataclass(slots=True, eq=False)
class _Client:
    """
    单个已连接客户端。

    刻意用 ``eq=False``：dataclass 默认会按字段生成 ``__eq__`` 并把
    ``__hash__`` 置为 ``None``，那样实例就无法放进 ``set``。客户端注册表要的是
    **身份**语义（同一个对象才算同一个客户端），而不是值相等语义。
    """

    ws: web.WebSocketResponse
    queue: asyncio.Queue
    task: asyncio.Task | None = None
    stats: ClientStats = field(default_factory=ClientStats)


class WsBroadcaster:
    """管理客户端集合与帧广播。"""

    __slots__ = (
        "_source", "_path", "_queue_size", "_max_clients",
        "_heartbeat", "_send_timeout", "_compress", "_clients",
        "_total_dropped", "_total_sent",
    )

    def __init__(self, transport_cfg: dict, source: PayloadSource) -> None:
        self._source = source
        self._path = loader.as_str(transport_cfg, "ws_path", module=_CFG)
        self._queue_size = max(
            loader.as_int(transport_cfg, "client_queue_size", module=_CFG), 1
        )
        self._max_clients = loader.as_int(transport_cfg, "max_clients", module=_CFG)
        self._heartbeat = loader.as_float(
            transport_cfg, "heartbeat_interval_s", module=_CFG
        )
        self._send_timeout = loader.as_float(
            transport_cfg, "send_timeout_s", module=_CFG
        )
        self._compress = loader.as_bool(
            transport_cfg, "ws_compression", module=_CFG
        )
        self._clients: set[_Client] = set()
        self._total_dropped = 0
        self._total_sent = 0

    # ------------------------------------------------------------------ #
    # 路由
    # ------------------------------------------------------------------ #

    @property
    def path(self) -> str:
        return self._path

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """``GET /ws`` 的处理函数。"""
        if len(self._clients) >= self._max_clients:
            raise web.HTTPServiceUnavailable(
                text=f"已达最大客户端数 {self._max_clients}"
            )

        # compress 显式传参，不吃 aiohttp 的库默认值 —— 这一项开关一次就是
        # 4.41GB/日 ↔ 0.40GB/日（实测 11 倍）。靠库默认值意味着：库升级改了默认、
        # 或有人顺手写成 compress=False，线上流量会静默翻十倍而没有任何检查会红。
        ws = web.WebSocketResponse(
            heartbeat=self._heartbeat,
            max_msg_size=0,
            compress=self._compress,
        )
        await ws.prepare(request)

        client = _Client(
            ws=ws,
            queue=asyncio.Queue(maxsize=self._queue_size),
            stats=ClientStats(
                peer=str(request.remote or "?"), connected_at=now_ts()
            ),
        )
        self._clients.add(client)
        client.task = asyncio.create_task(self._sender(client))

        # 新连接立刻补一帧，避免前端空等到下一次推送。
        payload = self._source.latest_payload()
        if payload is not None:
            self._offer(client, payload[0])

        try:
            async for message in ws:
                if message.type is WSMsgType.ERROR:
                    break
                # 前端目前不需要上行指令；收到文本就回一帧最新数据。
                if message.type is WSMsgType.TEXT:
                    latest = self._source.latest_payload()
                    if latest is not None:
                        self._offer(client, latest[0])
        finally:
            await self._unregister(client)

        return ws

    # ------------------------------------------------------------------ #
    # 广播
    # ------------------------------------------------------------------ #

    def broadcast(self, text: str) -> int:
        """
        把一帧推给所有客户端，返回实际入队的客户端数。

        **同步方法，绝不 await**——这是 fail-closed 的关键。生产者（特征循环）
        调用它时不可能被任何慢客户端阻塞。
        """
        if not self._clients:
            return 0
        delivered = 0
        for client in tuple(self._clients):
            if self._offer(client, text):
                delivered += 1
        return delivered

    def _offer(self, client: _Client, text: str) -> bool:
        """入队；队列满则丢最旧的一帧。返回是否成功入队。"""
        try:
            client.queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            pass

        # 丢掉最旧的，再放最新的：宁可少几帧，也要让画面停在"最近"而不是"最早"。
        try:
            client.queue.get_nowait()
            client.stats.dropped += 1
            self._total_dropped += 1
        except asyncio.QueueEmpty:
            pass

        try:
            client.queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            return False

    # ------------------------------------------------------------------ #
    # 客户端生命周期
    # ------------------------------------------------------------------ #

    async def _sender(self, client: _Client) -> None:
        """
        每客户端一个发送协程。

        写 socket 带超时：一个 TCP 接收窗口被打满的客户端会让 ``send_str``
        长时间挂住。超时后直接放弃该连接——继续等它只会拖住这个协程和内存。
        异常一律就地吞掉，绝不向上冒泡影响行情主循环。
        """
        try:
            while True:
                text = await client.queue.get()
                if client.ws.closed:
                    break
                await asyncio.wait_for(
                    client.ws.send_str(text), timeout=self._send_timeout
                )
                client.stats.sent += 1
                self._total_sent += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            # 含 send 超时：这个客户端写不动了，放弃它即可。
            pass

    async def _unregister(self, client: _Client) -> None:
        self._clients.discard(client)
        task = client.task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            if not client.ws.closed:
                await client.ws.close()
        except Exception:
            pass

    async def close_all(self) -> None:
        for client in tuple(self._clients):
            await self._unregister(client)

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def stats(self) -> dict[str, Any]:
        return {
            "clients": len(self._clients),
            "sent": self._total_sent,
            "dropped": self._total_dropped,
            "per_client": [
                {
                    "peer": c.stats.peer,
                    "sent": c.stats.sent,
                    "dropped": c.stats.dropped,
                    "age_s": round(now_ts() - c.stats.connected_at, 1),
                }
                for c in self._clients
            ],
        }
