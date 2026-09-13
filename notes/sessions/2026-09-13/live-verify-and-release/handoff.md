# Handoff — live-verify-and-release

TASK-ID: live-verify-and-release
DATE: 2026-09-13
TIER: T2（触及仓库 + 提交 + 推送）
STATUS: complete（含一条**未定位**的环境异常）
CHANGE-ID: N/A:该仓库未使用 OpenSpec

STARTUP-PROOF: N/A:本 root 由 KAI 指令直接开工，第一个动作就是起服务，
不存在"改动前基线"可捕获。**刻意不回填 `startup.md`**（skill 明令禁止回填）。

## 结论

KAI 两条指令的结果，**一条全绿，一条只到一半，且那一半是日历造成的，不是缺陷**。

### 1. 纯实盘路径 —— 连通性已验证，出图未验证（今天无法验证）

| 链路环节 | 结果 | 证据 |
|---|---|---|
| 连 IB Gateway `4002` | ✅ | 端口探活 `4002 OPEN`；日志继续走到拉链 |
| `Pipeline()` 无参构造（硬切改动点） | ✅ | `app/pipeline.py` 无 `simulate` 形参也能起 |
| 会话/到期装配 | ✅ | `启动 delayed \| 到期 20260913 \| 会话 {… is_open: False …}` |
| 出站限速桶在实盘路径生效 | ✅ | `ibkr.rate_limit 出站限速桶显式设为 45 条 / 1s` |
| SQLite 恢复（上一提交的功能） | ✅ | `已从 SQLite 恢复 40 个历史桶` |
| qualify SPX + 拉 SPXW 链 | ✅ | 拿到到期列表 `20260914…20260918` |
| 0DTE 切片 | ❌ `ChainResolveError` | **今天是周日，无 20260913 到期合约** |
| 72 条订阅 + 热力图出图 | ⛔ 未验证 | 服务在切片处 fail-closed 退出 |
| 4 个需服务的检查 | ⛔ 未跑 | 8060 起不来（服务无法常驻） |

**为什么这不是缺陷**：`pick_zero_dte` 找不到当日到期就抛错退出，正是 fail-closed 的
正确行为 —— 硬切删掉模拟盘后**没有**"退回合成源"的降级路径，所以无 0DTE 时
系统宁可退出也不出假图。这正是 KAI 要的形态。

**它确实暴露了一个硬切的真实代价**：删掉模拟盘后，**非交易日无法起服务**，
因此 4 个需服务的检查（`check_web_contract` / `check_page_render` /
`check_ws_compression` / `ws_probe`）在周末/盘前/盘后**跑不了**。
这不是回归，是取舍的必然结果，但值得写进已知边界。

### 2. 提交并推送 —— 已完成并核实

| 项 | 值 |
|---|---|
| 提交 | `2f2794f refactor(simulator)!: hard-cut the simulator, leaving a live-only system` |
| 暂存规模 | 78 项 = 60 A（含 59 个 `notes/`）+ 13 M + 5 D |
| 推送 | `3eeb55b..2f2794f  main -> main` |
| **远端核实** | `git ls-remote origin refs/heads/main` = `2f2794fe1bccd07d53d665e1b5bbf6224bbc7028` = 本地 HEAD ✅ |
| 工作树 | 干净（`git status --short` = 0） |
| 敏感串扫描 | 无凭据；命中全是探针 `clientId=97/98/99` 这类非敏感 ID |

`notes/` 的 59 个文件是**重新入库** —— 它在 `2447d53` 里被删（提交信息原文
"Remove notes/ directory (superseded by .workbuddy-ai/memory/)"），
KAI 2026-09-13 决策复活，故本次提交是**有意反转该提交的决定**，已在提交信息中写明。

CHANGED-PATHS: 78 项（60 增 / 13 改 / 5 删），已随 `2f2794f` 入库
- 产品代码 13 改 + 5 删 + `tools/fixtures.py` 1 增 —— 明细见 `simulator-hard-cut`
- `notes/` 59 文件重新入库（含本 root 与 `notes-dedup-tiering`）
- 本 root 新增：`handoff.md`、`project_state.md`

VALIDATION-SUMMARY: `run.py --check` **11/11 全部通过**（提交前）；
实盘链路跑到 0DTE 切片，`ChainResolveError` 为周日无当日期权的正确 fail-closed；
`git ls-remote` 确认远端已收到提交。

COMMAND-EVIDENCE:
- `for p in 4001 4002` → `4001 closed` / `4002 OPEN`
- `run.py`（隔离 venv + `NO_PROXY`）→ 日志 4 行正常 + `ChainResolveError`
  ```
  02:56:13 INFO pipeline   启动 delayed | 到期 20260913 | 会话 {… is_open: False …}
  02:56:13 INFO pipeline   界面地址 http://127.0.0.1:8060/ | 行情通道 ws://…/ws
  02:56:14 INFO pipeline   已从 SQLite 恢复 40 个历史桶
  02:56:15 INFO ibkr.rate_limit  出站限速桶显式设为 45 条 / 1s
  core.errors.ChainResolveError: tradingClass='SPXW' 下没有当日到期（20260913）的合约。
    最近的到期日: ['20260914', '20260915', '20260916', '20260917', '20260918']
  ```
- `python run.py --check` → `结果: 全部通过`
- `git commit` → `2f2794f`；`git push origin main` → `3eeb55b..2f2794f  main -> main`
- `git ls-remote origin refs/heads/main` → `2f2794fe…`（= HEAD）
- `git status --short` → 0 项

NOTES-PATHS: 2 个
- `notes/sessions/2026-09-13/live-verify-and-release/handoff.md`
- `notes/sessions/2026-09-13/live-verify-and-release/project_state.md`

OPEN-RISKS: 3 条
1. **[中] 实盘出图仍未验证过** —— 硬切后系统只剩实盘路径，而**至今没在任何交易日
   跑过一次**（本机两个会话都撞上非交易时段）。下一个交易日必须补跑：
   `mode` 正确、72 条订阅、热力图出图、`health.rate_limit` 四要素。
2. **[中] 4 个需服务的检查仍无证据** —— 且现在**只有交易日才能跑**（见 `project_state.md` §2）。
3. **[低] `git fetch` 在本环境不落地 remote-tracking ref（未定位）** ——
   详见 `project_state.md` §3。不影响提交与推送（远端已核实），但 `git status -sb`
   会显示 `[gone]`，属**未定位的环境异常**，不声称已知原因。

已裁定不再重提（KAI 2026-09-13）：方案 B；回溯历史 8 个会话。
