"""
L5 — 传输服务装配。
====================
唯一职责：把静态页、WebSocket、健康检查挂到同一个 aiohttp 应用上，并管理
服务器与推送循环的生命周期。

同端口的意义
------------
前端页面和 WebSocket 共用一个端口，意味着部署时只需要放行一个端口、前端不需要
关心跨域、也不需要为 WS 单独配反向代理。对一个本地盯盘工具，这能省掉一整类
"连不上"的排查。

依赖：L0、L5 内部。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiohttp import web

from config import loader
from contracts.ports import PayloadSource
from core.clock import now_ts

from transport.http_static import StaticHandler
from transport.push_loop import PushLoop
from transport.ws_broadcaster import WsBroadcaster

_CFG = "transport"


class TransportServer:
    """HTTP + WebSocket 服务器。"""

    __slots__ = (
        "_cfg", "_source", "_host", "_port", "_health_path",
        "_broadcaster", "_static", "_push", "_app", "_runner", "_site",
    )

    def __init__(
        self,
        transport_cfg: dict,
        source: PayloadSource,
        base_dir: Path,
    ) -> None:
        self._cfg = transport_cfg
        self._source = source
        self._host = loader.as_str(transport_cfg, "host", module=_CFG)
        self._port = loader.as_int(transport_cfg, "http_port", module=_CFG)
        self._health_path = loader.as_str(transport_cfg, "health_path", module=_CFG)

        self._broadcaster = WsBroadcaster(transport_cfg, source)
        self._static = StaticHandler(transport_cfg, base_dir)
        self._push = PushLoop(source, self._broadcaster, transport_cfg)

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # ------------------------------------------------------------------ #
    # 属性
    # ------------------------------------------------------------------ #

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/"

    @property
    def ws_url(self) -> str:
        return f"ws://{self._host}:{self._port}{self._broadcaster.path}"

    @property
    def static_enabled(self) -> bool:
        return self._static.enabled

    @property
    def static_root(self) -> Path:
        return self._static.root

    @property
    def client_count(self) -> int:
        return self._broadcaster.client_count

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._runner is not None:
            return

        app = web.Application()
        app.router.add_get(self._broadcaster.path, self._broadcaster.handle)
        app.router.add_get(self._health_path, self._handle_health)
        app.router.add_get("/runtime-config.js", self._handle_runtime_config)
        self._static.register(app)

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()

        self._app = app
        self._runner = runner
        self._site = site

        await self._push.start()

    async def stop(self) -> None:
        await self._push.stop()
        await self._broadcaster.close_all()

        site, self._site = self._site, None
        runner, self._runner = self._runner, None
        self._app = None

        if site is not None:
            try:
                await site.stop()
            except Exception:
                pass
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #

    async def _handle_runtime_config(self, request: web.Request) -> web.Response:
        """
        把运行期配置注入前端。

        前端需要知道 WS 路径、推送间隔这些值，但它们都定义在
        ``config/transport.json`` 里。让前端复制一份就等于制造"两份真相"，
        改一处忘一处必然连不上。这里由后端把当前生效的值直接吐成一段 JS，
        前端读取 ``window.SWATCH_RUNTIME`` 即可——零重复、零漂移。
        """
        body = json.dumps(
            {
                "wsPath": self._broadcaster.path,
                "healthPath": self._health_path,
                "pushIntervalMs": int(round(self._push.interval_s * 1000)),
                "host": self._host,
                "port": self._port,
            },
            separators=(",", ":"),
        )
        return web.Response(
            text=f"window.SWATCH_RUNTIME={body};",
            content_type="application/javascript",
            charset="utf-8",
            headers={"Cache-Control": "no-store"},
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        payload = self._source.latest_payload()
        return web.json_response(
            {
                "ts": now_ts(),
                "ws_path": self._broadcaster.path,
                "frames": self._source.frame_count(),
                "latest_seq": payload[1] if payload else None,
                "payload_bytes": len(payload[0]) if payload else 0,
                "clients": self._broadcaster.stats(),
                "push": self._push.stats(),
                "static_root": str(self._static.root),
                "static_enabled": self._static.enabled,
            }
        )

    def stats(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "clients": self._broadcaster.client_count,
            "broadcaster": self._broadcaster.stats(),
            "push": self._push.stats(),
        }
