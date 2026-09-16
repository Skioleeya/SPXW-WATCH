"""
L7 — 静态页服务。
==================
唯一职责：把 ``web/`` 目录挂到 HTTP 路由上，让浏览器能打开前端页面。

安全边界
--------
只暴露 ``static_dir`` 这一棵子树，且路径解析后必须仍在该子树内——否则
``GET /../../config/ibkr.json`` 这类路径穿越请求会把配置甚至源码读出去。
本地工具同样要做这个检查：默认监听 127.0.0.1，但端口可能被局域网其他进程
代理出去。

依赖：L0。
"""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from config import loader

_CFG = "transport"

# 前端只需要这几种类型；其余一律按下载处理。
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class StaticHandler:
    """``web/`` 目录的只读服务。"""

    __slots__ = ("_root", "_index", "_enabled")

    def __init__(self, transport_cfg: dict, base_dir: Path) -> None:
        raw = loader.as_str(transport_cfg, "static_dir", module=_CFG)
        self._index = loader.as_str(transport_cfg, "http_index_file", module=_CFG)
        candidate = (base_dir / raw).resolve()
        self._root = candidate
        self._enabled = candidate.is_dir()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------ #
    # 路由
    # ------------------------------------------------------------------ #

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """``GET /{tail:.*}`` 的处理函数。"""
        if not self._enabled:
            raise web.HTTPServiceUnavailable(
                text=f"静态目录不存在: {self._root}"
            )

        tail = request.match_info.get("tail", "")
        target = self._resolve(tail)
        if target is None:
            raise web.HTTPNotFound(text=f"未找到 {tail or self._index}")

        return web.FileResponse(
            path=target,
            headers={
                "Content-Type": _CONTENT_TYPES.get(
                    target.suffix.lower(), "application/octet-stream"
                ),
                # 开发期必须禁缓存，否则改了 JS 刷新看不到效果。
                "Cache-Control": "no-store",
            },
        )

    def _resolve(self, tail: str) -> Path | None:
        """
        把请求路径解析成磁盘路径。

        解析后必须仍位于 ``_root`` 之内，否则判定为路径穿越。
        """
        relative = tail.strip("/") or self._index
        candidate = (self._root / relative).resolve()

        if not self._is_within(candidate):
            return None
        if candidate.is_dir():
            candidate = (candidate / self._index).resolve()
            if not self._is_within(candidate):
                return None
        if not candidate.is_file():
            return None
        return candidate

    def _is_within(self, path: Path) -> bool:
        try:
            path.relative_to(self._root)
        except ValueError:
            return False
        return True

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #

    def register(self, app: web.Application) -> None:
        app.router.add_get("/", self.handle)
        app.router.add_get("/{tail:.*}", self.handle)
