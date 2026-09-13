"""
L6 — 页面渲染回归。
====================
唯一职责：用真实浏览器打开面板，断言它**真的画出来了**，而且没有抛渲染异常。

为什么需要它
------------
探针校验的是"后端发的对不对"，契约检查校验的是"前端读的字段存不存在"，
两者都绿也不代表页面能看：Skew 面板曾经因为一个 ``visualMap`` 配置在 vendor 的
ECharts 5.5.1 上必抛 ``Cannot read properties of undefined (reading 'coord')``，
整块曲线渲染中断 —— 后端数据完全正常、字段名也完全对得上，只有真拿浏览器打开
才看得见。

这也是"打开的到底是不是我们的页面"的封口检查：8060 上若有别的进程（代理 / 网关）
在应答，Chrome 会拿到**别人的错误页**，而那页面上也有 ``<button>``，于是第 7 组
断言里的"周期按钮已生成"会**假通过**。故第 0 组先用本项目独有的元素 id 做哨兵，
哨兵不过即判失败并中止（见 ``SENTINELS`` 与 ``missing_sentinels``）。

这是"没人真正看过页面"这个盲区的封口检查。它跑得比人快，也比人可靠。

用法::

    python tools/check_page_render.py                       # 需要服务已在跑
    python tools/check_page_render.py --url http://127.0.0.1:8060/
    python tools/check_page_render.py --chrome "C:/path/to/chrome.exe"

Chrome 路径按顺序自动探测；找不到时本检查**跳过并返回 0**，不会把"没装浏览器"
误判成"页面坏了"。
"""

from __future__ import annotations

import argparse
import html as html_mod
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

#: Chrome 常见位置。按顺序探测，第一个存在的就用。
CHROME_CANDIDATES: tuple[str, ...] = (
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expanduser("~/.agent-browser/browsers/chrome-153.0.8010.36/chrome.exe"),
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


#: 本项目页面独有的元素 id，用作"拿到的确实是我们的面板"的哨兵。
#: 见 main() 里第 0 组断言的说明 —— 少了它，代理错误页会被误判成"页面正常"。
SENTINELS: tuple[str, ...] = ("topbar", "heatmap", "skew", "st-conn")


def missing_sentinels(dom: str) -> list[str]:
    """
    返回 ``dom`` 里缺失的哨兵元素 id（空列表 = 拿到的确实是本项目的面板）。

    抽成独立函数是为了让它**可被离线验证**：真实 ``web/index.html`` 必须返回空
    列表，Chrome 的网络错误页必须返回非空列表。判据不能只靠"在真机上跑一次"来
    证明 —— 本环境下 Chrome 连不到本地监听，跑不出正向用例。
    """
    return [eid for eid in SENTINELS if f'id="{eid}"' not in dom]


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


def find_chrome(explicit: str | None) -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() else None
    for path in CHROME_CANDIDATES:
        if path and Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("google-chrome")
    return found


def dump_dom(chrome: str, url: str, budget_ms: int) -> str:
    """
    headless 打开页面，等 JS 跑完后把最终 DOM 吐出来。

    刻意**不传** ``--user-data-dir``：本环境下指定临时 profile 会让 Chrome
    卡住不返回（实测同一命令去掉该参数即正常）。代价是不能并发跑多次，而本检查
    本来就只该串行跑。
    """
    out = subprocess.run(
        [
            chrome, "--headless", "--disable-gpu", "--no-sandbox",
            # 崩溃上报器在部分环境下会因管道残留直接让进程退出（exit 3），
            # 与本检查无关，一律关掉。
            "--disable-crash-reporter", "--disable-breakpad", "--no-first-run",
            f"--virtual-time-budget={budget_ms}",
            "--dump-dom", url,
        ],
        capture_output=True, text=True, timeout=120,
    )
    return out.stdout or ""


def _text(dom: str, element_id: str) -> str | None:
    """取某个元素的文本内容。"""
    match = re.search(
        rf'id="{re.escape(element_id)}"[^>]*>(.*?)</', dom, re.S
    )
    return html_mod.unescape(match.group(1)).strip() if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_page_render.py")
    parser.add_argument("--url", default="http://127.0.0.1:8060/")
    parser.add_argument("--chrome", default=None)
    parser.add_argument("--budget", type=int, default=14000,
                        help="等待 JS 运行的虚拟时间预算（毫秒）")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("页面渲染回归（真浏览器打开，断言画出来了）")
    print("=" * 72)

    chrome = find_chrome(args.chrome)
    if chrome is None:
        print(f"{YELLOW}未找到 Chrome，跳过本检查{RESET}")
        print("  提示：用 --chrome 指定路径，或先跑 `agent-browser install`")
        return 0
    print(f"  浏览器: {chrome}\n")

    try:
        dom = dump_dom(chrome, args.url, args.budget)
    except subprocess.TimeoutExpired:
        print(f"  {RED}打开页面超时{RESET}")
        return 1

    if not dom:
        print(f"  {RED}没有拿到 DOM —— 服务没起来？{RESET}  {args.url}")
        return 1

    passed = True

    # 0) 哨兵：拿到的到底是不是本项目的页面。
    #
    # 为什么必须有这一步：2026-09-13 实测发现，当 8060 上没有我们的服务、而本机
    # 环境里有一个 HTTP 代理在监听同一端口时，Chrome 会拿到代理的 502 错误页 ——
    # 那页面上也有 `<button>`，于是下面第 7 组断言里的"周期按钮已生成（≥ 2 档）"
    # 会**报 ok**，而面板其实一个字都没渲染。**假通过比假失败危险得多**，所以先
    # 用本项目独有的元素 id 做哨兵；哨兵不过就直接判失败并返回，不再往下断言 ——
    # 在一个陌生页面上跑后面的断言，结论没有意义。
    missing = missing_sentinels(dom)
    if missing:
        _check("拿到的页面是本项目的面板（哨兵元素齐备）", False,
               "缺失: " + ", ".join(missing) + " —— 打开的可能是代理/网关的错误页，"
               "或服务没起来。后续断言已跳过。")
        print()
        print("=" * 72)
        print(f"{RED}结果: 页面不是本项目的面板，检查中止{RESET}")
        return 1
    _check("拿到的页面是本项目的面板（哨兵元素齐备）", True,
           "、".join(SENTINELS))

    # 1) 渲染异常：ws_client 捕获渲染回调异常后会写进状态栏。
    status = _text(dom, "sb-msg") or ""
    passed &= _check(
        "无渲染回调异常",
        "渲染回调异常" not in status,
        status[:120] if "渲染回调异常" in status else "",
    )

    # 2) 热力图：面板头部的 meta 只在 update() 成功返回后才写入。
    meta = _text(dom, "heatmap-meta") or ""
    hm = re.search(r"(\d+)\s*档\s*×\s*(\d+)\s*桶\s*·\s*([\d,]+)\s*格", meta)
    passed &= _check(
        "热力图已渲染出矩阵",
        bool(hm) and int(hm.group(2)) > 1 and int(hm.group(3).replace(",", "")) > 0,
        meta or "meta 为空（面板未渲染）",
    )

    # 3) Skew：同样只在 update() 成功返回后才写入。
    skew_meta = _text(dom, "skew-meta") or ""
    passed &= _check(
        "Skew 曲线已渲染",
        bool(re.search(r"\d+\s*点\s*·\s*当前", skew_meta)),
        skew_meta or "meta 为空（面板未渲染）",
    )

    # 4) 连接状态
    conn = _text(dom, "st-conn") or ""
    passed &= _check("连接状态正常", "connected" in conn, conn or "未取到")

    # 5) 两块面板各至少一个 canvas —— 没有任何 canvas 说明 ECharts 根本没画。
    canvases = len(re.findall(r"<canvas", dom))
    passed &= _check("两块面板均已出图（canvas ≥ 2）", canvases >= 2,
                     f"{canvases} 个 canvas")

    # 6) 顶栏读数不得全是占位符
    spot = _text(dom, "ro-spot") or ""
    passed &= _check("顶栏现价已填充", spot not in ("", "--"), spot)

    # 7) 时间周期切换：按钮由 JS 生成，meta 里的周期标签必须与选中态一致。
    #    一条检查同时覆盖三种坏法 —— 按钮没生成、选中态没落到渲染上、meta 没接周期。
    #    这三件事都不会让任何探针变红，只会让面板安静地画错粒度。
    buttons = re.findall(r'<button[^>]*class="([^"]*)"[^>]*>([^<]*)</button>', dom)
    labels = [text.strip() for _, text in buttons]
    chosen = [text.strip() for cls, text in buttons if cls == "on"]
    passed &= _check("周期按钮已生成（≥ 2 档）", len(buttons) >= 2,
                     "、".join(labels) or "一个都没有")
    passed &= _check("有且仅有一个周期处于选中态", len(chosen) == 1,
                     "选中: " + "、".join(chosen) if chosen else "无选中态")
    passed &= _check("热力图 meta 带上当前周期", bool(chosen) and chosen[0] in meta,
                     meta or "meta 为空")

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if passed
          else f"{RED}结果: 存在失败项{RESET}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
