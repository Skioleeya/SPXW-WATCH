"""
L8 — 启动期的持久化接回。
==========================
唯一职责：把**上一个进程**留下的历史会话数据接回本次运行 —— 打开本会话的库文件、
归档别的会话、恢复热力图原始桶与 Skew 折线。

为什么从 ``pipeline.py`` 拆出来
-------------------------------
组装根要同时容纳"装配 + 生命周期 + 三条循环 + 只读信息"，加完曲面接线后逼近
400 行门禁（判据 ``>=`` 即超）。这里是一块**边界清晰**的职能：它只在 ``start()``
里跑一次，输入输出都是明确定义的对象，且**不参与**运行期循环。
拆它不改变任何行为，只把"启动期 IO"与"运行期编排"分开。

为什么这一段必须写日志（而 ``features/`` 整层不写）
---------------------------------------------------
``features/`` 是纯计算层，不持 logger；但**动数据必须留痕**：
归档了哪几个文件、丢弃了多少行旧格式数据、恢复了多少个桶 —— 这些是事后
唯一能回答"我的数据去哪了"的线索。所以日志落在本层（组装层是唯一允许
同时看见 L5 与 L6/L7 的角色）。

⚠️ 恢复必须限定在**本会话**（``session_key``）
---------------------------------------------
``bucket_index`` 是**日内坐标、每个交易日复用**。不带会话身份就会把别的交易日的
桶当成今天的读进来 —— 表现为热力图左端出现一段"假 0 带"、Skew 曲线画到未来。
``features/persistence.py`` 按 ``session_key`` 过滤，本模块只负责把正确的 key 传下去。

依赖：L0（config / contracts）、L5（features.persistence 的鸭子类型接口）、
L7 及以下均不直接使用。本模块**不 import** L5 的具体类 —— 只按接口调用。
"""

from __future__ import annotations

from typing import Any


async def boot_persistence(writer: Any, engine: Any, clock: Any, log: Any) -> None:
    """
    打开本会话的库、归档别的会话、恢复历史桶与 Skew 点。

    参数都按**鸭子类型**使用（``writer`` / ``engine`` / ``clock`` / ``log``），
    本模块不 import 它们的类 —— 这样 L8 的拆分不会引入新的层间耦合。

    ``session_key`` = 当日到期日（``clock.expiry_str()``）。网格跨午夜而到期日
    不跨，所以 0DTE 的到期日就是会话身份（见 ``core/session_grid.py``）。
    """
    session_key = clock.expiry_str()

    archived, held_back = await writer.start(session_key)
    if archived:
        # 保留策略 = db_dir 只留当前会话，历史**归档不删**。归档必须留痕：
        # features/ 整层不写日志，这行是唯一能看到"搬了哪几个文件"的地方。
        log.info(
            "已归档 %d 个历史会话文件到 %s（db_dir 只留当前会话）: %s",
            len(archived), writer.archive_dir, "、".join(archived),
        )
    if held_back:
        # 冲突比成功更显眼：归档目录同名**不覆盖** ⇒ 源文件仍留在 db_dir，
        # "db_dir 只留当前会话"这条不变量此刻**不成立**，必须看得见。
        log.warning(
            "有 %d 个历史会话文件未归档（归档目录已有同名，不覆盖）: %s",
            len(held_back), "、".join(held_back),
        )
    if writer.legacy_dropped_count:
        log.warning(
            "丢弃 %d 行无会话身份的旧持久化数据（旧表缺 session_key 列，"
            "无法判断归属哪个交易日）", writer.legacy_dropped_count,
        )
    log.info("持久化落点 %s（会话 %s，同日内重启续写同一文件）",
             writer.session_path, session_key)

    recovered = writer.recover(session_key)
    if recovered:
        engine.restore_heatmap(recovered)
        log.info("已从 SQLite 恢复 %d 个历史桶（会话 %s）",
                 len(recovered), session_key)

    recovered_skew = writer.recover_skew(session_key)
    if recovered_skew:
        engine.restore_skew(recovered_skew)
        log.info("已从 SQLite 恢复 %d 个历史 Skew 点（会话 %s）",
                 len(recovered_skew), session_key)
