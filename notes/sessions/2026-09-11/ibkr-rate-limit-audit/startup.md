# Startup: ibkr-rate-limit-audit

STARTUP-PROOF: baseline=`run.py --check` **10/10 通过**（69 文件 / 最长
`acquisition/feed_service.py` 395 行 / 死键 0）；本会话为**只读审计**，
未修改任何生产代码。IB Gateway 10.50 模拟账户在 `127.0.0.1:4002` 实测可连
（`serverVersion=178`）。

## Session

- 任务 id：`ibkr-rate-limit-audit`
- 日期：2026-09-11
- 类型：审计（read-only），无代码改动
- 触发：KAI 提问 —— IB Gateway 10.50 已启动并登录模拟账户，要求核实
  IBKR 官方限速与配额，并确认项目**是否成功配置了专门的限速桶**，
  让订阅与退订流畅执行，且**禁止硬编码**。

## Scope Understanding

- In scope：
  1. 查证 IBKR 官方（TWS API / IB Gateway）的限速规则与配额上限。
  2. 定位项目中限速相关实现，判断"限速桶"是否存在、在哪一层、阈值多少。
  3. 实测验证订阅/退订路径在真实 IB Gateway 上是否流畅（不触发限流错误）。
  4. 核实限速参数是否满足项目第 3 条硬约束（禁止硬编码，必须配置化）。
- Out of scope：
  1. 不修改任何生产代码（本次为审计，处置方案留给 KAI 决策）。
  2. 不做历史数据 pacing（本项目只用实时行情，不涉及 `reqHistoricalData`）。
  3. 不评估行情权限/付费档位（除实测中顺带观察到的 Error 10090）。

## Prior Context Read

- `.workbuddy-ai/memory/MEMORY.md`（五条硬约束、机械校验映射、已知缺口、环境坑）
- `.workbuddy-ai/memory/2026-09-11.md`（四轮工作记录，含 selfcheck 加固与死键处置）
- `notes/context/{project_state,open_tasks,handoff}.md`
- `notes/sessions/2026-09-11/dead-key-resolution/handoff.md`（格式与既有结论）
- `config/{ibkr,subscription,app}.json`
- `acquisition/{ibkr_gateway,subscription_manager,feed_service,chain_resolver,
  contract_factory,tick_router}.py`
- `tools/{selfcheck_hardcode,selfcheck_core}.py`
- 第三方库源码：`ib_async` 2.1.0 的 `client.py` / `ib.py`

## Recent Git Context

- Key commits reviewed: 仅 1 个 `Initial commit`（工作区干净），无后续提交历史
  可供比对 —— 与 `dead-key-resolution/startup.md` 记录一致。

## Worker Readiness

- Risks noticed：
  1. 项目里名为 `throttled` 的状态**不是**限速桶状态，而是 Error 300 退避 ——
     命名容易误导审计方向，必须先分清再下结论。
  2. `notes/` 与 `.workbuddy-ai/memory/` 两套证据体系并行，存在"前置证据丢失"
     前例（见 2026-09-11 日志第一轮）。
  3. 本机回环请求会被代理拦成 502，实测需 `NO_PROXY=127.0.0.1,localhost`；
     `ib_async` 走裸 TCP，理论上不受代理影响，但仍按既有约定设置。
- Blockers noticed：无。IB Gateway 已在 `4002` 监听，可实测。
