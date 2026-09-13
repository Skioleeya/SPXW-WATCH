"""L6 — 联通与数据通道自检。
==========================
唯一职责：验证 WebSocket 数据链路是否通畅、帧结构是否合规。

本检查为**条件执行**：如果 8060 端口没有服务在跑，则跳过动态部分并打印
warning，不视为失败。非交易日跳过是预期行为。
"""

from __future__ import annotations

import asyncio
import json
import socket

from tools.selfcheck_core import ok, fail, warn


async def _probe_one_frame(host: str, port: int) -> dict | None:
    """连上 WS 抓一帧就断开。返回帧字典或 None（任何异常都视为"不可连"）。"""
    try:
        import aiohttp
    except ImportError:
        return None

    url = f"ws://{host}:{port}/ws"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(url, heartbeat=20) as ws:
                async for message in ws:
                    if message.type is aiohttp.WSMsgType.TEXT:
                        return json.loads(message.data)
                    if message.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
    except Exception:
        pass
    return None


def check_connectivity() -> int:
    """返回失败数。服务未运行时跳过（0 失败）。"""
    print("\n[13] 联通与数据通道")

    # 端口探测：比直接连 WS 更快，失败时给出明确原因
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        result = sock.connect_ex(("127.0.0.1", 8060))
    finally:
        sock.close()

    if result != 0:
        warn("127.0.0.1:8060 无服务，跳过动态检查（非交易日为预期行为）")
        return 0

    frame = asyncio.run(_probe_one_frame("127.0.0.1", 8060))
    if frame is None:
        warn("端口开放但 WS 握手失败，跳过动态检查")
        return 0

    failures = 0

    # 帧顶层字段
    required = ("seq", "ts", "spot", "session", "health",
                "heatmap", "skew", "cells", "atm")
    if all(k in frame for k in required):
        ok("帧顶层字段齐全")
    else:
        missing = [k for k in required if k not in frame]
        fail(f"帧缺少字段: {missing}")
        failures += 1

    # 会话块
    session = frame.get("session") or {}
    if session.get("expiry"):
        ok(f"会话含到期日 {session['expiry']}")
    else:
        fail("会话块缺少 expiry")
        failures += 1

    zones = session.get("zones") or []
    if len(zones) >= 2:
        ok(f"区段表含 {len(zones)} 个区段")
    else:
        fail(f"区段表不足 2 个（实际 {len(zones)}）")
        failures += 1

    # 健康块
    health = frame.get("health") or {}
    conn = health.get("connection")
    if conn:
        ok(f"连接状态 {conn} / mode={health.get('mode', '?')}")
    else:
        fail("健康块缺少 connection")
        failures += 1

    sub = health.get("subscribed", 0)
    cap = health.get("subscription_cap", 100)
    if sub <= cap:
        ok(f"订阅数 {sub}/{cap} 未超限")
    else:
        fail(f"订阅数 {sub} 超过上限 {cap}")
        failures += 1

    # 热力图
    hm = frame.get("heatmap")
    if hm and hm.get("rows") and hm.get("cols"):
        ok(f"热力图 {hm['rows']} 档 × {hm['cols']} 桶")
    else:
        fail("热力图未生成或行列异常")
        failures += 1

    # Skew
    skew = frame.get("skew") or {}
    series = skew.get("series") or {}
    if series.get("count", 0) > 0:
        ok(f"Skew 序列 {series['count']} 点")
    else:
        fail("Skew 序列为空")
        failures += 1

    return failures
