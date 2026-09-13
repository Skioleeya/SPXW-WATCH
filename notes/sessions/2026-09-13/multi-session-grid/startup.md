# Startup: multi-session-grid

STARTUP-PROOF: 基线读数于本会话开头（2026-09-13 08:37 ET）、**首次编辑之前**采集，
全部为只读命令，未改动任何文件：

```
python run.py --check                     → rc=0（11/11）
python tools/check_session_grid.py        → 打印"全部通过" 但 rc=1   ← 缺陷 A
python tools/check_skew_alignment.py      → NameError: _config      ← 缺陷 B
python tools/check_period_aggregation.py --selftest
                                          → 2 项失败（"切列忽略区段过滤"未被抓住、
                                            "变异点已失效 pos = index[b]"）← 缺陷 C
13 个本地回归批量                          → 11 个 rc=0，2 个 rc=1（即上两条）
node --check web/*.js                     → 7/7 OK
git status -sb                            → HEAD=4b9a0b0，29 个已跟踪文件被改
                                            + 1 项未跟踪（tools/check_session_grid.py）
```

⚠️ 本文件在工作进行中才落盘（会话由一句 `continue` 起手，起手动作是只读侦察，
没有"开工前"的自然断点）—— 上面读数的**采集时刻**早于首次编辑，文件的**写入时刻**
晚于编辑，如实记录。

## Session

- 起手：KAI 只给了一句 `continue`。工作区是空的，`notes/context/` 指向的上一轮
  是 `recheck-keyorder-memory`（已提交 `792e4a3`、声称工作区干净）。
- 侦察发现：那之后还有一段**未提交、无会话记录**的在建改动 —— 多会话交易日网格
  （GTH + 空档 + RTH）横跨 `config` / `core` / `contracts` / `state` / `serialization`
  / `app` / `web` / `tools` 共 29 个文件 + 1 个新门禁，+1265/−304。
- 本轮定位：**把这段在建改动推到自洽可交付**（修缺陷 → 复验 → 写记录），不是新功能。

## Scope Understanding

- In scope:
  1. 修 **1 处生产缺陷**：`web/period.js::alignSkew` 忽略 `grid.index`；
  2. 修 **3 处门禁缺陷**：`check_session_grid` 退出码取反、`check_period_aggregation`
     两组对照没接进 `evaluate()`、`skew_reference` 的 `_config()` NameError；
  3. 全量复验（自检 + 13 个本地回归 + 关键 `--selftest` + 前端语法）；
  4. 用离线等价物补跑 `check_web_contract` 的三段（本机缺 `aiohttp`）；
  5. 同步 `README.md` 里已被改动推翻的口径；
  6. 写会话记录（三件套）并更新 `notes/context/`。
- Out of scope:
  - **不改会话定义本身**（GTH 20:15→09:25 / RTH 09:30→16:00 / 30 秒桶）；
  - **不动 `web/` 的视觉**（按钮样式、配色、布局）；
  - **不提交、不推送** —— 留给 KAI 定；
  - 不碰 `notes/` 里其它会话目录（历史记录只读）；
  - 真实链路渲染验收 —— 周日无当日 SPXW 到期，服务 fail-closed，只能盘中做。

## Prior Context Read

- `notes/context/{project_state,handoff,open_tasks}.md` —— 取到的约束：
  系统已是**纯实盘**（模拟盘物理删除）、非交易日服务 fail-closed；
  "记录里写了"不等于"系统里有"（上一轮定时任务静默失效的教训），
  所以本轮凡"已通过"一律以**跑一遍**为准。
- `notes/sessions/2026-09-13/recheck-keyorder-memory/handoff.md` —— 取到的约束：
  上一轮已提交 `792e4a3` 并声称"工作区干净"；本轮 `git status` 推翻其后半句。
- skill `notes-session-records` —— 取到的约束：三件套上限、每个事实只有一个归属文件。
- 项目 `MEMORY.md` —— 取到的约束：`tools/` 的自检豁免只含 [2] 分层 / [9] 单一职能 /
  [10] 硬编码，**不豁免 [1] 行数**（本轮因此被 [1] 抓过一次，见 `project_state.md`）。

## Recent Git Context

- Key commits reviewed: `4b9a0b0`（docs(notes)，HEAD）、`792e4a3`（冷数据键序降序）。
- ⚠️ 在建改动的起点是 `4b9a0b0` 之后的工作区，**没有任何提交承载它** ——
  也就是说：如果这轮不做，这段改动的唯一副本就是工作区。

## Worker Readiness

- Risks noticed: 在建改动**同时改了门禁与被测代码**，其中两处改错。这两处错法的共同
  后果都是"**报绿但是假的**"：退出码取反让"有失败"返回 0；两组对照没接进
  `evaluate()` 让七组里有两组**从未执行**却照样打印"全部通过"。与本项目最怕的
  "探针全绿但实际是坏的"完全同族。
- Blockers noticed: 本机缺 `aiohttp` / `ib_async`；周日无当日到期 ⇒
  `check_web_contract` / `check_page_render` / `check_ws_compression` / `ws_probe`
  四项只有盘中能跑。
