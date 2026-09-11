"""回归：验证行情源断开→重连→恢复的全链路回调。

覆盖点
------
1. `_on_disconnect` 被调用时状态正确记录。
2. `_on_reconnect` 被调用时：
   a. 异步重建订阅任务被创建（`_resubscribe_task` 非 None 且未 done）。
   b. 重连钩子 `_reconnect_hook` 被调用。
   c. 钩子异常被吞掉，不中断重连流程。
3. 多次快速重连不会堆积多个 `_resubscribe_task`（前一次 done 后才创建新的）。

为什么不做真实断开
------------------
真实 IBKR 断开需要操控外部 Gateway/TWS，无法在隔离回归中复现。
本测试通过直接调用 `FeedService` 的内部回调方法，验证状态机与调用链
的正确性——这是"断开→重连"链路中项目代码可控的部分。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from acquisition.feed_service import IbkrFeed, StatusLevel


def _make_feed() -> IbkrFeed:
    """构造一个最小可用的 FeedService，全部外部依赖用 mock 替代。"""
    feed = IbkrFeed.__new__(IbkrFeed)
    feed._running = True
    feed._messages = []
    feed._reconnect_hook = None
    feed._resubscribe_task = None
    feed._mode = MagicMock()
    feed._mode.value = "delayed"

    # 子组件（mock）
    feed._error_handler = MagicMock()
    feed._error_handler.recover_at = 0.0
    feed._follower = MagicMock()

    # gateway
    g = MagicMock()
    g.state = "connected"
    g.rate_limit = {}
    feed._gateway = g

    # tap
    t = MagicMock()
    t.last_spot = 5500.0
    feed._tap = t

    # router
    r = MagicMock()
    r.routed = 42
    r.rejected = 7
    feed._router = r

    # manager
    m = MagicMock()
    m.count = 72
    m.capacity = 92
    m.in_backoff = False
    m.resubscribe_all = AsyncMock(return_value=72)
    feed._manager = m

    # slice / resolver / factory / window / centre —— 只参与 status()，不参与重连
    feed._slice = MagicMock()
    feed._slice.expiry = "20260911"
    feed._resolver = MagicMock()
    feed._factory = MagicMock()
    feed._window = []
    feed._centre = 0.0

    feed._sink = MagicMock()
    return feed


async def _case_disconnect_records_message() -> None:
    feed = _make_feed()
    feed._on_disconnect()
    assert any("断开" in m for m in feed._messages), "disconnect 应记录日志"


async def _case_reconnect_creates_resubscribe_task() -> None:
    feed = _make_feed()
    assert feed._resubscribe_task is None
    feed._on_reconnect()
    assert feed._resubscribe_task is not None, "重连应创建 _resubscribe_task"
    assert not feed._resubscribe_task.done(), "任务应仍在运行"
    # 清理
    feed._resubscribe_task.cancel()
    try:
        await feed._resubscribe_task
    except asyncio.CancelledError:
        pass


async def _case_reconnect_calls_hook() -> None:
    feed = _make_feed()
    called = []
    feed._reconnect_hook = lambda: called.append(1)
    feed._on_reconnect()
    assert len(called) == 1, "重连钩子应被调用一次"
    feed._resubscribe_task.cancel()
    try:
        await feed._resubscribe_task
    except asyncio.CancelledError:
        pass


async def _case_reconnect_swallows_hook_exception() -> None:
    feed = _make_feed()
    feed._reconnect_hook = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    feed._on_reconnect()  # 不应抛异常
    assert any("boom" in m for m in feed._messages), "钩子异常应被记录"
    feed._resubscribe_task.cancel()
    try:
        await feed._resubscribe_task
    except asyncio.CancelledError:
        pass


async def _case_reconnect_not_duplicated() -> None:
    feed = _make_feed()
    feed._on_reconnect()
    first_task = feed._resubscribe_task
    # 第二次重连，前一次任务仍在运行（未 done）=> 不应创建新任务
    feed._on_reconnect()
    assert feed._resubscribe_task is first_task, "不应重复创建 resubscribe 任务"
    first_task.cancel()
    try:
        await first_task
    except asyncio.CancelledError:
        pass


async def _case_reconnect_after_task_done() -> None:
    feed = _make_feed()
    feed._on_reconnect()
    old_task = feed._resubscribe_task
    # 模拟任务完成
    old_task.cancel()
    try:
        await old_task
    except asyncio.CancelledError:
        pass
    # 再次重连
    feed._on_reconnect()
    assert feed._resubscribe_task is not old_task, "旧任务完成后应创建新任务"
    assert feed._resubscribe_task is not None
    feed._resubscribe_task.cancel()
    try:
        await feed._resubscribe_task
    except asyncio.CancelledError:
        pass


_CASES = [
    _case_disconnect_records_message,
    _case_reconnect_creates_resubscribe_task,
    _case_reconnect_calls_hook,
    _case_reconnect_swallows_hook_exception,
    _case_reconnect_not_duplicated,
    _case_reconnect_after_task_done,
]


async def main() -> int:
    passed = 0
    for case in _CASES:
        name = case.__name__
        try:
            await case()
            print(f"  [ok] {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  [FAIL] {name}: {exc}")
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc!r}")

    print(f"\n结果: {passed}/{len(_CASES)} 通过")
    return 0 if passed == len(_CASES) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
