# Startup: gth-spot-basis-research

STARTUP-PROOF: `git rev-parse --short HEAD` → `92a516c`；`git status --porcelain` → 空（工作区干净）。
探针落点 `tmp/` 已登记在 `.gitignore` 与 `NON_SOURCE_DIRS`。本会话**尚未修改任何代码**。

## Session

- 任务：调研 GTH（Globex/盘前）时段 SPXW 的 ATM 现货基准业界做法，
  判定"订阅 ES + RTH 记基差 + GTH 用 ES − basis 合成"是否为主流。
- 触发：上一会话 FairSpotEstimator（期权平价反推）被否并撤回，
  结论记录在 `.workbuddy-ai/memory/2026-09-14.md`。
- KAI 明确要求：用学术/权威来源查证，不要凭印象。

## Scope Understanding

- In scope：查证官方口径（Cboe / S&P DJI / SEC）、业界发布口径、学术文献；
  复算上一轮被否方案的数值；核对本项目日志中的现货读数。
- Out of scope：**不改任何代码 / 不加订阅 / 不跑实盘探针** —— 上一轮教训"应先问再改"，
  本轮只出结论与探针方案，等 KAI 拍板。

## Prior Context Read

- `.workbuddy-ai/memory/2026-09-14.md` —— 取到的**约束**：GTH 公允价方向定为"参考 ES 期货"，
  不再走期权反推；且"应先问再改"。
- `notes/context/open_tasks.md` —— 取到的**约束**：不设任何验收自动任务，由 KAI 手动验证。
- `config/ibkr.json` —— 取到的事实：`market_data_type=3`（择优）、
  `generic_tick_list="106"`（无 162）、`max_underlying_age_s=10.0`、SPX 指数 conId=416904。
- 未复述以上文件的内容，只记其施加的约束。

## Recent Git Context

- Key commits reviewed：`92a516c`（HEAD，docs 同步）、`af2e2e4`（P0–P3 落地）。
- `c0836ed`（FairSpotEstimator）已被 `git reset --hard HEAD~1` 撤销，不在历史中。

## Worker Readiness

- Risks noticed：
  1. 存在一个**残留进程**（PID 15612）占用 8060，其日志字段 `公允` 在 HEAD 代码中**不存在**
     ⇒ 该进程跑的是已撤回的构建，会让"实盘验证"看到不存在于当前代码的行为。
  2. 日志 `现货 7591.70` 与 SPX 官方周五收盘差 ~64 点，与"IBKR 给 RTH 收盘价"的前提不符。
- Blockers noticed：无（本轮为只读调研）。
