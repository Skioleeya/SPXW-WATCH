"""
L6 — 行情通道探针。
====================
唯一职责：作为前端之外的一个"独立客户端"，连上 WebSocket 抓若干帧并校验结构。

为什么需要它
------------
前端是黑盒——页面白屏可能是数据问题、也可能是渲染问题。有一个能直接打印并校验
帧内容的命令行客户端，就能把"数据链路"和"渲染"彻底分开定位。

用法::

    python tools/ws_probe.py                 # 抓 10 帧后退出
    python tools/ws_probe.py --frames 40     # 抓 40 帧
    python tools/ws_probe.py --url ws://127.0.0.1:8060/ws
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from serialization.bitmap_codec import unpack  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def decode_matrix(hm: dict) -> list[list[float | None]]:
    """
    线上数值块 ``[位图][定标整数]`` → 二维数组。

    约定与 ``web/matrix_codec.js`` 完全一致，两边由
    ``tools/check_matrix_codec.py`` 逐值对拍 —— 探针若用另一套解读，
    "探针全绿"就不再等于"前端画得对"。
    """
    return unpack(hm["bm"], hm["i16"], hm["rows"], hm["cols"], hm["scale"])


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


async def probe(url: str, want_frames: int) -> int:
    frames: list[dict] = []
    gaps = 0
    last_seq: int | None = None
    serial_cfg = loader.load("serialization")

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(url, heartbeat=20) as ws:
            print(f"已连接 {url}，抓取 {want_frames} 帧 ...\n")
            async for message in ws:
                if message.type is aiohttp.WSMsgType.TEXT:
                    frame = json.loads(message.data)
                    seq = frame.get("seq")
                    if last_seq is not None and isinstance(seq, int) and seq > last_seq + 1:
                        gaps += 1
                    last_seq = seq
                    frames.append(frame)
                    if len(frames) >= want_frames:
                        break
                elif message.type in (
                    aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR
                ):
                    print(f"{RED}通道提前关闭{RESET}")
                    break

    if not frames:
        print(f"{RED}没有收到任何帧{RESET}")
        return 1

    print(f"收到 {len(frames)} 帧，序号缺口 {gaps} 处\n")
    print("=" * 72)
    print("结构校验")
    print("=" * 72)

    first, last = frames[0], frames[-1]
    passed = True

    passed &= _check("顶层字段齐全",
                     all(k in last for k in
                         ("seq", "ts", "spot", "session", "health",
                          "heatmap", "skew", "cells", "atm")))

    seqs = [f["seq"] for f in frames]
    passed &= _check("帧序号单调递增", seqs == sorted(seqs),
                     f"{seqs[0]} → {seqs[-1]}")

    session = last["session"]
    passed &= _check("会话块含到期日", bool(session.get("expiry")),
                     str(session.get("expiry")))
    # 不写死"= 390"：桶宽可配，写死只会在改桶宽时变成假警报。
    # 改校验跨字段不变量 —— 桶数 × 基线桶宽 必须等于**整个交易日网格**的长度
    # （各会话 + 它们之间的空档），而不是某一个会话的长度。
    hm_probe = last.get("heatmap") or {}
    bucket_s = hm_probe.get("bucket_seconds")
    session_s = round((session.get("elapsed_s") or 0) +
                      (session.get("seconds_to_close") or 0))
    passed &= _check(
        "时间桶恰好铺满交易日网格（桶数 × 桶宽 = 网格长度）",
        bool(bucket_s) and session.get("bucket_count", 0) * bucket_s == session_s,
        f"{session.get('bucket_count')} 桶 × {bucket_s}s vs 网格 {session_s}s")

    zones = session.get("zones") or []
    passed &= _check("会话块含网格区段表（前端时段切换的依据）",
                     len(zones) >= 2, f"{len(zones)} 个区段")
    if zones:
        # 区段必须首尾相接铺满网格：既不留缝（那段列没人管），也不重叠
        # （同一列被两个区段认领，切列时会被复制一份）。
        cursor = 0
        tiled = True
        sessions_only = 0
        for zone in zones:
            if int(zone.get("first", -1)) != cursor:
                tiled = False
                break
            cursor = int(zone.get("last", -1)) + 1
            if zone.get("is_session"):
                sessions_only += 1
        passed &= _check("区段表首尾相接铺满网格（无缝隙、无重叠）",
                         tiled and cursor == session.get("bucket_count"),
                         f"覆盖到第 {cursor} 桶 / 共 {session.get('bucket_count')} 桶")
        passed &= _check("区段表含至少一个真实会话", sessions_only > 0,
                         f"{sessions_only} 个会话区段")

    health = last["health"]
    passed &= _check("健康块含连接状态", bool(health.get("connection")),
                     f"{health.get('connection')} / {health.get('mode')}")
    passed &= _check("订阅数未超 IBKR 上限 100",
                     (health.get("subscribed") or 0) <= 100,
                     f"{health.get('subscribed')}/{health.get('subscription_cap')}")

    hm = last["heatmap"]
    if hm:
        passed &= _check("热力图行数 > 0", hm["rows"] > 0, f"{hm['rows']} 档")
        passed &= _check("热力图列数随时间增长",
                         hm["cols"] >= first["heatmap"]["cols"] if first["heatmap"] else True,
                         f"{first['heatmap']['cols'] if first['heatmap'] else 0} → {hm['cols']} 桶")
        passed &= _check("色标量程为正", hm["vmax"] > 0, f"±{hm['vmax']}")
        passed &= _check("行数与 strikes 对齐", hm["rows"] == len(hm["strikes"]))
        values = decode_matrix(hm)
        passed &= _check("每行列数与 labels 对齐",
                         all(len(row) == len(hm["labels"]) for row in values))
        passed &= _check("数值块编码名与配置一致",
                         hm.get("enc") == serial_cfg["heatmap_encoding"],
                         f"{hm.get('enc')}")
        passed &= _check("位图置位数与 filled 一致",
                         sum(1 for row in values for v in row if v is not None)
                         == hm.get("filled"),
                         f"{hm.get('filled')} 格")
        flat = [v for row in values for v in row if v is not None]
        passed &= _check("矩阵含有效数值", len(flat) > 0, f"{len(flat)} 格")
        passed &= _check("无 NaN / Infinity 字面量",
                         not any(v != v or v in (float("inf"), float("-inf"))
                                 for v in flat))
    else:
        passed &= _check("热力图已生成", False, "仍为 null")

    skew = last["skew"]
    series = skew.get("series", {})
    passed &= _check("Skew 序列有点", series.get("count", 0) > 0,
                     f"{series.get('count')} 点")
    passed &= _check("Skew 序列各列等长",
                     len({len(series.get(k, [])) for k in
                          ("ts", "label", "skew", "atm", "put25", "call25")}) == 1)
    latest = skew.get("latest")
    if latest:
        passed &= _check("最新 Skew 有定义", latest.get("skew") is not None,
                         f"25Δ = {latest.get('skew')}")
        passed &= _check("25Δ Put 行权价低于现价",
                         latest.get("put25_strike") is not None
                         and latest["put25_strike"] < last["spot"],
                         f"{latest.get('put25_strike')} < {last['spot']}")
        passed &= _check("25Δ Call 行权价高于现价",
                         latest.get("call25_strike") is not None
                         and latest["call25_strike"] > last["spot"],
                         f"{latest.get('call25_strike')} > {last['spot']}")

    cells = last["cells"]
    passed &= _check("网格点明细非空", len(cells) > 0, f"{len(cells)} 条")
    if cells:
        sample = cells[0]
        passed &= _check("明细字段齐全",
                         all(k in sample for k in
                             ("strike", "right", "iv", "delta", "quality", "impulse")))

    print()
    print("=" * 72)
    print(f"末帧摘要: spot={last['spot']} | 载荷 {len(json.dumps(last)):,} 字节")
    print(f"  热力图 {hm['rows'] if hm else 0} 档 × {hm['cols'] if hm else 0} 桶"
          if hm else "  热力图 尚未生成")
    print(f"  25Δ Skew = {latest.get('skew') if latest else '--'}")
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if passed
          else f"{RED}结果: 存在失败项{RESET}")
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ws_probe.py")
    parser.add_argument("--url", default="ws://127.0.0.1:8060/ws")
    parser.add_argument("--frames", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        return asyncio.run(probe(args.url, args.frames))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
