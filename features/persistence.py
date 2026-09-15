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

一个交易日一个文件
------------------
``bucket_index`` 是**日内坐标**（0..2369，从会话开盘起算），**每个交易日复用
同一段序号** ⇒ 多个交易日同表就必须靠一列去区分，而那列丢了、或查询忘了带
过滤，昨天的桶就会落到今天的时刻上（2026-09-15 实测：昨天 RTH 的数据被画在
今天 GTH 的时刻上，对外帧的 ``skew.latest`` 报出昨天 14:26:48 的点）。

本模块因此把落点交给 ``SessionFileStore``：**一天一个文件**，
``data/sessions/20260915.db`` 里只可能有 20260915 的桶。同一天内重启接着写
同一个文件；跨日（0DTE 换到期日）换新文件。行里仍保留 ``session_key`` 列，
让文件**自述**归属 —— 文件被改名贴错日期时，查询一条也取不到（图上留白），
而不是把别天的桶画出来。

保留策略：**db_dir 只留当前会话，历史归档不删**（KAI 2026-09-15 定）。
``start()`` 在打开本会话文件后，把 db_dir 里所有非当前会话的库文件**移动**到
``archive_dir``，并把 **``(已归档, 未归档)`` 两组文件名返回给调用方**。
为什么返回而不是在这里记日志：``features/`` 整层不写日志（纯计算层），归档与
冲突必须由 ``app/pipeline.py`` 当场各记一行 —— **动到一整个交易日的数据绝不允许
静默发生**。跨日那一刻产生的旧文件不在此处归档（本层无日志可记），留到下次启动。

本模块只负责**队列、批量调度与序列化**；文件与表在
``features/persistence_store.py``。

依赖：L0。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from config import loader
from contracts.enums import Quality
from contracts.feature import SkewPoint
from features.persistence_store import SessionFileStore, require_session_key

_PERSIST = "persistence"


class AsyncPersistenceWriter:
    """
    旁路 SQLite 写入器。

    生命周期
    --------
    1. ``start(session_key)``：打开**本会话**的库文件、建表、启动后台 worker。
    2. ``enqueue()``：主循环把待写桶丢进队列（非阻塞；满则丢）。
    3. ``stop()``：取消 worker、等它写完队列中剩余项、关闭连接。
    4. ``recover()``：读取**指定会话**的全部桶，返回给调用方恢复进 HeatmapEngine。
    """

    __slots__ = (
        "_store", "_queue", "_interval",
        "_worker_task", "_running", "_dropped", "_written",
    )

    def __init__(self, persist_cfg: dict) -> None:
        self._store = SessionFileStore(persist_cfg)
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

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self, session_key: str) -> tuple[list[str], list[str]]:
        """
        打开**本会话**的库文件、归档别的会话的文件、启动后台 worker。

        ``session_key`` 必填：它既决定这一轮写进哪个文件，也决定重启时从哪个
        文件恢复。同一个交易日内反复重启会落到同一个文件上（这是设计目标）。

        **返回 ``(已归档, 未归档)`` 两组文件名**（都可能为空列表）。顺序是
        "先 open 再 archive"：保证当前会话的文件已经存在，不会被自己搬走。
        调用方（``app/pipeline.py``）必须把两组结果都记进日志 ——
        移动一整个交易日的持久化数据不允许静默发生，"没搬成"更不允许。
        """
        if not self._store.enabled:
            return [], []
        self._store.open_session(session_key)
        archived, held_back = self._store.archive_other_sessions(session_key)
        self._running = True
        self._worker_task = asyncio.create_task(self._writer_worker())
        return archived, held_back

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
        self._store.close()

    # ------------------------------------------------------------------ #
    # 生产者接口（主循环调用）
    # ------------------------------------------------------------------ #

    def enqueue(
        self,
        bucket_index: int,
        ivs: dict[float, float],
        is_break: bool,
        session_key: str,
    ) -> None:
        """
        把一列桶数据丢进写入队列。

        ``session_key`` 是**必填**的会话身份（当日到期日）。空值直接抛错，
        不接受"没有身份的行" —— 那种行落盘后无法与其它交易日区分。

        队列满时**静默丢弃**，不阻塞主循环。丢桶数通过 ``dropped_count`` 可见。
        """
        if not self._store.enabled:
            return
        payload = {
            "_kind": "heatmap",
            "session_key": require_session_key(session_key),
            "bucket_index": int(bucket_index),
            "ivs": {str(k): float(v) for k, v in ivs.items()},
            "break": bool(is_break),
        }
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._dropped += 1

    def enqueue_skew(
        self, bucket_index: int, point: SkewPoint, session_key: str
    ) -> None:
        """把当前桶的 Skew 点丢进写入队列（``session_key`` 语义同 ``enqueue``）。"""
        if not self._store.enabled:
            return
        payload = {
            "_kind": "skew",
            "session_key": require_session_key(session_key),
            "bucket_index": int(bucket_index),
            "skew": self._skew_to_dict(point),
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

    @property
    def legacy_dropped_count(self) -> int:
        """本次运行累计丢弃的"无会话身份"旧行数（见 ``SessionFileStore``）。"""
        return self._store.legacy_dropped_count

    @property
    def archive_dir(self) -> Path:
        """历史会话库的归档目录（见 ``SessionFileStore.archive_dir``）。"""
        return self._store.archive_dir

    @property
    def session_path(self) -> Path | None:
        """
        当前打开的会话库文件路径；未打开（禁用或尚未 ``start``）为 None。

        单独暴露出来是为了让"今天到底写进哪个文件"**在日志里可见** —— 分文件
        之后这是第一个要能确认的事，而恢复为 0 个桶时原本一行日志都没有。
        """
        return self._store.current_path

    # ------------------------------------------------------------------ #
    # 恢复
    # ------------------------------------------------------------------ #

    def recover(self, session_key: str) -> list[dict]:
        """
        读取**指定会话**已存的桶，返回给 HeatmapEngine 恢复。

        会话身份同时决定读哪个文件、以及文件内按哪一段行过滤：两者都必须对。
        文件按日期分，所以"读错交易日"在路径这一层就已经不可能；列上的过滤是
        第二道 —— 它挡的是"文件被改名贴错日期"这种人工失误。

        返回格式：
        ``[{bucket_index: int, ivs: {float(strike): float}, break: bool}, ...]``
        """
        out: list[dict] = []
        for idx, ivs_json, is_break in self._store.load_heatmap(session_key):
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

    def recover_skew(self, session_key: str) -> list[SkewPoint]:
        """读取**指定会话**已存的 Skew 点，返回给 SkewEngine 恢复。"""
        out: list[SkewPoint] = []
        for _idx, skew_json in self._store.load_skew(session_key):
            try:
                d = json.loads(skew_json)
            except json.JSONDecodeError:
                continue
            out.append(self._skew_from_dict(d))
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
        """
        按会话分派：每条载荷写进**它自己**那个交易日的文件。

        批次里可能**混着两个会话** —— 跨日那一刻的队列里，旧会话的尾巴与新会话
        的开头同时存在。所以这里逐条按 ``session_key`` 切文件，而不是"打开一次、
        整批写进去"：后者会把旧会话的桶写进新会话的文件，正是分文件要堵的那类
        静默错值，只是换了个位置。

        ``open_session`` 对"已是当前会话"是空操作，所以正常批次只多一次字符串
        比较，没有额外 IO。
        """
        if not self._store.enabled:
            return
        for item in batch:
            self._store.open_session(item["session_key"])
            if item.get("_kind", "heatmap") == "heatmap":
                self._store.put_heatmap(
                    item["bucket_index"],
                    json.dumps(item["ivs"], separators=(",", ":")),
                    item["break"],
                )
            else:
                self._store.put_skew(
                    item["bucket_index"],
                    json.dumps(item["skew"], separators=(",", ":")),
                )
        self._store.commit()

    # ------------------------------------------------------------------ #
    # 序列化
    # ------------------------------------------------------------------ #

    @staticmethod
    def _skew_to_dict(point: SkewPoint) -> dict[str, Any]:
        return {
            "ts": float(point.ts),
            "spot": float(point.spot),
            "atm_iv": point.atm_iv,
            "put25_iv": point.put25_iv,
            "call25_iv": point.call25_iv,
            "put25_strike": point.put25_strike,
            "call25_strike": point.call25_strike,
            "put25_delta": point.put25_delta,
            "call25_delta": point.call25_delta,
            "skew_25d_vol_points": point.skew_25d_vol_points,
            "butterfly_vol_points": point.butterfly_vol_points,
            "quality": str(point.quality),
        }

    @staticmethod
    def _skew_from_dict(d: dict) -> SkewPoint:
        return SkewPoint(
            ts=float(d["ts"]),
            spot=float(d["spot"]),
            atm_iv=d.get("atm_iv"),
            put25_iv=d.get("put25_iv"),
            call25_iv=d.get("call25_iv"),
            put25_strike=d.get("put25_strike"),
            call25_strike=d.get("call25_strike"),
            put25_delta=d.get("put25_delta"),
            call25_delta=d.get("call25_delta"),
            skew_25d_vol_points=d.get("skew_25d_vol_points"),
            butterfly_vol_points=d.get("butterfly_vol_points"),
            quality=Quality(d.get("quality", "missing")),
        )
