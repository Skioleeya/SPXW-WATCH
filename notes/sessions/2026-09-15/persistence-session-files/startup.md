# Startup — persistence-session-files

STARTUP-PROOF: 下列读数均为**改动前**实测（2026-09-15 01:00–01:03 EDT；此时
`features/persistence_store.py` 尚不存在，`config/persistence.json` 仍是 `db_path`）。

## Session

- 对话：与 `persistence-session-identity` 同一轮对话的**后续请求**，但属**独立
  工作流**（那一条修正确性，这一条改存储布局），故各占一个会话根。
- 请求（KAI 原话）：

  > 我目标就是 第一天就写第一天的数据，重启后接着写第一天的；第二天新开一份，
  > 第二天重启，继续写第二天的……

## Scope Understanding

- In scope: 持久化落点从单库 `data/session.db` 改为**一交易日一文件**；同一天内
  重启续写同一文件；跨日换新文件；把当前会话已有数据迁过去；回归、门禁与 README。
- Out of scope: 旧会话文件的**保留/清理策略**（未做，见 handoff 的 `OPEN-RISKS`）；
  `data/session.db` 的删除（**不动**，留作迁移前存档）；前端与传输层（未触碰）。

## Prior Context Read

- `notes/sessions/2026-09-15/persistence-session-identity/handoff.md` —— 取到的
  **约束**：会话身份 = **当日到期日**（`SessionClock.expiry_str()`），且它由
  **上层提供、持久化层不自行推算**。本轮的落点直接复用这一口径，**没有引入
  第二种会话身份定义**。
- `notes/context/open_tasks.md` —— 取到的**约束**：Active#1（跨会话污染）已关闭；
  本轮不得回退那条修复（`session_key` 列与恢复过滤都要留着）。
- `tools/selfcheck_core.py` / `tools/selfcheck_config.py` —— 取到的**约束**：
  `[5]` 按 `REQUIRED_KEYS` 查必需键、`[7]` 把"声明了但没人读"的键判为**失败**
  （`UNWIRED_IS_FAILURE = True`）⇒ 改配置键必须同步改 `REQUIRED_KEYS` 并在代码里
  真的读它，否则门禁直接红。

## Recent Git Context

- Key commits reviewed: `HEAD = 9ec4fb9`。上一轮改动（`persistence-session-identity`
  的五个文件 + README）**未提交** ⇒ 本轮在**脏工作区**上叠加，无法用 `git diff`
  区分两轮改动。

## Worker Readiness

- Risks noticed（均为改动前实测）：
  - `features/persistence.py` = **384 行**，距 `[1]` 的 400 行上限只剩 **16 行**
    ⇒ 任何实质改动都放不下，必须拆分（`wc -l` 实测）。
  - `features/feature_engine.py:342-344` 的 `_sync_session()` **运行期会改
    `_session_key`**，而 writer 的连接在 `start()` 开一次、`_db_path` 在
    `__init__` 定一次 ⇒ 跨日若不换文件，新会话的桶会写进**旧日期**的文件，
    下次启动读不到 ⇒ **静默丢数据**（与刚修的缺陷同类）。
  - `data/session.db` = 1,064,960 B，其中 `freelist_count = 243` 页
    （≈972 KB）是 `_drop_legacy_tables()` 丢 1830 行后留下的空闲页；
    `auto_vacuum = 0`、全项目 `VACUUM` 调用 **0 处** ⇒ 单库方案空间永不归还。
  - 服务在跑（GID 10316 占 8060，连 4002）⇒ **必须先停服再迁移**，否则迁移快照
    与在写数据竞争。
- Blockers noticed: none（IB Gateway 4002 在听）。
