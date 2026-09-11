"""
L6 — 热力图 ΔIV 分布诊断。
==========================
唯一职责：连上行情通道抓一帧，统计矩阵里 ΔIV 的分布，回答一个问题——

    "当前配置的色标下限，对今天的行情来说是不是设歪了？"

为什么要单独一个工具
--------------------
色标量程（``heatmap_color_quantile`` / ``heatmap_color_floor_vol_points``）是
纯呈现参数，但它直接决定"信号看不看得见"。设高了，一次真实恐慌会被压成一片灰；
设低了，死水行情的噪声会被放大成满屏色块。这两个数只能靠实际分布来定，不能拍
脑袋。本工具把分布打出来，让调整有依据。

用法::

    python tools/heatmap_stats.py
    python tools/heatmap_stats.py --url ws://127.0.0.1:8060/ws --tail 30
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

_QUANTILES = (0.50, 0.75, 0.90, 0.95, 0.99, 1.00)


def _percentile(ascending: list[float], q: float) -> float:
    """``ascending`` 必须是按绝对值**升序**排好的列表。"""
    if not ascending:
        return 0.0
    index = min(int(q * (len(ascending) - 1)), len(ascending) - 1)
    return abs(ascending[index])


async def fetch_frame(url: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(url, heartbeat=20) as ws:
            async for message in ws:
                if message.type is aiohttp.WSMsgType.TEXT:
                    return json.loads(message.data)
    raise RuntimeError("未收到任何帧")


def _row_report(block: dict, spot: float) -> None:
    """
    逐行打印覆盖情况。

    这是排查"热力图中间有个洞"这类问题的关键视图：洞既可能是**真的没数据**
    （行缺失 / 该行整段为 null），也可能是**有数据但值恒为 0**（渲染成背景色，
    看起来像没数据）。两者修法完全不同，必须分开看。
    """
    strikes = block["strikes"]
    rights = block["rights"]
    values = block["values"]
    labels = block["labels"]
    cols = len(labels)

    print(f"\n逐行覆盖（现价 {spot}）")
    print(f"  {'行权价':>8} {'向':>2} {'有值':>5} {'首列':>5} {'末列':>5} "
          f"{'|ΔIV|中位':>10} {'|ΔIV|最大':>10}")
    for index, (strike, right, row) in enumerate(zip(strikes, rights, values)):
        filled = [c for c, v in enumerate(row) if v is not None]
        if filled:
            numbers = sorted(abs(row[c]) for c in filled)
            mid = numbers[len(numbers) // 2]
            top = numbers[-1]
        else:
            mid = top = 0.0
        marker = "  ← 现价" if abs(strike - spot) <= 2.5 else ""
        print(f"  {strike:>8.1f} {right:>2} {len(filled):>5} "
              f"{(filled[0] if filled else -1):>5} {(filled[-1] if filled else -1):>5} "
              f"{mid:>10.4f} {top:>10.4f}{marker}")
    print(f"  （共 {len(strikes)} 行 × {cols} 列）")


def report(frame: dict, tail: int, rows: bool) -> int:
    block = frame.get("heatmap")
    # 线上数值块是「位图 + 定标整数」，这里就地还原成 values，
    # 下面的统计逻辑一行都不用改（约定同 web/matrix_codec.js）。
    if block and not block.get("values") and block.get("bm"):
        block["values"] = unpack(
            block["bm"], block["i16"], block["rows"], block["cols"], block["scale"]
        )
    if not block or not block.get("values"):
        print("当前帧还没有热力图矩阵（会话刚开始，或数据尚未到位）")
        return 1

    cols = block["cols"]
    flat = [v for row in block["values"] for v in row if v is not None]
    if not flat:
        print(f"矩阵 {block['rows']} 档 × {cols} 桶，但还没有任何可差分的值")
        return 1

    ordered = sorted(flat, key=abs)

    serial_cfg = loader.load("serialization")
    configured_q = loader.as_float(serial_cfg, "heatmap_color_quantile", module="serialization")
    configured_floor = loader.as_float(
        serial_cfg, "heatmap_color_floor_vol_points", module="serialization"
    )

    print("=" * 72)
    print(f"矩阵 {block['rows']} 档 × {cols} 桶 | 有值格 {len(flat)} | "
          f"末帧 vmax ±{block['vmax']}")
    print("=" * 72)
    print("\n全量 |ΔIV| 分布（波动率点）")
    print(f"   最大值  {abs(ordered[-1]):8.4f}")
    for q in _QUANTILES:
        print(f"  {q * 100:5.1f} 分位  {_percentile(ordered, q):8.4f}")

    if tail > 0 and cols > tail:
        recent = [v for row in block["values"] for v in row[cols - tail:] if v is not None]
        recent_ordered = sorted(recent, key=abs)
        print(f"\n近 {tail} 列 |ΔIV| 分布")
        print(f"   最大值  {abs(recent_ordered[-1]):8.4f}")
        for q in _QUANTILES:
            print(f"  {q * 100:5.1f} 分位  {_percentile(recent_ordered, q):8.4f}")

    picked = _percentile(ordered, configured_q)
    print("\n配置评估")
    print(f"  分位点 {configured_q}  →  实取 {picked:.4f}")
    print(f"  下限保护 {configured_floor}  →  {'生效（信号被压到下限）' if picked < configured_floor else '未生效'}")
    if picked < configured_floor:
        print(f"  [提示] 当前 {configured_q} 分位低于下限，色标恒为 ±{configured_floor}。")
        print("         若希望近期信号更醒目，可下调 heatmap_color_floor_vol_points。")

    if rows:
        _row_report(block, block.get("spot", 0.0))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatmap_stats.py")
    parser.add_argument("--url", default="ws://127.0.0.1:8060/ws")
    parser.add_argument("--tail", type=int, default=30,
                        help="额外统计最近 N 列的分布，0 表示跳过")
    parser.add_argument("--rows", action="store_true",
                        help="逐行打印覆盖情况（排查'中间空洞'用）")
    args = parser.parse_args(argv)
    try:
        frame = asyncio.run(fetch_frame(args.url))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"抓帧失败: {exc}")
        return 1
    return report(frame, args.tail, args.rows)


if __name__ == "__main__":
    raise SystemExit(main())
