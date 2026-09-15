"""回归：旁路异步 SQLite 持久化（往返与队列语义）。

覆盖点
------
1. ``enqueue`` → ``recover`` 往返：写入的桶能完整读回。
2. 断代标记 ``break`` 被保留。
3. 同一桶多次写入：``INSERT OR REPLACE`` 幂等，最终值正确。
4. 队列满时丢桶：``dropped_count`` 递增，不抛异常。
5. ``load_snapshot`` 后引擎状态与落盘内容一致（行数、断代数、断代桶）。
6. 冷数据的键序恒为**降序**，与 ``_buckets`` 的首次出现顺序无关，且与对外帧
   的 ``strikes`` 同向（高行权价在前）。
7. **旧结构迁移**：缺 ``session_key`` 列的旧表被整张丢弃，且丢弃行数被如实报出。
8. **空会话身份被拒**：写入与读取两侧都不得接受"无身份的行"。

**分文件语义**（一交易日一文件、同日内重启续写、跨日切文件、模板越界）不在本
文件，在 ``tools/check_persistence_sessions.py`` —— 两个文件各自 < 400 行，且
各自只有一个主题。

注：本文件**不**覆盖 ``build()`` 的 ΔIV（``_row_values`` 的前向填充与留白由
``tools/check_reconnect_gap.py`` 覆盖），此前 docstring 声称覆盖，与代码不符。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import loader  # noqa: E402
from features.heatmap_engine import HeatmapEngine  # noqa: E402
from features.persistence import AsyncPersistenceWriter  # noqa: E402
from tools.fixtures import persist_cfg  # noqa: E402

SESSION = "20260915"


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
    """串行化配置：**直接用真配置，不要在这里手写键表**。

    ``HeatmapEngine.__init__`` 每加一个必读键（如 ``6828e3a`` 新增的
    ``heatmap_max_ffill_buckets``），手写夹具就会漏，而 ``config.loader`` 按
    「缺键即抛错」fail-fast ⇒ 整条回归变红。2026-09-14 实测：本文件正是这样
    自 ``6828e3a`` 起红了（``3/5 通过``）而无人察觉 —— 手写的测试夹具是
    **第二份真相**，必然漂移。真配置是唯一真相，与
    ``tools/check_reconnect_gap.py`` 同一手法。

    本回归不碰 ``_prune``（只在 ``ingest`` 里用 ``_max_buckets``）与 ``build()``
    （只在里面用 ``_min_buckets``），所以网格大小取真值即可，无需覆盖。

    返回**浅拷贝** —— ``loader.load`` 带缓存，直接改会污染其它检查。
    """
    return dict(loader.load("serialization"))


def _open(writer: AsyncPersistenceWriter) -> None:
    """白盒：直接打开会话文件，不起 async worker（回归要确定性、不要后台竞争）。"""
    writer._store.open_session(SESSION)


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
        writer = AsyncPersistenceWriter(persist_cfg(Path(tmp)))
        _open(writer)

        # 手动入队并同步刷
        for idx in (10, 11, 12):
            ivs = engine.dump_bucket(idx)
            writer.enqueue(idx, ivs, engine.is_break(idx), SESSION)
        writer._batch_write([writer._queue.get_nowait() for _ in range(3)])

        recovered = writer.recover(SESSION)
        writer._store.close()
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
    with tempfile.TemporaryDirectory() as tmp:
        writer = AsyncPersistenceWriter(persist_cfg(Path(tmp)))
        _open(writer)

        # 第一次写入
        writer.enqueue(5, {5500.0: 0.10}, False, SESSION)
        writer._batch_write([writer._queue.get_nowait()])

        # 第二次覆盖同一桶
        writer.enqueue(5, {5500.0: 0.99}, False, SESSION)
        writer._batch_write([writer._queue.get_nowait()])

        recovered = writer.recover(SESSION)
        writer._store.close()

        assert len(recovered) == 1
        assert recovered[0]["ivs"][5500.0] == 0.99


def _case_queue_drop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        writer = AsyncPersistenceWriter(persist_cfg(Path(tmp), queue_maxsize=2))

        writer.enqueue(1, {5500.0: 0.1}, False, SESSION)
        writer.enqueue(2, {5500.0: 0.2}, False, SESSION)
        writer.enqueue(3, {5500.0: 0.3}, False, SESSION)  # 队列满，应被丢弃
        assert writer.dropped_count == 1


def _case_disabled_no_op() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = persist_cfg(Path(tmp))
        cfg["enabled"] = False
        writer = AsyncPersistenceWriter(cfg)

        writer.enqueue(1, {5500.0: 0.1}, False, SESSION)
        assert writer.dropped_count == 0  # 不操作
        assert writer.recover(SESSION) == []
        assert writer.session_path is None, "关闭状态不得打开任何库文件"


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
        writer = AsyncPersistenceWriter(persist_cfg(Path(tmp)))
        _open(writer)
        writer.enqueue(10, engine.dump_bucket(10), False, SESSION)
        writer._batch_write([writer._queue.get_nowait()])

        rows = writer._store.load_heatmap(SESSION)
        assert len(rows) == 1, f"应落盘 1 行，实际 {len(rows)}"
        raw = json.loads(rows[0][1])
        on_disk = [float(k) for k in raw]
        assert on_disk == sorted(on_disk, reverse=True), f"落盘键序非降序: {on_disk}"

        recovered = writer.recover(SESSION)
        writer._store.close()

    keys = list(recovered[0]["ivs"])
    assert keys == expected, f"recover 后键序变了: {keys}"

    engine2 = HeatmapEngine(clock, serial)
    engine2.load_snapshot(recovered)
    assert list(engine2.dump_bucket(10)) == expected, "load_snapshot 后键序变了"


def _case_legacy_table_dropped() -> None:
    """缺 ``session_key`` 列的旧表必须整张丢弃，并**如实报出**丢弃行数。

    旧行没有会话身份 ⇒ 留着只能靠猜；宁可丢。判据同时要求丢弃数被报出 ——
    否则"丢弃"会变成静默的数据丢失，比错值更难发现。

    再跑一次 ``ensure_tables()`` 不得再丢（累计值不变），否则每次重启都会把当天
    的数据也丢掉。
    """
    with tempfile.TemporaryDirectory() as tmp:
        cfg = persist_cfg(Path(tmp))
        # 文件名从真配置的模板派生，不在这里写死 —— 否则模板改了、回归还在测旧名字
        db = Path(tmp) / cfg["db_filename"].format(session_key=SESSION)
        conn = sqlite3.connect(str(db), timeout=5.0)
        conn.execute(
            "CREATE TABLE heatmap_buckets ("
            "bucket_index INTEGER PRIMARY KEY, ivs_json TEXT NOT NULL, "
            "is_break INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE skew_points ("
            "bucket_index INTEGER PRIMARY KEY, skew_json TEXT NOT NULL)"
        )
        for i in range(4):
            conn.execute(
                "INSERT INTO heatmap_buckets VALUES (?, ?, 0)",
                (i, json.dumps({"5500.0": 0.1})),
            )
        conn.execute("INSERT INTO skew_points VALUES (?, ?)", (0, "{}"))
        conn.commit()
        conn.close()

        writer = AsyncPersistenceWriter(cfg)
        _open(writer)

        assert writer.legacy_dropped_count == 5, \
            f"应丢弃 4 桶 + 1 点 = 5 行，实际 {writer.legacy_dropped_count}"
        assert writer.recover(SESSION) == [], "旧行仍被恢复"
        assert writer.recover_skew(SESSION) == [], "旧 Skew 点仍被恢复"

        writer._store.ensure_tables()
        assert writer.legacy_dropped_count == 5, "新结构不应再触发丢弃"
        writer._store.close()


def _case_empty_session_key_rejected() -> None:
    """空会话身份必须抛错，不得落盘成"无身份的行"。

    空值落盘后与其它交易日无法区分，恢复时只能靠猜 —— 那正是本模块要堵的
    静默错值。写入与读取两侧都要拦。
    """
    with tempfile.TemporaryDirectory() as tmp:
        writer = AsyncPersistenceWriter(persist_cfg(Path(tmp)))
        for bad in ("", "   "):
            for call in (
                lambda: writer.enqueue(1, {5500.0: 0.1}, False, bad),
                lambda: writer.enqueue_skew(1, MagicMock(), bad),
                lambda: writer.recover(bad),
                lambda: writer.recover_skew(bad),
            ):
                try:
                    call()
                except ValueError:
                    continue
                raise AssertionError(f"空会话身份未被拒绝: {bad!r}")
        assert writer._queue.empty(), "被拒的载荷不得入队"


_CASES = [
    _case_roundtrip,
    _case_idempotent_overwrite,
    _case_queue_drop,
    _case_disabled_no_op,
    _case_key_order_descending,
    _case_legacy_table_dropped,
    _case_empty_session_key_rejected,
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
