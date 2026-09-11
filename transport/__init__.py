"""
L5 — 传输层。

职责边界
--------
把 L4 产出的成品 JSON 文本推给浏览器，并顺带服务前端静态页。

* 只认识 L0 的 ``PayloadSource`` 协议，不知道帧里有什么字段。
* **不阻塞生产者**：慢客户端丢帧，而不是让特征循环等待。
* 不参与任何业务计算。

只依赖 L0 与 L5 内部。
"""

from transport.http_static import StaticHandler
from transport.push_loop import PushLoop
from transport.server import TransportServer
from transport.ws_broadcaster import ClientStats, WsBroadcaster

__all__ = [
    "ClientStats",
    "PushLoop",
    "StaticHandler",
    "TransportServer",
    "WsBroadcaster",
]
