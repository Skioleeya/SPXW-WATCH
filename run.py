#!/usr/bin/env python3
"""
0DTE IV Skew 与日内动能监控系统 —— 启动入口。
=============================================

用法::

    python run.py                # 连接 IBKR，启动服务
    python run.py --check        # 只做配置与分层自检，不启动服务

打开浏览器访问打印出来的地址即可（默认 http://127.0.0.1:8060/）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="0DTE IV Skew 与日内动能监控系统",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="只运行配置与架构自检，然后退出",
    )
    return parser.parse_args(argv)


async def _run() -> int:
    from app.pipeline import Pipeline

    pipeline = Pipeline()
    try:
        await pipeline.run_until_cancelled()
    except asyncio.CancelledError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.check:
        from tools.selfcheck import run_selfcheck

        return run_selfcheck()

    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
