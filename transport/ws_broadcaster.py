"""
L7 — WebSocket 广播器。
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

但"写不动是它自己的事"**不等于**"写不动了还留着它"
----------------------------------------------------
**注销由"发送协程结束"直接触发，不由 socket 关闭触发。** ``handle()`` 拿
``asyncio.wait({发送协程, 读协程}, FIRST_COMPLETED)`` 赛跑，谁先结束都立刻走
``_unregister``，与 socket 能不能写出去无关。

为什么不能写成"发送协程退出时关掉 ws，把读循环顶醒"（**实测走不通**）：对端不读
时发送缓冲是满的，``ws.close()`` 内部的 ``drain()`` 会挂住；即使超时后 aiohttp 去
关底层 transport，``transport.close()`` 也要等缓冲冲出去才真正断开 ⇒ 读循环**永远
不醒**（实测 ``ws.closed=True``、``transport.is_closing()=True``、
``ws._waiting=True`` 三者同时成立，客户端一直留在注册表里：``sent`` 冻结在 5044、
``dropped`` 单调涨到 20946、挂了 4 小时 11 分，全程无任何报错）。把不变量的成立
条件绑在"TCP 还写得动"上，等于没有不变量。

来历与逐段证据见 ``notes/sessions/2026-09-17/frontend-data-outage/handoff.md``。

依赖：L0、L1。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

from config import loader
from contracts.ports import PayloadSource
from core.clock import now_ts
from core.logging_setup import get_logger

_CFG = "transport"


@dataclass(slots=True)
class ClientStats:
    """单个客户端的运行统计。"""

    peer: str = ""
    sent: int = 0
    dropped: int = 0
    connected_at: float = 0.0
    #: 最近一次成功发出的时刻（``0.0`` = 一帧都没发出去过）。与 ``sent`` 的区别：
    #: ``sent`` 冻结只说明"没在发"，本字段能进一步区分"从没发过"和"发过又停了"。
    last_sent_at: float = 0.0
    #: 发送协程因异常/超时放弃该连接的次数。正常客户端恒为 0；非 0 即"这条连接是
    #: 被我们主动断掉的"，不必再去翻日志。
    send_failures: int = 0


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
    reader: asyncio.Task | None = None
    stats: ClientStats = field(default_factory=ClientStats)


class WsBroadcaster:
    """管理客户端集合与帧广播。"""

    __slots__ = (
        "_source", "_path", "_queue_size", "_max_clients",
        "_heartbeat", "_send_timeout", "_compress", "_clients",
        "_total_dropped", "_total_sent", "_log",
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
        # 用项目自己的命名空间，与 transport.access 同一约定。
        self._log = get_logger("transport.ws")

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
        client.reader = asyncio.create_task(self._reader(client))

        # 新连接立刻补一帧，避免前端空等到下一次推送。
        payload = self._source.latest_payload()
        if payload is not None:
            self._offer(client, payload[0])

        try:
            # 注销由**任一侧结束**触发 —— 这是本文件的核心不变量。
            #
            # 旧写法是就地 `async for message in ws:`，那个循环只能靠 socket 被关掉
            # 才结束（前端从不发上行消息）；而发送协程因超时放弃时并不保证关得掉
            # socket（见模块头部实测）⇒ 循环永不结束 ⇒ `finally` 永不执行 ⇒
            # 客户端变僵尸。改成赛跑后，"发送协程死了"这件事本身就足以触发注销，
            # 与 socket 状态解耦。
            await asyncio.wait(
                {client.task, client.reader},
                return_when=asyncio.FIRST_COMPLETED,
            )
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

        异常一律就地吞掉，绝不向上冒泡影响行情主循环；但**吞掉不等于装作没发生**：
        记一条 WARN、累加 ``send_failures``。本协程一旦退出（正常 ``break``、异常、
        或被取消），``handle()`` 的赛跑立刻结束并注销该客户端 —— 注销不依赖本协程
        去关 socket（那样关不掉，见模块头部实测）。
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
                client.stats.last_sent_at = now_ts()
                self._total_sent += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 含 send 超时：这个客户端写不动了，放弃它即可。
            client.stats.send_failures += 1
            self._log.warning(
                "客户端 %s 发送失败（%s），已发 %d 帧 / 丢 %d 帧，放弃该连接",
                client.stats.peer, f"{type(exc).__name__}: {exc}",
                client.stats.sent, client.stats.dropped,
            )

    async def _reader(self, client: _Client) -> None:
        """
        读循环：只负责感知"前端断开"与上行消息，本身不产出任何数据。

        单独成协程（而不是就地写在 ``handle()`` 里）是为了让它能与发送协程赛跑，
        从而让注销与 socket 状态解耦 —— 理由见 ``handle()`` 里的说明。
        """
        async for message in client.ws:
            if message.type is WSMsgType.ERROR:
                return
            # 前端目前不需要上行指令；收到文本就回一帧最新数据。
            if message.type is WSMsgType.TEXT:
                latest = self._source.latest_payload()
                if latest is not None:
                    self._offer(client, latest[0])

    async def _unregister(self, client: _Client) -> None:
        """
        注销客户端：移出注册表 + 收拾两个协程与连接。

        **先移出注册表，再清理** —— 顺序不能反：注册表才是 ``max_clients`` 名额与
        丢帧统计的依据；而清理可能慢（对端不读时 ``ws.close()`` 会卡在 drain 上），
        不能让它继续占着名额。
        """
        self._clients.discard(client)

        tasks = [t for t in (client.task, client.reader) if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            # 全部 await 一遍：既保证它们真的结束（不留 "Task was destroyed but it
            # is pending"），也顺手取走异常，避免 "never retrieved" 噪音。
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        try:
            # 带超时：对端不读时 close() 内部的 drain 会挂住，这里绝不能再挂。
            # 关不掉也无妨 —— 客户端已经不在注册表里，等对端能读了缓冲自然会冲出去。
            await asyncio.wait_for(client.ws.close(), timeout=self._send_timeout)
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
                    # **派生**，不另存字段：只有 task 的生死是唯一真相，
                    # 另存一个布尔量就会和它漂移。
                    "sender_alive": c.task is not None and not c.task.done(),
                    "last_sent_age_s": (
                        round(now_ts() - c.stats.last_sent_at, 1)
                        if c.stats.last_sent_at else None
                    ),
                    "send_failures": c.stats.send_failures,
                }
                for c in self._clients
            ],
        }
