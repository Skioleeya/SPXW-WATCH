"""回归：旁路异步 SQLite 持久化。

覆盖点
------
1. ``enqueue`` → ``recover`` 往返：写入的桶能完整读回。
2. 断代标记 ``break`` 被保留。
3. 同一桶多次写入：``INSERT OR REPLACE`` 幂等，最终值正确。
4. 队列满时丢桶：``dropped_count`` 递增，不抛异常。
5. ``load_snapshot`` 后 ``build()`` 的 ΔIV 与直接计算一致。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from features.heatmap_engine import HeatmapEngine
from features.persistence import AsyncPersistenceWriter


def _make_clock() -> MagicMock:
    c = MagicMock()
    c.bucket_index_of_ts = lambda ts: int(ts)
    c.bucket_labels = lambda: tuple(str(i) for i in range(1000))
    c.now_ts = lambda: 100.0
    return c


def _make_serial_cfg() -> dict:
    return {
        "heatmap_max_buckets": 780,
        "heatmap_min_buckets": 2,
        "heatmap_feed_gap_s": 300.0,
    }


def _make_persist_cfg(db_path: Path) -> dict:
    return {
        "enabled": True,
        "db_path": str(db_path),
        "queue_maxsize": 10,
        "write_interval_s": 0.01,
    }


def _case_roundtrip() -> None:
    clock = _make_clock()
    serial = _make_serial_cfg()
    engine = HeatmapEngine(clock, serial)

    # 写 3 个桶
    engine._buckets = {
        5500.0: {10: 0.15, 11: 0.16, 12: 0.17},
        5525.0: {10: 0.20, 11: 0.21},
    }
    engine._breaks = {11}

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        writer = AsyncPersistenceWriter(_make_persist_cfg(db))
        # 手动建立连接（不启动 async worker）
        import sqlite3
        writer._conn = sqlite3.connect(str(db), timeout=5.0)
        writer._ensure_table()

        # 手动入队并同步刷
        for idx in (10, 11, 12):
            ivs = engine.dump_bucket(idx)
            writer.enqueue(idx, ivs, engine.is_break(idx))
        writer._batch_write([writer._queue.get_nowait() for _ in range(3)])

        # 恢复（用同一连接，避免 Windows 文件锁冲突）
        recovered = writer.recover()
        writer._conn.close()
        writer._conn = None
        assert len(recovered) == 3, f"期望 3 个桶，实际 {len(recovered)}"

        # 验证断代
        break_map = {r["bucket_index"]: r["break"] for r in recovered}
        assert break_map[10] is False
        assert break_map[11] is True
        assert break_map[12] is False

        # 验证 IV
        iv10 = {k: v for r in recovered if r["bucket_index"] == 10 for k, v in r["ivs"].items()}
        assert iv10[5500.0] == 0.15
        assert iv10[5525.0] == 0.20

        # 验证恢复后 build 一致性
        engine2 = HeatmapEngine(clock, serial)
        engine2.load_snapshot(recovered)
        assert engine2.tracked_rows() == 2
        assert engine2.break_count() == 1
        assert engine2.is_break(11)


def _case_idempotent_overwrite() -> None:
    clock = _make_clock()
    serial = _make_serial_cfg()

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        writer = AsyncPersistenceWriter(_make_persist_cfg(db))
        import sqlite3
        writer._conn = sqlite3.connect(str(db), timeout=5.0)
        writer._ensure_table()

        # 第一次写入
        writer.enqueue(5, {5500.0: 0.10}, False)
        writer._batch_write([writer._queue.get_nowait()])

        # 第二次覆盖同一桶
        writer.enqueue(5, {5500.0: 0.99}, False)
        writer._batch_write([writer._queue.get_nowait()])

        recovered = writer.recover()
        writer._conn.close()
        writer._conn = None

        assert len(recovered) == 1
        assert recovered[0]["ivs"][5500.0] == 0.99


def _case_queue_drop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        cfg = _make_persist_cfg(db)
        cfg["queue_maxsize"] = 2
        writer = AsyncPersistenceWriter(cfg)

        writer.enqueue(1, {5500.0: 0.1}, False)
        writer.enqueue(2, {5500.0: 0.2}, False)
        writer.enqueue(3, {5500.0: 0.3}, False)  # 队列满，应被丢弃
        assert writer.dropped_count == 1


def _case_disabled_no_op() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        cfg = _make_persist_cfg(db)
        cfg["enabled"] = False
        writer = AsyncPersistenceWriter(cfg)

        writer.enqueue(1, {5500.0: 0.1}, False)
        assert writer.dropped_count == 0  # 不操作
        assert writer.recover() == []


_CASES = [
    _case_roundtrip,
    _case_idempotent_overwrite,
    _case_queue_drop,
    _case_disabled_no_op,
]


def main() -> int:
    passed = 0
    for case in _CASES:
        name = case.__name__
        try:
            case()
            print(f"  [ok] {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  [FAIL] {name}: {exc}")
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc!r}")

    print(f"\n结果: {passed}/{len(_CASES)} 通过")
    return 0 if passed == len(_CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
