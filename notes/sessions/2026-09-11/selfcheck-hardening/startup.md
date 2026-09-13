# Startup: selfcheck-hardening

STARTUP-PROOF: baseline=run.py --check 通过（61 文件 / 最长 tools/selfcheck.py 386 行，
7 项）+ 7 个回归全过（smoke / side_flip / subscription_qualify / tick_router /
session_rollover / web_contract / page_render）+ ws_probe 20/20；改动前基线为绿。

## Session

- 日期：2026-09-11
- 仓库根：`E:\US.market\SPXW SWATCH\spxw_swatch`
- 会话目标：把 KAI 明确的五条项目硬约束补齐为可执行检查；并把上一轮审计发现的
  死配置键按"L2 自己管自己的裁剪节奏"接线。

## Scope Understanding

- In scope:
  - `state.json.prune_interval_s` 真正接进 L6 维护循环（裁剪节奏归 L2 所有）
  - 为约束 2（单一职能）、约束 3（禁止硬编码）、约束 5（配置键归属）补机械检查
  - 因自检文件已达 386/400 行，按单一职能拆分 `tools/selfcheck.py`
  - 为新增检查做**非空转验证**（注入违规必须报 FAIL）
  - 同步 README（§1 工具清单、§3 配置规则、§9 检查表、§10 已知边界）
- Out of scope:
  - 实盘（`run.py --live`）的"连上之后能否收到数据"——仍需真实 TWS / IB Gateway
  - 调整任何业务参数或色标取值
  - 引入新依赖（新增检查全部用标准库 `ast` / `json`）

## Prior Context Read

- `README.md`（分层架构、六条约束、已知边界）
- `notes/context/{project_state,open_tasks,handoff}.md` 与
  `notes/sessions/2026-09-11/session-rollover-and-render-fix/*`
- `tools/selfcheck.py`（386 行，含 [1]–[7] 全部检查）
- `config/loader.py`、`state/tick_store.py`、`app/pipeline.py`、`core/clock.py`、
  `contracts/ports.py`、`contracts/frame.py`
- `config/` 下全部 10 份 JSON

## Recent Git Context

- Key commits reviewed: `755b221 Initial commit: SPXW SWATCH — 0DTE IV impulse
  heatmap & 25Δ skew radar`（仓库只有一个初始提交，工作区干净，无可回溯的分步历史）

## Worker Readiness

- Risks noticed:
  - 自检文件 386/400 行，只剩 14 行余量；加三条检查必然越界，**必须先拆分**。
  - 新检查若标定不当会误伤合法代码（`contracts/` 的 DTO 集合、`core/errors.py`
    的 15 个异常类、各 `__init__.py` 的 `__all__`、IBKR 协议码表）。
    因此每条检查都先跑标定脚本，再逐个定性。
  - 本机三个 Python 解释器**都没有 `tzdata`**，`SimClock` 会抛
    `ZoneInfoNotFoundError`，5 个回归跑不起来 —— 会造成"回归没跑却说通过"。
- Blockers noticed:
  - 无。已用隔离 venv（`.workbuddy-ai/binaries/python/envs/default`）装
    `requirements.txt` 绕开，不构成阻塞。
