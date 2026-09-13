"""
L6 — 前端契约回归。
====================
唯一职责：证明前端读的每一个字段，后端真的在发；前端引用的每一个 DOM id 和
每一个 ``CFG.*`` 配置键，真的存在。

为什么需要它
------------
热力图曾经整整一屏是空的，而探针 20 项全绿 —— 因为探针校验的是"后端发的对不对"，
没人校验"前端读的和后端发的对不对得上"。这两件事之间那条缝，正是前端 bug 唯一能
藏身的地方。字段名差一个字母（``put25_iv`` 写成 ``put25iv``）不会报任何错，只会
安静地渲染成 ``--``。

它做三件事，全部是"引用 → 定义"的对照：

1. ``app.js`` 里的 ``el("x")`` / ``setText("x")`` / ``setClass("x")`` → ``index.html``
   里必须有 ``id="x"``。少一个就是一次静默的空操作。
2. JS 里的 ``CFG.a.b`` → ``config.js`` 里必须真有这条路径。写错的配置键读出来是
   ``undefined``，而 ``undefined`` 在算术里会变成 ``NaN``，最终渲染成一片空白。
3. 前端声明的载荷字段路径 → 后端实际发出的帧里必须存在。**键缺失算失败，
   值为 null 不算** —— ``null`` 是"还没到那个时间"的合法语义。

用法::

    python tools/check_web_contract.py
    python tools/check_web_contract.py --url ws://127.0.0.1:8060/ws
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: 前端实际读取的载荷字段路径。这份清单是**手抄**自 web/*.js 的读取点，
#: 不是自动推断的——自动推断会把 `frame.foo` 这种动态访问一起抓进来。
#: 每加一个前端读数，就应该在这里补一行，否则回归覆盖不到它。
PAYLOAD_PATHS: tuple[str, ...] = (
    # 顶层
    "seq", "ts", "spot", "atm", "session", "health", "heatmap", "skew", "cells",
    # app.js → 顶栏读数
    "atm.atm_strike", "atm.atm_iv", "atm.straddle",
    "atm.put25_iv", "atm.call25_iv", "atm.butterfly", "atm.skew_25d",
    # app.js → 状态行
    "session.expiry", "session.elapsed_s", "session.bucket_count",
    "session.bucket_index",
    # app.js → 时段切换（GTH / RTH / 全时段）。按钮**不写死**在后端：标签与列
    # 区间都从这张区段表来，前端照着生成。少一个键就是少一个按钮或切错列。
    "session.zones",
    "session.zones.0.id", "session.zones.0.label", "session.zones.0.is_session",
    "session.zones.0.first", "session.zones.0.last",
    "health.subscribed", "health.subscription_cap", "health.last_tick_age_s",
    "health.store_cells", "health.connection", "health.mode", "health.messages",
    # matrix_codec.js（线上数值块 = 位图 + 定标整数；解出 values 后
    # heatmap.js / period.js 照旧读 block.values，所以那里不用改）
    "heatmap.enc", "heatmap.scale", "heatmap.bm", "heatmap.i16",
    "heatmap.filled", "heatmap.rows", "heatmap.cols",
    # heatmap.js
    "heatmap.strikes", "heatmap.labels",
    "heatmap.rights", "heatmap.vmax",
    # period.js（周期聚合要用基线桶宽换算组大小，并用后端的色标规则重算量程）
    "heatmap.bucket_seconds", "heatmap.scale_policy",
    "heatmap.scale_policy.quantile", "heatmap.scale_policy.floor",
    # skew.js + app.js —— 折线对齐到热力图列网格（bucket 定列、ts 定量程窗口）。
    # 纵轴量程由前端按**当前视口**算（不再有后端下发的窗口长度：那样缩放到早盘
    # 段会把整条曲线裁到画面外，见 web/skew.js 模块 docstring）。
    "skew.series", "skew.series.ts", "skew.series.bucket", "skew.series.label",
    "skew.series.skew", "skew.series.atm",
    "skew.series.put25", "skew.series.call25",
    "skew.latest", "skew.latest.skew", "skew.latest.atm",
)


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


# ---------------------------------------------------------------------------
# 静态对照 1：DOM id
# ---------------------------------------------------------------------------

_ID_CALL = re.compile(r'(?:el|setText|setClass)\(\s*"([^"]+)"')
_HTML_ID = re.compile(r'id="([^"]+)"')


def check_dom_ids() -> bool:
    html_ids = set(_HTML_ID.findall((WEB / "index.html").read_text("utf-8")))
    used: dict[str, str] = {}
    for js in ("app.js",):
        src = (WEB / js).read_text("utf-8")
        for name in _ID_CALL.findall(src):
            used.setdefault(name, js)

    missing = sorted(n for n in used if n not in html_ids)
    print(f"[1] DOM id：JS 引用 {len(used)} 个，HTML 定义 {len(html_ids)} 个")
    return _check("JS 引用的 id 全部存在", not missing,
                  "缺失: " + ", ".join(missing) if missing else "")


# ---------------------------------------------------------------------------
# 静态对照 2：CFG 配置路径
# ---------------------------------------------------------------------------

_CFG_PATH = re.compile(r'CFG((?:\.\w+)+)')


def _load_config_js() -> dict[str, Any]:
    """用 Node 求值 config.js —— 手写 JS 对象字面量解析器只会制造新的 bug。"""
    script = (
        "const fs=require('fs');"
        "const window={};"
        "eval(fs.readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(JSON.stringify(window.SWATCH_CONFIG));"
    )
    out = subprocess.run(
        ["node", "-e", script, str(WEB / "config.js")],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"config.js 求值失败: {out.stderr.strip()}")
    return json.loads(out.stdout)


def _resolve(obj: Any, path: str) -> tuple[bool, Any]:
    """
    返回 (键是否存在, 值)。值可以是 None，但中间键缺失即视为不存在。

    路径里出现数字段时按**数组下标**解析（``session.zones.0.id``）—— 这样
    数组元素内部的键名也能被钉住，而不只是"这个数组在"。元素类型不是数组
    时视为不存在。
    """
    node = obj
    for part in path.split("."):
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                return False, None
            node = node[int(part)]
            continue
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def check_cfg_paths() -> bool:
    cfg = _load_config_js()
    used: set[str] = set()
    for js in ("app.js", "heatmap.js", "skew.js", "period.js",
               "matrix_codec.js", "ws_client.js"):
        src = (WEB / js).read_text("utf-8")
        used.update(m.group(1).lstrip(".") for m in _CFG_PATH.finditer(src))

    missing = sorted(p for p in used if not _resolve(cfg, p)[0])
    print(f"[2] CFG 路径：JS 引用 {len(used)} 条")
    return _check("CFG 引用的配置键全部存在", not missing,
                  "缺失: " + ", ".join(missing) if missing else "")


# ---------------------------------------------------------------------------
# 动态对照 3：载荷字段
# ---------------------------------------------------------------------------

async def _grab_frame(url: str, want: int) -> dict | None:
    timeout = aiohttp.ClientTimeout(total=60)
    last: dict | None = None
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(url, heartbeat=20) as ws:
            async for message in ws:
                if message.type is aiohttp.WSMsgType.TEXT:
                    last = json.loads(message.data)
                    want -= 1
                    if want <= 0:
                        break
                elif message.type in (
                    aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR
                ):
                    break
    return last


def check_payload(frame: dict) -> bool:
    missing = [p for p in PAYLOAD_PATHS if not _resolve(frame, p)[0]]
    print(f"[3] 载荷字段：前端声明读取 {len(PAYLOAD_PATHS)} 条路径")
    ok = _check("前端读的字段后端全部在发", not missing,
                "缺失: " + ", ".join(missing) if missing else "")

    # 顺带把"有键但整块为 null"的情形点出来 —— 不是失败，但值得知道
    nulls = [p for p in PAYLOAD_PATHS if _resolve(frame, p)[1] is None]
    if nulls:
        print(f"      注意：{len(nulls)} 条路径当前为 null（合法，表示尚未产生）："
              f"{', '.join(nulls[:6])}{' …' if len(nulls) > 6 else ''}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_web_contract.py")
    parser.add_argument("--url", default="ws://127.0.0.1:8060/ws")
    parser.add_argument("--frames", type=int, default=3)
    args = parser.parse_args(argv)

    print("=" * 72)
    print("前端契约回归（引用 → 定义）")
    print("=" * 72)

    passed = True
    passed &= check_dom_ids()
    passed &= check_cfg_paths()

    try:
        frame = asyncio.run(_grab_frame(args.url, args.frames))
    except Exception as exc:  # noqa: BLE001 — 连不上就是失败，要把原因打出来
        print(f"[3] 载荷字段：{RED}无法连接 {args.url}{RESET}  {exc}")
        frame = None
    if frame is None:
        passed = False
    else:
        passed &= check_payload(frame)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if passed
          else f"{RED}结果: 存在失败项{RESET}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
