# Startup: persistence-session-identity

STARTUP-PROOF: 见下「Baseline」。**本文件在编辑发生之后才落盘** —— 会话开头是
KAI 指令"启动系统"，排查出缺陷后立即动手。下列读数**全部取自改动前的
00:27–00:33 EDT**，逐条给时间戳，**没有事后补测**；改动前的 `run.py --check`
基线 **N/A:未在改动前捕获**（当时只跑了活链路探针）。

## Session

- 任务：KAI 指令"启动系统"。启动成功后核验时挖出**跨会话持久化污染**，KAI 选定结构性修复。
- 日期：2026-09-15（EDT），GTH 段（20:15→09:25），当日 0DTE 到期 `20260915`。
- TIER: **T2** —— 跨 L3/L6、改表结构、新增回归。

## Baseline（改动前实测）

| 时刻 | 读数 |
|---|---|
| 00:26 | 端口：4002 OPEN；4001/7496/7497 closed；8060 closed；无 python 残留进程 |
| 00:27:58 | `venv/Scripts/python.exe -u run.py` → `流水线已就绪`（11–15s） |
| 00:27:43 | 启动日志：`到期 20260915 \| bucket_index 505 / 2370`；`已从 SQLite 恢复 915 个历史桶 / 915 个 Skew 点` |
| 00:29 | `data/session.db`：`heatmap_buckets` 915 行 / `skew_points` 915 行。**两表列只有 `bucket_index`（+`ivs_json`/`is_break`）与 `(skew_json)` —— 没有任何会话列** |
| 00:29 | 按行内 `ts` 的日期分布：`{2026-09-13: 3, 2026-09-14: 906, 2026-09-15: 6}`；`max bucket_index = 2183` → `ts = 2026-09-14T14:26:48` |
| 00:30 | 活帧：`skew.series.count = 915`、bucket `0..2183`、`labels[-1] = "14:26:30"`、`skew.latest.ts = 2026-09-14T14:26:48`（**昨天**）；heatmap 24 档 × 514 桶、labels `20:15:00 → 00:31:30`、`bucket_index 513` |
| 00:31 | `tools/ws_probe.py --frames 8` → **26/27**，唯一 FAIL = `25Δ Put 行权价低于现价 7626.51 < 7605.41` |
| 00:30 | 截图 `tmp/startup_panel_20260915_0030.png`（108,869 B）：左侧 20:15–20:35 纯绿块（假 0 带）、右侧 23:5x–00:31 彩色块（= **昨天**的 RTH 数据画在今天 GTH 的时刻上） |
| 00:26 | `git rev-parse HEAD` = `9ec4fb9` |

## Scope Understanding

- In scope: `features/persistence.py`（表结构 + 按会话过滤 + 旧表迁移）、
  `features/feature_engine.py`（写入侧带会话身份）、`app/pipeline.py`（恢复侧带会话身份 + 日志）、
  `tools/check_persistence.py`（回归）、`README.md` §5（设计文档）。
- Out of scope: `recover()` 只取"最后一段连续桶"（`open_tasks.md` 旧残留的另一半，
  **KAI 本轮未选**）；`web/` 前端（空壳，不改）；不手工删 `data/`（改由代码迁移）；
  `tools/check_page_render.py` 等 6 个既有失败回归（与本轮无关）。

## Prior Context Read

- `notes/context/open_tasks.md` Active#1 —— 同一根因已登记，但只覆盖"bucket 0 ⇒ 20:15 起
  假 0 带"一种表现。**取到的约束**：修根因即可，不必为每种表现各打一个补丁。
- 项目 `MEMORY.md` 速查卡 K —— **取到的约束**：`recover()` 读全部行是已知形状，
  且"只取最后一段连续桶"这一方案 **KAI 曾否掉** ⇒ 本轮方案**不得依赖"桶序号单调"**
  （否则会话早期仍会把昨天的低位桶当成今天的历史）。
- `README.md` §10 —— **取到的约束**：跨会话复用桶序号"必须堵"，而
  `tools/check_session_rollover.py` 只覆盖**内存路径**（`_sync_session` + 按到期日过滤 tick）
  ⇒ 持久化恢复路径需要自己的守卫。

## Recent Git Context

- Key commits reviewed: `9ec4fb9`（HEAD）。
- 工作区已含**另一会话未提交**的改动：`notes/context/handoff.md`、`notes/context/open_tasks.md`、
  `web/config.js`，以及未跟踪的 `notes/sessions/2026-09-14/live-render-verify/`。
  本轮**不替它背书、不纳入**（见 `handoff.md::OPEN-RISKS`）。

## Worker Readiness

- Risks noticed: 重启会把 1830 行旧持久化数据整张丢弃。代价核算 —— 今天（`20260915`）
  的真实数据只有 00:27 之后的 ~25 个桶，而 20:15–00:27 段**本就没有数据**
  （当时无进程在跑，库里没有该段的任何行）⇒ 丢失可忽略。
- Blockers noticed: 无。IB Gateway 已在 `127.0.0.1:4002` 监听（KAI 于 00:27 前启动）。
