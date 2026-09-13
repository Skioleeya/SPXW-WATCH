# Startup: recheck-keyorder-memory

STARTUP-PROOF: 改动前的基线读数**确实先于任何编辑采集**（本会话第一步是只读复核）：
`run.py --check` → `rc=0`（11/11）；`node --check web/*.js` → 7/7 OK；
`tools/check_persistence.py` → 5/5（当时键序用例还是**升序**）；
`git status -sb` → 13 个已跟踪文件被改 + 4 项未跟踪。
⚠️ 本文件在编辑**之后**才落盘（会话由 KAI 贴入上一轮终态报告起手，没有"开工前"的
自然断点）—— 上面读数的**采集时刻**早于编辑，文件的**写入时刻**晚于编辑，如实记录。

## Session

- 起手：KAI 贴入上一轮 `skew-period-consistency` 的终态报告，要求按该报告继续。
- 本轮定位：**交接复核 + 收尾**，不是新功能。

## Scope Understanding

- In scope:
  1. 只读复核上一轮报告的每一条断言（含它自称"未验证"的部分）；
  2. 重建丢失的一次性开盘验收定时任务；
  3. 冷数据键序统一为降序（KAI 选定）；
  4. `MEMORY.md` 按主题蒸馏（当时余量仅 42 字符）；
  5. 补写上一轮 handoff 的 `CHANGED-PATHS` 缺口；
  6. 提交两个会话累积的未提交改动。
- Out of scope:
  - `check_web_contract.py` 顶层 `import aiohttp` 内移 —— 三项待定里 KAI 本轮
    **未选**它，保持原样；
  - 真实链路渲染验收 —— 周日无当日 SPXW 到期，服务 fail-closed，只能等
    2026-09-14 盘中（已重建定时任务）；
  - `web/` 任何改动（KAI 2026-09-13 裁定"前端是空壳，不加门禁"）。

## Prior Context Read

- `notes/sessions/2026-09-13/skew-period-consistency/handoff.md` —— 取到的约束：
  该会话的三个前端文件改动**没有真实链路截图**；`alignSkew` 的 `label` 是复制来的，
  "逐列标签相同"不可作判据（本轮不重复验证，只在文档里保留该警告）。
- `notes/context/{project_state,open_tasks,handoff}.md` —— 取到的约束：
  开盘验收被记为"已设定时任务"（本轮推翻，见 `project_state.md`）。
- `.workbuddy-ai/memory/MEMORY.md` —— 取到的约束：文件头的三分判据
  （"静默出错值的约束留本文件、立刻报错的坑放 skill"）是本轮蒸馏的取舍标准。
- skill `spxw-live-verify` —— 取到的约束：本机缺 `ib_async`/`aiohttp`；
  非交易日服务在 `pick_zero_dte` 处 fail-closed，别把红判成回归破坏。

## Recent Git Context

- Key commits reviewed: `1299fdb`（notes 提交）、`7ffe882`（帧降序 + 冷数据键序）。
  ⚠️ `7ffe882` 给冷数据加的正是**升序** `sorted()`，本轮把它翻成降序 —— 这是同一条
  不变量的**方向修正**，不是新增不变量。

## Worker Readiness

- Risks noticed: 冷数据键序方向属"静默错配行号"类风险（直接读 `session.db` 的人会
  默认某个方向），所以产出点与回归必须**同时**改，且回归要做**双向**证伪
  （不排序、退回旧升序，两种变异都必须 FAIL）。
- Blockers noticed: 本机缺 `ib_async` / `aiohttp`；周日无当日到期，服务起不来
  ⇒ 4 个需服务的检查与 `check_reconnect_flow` 本轮同样跑不了。
