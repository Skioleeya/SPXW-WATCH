"""
L3 — 旁路异步持久化。
========================
把 HeatmapEngine 的原始 IV 桶异步写入 SQLite，服务重启时可恢复。

为什么是"旁路"
------------
本模块通过 ``asyncio.Queue`` 与主循环解耦：写入慢不会卡住行情接收和
WebSocket 推送。队列满时新桶被静默丢弃（计数可见），主循环无感知。

为什么是"原始 IV"而不是 ΔIV
--------------------------
ΔIV 是差分产物，恢复时如果前一个有值、前一个没值，差分行为会不同。
存原始 IV 让恢复后的 ``HeatmapEngine`` 自己重新走差分逻辑，语义一致。

依赖：L0。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from config import loader

_PERSIST = "persistence"


class AsyncPersistenceWriter:
    """
    旁路 SQLite 写入器。

    生命周期
    --------
    1. ``start()``：连接 SQLite、建表、启动后台 worker。
    2. ``enqueue()``：主循环把待写桶丢进队列（非阻塞；满则丢）。
    3. ``stop()``：取消 worker、等它写完队列中剩余项、关闭连接。
    4. ``recover()``：读取当日全部桶，返回给调用方恢复进 HeatmapEngine。
    """

    __slots__ = (
        "_enabled", "_db_path", "_queue", "_interval",
        "_worker_task", "_running", "_dropped", "_written",
        "_conn",
    )

    def __init__(self, persist_cfg: dict) -> None:
        self._enabled = loader.as_bool(persist_cfg, "enabled", module=_PERSIST)
        self._db_path = Path(loader.as_str(persist_cfg, "db_path", module=_PERSIST))
        self._queue: asyncio.Queue[dict] = asyncio.Queue(
            maxsize=loader.as_int(persist_cfg, "queue_maxsize", module=_PERSIST)
        )
        self._interval = loader.as_float(
            persist_cfg, "write_interval_s", module=_PERSIST
        )
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._dropped = 0
        self._written = 0
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if not self._enabled:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        self._ensure_table()
        self._running = True
        self._worker_task = asyncio.create_task(self._writer_worker())

    async def stop(self) -> None:
        self._running = False
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        # 把队列里剩余的桶同步刷掉
        remaining = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            self._batch_write(remaining)
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ #
    # 生产者接口（主循环调用）
    # ------------------------------------------------------------------ #

    def enqueue(self, bucket_index: int, ivs: dict[float, float], is_break: bool) -> None:
        """
        把一列桶数据丢进写入队列。

        队列满时**静默丢弃**，不阻塞主循环。丢桶数通过 ``dropped_count`` 可见。
        """
        if not self._enabled:
            return
        payload = {
            "bucket_index": int(bucket_index),
            "ivs": {str(k): float(v) for k, v in ivs.items()},
            "break": bool(is_break),
        }
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._dropped += 1

    @property
    def dropped_count(self) -> int:
        return self._dropped

    @property
    def written_count(self) -> int:
        return self._written

    # ------------------------------------------------------------------ #
    # 恢复
    # ------------------------------------------------------------------ #

    def recover(self) -> list[dict]:
        """
        读取 SQLite 中全部已存桶，返回给 HeatmapEngine 恢复。

        返回格式：
        ``[{bucket_index: int, ivs: {float(strike): float}, break: bool}, ...]``
        """
        if not self._enabled or not self._db_path.exists():
            return []
        try:
            if self._conn is not None:
                cur = self._conn.execute(
                    "SELECT bucket_index, ivs_json, is_break "
                    "FROM heatmap_buckets ORDER BY bucket_index"
                )
                rows = cur.fetchall()
            else:
                with sqlite3.connect(str(self._db_path), timeout=5.0) as conn:
                    cur = conn.execute(
                        "SELECT bucket_index, ivs_json, is_break "
                        "FROM heatmap_buckets ORDER BY bucket_index"
                    )
                    rows = cur.fetchall()
        except sqlite3.Error:
            return []

        out: list[dict] = []
        for idx, ivs_json, is_break in rows:
            try:
                ivs = json.loads(ivs_json)
            except json.JSONDecodeError:
                continue
            out.append({
                "bucket_index": int(idx),
                "ivs": {float(k): float(v) for k, v in ivs.items()},
                "break": bool(is_break),
            })
        return out

    # ------------------------------------------------------------------ #
    # 后台 worker
    # ------------------------------------------------------------------ #

    async def _writer_worker(self) -> None:
        """死循环：sleep → 批量消费队列 → 写入 SQLite。"""
        while self._running:
            await asyncio.sleep(self._interval)
            batch: list[dict] = []
            while not self._queue.empty():
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if batch:
                self._batch_write(batch)
                self._written += len(batch)

    def _batch_write(self, batch: list[dict]) -> None:
        if self._conn is None:
            return
        try:
            for item in batch:
                self._conn.execute(
                    "INSERT OR REPLACE INTO heatmap_buckets "
                    "(bucket_index, ivs_json, is_break) VALUES (?, ?, ?)",
                    (
                        item["bucket_index"],
                        json.dumps(item["ivs"], separators=(",", ":")),
                        int(item["break"]),
                    ),
                )
            self._conn.commit()
        except sqlite3.Error:
            pass  # 旁路：写失败不中断主流程

    def _ensure_table(self) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS heatmap_buckets ("
            "bucket_index INTEGER PRIMARY KEY, "
            "ivs_json TEXT NOT NULL, "
            "is_break INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        self._conn.commit()
