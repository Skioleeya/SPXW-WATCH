# Project State — persistence-session-files

本文件只放**"为什么"**：设计取舍、被否方案、踩到的陷阱。事实与命令证据在
`handoff.md`。

## 三个决策

### 决策 1：文件边界之外，行内 `session_key` 列**保留**

**被否**：既然文件名已经是日期，把列去掉、主键退回 `bucket_index`。

**保留的理由**：让文件**自述**归属。文件被改名贴错日期时（人工失误，最容易发生
的那一类），查询里的 `WHERE session_key = ?` 一条都取不到 ⇒ 图上**留白**，是**响**
的；去掉列之后同样的错误会把别天的桶当这天的画出来 ⇒ **静默错值**。
方向必须选响的那一侧（与 `NON_SOURCE_DIRS` 用排除表而非白名单同一条推理）。

### 决策 2：`_batch_write` **逐条**按会话切文件，而不是"整批一个连接"

跨日那一刻的队列里，**旧会话的尾巴与新会话的开头同时存在**。整批只按
`batch[0]` 开一次连接，会把旧会话的桶写进新会话的文件 —— 与分文件要堵的缺陷
同类，只是换了个位置。

`open_session` 对"已是当前会话"是空操作，所以正常批次只多一次字符串比较，
**没有额外 IO**。

### 决策 3：`SessionFileStore.close()` 必须**先提交再关闭**

本轮唯一一个"写完才发现"的陷阱：`sqlite3.Connection.close()` 对**未提交事务是
回滚**。批尾本来还会 `commit()` 一次，但换文件之后那次提交已经写在**新**文件的
连接上了 ⇒ 旧文件刚写的那批被**静默丢掉**。

实测形状：`check_persistence_sessions` 报
`_case_rollover_splits_batch: 旧会话应 1 个桶，实际 0`。

⚠️ 同族陷阱（顺手修掉）：`with sqlite3.connect(...) as conn` **不关闭连接** ——
连接对象的上下文管理器只管事务。原 `_fetch_session_rows` 就是这么写的，但那时
几乎总走已打开的连接所以看不出来；分文件后读取**非当前会话**每次都走临时连接，
Windows 上句柄不释放（临时目录删不掉，`PermissionError 13`）。已改显式 `close()`。

## 被否方案

| 方案 | 否决理由 |
|---|---|
| 保持单库 + 启动时 `DELETE` 非本会话 + `VACUUM` | 解决空间不归还，但**不满足 KAI 的目标**（磁盘上没有按天的边界）。留作备选。 |
| `data/<YYYY-MM>.db` 按月分片 | 折中，但目标粒度是**交易日**；按月仍然要在文件内靠列区分。 |
| 跨日不换文件、只靠列区分 | 静默丢数据（新会话的桶进旧文件，下次恢复读不到），否决。 |
| 去掉 `session_key` 列 | 见决策 1，静默错值方向，否决。 |
| `db_filename` 模板含路径分隔符时"自动规范化" | 会把文件静默写到别处 ⇒ 恢复永远读不到。改为**越界即抛错**。 |
| 逐日文件改用 `unlink()` 删除（02:2x 一度落地） | **销毁逐交易日原始记录** —— 那是 KAI 要留的历史数据。改为 `rename()` 归档。见「误读史」。 |
| 归档目录同名时**覆盖** | 会静默丢掉历史件。改为**跳过 + 计入未归档 + 报 WARNING**。 |
| `archive_dir` 允许落在 `db_dir` 之内 | 归档件下次启动又被当成待归档项（无限自搬）。改为**构造期抛错**。 |

## 为什么要多一个 `persistence_store.py`

`features/persistence.py` 改动前 **384 行 / 上限 400**（余 16 行）；本轮新增路径
派生、热切连接、建表迁移约 +40~45 行 ⇒ **必然超限**。按"单一文件单一职能"拆成：

- `features/persistence_store.py`：**文件与表** —— 路径派生、连接的开/切/关、
  建表与旧结构丢弃、写入、只读取行。
- `features/persistence.py`：**队列与调度** —— `asyncio.Queue`、批量消费、
  序列化（dict ↔ JSON、`SkewPoint` ↔ dict）、恢复结果的字典转换。

拆完：`persistence.py` 310 行 / `persistence_store.py` 332 行，两者都在门禁内。

`require_session_key()` 只定义**一份**（在 store 里），`persistence.py` import 它 ——
写入侧与读取侧都要拦空身份，各写一份必然漂移（项目在 `TRUSTWORTHY_QUALITIES`
上已经踩过一次"抄三遍、其中一份忘了修"）。

## 迁移的做法与边界

`data/session.db` 里 20260915 会话的 88+88 行，经 `tmp/migrate_session_files.py`
搬到 `data/sessions/20260915.db`。**走 `SessionFileStore` 本身写**，而不是手写
`INSERT` —— 否则迁移脚本会自造一套 schema，成为第二份真相。

**原文件不删、不动**，留作迁移前存档。删不删由 KAI 定（动项目数据需明令）。
→ **2026-09-15 02:2x 已定并执行：删除，无备份**（见下节）。

## 保留策略（2026-09-15，03:1x 定稿 = 归档不删）

### ⚠️ 误读史（必须先看，否则会"简化"回去）

02:2x 我写下的是「旧会话文件：**不留档、不备份，只留当前会话**」并实现成
`unlink()`。**这是误读。** KAI 的原话是：

> **"1.'不留档、不备份' 只针对旧单库 `data/session.db`，你真笨！！；
> 2.改'删除'为'归档' —— `unlink()` → `rename()` 到 `data/archive/<到期日>.db`。"**

即：**"不留档、不备份"的对象只有旧单库 `data/session.db` 一个文件**；
逐日会话文件是**逐交易日 ΔIV/Skew 的原始记录**，KAI 先已纠正定性
（*"这就是历史数据，有用。傻逼"*）—— 我把它当成了"占盘的脏东西"。

⇒ **`data/sessions/<到期日>.db` 永不被删除。** 现行策略：`db_dir` 只留当前会话，
其余**移动**到 `data/archive/`。任何"改成删除更省事"的想法都是这条误读的重演。

### 现行三层（与"文件/表 vs 队列/调度"的边界一致）

| 层 | 责任 | 关键点 |
|---|---|---|
| `SessionFileStore.archive_other_sessions(keep_key)` | **机制**：把 `db_dir` 内所有非当前会话的库文件**移动**到 `archive_dir`，返回 `(已归档, 未归档)` | 三道闸门 + 一道构造期校验（见下） |
| `AsyncPersistenceWriter.start()` | **时机**：打开本会话文件后调用一次，把元组交给调用方 | 先 `open_session` 再归档 ⇒ 当前会话的文件不会被自己搬走 |
| `app/pipeline.py` | **留痕**：已归档 ⇒ INFO 一行；未归档 ⇒ **WARNING** 一行 | `features/` 整层不写日志 ⇒ 这里是唯一能看到"搬了/没搬哪几个"的地方 |

### 三道闸门 + 一道构造期校验

```text
闸门①  只在 self._db_dir.glob(self._filename.format(session_key="*")) 之内
       —— glob 不抬到 db_dir.parent（否则会波及旧单库 / 别的目录）
闸门②  只匹配 db_filename 模板**派生的名字**，且 != keep_name
       —— 模板改了 = 换命名空间，不会误搬同名无关文件
闸门③  目标 data/archive/<name> 已存在 ⇒ 计入 held_back、源文件**留原地**
       —— 宁可留原地 + 报响，也不覆盖历史件
校验   archive_dir 落在 db_dir 之内（等于或为其父）⇒ **构造时抛 ValueError**
       —— 否则归档件下次启动又被当成待归档项，无限自搬
```

**为什么分 `(已归档, 未归档)` 两个返回值**：调用方要分别记 INFO 与 WARNING ——
"没归档成功"必须比"归档成功"更显眼。合成一个 `list` 就丢了这个区分。

### 为什么归档只在启动时做

`features/` 整层没有 logger（纯计算层）。跨日那一刻换文件时归档的话，搬走**一整天
数据**却没有任何日志 —— 静默动数据比留一个文件更糟。所以跨日残留留到下次启动才搬，
**未归档数 = 自上次启动以来的交易日数**（实测 `tmp/probe_rollover_residue.py`：
进程不重启跨 5 个交易日 ⇒ 当前会话 1 + 未归档 4 = **5 个**文件 ≈ 9.4 MB；
每天重启一次则 1 个）。**残留文件永不会被读到**，只是占盘。

**KAI 2026-09-15 问过"要不要立刻清"，结论：不清。** 三条理由：① 只占盘不污染
（读侧只开当前会话文件）；② 2.35 MB/天不值钱（`data/` 在 `.gitignore`）；
③ 要"立刻清"得把计数/日志从 `features/` 上提到 `app/` ⇒ 新代码 + 新回归 + 新失败面。

**自我更正**：我一度说"跨日那一刻删/搬更危险（有竞态）" —— **读代码后证伪**：
`open_session` 键变时走 `close()`，内部先 `commit()` 再 `conn.close()`
（`persistence_store.py:217-221`）⇒ 旧文件已提交关闭，是搬它**最安全**的时刻。
文档本来就写的是"无日志可记"，**不是**"更危险"，无需改。

### 旧单库 `data/session.db` 的处置（与上面互不牵连）

**02:2x 已按 KAI 明令删除，无备份。** 删除前实况：1,064,960 B，
`heatmap_buckets` / `skew_points` 各 88 行，mtime 停在 01:22:07（已停写）。
`data/` 在 `.gitignore` ⇒ **不可恢复**。删除后 `data/` 只剩 `sessions/`。
**"不留档、不备份"只对这一个文件成立。**

### 实盘验证（不是只有单测）

```text
# 删除时代（02:3x）已作废，仅存档对照：
  02:31:37 INFO 已清理 1 个非本会话的持久化文件（只留当前会话，不留档）: 20990101.db
# 归档时代（03:1x，现行）：
  造 data/sessions/20990101.db（走 SessionFileStore 写，20,480 B）→ 停服 → 新代码重启
  03:18:42 INFO pipeline 已归档 1 个历史会话文件到 data\archive（db_dir 只留当前会话）: 20990101.db
  ⇒ data/sessions/ 只剩 20260915.db（413,696 B）
  ⇒ data/archive/20990101.db（20,480 B）**在**  ← 历史原始记录没丢
  服务：03:20:12 流水线已就绪；恢复 275 桶 / 275 Skew 点
```

### 非空转

```text
tmp/probe_mutation_archive.py  三个变异：
  ① start() 不归档            → 抓 1 条
  ② glob 抬到 db_dir.parent   → 抓 3 条
  ③ 同名无条件覆盖            → 抓 1 条
  还原后 7/7 全绿
tmp/probe_mutation_prune.py  **已失效**（prune_other_sessions 已不存在，一跑即 AttributeError）
```


## 收尾轮：残留清扫的边界（为什么只改这几处）

判据只有一条：**本次改动使哪条既有陈述变成假的，就修哪条**；改动之前就已经是假的，
只登记不擅改（改它要先定口径，且不属本改动的责任范围）。

| 位置 | 处置 | 理由 |
|---|---|---|
| `features/heatmap_engine.py` docstring | **改** | 它点名 `session.db`，改后该文件不再是落点 ⇒ 陈述变假 |
| `.gitignore` 的 `data/` 创建者 | **改** | 建目录的代码已从 `persistence.py` 移到 `persistence_store.py` |
| `README.md §5` | **改** | 该节是落点的唯一设计归属；只写 `persistence.py` 会让读者以为文件与表也归它 |
| `notes/memory/RULES.md §6.1` | **改（按实测重测）** | §6.1 自称"基线数字唯一归属"，却停在 `check_persistence.py 5/5`（现 7/7）、`21 个 check`（现 22）⇒ 与 README 的"7 组 + 4 组"构成**两份真相** |
| `notes/memory/ARCHITECTURE.md §4` | **不改，只登记** | 改动前就已过期（模块名对不上、JSON/JS 计数不符），且"列代表性模块还是全列"是口径问题 |
| `tmp/*.py` 一次性探针 | **不改，只登记** | `tmp/` 是 gitignore 的一次性脚本区；`migrate_session_files.py` 还是本轮的迁移证据 |

**归档与历史会话记录一律不动**：`notes/sessions/**` 是"当时为真"的证据，retro-fit
会把证据改成"现在为真"，那它就不再是证据。

清扫后存活代码/配置/README 对 `session.db` / `db_path` **0 命中**；剩下的引用只落在
`notes/sessions/**`（历史证据）、`notes/context/**`（描述本次改名；旧单库已于 02:2x 删除）、
`tmp/*.py`（一次性探针）三类**非存活**位置。
