"""
L6 — WebSocket 压缩回归。
==========================
唯一职责：证明行情通道**真的在协商 permessage-deflate**，并量出线上字节数。

为什么必须有它
--------------
``aiohttp.web.WebSocketResponse`` 的 ``compress`` 参数默认是 ``True``，于是
压缩**一直开着但项目代码里没有一个字提到它**。实测同一段行情：

* 不协商压缩：184 KB/s ⇒ **4.41 GB / 交易日**
* 协商压缩：  16 KB/s ⇒ **0.40 GB / 交易日**

11 倍。而这件事没有任何机械校验 —— 库升级改了默认值、有人顺手写
``compress=False``、或者中间加了一层不做透传的反向代理，流量会静默翻十倍而
**所有现有检查照样全绿**。这正是"探针全绿但实际是坏的"的典型样本。

所以这里不看代码，只看线上：裸 socket 做握手，断言响应头回显
``Sec-WebSocket-Extensions: permessage-deflate``，再实测线上/解压后字节比。

``--selftest`` 不重启服务也能证伪
---------------------------------
对照组是"**故意不 offer 扩展**"：同一台服务、同一段行情，只要客户端不提，
服务端就不会压。若此时比率仍然达标，说明这个阈值根本不具备判别力（空转）。
不需要改配置、不需要重启，一次运行就能证明对照有效。

用法::

    python tools/check_ws_compression.py
    python tools/check_ws_compression.py --selftest
    python tools/check_ws_compression.py --seconds 20
"""

from __future__ import annotations

import argparse
import base64
import os
import socket
import statistics
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import loader  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: 压缩比下限。实测开=91%、关=0%，阈值取 80%：既能容忍矩阵宽度变化带来的
#: 波动，又不可能把"根本没压"放过去。
MIN_SAVING = 0.80

#: 采样窗口。太短会把握手首帧算进均值（那时 deflate 字典还空着，比率偏低）。
WINDOW_S = 12.0


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


# --------------------------------------------------------------------------- #
# 裸 WebSocket 客户端（不经过 aiohttp，才数得到真实 TCP 字节）
# --------------------------------------------------------------------------- #

class _Reader:
    def __init__(self, sock: socket.socket, initial: bytes) -> None:
        self.sock = sock
        self.buf = initial
        self.wire = len(initial)

    def _fill(self, n: int) -> None:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("服务端关闭了连接")
            self.buf += chunk
            self.wire += len(chunk)

    def take(self, n: int) -> bytes:
        self._fill(n)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out


def _handshake(sock: socket.socket, host: str, port: int, path: str,
               offer: bool) -> tuple[str, bytes]:
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}:{port}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    if offer:
        lines.append(
            "Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits"
        )
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())

    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("握手阶段连接被关闭")
        buf += chunk
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head.decode("latin-1"), rest


def _send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    """客户端 → 服务端的帧必须加掩码（RFC 6455）。"""
    mask = os.urandom(4)
    masked = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | opcode, 0x80 | n])
    elif n < 65536:
        head = bytes([0x80 | opcode, 0x80 | 126]) + n.to_bytes(2, "big")
    else:
        head = bytes([0x80 | opcode, 0x80 | 127]) + n.to_bytes(8, "big")
    sock.sendall(head + mask + masked)


def _read_frame(r: _Reader) -> tuple[int, bytes]:
    b0, b1 = r.take(2)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        length = int.from_bytes(r.take(2), "big")
    elif length == 127:
        length = int.from_bytes(r.take(8), "big")
    mask = r.take(4) if masked else b""
    raw = r.take(length)
    if masked:
        raw = bytes(c ^ mask[i % 4] for i, c in enumerate(raw))
    return opcode, raw


def measure(offer: bool, seconds: float) -> dict:
    """连一次、抓若干帧，返回线上与解压后的字节数。"""
    tcfg = loader.load("transport")
    host = loader.as_str(tcfg, "host", module="transport")
    port = loader.as_int(tcfg, "http_port", module="transport")
    path = loader.as_str(tcfg, "ws_path", module="transport")

    sock = socket.create_connection((host, port), timeout=15)
    sock.settimeout(15)
    try:
        head, rest = _handshake(sock, host, port, path, offer)
        negotiated = "permessage-deflate" in head.lower()

        r = _Reader(sock, rest)
        # 上下文接管：deflate 字典跨消息保留，必须全程共用一个解压对象。
        dec = zlib.decompressobj(-15) if negotiated else None

        wire: list[int] = []
        plain: list[int] = []
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < seconds:
                opcode, data = _read_frame(r)
                if opcode == 0x9:
                    # 服务端 heartbeat_interval_s（默认 20s）会发 ping。
                    # **必须回 pong**，否则连接会被服务端关掉 —— 表现为
                    # "采样到帧数偏少 / 中途 EOF"，很容易误判成压缩有问题。
                    _send_frame(sock, 0xA, data)
                    continue
                if opcode not in (0x1, 0x2):   # 只统计 text / binary
                    continue
                wire.append(len(data))
                if dec is None:
                    plain.append(len(data))
                else:
                    plain.append(len(dec.decompress(data + b"\x00\x00\xff\xff")))
        except (EOFError, socket.timeout, zlib.error):
            pass

        span = max(time.monotonic() - t0, 1e-6)
        return {
            "negotiated": negotiated,
            "frames": len(wire),
            "wire_total": r.wire,
            "span_s": span,
            "wire_mean": statistics.mean(wire) if wire else 0.0,
            "plain_mean": statistics.mean(plain) if plain else 0.0,
        }
    finally:
        sock.close()


def _saving(stat: dict) -> float:
    if not stat["plain_mean"]:
        return 0.0
    return 1.0 - stat["wire_mean"] / stat["plain_mean"]


def _print_stat(tag: str, stat: dict) -> None:
    print(f"  {tag}: 帧 {stat['frames']} · 线上帧体均 {stat['wire_mean']:,.0f} B"
          f" · 解压后均 {stat['plain_mean']:,.0f} B"
          f" · 省 {_saving(stat) * 100:.1f}%"
          f" · {stat['wire_total'] / stat['span_s'] / 1024:.1f} KB/s")


def run(seconds: float) -> int:
    stat = measure(offer=True, seconds=seconds)
    passed = True

    passed &= _check("服务端回显 permessage-deflate",
                     stat["negotiated"],
                     "已协商" if stat["negotiated"] else "**未协商，流量将放大 11 倍**")
    passed &= _check("采样到帧", stat["frames"] > 0, f"{stat['frames']} 帧")

    saving = _saving(stat)
    passed &= _check(f"线上压缩比 ≥ {MIN_SAVING * 100:.0f}%",
                     saving >= MIN_SAVING, f"实测 {saving * 100:.1f}%")

    if stat["frames"]:
        per_day = stat["wire_total"] / stat["span_s"] * 23400 / 1e9
        _print_stat("压缩开", stat)
        print(f"       ⇒ 按此速率，单个客户端一个交易日下行 ≈ {per_day:.2f} GB")
    return 0 if passed else 1


def selftest(seconds: float) -> int:
    """不 offer 扩展做对照：若比率仍达标，说明阈值没有判别力。"""
    print("\n=== 变异自检：客户端不 offer 扩展，看阈值抓不抓得住 ===")
    stat = measure(offer=False, seconds=seconds)
    _print_stat("压缩关", stat)

    saving = _saving(stat)
    caught = (not stat["negotiated"]) and saving < MIN_SAVING
    print(f"  {GREEN if caught else RED}[{'ok' if caught else 'FAIL'}]{RESET} "
          f"未协商 + 压缩比 {saving * 100:.1f}% < {MIN_SAVING * 100:.0f}% "
          f"→ {'对照有效（这组断言不是空转）' if caught else '**对照失效**'}")
    return 0 if caught else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="不 offer 扩展做对照，验证阈值具备判别力")
    ap.add_argument("--seconds", type=float, default=WINDOW_S)
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.seconds)

    print("=== 线上压缩（需要服务已在跑）===")
    return run(args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
