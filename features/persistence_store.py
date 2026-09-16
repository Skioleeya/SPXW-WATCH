"""
L5 — 按交易日分文件的 SQLite 存储。
=====================================
把"哪个交易日的数据放在哪个文件里"变成**文件系统上的事实**。

为什么分文件
------------
``bucket_index`` 是**日内坐标**（0..2369），**每个交易日复用同一段序号**。多个交易日塞进
同一张表就只能靠一列 ``session_key`` 去区分；那列丢了或某次查询忘了带过滤，昨天的桶就会
落到今天的时刻上 —— 2026-09-15 实测到的正是这个形状：昨天 RTH 的桶被画在今天 GTH 的时刻
上，帧的 ``skew.latest``（取 ``skew_series[-1]``）报出昨天 14:26:48 的点。分文件把这条
不变量抬到**文件边界**：``data/sessions/20260915.db`` 里只可能有 20260915 的桶 ——
读错都读不到，不依赖任何一列，也不依赖任何一次 WHERE。

会话身份在运行期会变（``_sync_session()`` 翻篇时改 ``_session_key`` 并 ``reset()``），
所以跨日那一刻必须**换文件**，否则新会话的桶继续写进旧日期的文件，下次启动从新日期
里什么也读不到 —— 静默丢数据，只是换了个位置。三种时序：同一天内重启 ⇒ 接着写
**同一个文件**；跨日 ⇒ 换**新文件**（会话身份由调用方提供，本模块**不自行推算**）；
旧结构文件 ⇒ 整张丢弃并**报出行数**。宁可丢，不可错。

**库文件用 WAL**（在 ``open_session`` 里设；它是写在库文件头的**持久属性**，设一次即可）。
``-wal`` / ``-shm`` 是 SQLite 的**附属文件**，不是"另一个交易日的库"：正常关闭时由 SQLite
自行归并清除；被硬杀则残留，由 ``archive_other_sessions`` **随库文件一起搬走** ——
漏搬就是把 WAL 里那部分数据永久丢掉。

保留策略：db_dir 只留当前会话，历史**归档不删**
------------------------------------------------
别的交易日的文件对本会话既不能读也不该读（读了就是把别天的桶画到今天），所以不该留在
db_dir 里；但它们**不是垃圾** —— 那是逐交易日的 ΔIV / Skew **原始记录**，回看、对拍、
做数据集只有这一份来源（KAI 2026-09-15：**"这就是历史数据，有用"**）。⇒ 启动时把非当前
会话的库文件（**连同 WAL 附属文件**）**移动**到 ``archive_dir``（``archive_other_sessions``）：
范围严格限制在 db_dir 之内，归档目录里**同名一律不覆盖**（跳过并上报，宁可留着也不毁历史）。
2026-09-15 02:2x 曾实现为 ``unlink()`` 删除（把 KAI "不留档、不备份"的适用范围从旧单库
``data/session.db`` 误扩到全部逐日文件）；同日改回归档，别"简化"回去。

本模块只管"文件与表"：路径派生、连接的开/切/关、建表、写入、只读取行、归档
非当前会话的文件。队列、批量调度与序列化（dict ↔ JSON、SkewPoint ↔ dict）都在
``features/persistence.py``。

依赖：L0（config）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from config import loader
from features.persistence_archive import SessionArchiver

_PERSIST = "persistence"


def require_session_key(session_key: str) -> str:
    """
    校验并归一化会话身份。

    空值一律抛错，不接受"没有身份的行"。会话身份要变成**文件名**，空身份会产出
    ``.db`` 这种无归属的文件，恢复时只能靠猜 —— 那正是本模块要堵的静默错值。
    定义在这里而不是各调用点各写一份：写入侧与读取侧都要拦，两份实现必然漂移。
    """
    key = str(session_key).strip()
    if not key:
        raise ValueError("会话身份（session_key）不能为空：无身份的桶无法与其它交易日区分")
    return key


class SessionFileStore:
    """
    一个交易日一个 SQLite 文件的存储。

    生命周期
    --------
    ``open_session(key)``：把连接切到该会话的文件（已打开同一会话时空操作）。
    ``put_heatmap`` / ``put_skew``：写入**当前打开的**会话（不提交）。
    ``commit()``：提交一批。
    ``load_heatmap(key)`` / ``load_skew(key)``：只读该会话的文件取行。
    ``close()``：关闭连接。

    行里的 ``session_key`` 取自 ``_open_key``（当前文件名所代表的会话），**不是**
    调用方每条各传一个 —— 这样"行里的会话"与"文件名里的会话"由构造保证一致，
    不可能对不上。
    """

    __slots__ = ("_enabled", "_db_dir", "_filename", "_archiver", "_conn",
                 "_open_key", "_legacy_dropped")

    def __init__(self, persist_cfg: dict) -> None:
        self._enabled = loader.as_bool(persist_cfg, "enabled", module=_PERSIST)
        self._db_dir = Path(loader.as_str(persist_cfg, "db_dir", module=_PERSIST))
        self._filename = loader.as_str(persist_cfg, "db_filename", module=_PERSIST)
        self._archiver = SessionArchiver(
            self._db_dir,
            Path(loader.as_str(persist_cfg, "archive_dir", module=_PERSIST)),
            self._filename,
        )
        self._conn: sqlite3.Connection | None = None
        self._open_key: str | None = None
        self._legacy_dropped = 0

    # ------------------------------------------------------------------ #
    # 只读属性
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def open_key(self) -> str | None:
        """当前打开的是哪个会话的文件；未打开为 None。"""
        return self._open_key

    @property
    def current_path(self) -> Path | None:
        """当前打开会话的库文件路径；未打开为 None（禁用或尚未 ``open_session``）。"""
        return None if self._open_key is None else self.path_for(self._open_key)

    @property
    def legacy_dropped_count(self) -> int:
        """本次运行**累计**丢弃的"无会话身份"旧行数（见 ``_drop_legacy_tables``）。"""
        return self._legacy_dropped

    @property
    def archive_dir(self) -> Path:
        """历史会话库的归档目录（``persistence.json::archive_dir``）。"""
        return self._archiver.archive_dir

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #

    def path_for(self, session_key: str) -> Path:
        """
        该会话的库文件路径。

        文件名由 ``persistence.json::db_filename`` 的 ``{session_key}`` 占位符
        决定（不硬编码）。**必须落在 db_dir 之内**：模板里出现 ``/`` 或 ``..``
        会把文件写到别处，而那种错不会报任何异常，只会让"恢复"永远读不到东西
        —— 所以这里越界即抛错，不静默接受。
        """
        key = require_session_key(session_key)
        path = self._db_dir / self._filename.format(session_key=key)
        if path.parent != self._db_dir:
            raise ValueError(
                f"db_filename 模板 {self._filename!r} 让会话 {key} 的库文件落在 "
                f"db_dir 之外（{path}）—— 模板不得含路径分隔符"
            )
        return path

    def archive_other_sessions(self, keep_key: str) -> tuple[list[str], list[str]]:
        """
        把 db_dir 里**非当前会话**的库文件**移动**到 ``archive_dir``。

        实现见 ``features/persistence_archive.py::SessionArchiver`` —— 那段逻辑
        （范围闸门、WAL 附属文件、同名不覆盖）只在启动时跑一次、与运行期的"开/写/读"
        无关，故按单一职能拆出；本方法只做**会话身份 → 文件名**的翻译与开关判断。

        返回 ``(已归档, 未归档)``：已归档 = 真正搬走的；未归档 = 归档目录已有同名
        （**不覆盖**，源文件留在 db_dir）或移动失败。两组都要记日志（调用方负责）：
        "没归档成功"必须比"归档成功"更显眼。本模块**不自行触发**归档 —— 它不知道
        "什么时候算旧"，只知道"哪个不是当前"。
        """
        key = require_session_key(keep_key)
        if not self._enabled:
            return [], []
        return self._archiver.archive_other_sessions(self.path_for(key).name)

    # ------------------------------------------------------------------ #
    # 连接
    # ------------------------------------------------------------------ #

    def open_session(self, session_key: str) -> None:
        """
        把连接切到该会话的文件。

        **已打开同一会话时是空操作** —— 热路径（批量写入）会对每条载荷调用它，
        换文件只在会话真的变了时才发生。关闭旧文件再开新文件，不做"两个文件同时
        开着"的优化：那会让 fd 随交易日累积，而本进程一次只服务一个会话。
        WAL 设不上时**抛错**：PRAGMA 对不支持的模式不报错、只沿用旧模式（见模块 docstring）。
        """
        key = require_session_key(session_key)
        if not self._enabled or key == self._open_key:
            return
        self.close()
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), timeout=5.0)
        mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError(f"{path} 无法切到 WAL 模式（PRAGMA 返回 {mode!r}）")
        self._open_key = key
        self.ensure_tables()

    def close(self) -> None:
        """
        提交并关闭当前连接。

        **必须先提交**：``sqlite3.Connection.close()`` 对未提交的事务是**回滚**。
        ``open_session`` 内部就是"close 再开"，所以换文件时若不提交，刚写进旧文件
        的整批数据会被丢掉 —— 而且**不报任何错**。

        2026-09-15 实测：跨日批次里旧会话的那一行就是这样消失的
        （``check_persistence_sessions`` 报"旧会话应 1 个桶，实际 0"）。批尾本来
        还会 ``commit()`` 一次，但那已经写在**新**文件的连接上了。
        """
        if self._conn is not None:
            self.commit()
            self._conn.close()
        self._conn = None
        self._open_key = None

    # ------------------------------------------------------------------ #
    # 表
    # ------------------------------------------------------------------ #

    def ensure_tables(self) -> None:
        """
        在当前连接上建表；若检测到**缺会话列的旧结构**，整张丢弃。

        ``session_key`` 仍是表的一部分（虽然文件名已经表达了它）：让文件**自述**
        归属。有人把文件改名贴错日期时，查询里的 ``WHERE session_key = ?`` 会
        一条都取不到（返回空 ⇒ 图上留白），而不是把别天的桶当成这天的画出来。
        """
        if self._conn is None:
            return
        self._legacy_dropped += self._drop_legacy_tables()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS heatmap_buckets ("
            "session_key TEXT NOT NULL, "
            "bucket_index INTEGER NOT NULL, "
            "ivs_json TEXT NOT NULL, "
            "is_break INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (session_key, bucket_index)"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS skew_points ("
            "session_key TEXT NOT NULL, "
            "bucket_index INTEGER NOT NULL, "
            "skew_json TEXT NOT NULL, "
            "PRIMARY KEY (session_key, bucket_index)"
            ")"
        )
        self._conn.commit()

    def _drop_legacy_tables(self) -> int:
        """
        丢弃"没有会话身份"的旧表，返回被丢弃的行数。

        旧表的主键只有 ``bucket_index``（日内坐标、每交易日复用），**无法判断
        一行属于哪一天** ⇒ 留着就等于把别的交易日的桶回灌进本会话。**宁可丢，
        不可错**：这些桶在新会话里本来就无效，行情重跑会重新写入。

        只在检测到旧结构（表存在且缺 ``session_key`` 列）时执行；已是新结构的
        表原样保留、不受影响。
        """
        if self._conn is None:
            return 0
        dropped = 0
        for table in ("heatmap_buckets", "skew_points"):
            cols = {
                row[1] for row in
                self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not cols or "session_key" in cols:
                continue
            row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            dropped += int(row[0]) if row else 0
            self._conn.execute(f"DROP TABLE {table}")
        return dropped

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #

    def put_heatmap(self, bucket_index: int, ivs_json: str, is_break: bool) -> None:
        """写入当前打开的会话。``session_key`` 取 ``_open_key``（见类 docstring）。"""
        self._execute(
            "INSERT OR REPLACE INTO heatmap_buckets "
            "(session_key, bucket_index, ivs_json, is_break) VALUES (?, ?, ?, ?)",
            (self._open_key, int(bucket_index), ivs_json, int(is_break)),
        )

    def put_skew(self, bucket_index: int, skew_json: str) -> None:
        """写入当前打开的会话。"""
        self._execute(
            "INSERT OR REPLACE INTO skew_points "
            "(session_key, bucket_index, skew_json) VALUES (?, ?, ?)",
            (self._open_key, int(bucket_index), skew_json),
        )

    def commit(self) -> None:
        """提交当前批次。失败静默（同 ``_execute``）。"""
        if self._conn is None:
            return
        try:
            self._conn.commit()
        except sqlite3.Error:
            pass

    def _execute(self, sql: str, params: tuple) -> None:
        """
        执行一条写语句。

        **写失败静默**：本模块是旁路，写不进去不能中断行情主流程与 WebSocket
        推送。丢桶数由 ``AsyncPersistenceWriter.dropped_count`` 与日志侧可见，
        不在这一层抛错。
        """
        if self._conn is None:
            return
        try:
            self._conn.execute(sql, params)
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #

    def load_heatmap(self, session_key: str) -> list[tuple]:
        """该会话的 ``(bucket_index, ivs_json, is_break)``，按桶序号升序。"""
        return self._read_rows(
            session_key,
            "SELECT bucket_index, ivs_json, is_break FROM heatmap_buckets "
            "WHERE session_key = ? ORDER BY bucket_index",
        )

    def load_skew(self, session_key: str) -> list[tuple]:
        """该会话的 ``(bucket_index, skew_json)``，按桶序号升序。"""
        return self._read_rows(
            session_key,
            "SELECT bucket_index, skew_json FROM skew_points "
            "WHERE session_key = ? ORDER BY bucket_index",
        )

    def _read_rows(self, session_key: str, sql: str) -> list[tuple]:
        """
        按会话身份取行。

        已打开同一会话时复用现有连接（Windows 上对同一文件反复开关连接既慢又
        容易撞锁）；否则只读打开该会话的文件。文件不存在、或读失败，一律返回
        空表 —— 旁路：读不出来不拖垮启动。

        ⚠️ 临时连接必须**显式 close**，不能用 ``with sqlite3.connect(...)`` ——
        连接对象的上下文管理器只管事务（提交/回滚），**不关闭连接**。原来那种
        写法在"总是复用已打开连接"时看不出问题；分文件之后，读取**非当前会话**
        的文件每次都走临时连接，泄漏就成了常态：Windows 上句柄不释放，测试的
        临时目录删不掉（``PermissionError 13``），长期跑则句柄数单调增长。
        """
        key = require_session_key(session_key)
        if not self._enabled:
            return []
        try:
            if key == self._open_key and self._conn is not None:
                return self._conn.execute(sql, (key,)).fetchall()
            path = self.path_for(key)
            if not path.exists():
                return []
            conn = sqlite3.connect(str(path), timeout=5.0)
            try:
                return conn.execute(sql, (key,)).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []
