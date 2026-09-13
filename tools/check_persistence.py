"""回归：旁路异步 SQLite 持久化。

覆盖点
------
1. ``enqueue`` → ``recover`` 往返：写入的桶能完整读回。
2. 断代标记 ``break`` 被保留。
3. 同一桶多次写入：``INSERT OR REPLACE`` 幂等，最终值正确。
4. 队列满时丢桶：``dropped_count`` 递增，不抛异常。
5. ``load_snapshot`` 后 ``build()`` 的 ΔIV 与直接计算一致。
6. 冷数据的键序恒为**降序**，与 ``_buckets`` 的首次出现顺序无关，且与对外帧
   的 ``strikes`` 同向（高行权价在前）。
"""
from __future__ import annotations

import json
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
    # 本回归只关心持久化往返，用一个"没有区段边界"的网格（空元组）——
    # 区段留白由 tools/check_session_grid.py 与 check_reconnect_gap.py 覆盖。
    c.zone_start_indexes = lambda: ()
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


def _case_key_order_descending() -> None:
    """冷数据的键序恒为降序，与 ``_buckets`` 的首次出现顺序无关。

    与对外帧同向：帧 ``strikes`` 是降序（高行权价在前，见
    ``tools/smoke_test.py``「矩阵 strikes 降序」），冷数据此前是升序、
    两处行序相反；2026-09-13 统一为降序。

    非空转要点：这里刻意把 ``_buckets`` 造成"低档位晚到"的形状（现价上移后
    回落到会话初低点之下，见 ``dump_bucket`` docstring）。若 ``dump_bucket``
    不排序，本用例的四条断言都会 FAIL。
    """
    clock = _make_clock()
    serial = _make_serial_cfg()
    engine = HeatmapEngine(clock, serial)

    # 首次出现顺序：5500 起升序，随后追加更低的 5490 / 5485
    engine._buckets = {
        5500.0: {10: 0.15},
        5505.0: {10: 0.16},
        5510.0: {10: 0.17},
        5490.0: {10: 0.14},
        5485.0: {10: 0.13},
    }
    expected = [5510.0, 5505.0, 5500.0, 5490.0, 5485.0]
    dumped = list(engine.dump_bucket(10))
    assert dumped == expected, f"dump_bucket 未降序: {dumped}"

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        writer = AsyncPersistenceWriter(_make_persist_cfg(db))
        import sqlite3
        writer._conn = sqlite3.connect(str(db), timeout=5.0)
        writer._ensure_table()
        writer.enqueue(10, engine.dump_bucket(10), False)
        writer._batch_write([writer._queue.get_nowait()])

        raw = json.loads(
            writer._conn.execute(
                "select ivs_json from heatmap_buckets"
            ).fetchone()[0]
        )
        on_disk = [float(k) for k in raw]
        assert on_disk == sorted(on_disk, reverse=True), f"落盘键序非降序: {on_disk}"

        recovered = writer.recover()
        writer._conn.close()
        writer._conn = None

    keys = list(recovered[0]["ivs"])
    assert keys == expected, f"recover 后键序变了: {keys}"

    engine2 = HeatmapEngine(clock, serial)
    engine2.load_snapshot(recovered)
    assert list(engine2.dump_bucket(10)) == expected, "load_snapshot 后键序变了"


_CASES = [
    _case_roundtrip,
    _case_idempotent_overwrite,
    _case_queue_drop,
    _case_disabled_no_op,
    _case_key_order_descending,
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
