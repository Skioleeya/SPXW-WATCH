"""
联通与数据通道检查（**不属于任何运行时层**）。
================================================

唯一职责：校验**帧契约与编码器的一致性**，以及在服务在跑时校验活链路结构。

为什么不能只做"连上 8060 抓一帧"
--------------------------------
那样写出来的检查有两个问题，都在旧实现上真实发生过：

1. **它依赖服务** —— 非交易日、盘前、盘后一律跳过，于是这条检查一年里大多数
   时间都是空的，而 ``--check`` 照旧报"通过"。
2. **它的判据是一份手工字段清单** —— 旧实现的清单是
   ``("seq", "ts", "spot", "session", "health", "heatmap", "skew", "cells", "atm")``。
   重写后 ``Frame`` 新增了 ``surface`` 字段，**清单没有跟着长** ⇒ 编码器漏掉整个
   曲面段也不会被这条检查发现。手工清单的腐烂是静默的。

所以本检查把判据**从契约派生**：

* 帧字段清单 = ``dataclasses.fields(Frame)`` —— 加字段自动纳入，不需要回来改工具；
* 逐个断言编码输出里存在对应键（允许**显式登记**的折叠，见 ``FOLDED_FIELDS``）；
* 反向再查一次：编码器产出了契约里没有的顶层键 ⇒ 警告（可能是编码器比契约新）。

这样"``Frame`` 加了字段、编码器没覆盖"这类**静默缺口**会在 ``--check`` 里直接变红，
而不是等下一次实盘看前端缺一块。

离线三项 + 在线一项
-------------------
``[13a]`` 帧字段覆盖（契约派生）· ``[13b]`` 真帧编码往返 · ``[13c]`` NaN 守卫
``[13d]`` 活链路结构（需 8060 有服务；无服务时跳过并说明，**不视为失败**）

运行::

    python tools/selfcheck_connectivity.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import socket
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import loader  # noqa: E402
from contracts.frame import (  # noqa: E402
    Frame,
    HealthBlock,
    SessionBlock,
    SessionZone,
)
from serialization.frame_encoder import FrameEncoder  # noqa: E402
from tools.fixtures import make_session_clock  # noqa: E402
from tools.selfcheck_core import fail, ok, warn  # noqa: E402

#: 契约字段 → 编码输出里的键路径。**只有真正折叠的字段才登记**，
#: 一对一对应的字段一律自动匹配，不进这张表。
#:
#: ``skew_series`` 折进 ``skew.series``：两者共用 ``skew`` 这个顶层块
#: （``skew.latest`` 是实时点、``skew.series`` 是已走满的桶），是刻意的形状，
#: 不是漏编码。表里的目标路径会被校验真实存在 —— 折叠目标写错或编码器改名，
#: 这条检查会报"折叠目标不存在"，而不是静默放过。
FOLDED_FIELDS: dict[str, tuple[str, ...]] = {
    "skew_series": ("skew", "series"),
}

#: 编码器产出的**非契约**顶层键（有意的附加元信息）。
EXTRA_TOP_LEVEL_KEYS = frozenset({"type"})

PROBE_HOST = "127.0.0.1"


def _key_paths(node, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """递归收集字典里所有键路径（列表只看第一个元素，形状足够代表整体）。"""
    found: set[tuple[str, ...]] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = prefix + (str(key),)
            found.add(path)
            found |= _key_paths(value, path)
    elif isinstance(node, list) and node:
        found |= _key_paths(node[0], prefix)
    return found


def _minimal_frame(seq: int = 1) -> Frame:
    """造一帧**最小可用**帧：只填必填字段，其余走契约默认值。

    ``zones`` 刻意填两段而不是留空 —— 留空时"区段表非空"这条判据会在 0 段的
    情况下也打印通过，那是空转（没有东西可比）。判据要验的是"区段被真的编进了
    帧里"，所以夹具必须带区段。
    """
    return Frame(
        seq=seq,
        ts=1_893_456_000.0,
        spot=6500.0,
        session=SessionBlock(
            date="2030-01-01", expiry="20300101", open="20:15", close="16:00",
            is_open=True, elapsed_s=3600.0, seconds_to_close=20000.0,
            bucket_index=120, bucket_count=2370,
            zones=(
                SessionZone(id="gth", label="GTH", is_session=True,
                            first=0, last=1579, open="20:15", close="09:25"),
                SessionZone(id="gap", label="", is_session=False,
                            first=1580, last=1589, open="09:25", close="09:30"),
                SessionZone(id="rth", label="RTH", is_session=True,
                            first=1590, last=2369, open="09:30", close="16:00"),
            ),
        ),
        health=HealthBlock(subscribed=48, subscription_cap=92),
    )


def check_frame_coverage(encoder: FrameEncoder) -> int:
    """[13a] ``Frame`` 的每个字段都必须被编码器覆盖。"""
    encoded = encoder.encode(_minimal_frame())
    paths = _key_paths(encoded)
    top = {str(k) for k in encoded}

    failures = 0
    contract_fields = {f.name for f in dataclasses.fields(Frame)}

    for name in sorted(contract_fields):
        if (name,) in paths:
            continue
        folded = FOLDED_FIELDS.get(name)
        if folded is not None and tuple(folded) in paths:
            continue
        if folded is not None:
            fail(f"契约字段 {name!r} 登记为折叠到 "
                 f"{'.'.join(folded)}，但编码输出里没有这个键路径")
        else:
            fail(f"契约字段 {name!r} 在编码输出里没有任何对应键 —— "
                 f"编码器漏覆盖，该字段会恒为缺省值（静默缺口）")
        failures += 1

    if not failures:
        ok(f"{len(contract_fields)} 个契约字段全部被编码器覆盖"
           f"（含 {len(FOLDED_FIELDS)} 处显式折叠）")

    # 反向：编码器不得产出契约外的顶层键（否则可能是"契约删了、编码器没删"）
    strays = sorted(top - contract_fields - set(EXTRA_TOP_LEVEL_KEYS))
    if strays:
        warn(f"编码器产出了契约外的顶层键 {strays} —— 若契约确实删掉了它们，"
             f"这里就是残留；若是有意附加，请登记进 EXTRA_TOP_LEVEL_KEYS")
    else:
        ok(f"编码器未产出契约外的顶层键（附加键仅 "
           f"{sorted(EXTRA_TOP_LEVEL_KEYS)}）")

    return failures


def check_frame_roundtrip(encoder: FrameEncoder) -> int:
    """[13b] 真帧必须能编成合法 JSON 文本，且关键字段类型正确。"""
    failures = 0
    text = encoder.dumps(_minimal_frame())
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"编码器产出的文本不是合法 JSON: {exc}")
        return 1

    if decoded.get("seq") == 1 and decoded.get("session", {}).get("expiry"):
        ok(f"最小帧编码往返正常（{len(text)} 字节，"
           f"{len(decoded)} 个顶层键）")
    else:
        fail(f"往返后关键字段丢失: seq={decoded.get('seq')!r}, "
             f"expiry={decoded.get('session', {}).get('expiry')!r}")
        failures += 1

    zones = decoded.get("session", {}).get("zones")
    if isinstance(zones, list) and len(zones) >= 2:
        ok(f"会话块携带区段表（{len(zones)} 段，逐段带 first/last）")
    elif isinstance(zones, list):
        fail(f"区段表只有 {len(zones)} 段 —— 前端切不出 GTH/RTH")
        failures += 1
    else:
        fail("会话块的 zones 不是数组 —— 前端无法切 GTH/RTH")
        failures += 1

    return failures


def check_nan_guard(encoder: FrameEncoder) -> int:
    """
    [13c] ``allow_nan=False`` 必须真的生效。

    Python 默认会把 NaN 写成裸 ``NaN``，那是**非法 JSON** —— 浏览器
    ``JSON.parse`` 直接抛错、整条推送链路静默死掉。关掉之后，漏网的 NaN 会在
    服务端立刻炸出来。这条守卫必须被机械验证：把 NaN 塞进帧里，编码必须**抛错**，
    而不是悄悄产出非法 JSON。
    """
    frame = _minimal_frame()
    poisoned = dataclasses.replace(frame, spot=float("nan"))
    try:
        encoder.dumps(poisoned)
    except ValueError as exc:
        ok(f"NaN 被编码器拒绝（{type(exc).__name__}）⇒ 不会产出非法 JSON")
        return 0
    fail("帧里含 NaN 时编码仍然成功 —— allow_nan=False 失效，前端会收到非法 JSON")
    return 1


async def _probe_one_frame(host: str, port: int) -> dict | None:
    """连上 WS 抓一帧就断开。任何异常都视为"不可连"。"""
    try:
        import aiohttp
    except ImportError:
        return None

    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(f"ws://{host}:{port}/ws",
                                          heartbeat=20) as ws:
                async for message in ws:
                    if message.type is aiohttp.WSMsgType.TEXT:
                        return json.loads(message.data)
                    if message.type in (aiohttp.WSMsgType.CLOSED,
                                        aiohttp.WSMsgType.ERROR):
                        break
    except Exception:
        return None
    return None


def check_live_link(host: str, port: int) -> int:
    """[13d] 活链路结构。服务未运行时跳过（**不视为失败**）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        reachable = sock.connect_ex((host, port)) == 0
    finally:
        sock.close()

    if not reachable:
        warn(f"{host}:{port} 无服务，跳过活链路检查（非交易日/盘前为预期）"
             f"—— 上面三项离线判据仍然有效")
        return 0

    frame = asyncio.run(_probe_one_frame(host, port))
    if frame is None:
        warn(f"{host}:{port} 端口开放但 WS 未取到帧，跳过（服务可能在启动中）")
        return 0

    failures = 0
    required = ("seq", "ts", "spot", "session", "health", "heatmap", "skew")
    missing = [k for k in required if k not in frame]
    if missing:
        fail(f"活帧缺少字段: {missing}")
        failures += 1
    else:
        ok("活帧顶层字段齐全")

    session = frame.get("session") or {}
    if session.get("expiry"):
        ok(f"会话到期日 {session['expiry']}")
    else:
        fail("会话块缺少 expiry")
        failures += 1

    health = frame.get("health") or {}
    sub, cap = health.get("subscribed", 0), health.get("subscription_cap", 0)
    if cap and sub > cap:
        fail(f"订阅数 {sub} 超过上限 {cap}")
        failures += 1
    else:
        ok(f"连接 {health.get('connection', '?')} / mode="
           f"{health.get('mode', '?')} / 订阅 {sub}/{cap}")

    heatmap = frame.get("heatmap")
    if heatmap and heatmap.get("rows") and heatmap.get("cols"):
        ok(f"热力图 {heatmap['rows']} 档 × {heatmap['cols']} 桶")
    else:
        fail("热力图未生成或行列异常")
        failures += 1

    return failures


def run_connectivity_checks() -> int:
    """供 ``--check`` 调用的入口。返回**失败条数**。

    ⚠️ **标题必须由本函数打印**（理由见 ``selfcheck_clock.run_clock_checks``）：
    ``--selftest`` 按段落编号定位目标检查项，标题不在这里就切不出那一段，
    变异判据会恒判为抓住。
    """
    print("\n[13] 联通与数据通道（帧契约一致性 + 活链路）")
    app_cfg = loader.load("app")
    serial_cfg = loader.load("serialization")
    transport_cfg = loader.load("transport")
    _, clock = make_session_clock(app_cfg, serial_cfg)
    encoder = FrameEncoder(serial_cfg, clock)

    failures = check_frame_coverage(encoder)
    failures += check_frame_roundtrip(encoder)
    failures += check_nan_guard(encoder)
    failures += check_live_link(
        loader.as_str(transport_cfg, "host", module="transport"),
        loader.as_int(transport_cfg, "http_port", module="transport"),
    )
    return failures


def main() -> int:
    failures = run_connectivity_checks()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
