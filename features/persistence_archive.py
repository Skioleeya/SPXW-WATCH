"""
L5 — 历史会话库的归档（**单一职能**）。
========================================

只做一件事：把 ``db_dir`` 里**非当前会话**的库文件搬到 ``archive_dir``。

为什么独立成文件
----------------
``features/persistence_store.py`` 管的是"当前会话的库怎么开、怎么写、怎么读"；
归档是**旁路的旁路** —— 只在启动时跑一次，处理的全是**与运行期已无关**的文件。
两者混在一起会让 store 撞 400 行门禁（2026-09-15 实测 404 行），且按"单一文件
单一职能"本就该分开。本类**零项目依赖**：所有路径由构造方传入。

⚠️ 为什么候选集必须覆盖 WAL 附属文件
------------------------------------
库文件用 WAL（见 ``persistence_store`` 模块 docstring）。``-wal`` 里可能存着
**尚未归并回主库**的已提交事务 —— 只搬 ``.db`` 而把 ``-wal`` 留在原地，就是把
那部分数据**永久丢掉，且不报任何错**。所以 glob 覆盖 ``-wal`` / ``-shm``，
当前会话那几份则按**文件名前缀**整体跳过。

保留策略（KAI 2026-09-15 定）：只搬不删
--------------------------------------
别的交易日的文件对本会话既不能读也不该读，所以不该留在 db_dir 里；但它们
**不是垃圾** —— 那是逐交易日的 ΔIV / Skew 原始记录，回看与对拍只有这一份来源。
⇒ 移动到 ``archive_dir``，归档目录里**同名一律不覆盖**（跳过并上报，宁可留着
也不毁历史）。2026-09-15 02:2x 曾实现为 ``unlink()`` 删除（把 KAI "不留档、
不备份"的适用范围从旧单库 ``data/session.db`` 误扩到全部逐日文件）；同日改回
归档，别"简化"回去。
"""
from __future__ import annotations

from pathlib import Path


class SessionArchiver:
    """把 ``db_dir`` 里非当前会话的库文件（含 WAL 附属文件）移到 ``archive_dir``。"""

    __slots__ = ("_db_dir", "_archive_dir", "_filename")

    def __init__(self, db_dir: Path, archive_dir: Path, filename_template: str) -> None:
        self._db_dir = db_dir
        self._archive_dir = archive_dir
        self._filename = filename_template
        self._require_outside_db_dir()

    @property
    def archive_dir(self) -> Path:
        """历史会话库的归档目录。"""
        return self._archive_dir

    def _require_outside_db_dir(self) -> None:
        """
        归档目录必须落在 db_dir **之外** —— 写错了就在构造时炸，不静默降级。

        归档目录若等于或位于 db_dir 之内，归档件下次启动又会被 glob 扫到、当成
        "待归档的旧会话"，每次启动在同一批文件上打转；这种配置错**不报任何异常**，
        只让"db_dir 里只有当前会话"这条不变量悄悄失效 —— 属静默错值。
        """
        db_dir = self._db_dir.resolve()
        archive = self._archive_dir.resolve()
        if archive == db_dir or db_dir in archive.parents:
            raise ValueError(
                f"archive_dir {self._archive_dir} 位于 db_dir {self._db_dir} 之内 —— "
                f"归档件会被下次启动当成待归档项"
            )

    def archive_other_sessions(self, keep_name: str) -> tuple[list[str], list[str]]:
        """
        把非当前会话的库文件**连同 WAL 附属文件**移到归档目录。

        ``keep_name`` 是当前会话的库文件名（由调用方从路径派生，本类不自行推算 ——
        会话身份的权威来源在 ``persistence_store``）。

        返回 ``(已归档, 未归档)``：已归档 = 真正搬走的；未归档 = 归档目录已有同名
        （**不覆盖**，源文件留在 db_dir）或移动失败（例如另一进程占着句柄）。分成
        两组是因为调用方要分别记 INFO 与 WARNING —— "没归档成功"必须比"归档成功"
        更显眼。

        范围是**两道闸门**，不是一句 ``mv *.db``：① 只在 ``db_dir`` **之内** glob
        —— 上一级放着别的东西（曾有旧单库 ``data/session.db``），越界就会把不属于
        本类的文件搬走；② 匹配文件名模板派生的名字**及其 WAL 附属文件**，当前会话
        那几份按**前缀**跳过。

        失败**跳过、不抛错**：本类是旁路，不得因为归档失败中断行情主流程；没搬走
        的会在下次启动时再试。源文件宁可留在 db_dir，也**不删**。
        """
        if not self._db_dir.is_dir():
            return [], []
        candidates = [
            p for p in sorted(self._db_dir.glob(
                self._filename.format(session_key="*") + "*"))
            if not p.name.startswith(keep_name) and p.is_file()
        ]
        if not candidates:
            return [], []
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        archived, held_back = [], []
        for path in candidates:
            target = self._archive_dir / path.name
            if target.exists():
                held_back.append(path.name)  # 同名不覆盖：宁可留着也不毁一份历史
                continue
            try:
                path.rename(target)  # 同卷移动；Windows 上目标已存在会抛错，再兜一层
            except OSError:
                held_back.append(path.name)
                continue
            archived.append(path.name)
        return archived, held_back
