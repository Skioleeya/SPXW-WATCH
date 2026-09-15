"""回归：持久化按交易日分文件 + 历史归档。

KAI 2026-09-15 定的目标：
**第一天就写第一天的数据，重启后接着写第一天的；第二天新开一份，
第二天重启，继续写第二天的。**

覆盖点
------
1. **一交易日一文件**：两个会话各自成文件，且**同一个 ``bucket_index``** 在
   两个文件里互不干扰 —— 日内坐标每交易日复用，这正是要证明隔离的地方。
2. **同日内重启续写同一文件**：跑完一轮再新起一个写入器指向同一目录，
   ``recover`` 读得回上一轮的桶；继续写之后桶数增长，**文件仍只有一个**。
3. **跨日换文件**：一个批次里混着旧会话的尾巴与新会话的开头，必须逐条按
   ``session_key`` 分派到各自的文件。
4. **坏配置被拒**：``db_filename`` 含路径分隔符时抛错（不得把库文件写到 db_dir
   之外）；``archive_dir`` 落在 db_dir 之内时抛错（否则归档件下次启动又会被
   当成待归档项，每次启动在同一批文件上打转）。
5. **保留策略 = db_dir 只留当前会话，历史归档不删**（KAI 2026-09-15 03:0x 定）：
   ``start()`` 把 db_dir 里所有非当前会话的库文件**移动**到 ``archive_dir``，
   并把 ``(已归档, 未归档)`` 返回给调用方（由 ``app/pipeline.py`` 记日志 ——
   动到一整个交易日的数据不允许静默）。**归档件内容必须完好**，这是"历史没丢"
   的判据。
6. **归档范围限制在 db_dir 之内**：旧单库 ``data/session.db`` 在 db_dir 的**上
   一级**（``db_dir`` = ``data/sessions``）。把归档写成"上一级也扫"就会把它一起
   搬走，且不报任何错 —— 所以这条要有独立用例钉住。
7. **归档目录同名不覆盖**：宁可让源文件留在 db_dir 并上报，也不静默毁掉一份历史。

第 1 / 3 条用 ``AsyncPersistenceWriter`` 走 ``_batch_write``（归档在 ``start()``
里，不影响批次内的分派）；第 5 / 7 条走 ``start()``；第 6 条直接调
``SessionFileStore.archive_other_sessions``，因为"移动范围"是 store 自己的契约。

为什么要单独一个文件
--------------------
``tools/check_persistence.py`` 已到 373 行、本组用例约 200 行，合并会破 400 行
门禁。两个文件的主题也确实是分开的：那边是"往返与队列语义"，这边是"落点、
跨日切换与归档"。

非空转验证
----------
三条判据都是**可被摘掉**的：

* 第 3 条：把 ``AsyncPersistenceWriter._batch_write`` 改成"只按 ``batch[0]`` 的
  会话开一次文件、整批写进去"，新会话的行就会落进旧会话的文件 ⇒ FAIL。
  2026-09-15 用 ``tmp/probe_mutation_rollover_batch.py`` 实测过（见会话记录）。
* 第 5 条：把 ``start()`` 里那句 ``archive_other_sessions`` 摘掉 ⇒ 旧文件仍在
  db_dir ⇒ FAIL。
* 第 7 条：把"同名跳过"改成 ``path.replace(target)``（无条件覆盖）⇒ 已有归档件
  被覆盖、源文件消失 ⇒ FAIL。

后两条 2026-09-15 用 ``tmp/probe_mutation_archive.py`` 实测（见会话记录）。

注：本文件不起真行情，也不碰 ``HeatmapEngine`` —— 只测落点、切文件与归档。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from features.persistence import AsyncPersistenceWriter  # noqa: E402
from features.persistence_store import SessionFileStore  # noqa: E402
from tools.fixtures import persist_cfg  # noqa: E402

SESSION = "20260915"
NEXT_SESSION = "20260916"
OTHER_SESSION = "20260914"


def _layout(tmp: str) -> tuple[Path, Path]:
    """测试目录布局：``<tmp>/sessions``（db_dir）+ ``<tmp>/archive``（archive_dir）。

    与真配置同形（``data/sessions`` + ``data/archive``），且**两者都在临时根
    之内** —— 否则归档会写到临时目录之外，成为跨用例的污染源。
    """
    db = Path(tmp) / "sessions"
    db.mkdir(exist_ok=True)
    return db, Path(tmp) / "archive"


def _files(directory: Path) -> list[str]:
    """目录下的库文件名（排序）。"""
    return sorted(p.name for p in directory.glob("*.db"))


def _heatmap_rows(db: Path) -> list[tuple]:
    """该文件的 ``(session_key, bucket_index, ivs_json)`` 列表。

    连接必须显式 close：``with sqlite3.connect(...)`` 只管事务、不关连接，
    在 Windows 上会让临时目录删不掉（``PermissionError 13``）。
    """
    conn = sqlite3.connect(str(db), timeout=5.0)
    try:
        return list(conn.execute(
            "SELECT session_key, bucket_index, ivs_json FROM heatmap_buckets"
            " ORDER BY bucket_index"))
    finally:
        conn.close()


def _session_keys_in(db: Path) -> set[str]:
    """该文件里出现过的会话身份集合（证明文件**自述**归属）。"""
    return {r[0] for r in _heatmap_rows(db)}


async def _run_session(writer: AsyncPersistenceWriter, key: str,
                       calls: list[tuple]) -> None:
    """跑一轮"启动 → 入队 → 停机"，模拟一次服务进程的完整生命期。

    不手动刷队列：``stop()`` 本来就会把剩余项同步落盘，走真实路径才作数。
    """
    await writer.start(key)
    for bucket_index, ivs, is_break in calls:
        writer.enqueue(bucket_index, ivs, is_break, key)
    await writer.stop()


def _case_one_file_per_session() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)
        writer = AsyncPersistenceWriter(persist_cfg(db, archive_dir=archive))
        # 刻意用同一个 index 10：日内坐标每交易日复用，这正是要证明隔离的地方
        writer.enqueue(10, {5500.0: 0.21}, False, SESSION)
        writer.enqueue(10, {5500.0: 0.11}, False, OTHER_SESSION)
        writer._batch_write([writer._queue.get_nowait() for _ in range(2)])

        today = writer.recover(SESSION)
        other = writer.recover(OTHER_SESSION)
        writer._store.close()

        assert len(today) == 1, f"今日会话应 1 个桶，实际 {len(today)}"
        assert today[0]["ivs"][5500.0] == 0.21, \
            f"今日桶的值不对（疑似取到别的会话）: {today[0]['ivs']}"
        assert len(other) == 1, f"昨日会话应 1 个桶，实际 {len(other)}"
        assert other[0]["ivs"][5500.0] == 0.11, \
            f"昨日桶的值不对（疑似取到别的会话）: {other[0]['ivs']}"

        expected = sorted([f"{SESSION}.db", f"{OTHER_SESSION}.db"])
        assert _files(db) == expected, f"两个会话应各自成文件，实际 {_files(db)}"

        for name, only in ((f"{SESSION}.db", SESSION),
                           (f"{OTHER_SESSION}.db", OTHER_SESSION)):
            keys = _session_keys_in(db / name)
            assert keys == {only}, f"{name} 里混入了别的会话的行: {keys}"


def _case_same_session_resumes_after_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)
        cfg = persist_cfg(db, archive_dir=archive)

        writer_a = AsyncPersistenceWriter(cfg)

        async def _first_run() -> None:
            await writer_a.start(SESSION)
            assert writer_a.session_path == db / f"{SESSION}.db", \
                f"落点不对: {writer_a.session_path}"
            writer_a.enqueue(10, {5500.0: 0.11}, False, SESSION)
            writer_a.enqueue(11, {5500.0: 0.12}, False, SESSION)
            await writer_a.stop()

        asyncio.run(_first_run())
        assert _files(db) == [f"{SESSION}.db"], \
            f"第一次运行应只产出 1 个文件，实际 {_files(db)}"

        # 重启：新进程、新写入器，指向同一个目录
        writer_b = AsyncPersistenceWriter(cfg)
        resumed = writer_b.recover(SESSION)
        assert len(resumed) == 2, f"重启后应读回 2 个桶，实际 {len(resumed)}"
        assert [r["bucket_index"] for r in resumed] == [10, 11]
        assert resumed[0]["ivs"][5500.0] == 0.11

        asyncio.run(_run_session(writer_b, SESSION, [(12, {5500.0: 0.13}, False)]))
        after = writer_b.recover(SESSION)
        assert len(after) == 3, f"续写后应有 3 个桶，实际 {len(after)}"
        assert [r["bucket_index"] for r in after] == [10, 11, 12]
        assert _files(db) == [f"{SESSION}.db"], \
            f"同一天内重启不得产出第二个文件，实际 {_files(db)}"


def _case_rollover_splits_batch() -> None:
    """跨日那一刻的批次里混着两个会话，必须逐条分派到各自的文件。

    非空转要点：把 ``_batch_write`` 改成"只按 ``batch[0]`` 的会话开一次文件、
    整批写进去"，新会话的行就会落进旧会话的文件 —— 本用例的第三条断言 FAIL。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)
        writer = AsyncPersistenceWriter(persist_cfg(db, archive_dir=archive))
        writer.enqueue(10, {5500.0: 0.21}, False, SESSION)
        writer.enqueue(10, {5500.0: 0.31}, False, NEXT_SESSION)
        batch = [writer._queue.get_nowait() for _ in range(2)]
        assert [i["session_key"] for i in batch] == [SESSION, NEXT_SESSION], \
            "夹具没造出跨日批次"
        writer._batch_write(batch)

        today = writer.recover(SESSION)
        nxt = writer.recover(NEXT_SESSION)
        writer._store.close()

        assert len(today) == 1, f"旧会话应 1 个桶，实际 {len(today)}"
        assert today[0]["ivs"][5500.0] == 0.21, "旧会话的桶取到了新会话的值"
        assert len(nxt) == 1, f"新会话应 1 个桶，实际 {len(nxt)}"
        assert nxt[0]["ivs"][5500.0] == 0.31, "新会话的桶取到了旧会话的值"

        expected = sorted([f"{SESSION}.db", f"{NEXT_SESSION}.db"])
        assert _files(db) == expected, f"跨日必须换文件，实际 {_files(db)}"


def _case_bad_layout_rejected() -> None:
    """两处"写错了不会报错、只会静默走偏"的配置，一律在构造时炸。

    ① ``db_filename`` 含路径分隔符 ⇒ 库文件被写到 db_dir 之外，而那种错
       **不报任何异常**，只让恢复永远读不到东西 —— 静默错值。
    ② ``archive_dir`` 落在 db_dir 之内 ⇒ 归档件下次启动又被 glob 扫到、当成
       待归档项，每次启动在同一批文件上打转，"db_dir 只留当前会话"这条不变量
       悄悄失效。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)

        for bad in ("../{session_key}.db", "sub/{session_key}.db",
                    "/elsewhere/{session_key}.db"):
            cfg = persist_cfg(db, archive_dir=archive)
            cfg["db_filename"] = bad
            writer = AsyncPersistenceWriter(cfg)
            try:
                writer._store.open_session(SESSION)
            except ValueError:
                continue
            raise AssertionError(f"越界模板未被拒绝: {bad!r}")

        for bad_archive in (db, db / "archive", db / "nested" / "archive"):
            try:
                SessionFileStore(persist_cfg(db, archive_dir=bad_archive))
            except ValueError:
                continue
            raise AssertionError(f"归档目录落在 db_dir 之内未被拒绝: {bad_archive}")

        # 对照：真布局必须放行（否则上面几条可能只是"什么都拒绝"）
        writer = AsyncPersistenceWriter(persist_cfg(db, archive_dir=archive))
        writer._store.open_session(SESSION)
        assert writer.session_path == db / f"{SESSION}.db"
        writer._store.close()


def _seed_session_file(db_dir: Path, key: str, iv: float) -> None:
    """在 db_dir 里造一个该会话的库文件（带一行数据），用来造"旧会话文件"。"""
    store = SessionFileStore(persist_cfg(db_dir))
    store.open_session(key)
    store.put_heatmap(10, json.dumps({"5500.0": iv}), False)
    store.close()


async def _start_capture_stop(
    writer: AsyncPersistenceWriter, key: str
) -> tuple[list[str], list[str], Path | None]:
    """跑一轮"启动 → 停机"，带出 ``start()`` 的归档结果与**停机前**的落点。

    落点必须在 ``stop()`` **之前**取：``stop()`` 会 ``close()``，而 ``close()``
    把 ``_open_key`` 清成 None ⇒ 停机后 ``session_path`` 恒为 None（不是缺陷，
    是"没打开任何会话"的正确表达）。
    """
    archived, held_back = await writer.start(key)
    path = writer.session_path
    await writer.stop()
    return archived, held_back, path


def _case_start_archives_other_sessions() -> None:
    """保留策略：``start()`` 把非当前会话的库文件**移动**到归档目录，不删。

    非空转要点：把 ``AsyncPersistenceWriter.start`` 里那句
    ``archive_other_sessions`` 摘掉，本用例立即 FAIL（两个旧文件仍在 db_dir）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)
        stale = (OTHER_SESSION, "20260913")
        for key in stale:
            _seed_session_file(db, key, 0.99)
        assert _files(db) == sorted(f"{k}.db" for k in stale), \
            f"夹具没造出旧会话文件，实际 {_files(db)}"

        writer = AsyncPersistenceWriter(persist_cfg(db, archive_dir=archive))
        archived, held_back, path = asyncio.run(_start_capture_stop(writer, SESSION))

        assert held_back == [], f"不该有未归档项，实际 {held_back}"
        assert sorted(archived) == sorted(f"{k}.db" for k in stale), \
            f"应返回被归档的两个文件名，实际 {archived}"
        assert _files(db) == [f"{SESSION}.db"], \
            f"启动后 db_dir 只应剩当前会话的文件，实际 {_files(db)}"
        assert path == db / f"{SESSION}.db", f"落点不对: {path}"

        # **历史没丢**：归档件在归档目录里，且内容完好（不是空壳）
        assert _files(archive) == sorted(f"{k}.db" for k in stale), \
            f"归档目录应有那两个文件，实际 {_files(archive)}"
        for key in stale:
            rows = _heatmap_rows(archive / f"{key}.db")
            assert len(rows) == 1 and rows[0][0] == key, \
                f"{key} 的归档件丢了行: {rows}"
            assert json.loads(rows[0][2]) == {"5500.0": 0.99}, \
                f"{key} 的归档件内容不对: {rows[0][2]}"

        # 当前会话那一份是新建的空库（没被自己搬走），读取正常
        assert writer.recover(SESSION) == []


def _case_archive_leaves_parent_dir_alone() -> None:
    """归档范围严格限制在 db_dir 之内 —— 旧单库 ``data/session.db`` 在上一级。

    这条不是洁癖：``data/session.db`` 与 db_dir（``data/sessions``）只差一层
    目录，把归档写成"连上一级一起扫"就会把它一起搬走，而且**不报任何错**。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)
        legacy = Path(tmp) / "session.db"           # 上一级：旧单库的命名形状
        legacy.write_bytes(b"legacy")
        stale = db / f"{OTHER_SESSION}.db"
        stale.write_bytes(b"stale")
        keep = db / f"{SESSION}.db"
        keep.write_bytes(b"keep")

        store = SessionFileStore(persist_cfg(db, archive_dir=archive))
        archived, held_back = store.archive_other_sessions(SESSION)

        assert archived == [f"{OTHER_SESSION}.db"], \
            f"应只搬 db_dir 内的旧会话文件，实际 {archived}"
        assert held_back == [], f"不该有未归档项，实际 {held_back}"
        assert legacy.exists(), "上一级的旧单库被误搬了 —— 归档范围越出了 db_dir"
        assert keep.exists(), "当前会话的文件被搬走了"
        assert not stale.exists(), "db_dir 内的旧会话文件没被搬走"
        assert (archive / f"{OTHER_SESSION}.db").exists(), "归档件不在归档目录里"


def _case_archive_conflict_does_not_overwrite() -> None:
    """归档目录已有同名 ⇒ **不覆盖**，源文件留在 db_dir 并计入"未归档"。

    为什么不能覆盖：归档件是**唯一**一份历史。同名意味着"这个交易日已经归档过"
    —— 覆盖等于用一份来源不明的数据替掉已有历史，且不报任何错。宁可让源文件
    留在 db_dir（下次启动再试）并把冲突上报。

    非空转要点：把"同名跳过"改成 ``path.replace(target)``（无条件覆盖），本用例
    的第二、三条断言立即 FAIL。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db, archive = _layout(tmp)
        archive.mkdir(exist_ok=True)
        _seed_session_file(db, OTHER_SESSION, 0.11)
        old = archive / f"{OTHER_SESSION}.db"
        old.write_bytes(b"already-archived")        # 已有归档件（内容刻意不同）

        store = SessionFileStore(persist_cfg(db, archive_dir=archive))
        archived, held_back = store.archive_other_sessions(SESSION)

        assert archived == [], f"同名时不该归档，实际 {archived}"
        assert held_back == [f"{OTHER_SESSION}.db"], \
            f"同名应计入未归档，实际 {held_back}"
        assert old.read_bytes() == b"already-archived", "已有归档件被覆盖了"
        assert (db / f"{OTHER_SESSION}.db").exists(), \
            "同名时源文件应留在 db_dir（下次启动再试）"


_CASES = [
    _case_one_file_per_session,
    _case_same_session_resumes_after_restart,
    _case_rollover_splits_batch,
    _case_bad_layout_rejected,
    _case_start_archives_other_sessions,
    _case_archive_leaves_parent_dir_alone,
    _case_archive_conflict_does_not_overwrite,
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
