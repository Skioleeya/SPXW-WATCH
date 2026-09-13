# Startup: record-reconciliation

STARTUP-PROOF: 加载后**当场实测**当前现实，不采信记录里的数字 ——
`python run.py --check` → **11/11 全部通过**（实测输出：
`[1] 70 个文件全部合规，最长 acquisition/feed_service.py = 397 行`）；
`wc -l acquisition/feed_service.py` → 397；`git ls-files '*.py' | wc -l` → 61
（+ 9 个未跟踪的 `.py` = 70，与自检口径吻合）。核对结果与活文档记载
**存在 4 处不一致**，逐条列在 `handoff.md` 的 `CHANGED-PATHS` / 正文里。

## Session

- 任务 id：`record-reconciliation`
- 日期：2026-09-11
- 触发：KAI 指令「加载项目记忆」。加载动作本身附带一次"记录 vs 现实"核对 ——
  这是 KAI 反复关注的失效模式（"记录与现实不一致"），故按惯例当场核对并修正，
  而不是只把记录读进上下文。

## Scope Understanding

- In scope：
  - 读取 `notes/context/{project_state,open_tasks,handoff}.md`、
    `.workbuddy-ai/memory/{MEMORY.md,2026-09-11.md}`、
    `notes/sessions/2026-09-11/*/`（5 个会话根）。
  - 用**可复现命令**实测当前现实（自检、行数、文件数、git 状态），
    与记录逐项对照。
  - 改正活文档里的事实性错误（数字、过时结论）。
- Out of scope：
  - **零生产代码改动** —— 未碰任何 `.py` / `.js` / `.css` / `.json`。
  - `notes/sessions/**` 下的**历史会话快照一律不改**：它们是当时的事实快照，
    回改等于伪造历史。只在活文档（`README.md` / `notes/context/*` /
    `.workbuddy-ai/memory/MEMORY.md`）上改正。
  - 不重启服务、不跑实盘（本次无链路改动）。

## Prior Context Read

- `notes/context/project_state.md`（活文档，93 行）、`notes/context/open_tasks.md`
  （活文档，120 行）、`notes/context/handoff.md`（活文档，11 行）。
- `.workbuddy-ai/memory/MEMORY.md`（项目长期约定）、
  `.workbuddy-ai/memory/2026-09-11.md`（当日日志，463 行 / 10 轮）。
- `notes/sessions/2026-09-11/` 下 5 个会话根：
  `session-rollover-and-render-fix` / `selfcheck-hardening` /
  `dead-key-resolution` / `ibkr-rate-limit-audit` / `iv-heatmap-turbo-palette`。
- `README.md`（469 行）§9 自检表、§10 已知边界。
- `tools/selfcheck_structure.py`（行数口径：`splitlines()`，`>= MAX_LINES` 即失败）。
- 环境约定（`.workbuddy-ai/memory/MEMORY.md`「环境」节）：隔离 venv、`NO_PROXY`、
  8060 端口复用、探针写工程外。

## Recent Git Context

- Key commits reviewed：`755b221 Initial commit: SPXW SWATCH — 0DTE IV impulse
  heatmap & 25Δ skew radar` —— **仓库只有这一个提交**。
- `git status --short`：31 个已跟踪文件处于 `M`（含 `README.md`、`config/*.json`、
  `acquisition/*.py`、`web/config.js` 等），另有 9 个未跟踪的 `.py`
  （`rate_limit_watch.py`、`spot_tap.py`、`tools/selfcheck_{config,core,duty,hardcode,slots,structure}.py`、
  `tools/check_clock_protocol.py`）与 4 个未跟踪的 `notes/sessions/...` 会话根。
  → **全部多轮工作仍在工作区，尚未提交。** 这不是缺陷，但意味着
  "记录里的 397 行"只存在于工作区，`git show HEAD:` 里是旧版本。
- `.workbuddy-ai/` 整体未跟踪（符合预期：它是工作记忆目录，不是产物）。

## Worker Readiness

- Risks noticed：
  1. **数字类记录容易腐烂。** 本次 4 处不一致中有 3 处是"数字没跟着改动走"
     （文件数 / 最长行数 / 检查项数），1 处是"结论被后续实测推翻"
     （README 仍写"实盘未验证"）。前者可以靠 `--check` 输出当唯一真相源收敛，
     后者只能靠人回改。
  2. **同一事实散落在 4 个地方**（`README.md` / `notes/context/project_state.md` /
     `notes/context/open_tasks.md` / `.workbuddy-ai/memory/MEMORY.md`），
     改一处就会制造新的不一致。这正是 `notes/` 与 `memory/` 是否收敛的
     未决问题（见 `open_tasks.md` 的 Stale 节）。
- Blockers noticed：无。
