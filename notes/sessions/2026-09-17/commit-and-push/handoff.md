TASK-ID: commit-and-push
DATE: 2026-09-17
TIER: T1
STATUS: complete
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
STARTUP-PROOF: N/A:本会话为仓库操作（提交/推送/引用存储修复），不改产品代码；
  基线即 `git status --porcelain` 的 **28 项脏态**，已记在下文 CHANGED-PATHS。

# Handoff — 五轮改动提交推送 + 修掉陈旧的远端跟踪引用

## 一句话

把叠在同一工作区的**五轮改动**（`heatmap-auto-roll` / `interaction-feedback-5fix` /
`skew-drag-interaction` / `heatmap-pan-drag` / `skew-dual-axis-zoom`）**提交并推送远端**，
工作区转干净；**顺带查出并修掉一个本地引用存储缺陷** —— 远端跟踪引用 `origin/main`
被钉在 `6828e3a`（2026-09-14），导致 `git status` 长期谎报 `[ahead 23]`。

## 为什么合并为一个提交（而不是按轮拆五个）

`web/index.html` 与 `web/config.js` 被五轮**共同**改动（新脚本标签、新配置块），
`web/heatmap*.js` 被三轮动过、`web/skew*.js` 被两轮动过 ⇒ **文件级无法拆**。
更硬的理由：中间态的 `web/heatmap.js` 会 import 尚未入库的
`heatmap_roll.js` / `heatmap_hover.js`，拆出来的中间提交**根本跑不起来** ——
那是伪造历史，不是保留历史。
沿用本仓库已有先例：`0d30943`（"文件级无法拆，合并为一提交"）、
`53da940`（"三轮改动在同一批文件里交错 ⇒ 合并为一个提交"）。

## CHANGED-PATHS

提交前脏态 = **28 项**（17 M + 11 ??）；提交后 = **0 项**。

- `ab853d3` `feat(web)` —— **19 文件 / +2151 −346**：
  14 个已跟踪（`README.md`、`tools/check_web_contract.py`、`web/` 12 个）
  + 5 个新增 `web/*.js`（`heatmap_hover` / `heatmap_roll` / `skew_regions` /
  `skew_zoom` / `view_chips`）
- `21293a1` `docs(notes)` —— **15 文件**：
  3 个已跟踪（`notes/context/{handoff,open_tasks,project_state}.md`）
  + 12 个新增（5 个会话目录 + `notes/analysis/2026-09-17-main-chart-interaction-audit.md`）
- 其后还有若干 `docs(notes)` 记录提交（含"引用陈旧**已确认复现**"的更正，以及本文件本身）
  —— ⚠️ **提交条数与哈希都以 `git log` 为准，不在记录里写死**（写死即过期）
- `tmp/` 与 `.workbuddy-ai/` 按 `.gitignore` 不入库（含本会话的提交信息草稿与
  `tmp/_packed-refs.bak`）

## COMMAND-EVIDENCE

```
# 提交前门禁（最终字节）
run.py --check                        ⇒ 16/16（94 py + 20 前端脚本全合规，最长 399 行）
node --check web/*.js                 ⇒ 20/20 全过
check_web_contract.py                 ⇒ 全部通过（DOM id 27 引用/34 定义、CFG 55 条、载荷 59 条）
check_web_contract.py --selftest      ⇒ RC=0（el / bindButton / ViewChips 三条取法全命中）

# 提交与推送
git commit -F tmp/_commit_msg_code.txt   ⇒ [main ab853d3] 19 files changed, +2151 -346
git commit -F tmp/_commit_msg_notes.txt  ⇒ [main 21293a1] 15 files changed
git push origin main                     ⇒ 390ac6e..21293a1  main -> main（此后又推两次）

# 收尾核对（**不写死 HEAD** —— 本会话后续还会追加记录提交，写死就会立刻过期）
不变式：本地 HEAD == 远端 refs/heads/main == 本地 origin/main（三者相等，每次 push 后均核过）
git status --short --branch = ## main...origin/main（无 ahead/behind）
git status --porcelain | wc -l = 0
git fsck --no-progress --connectivity-only ⇒ RC=0（只有 dangling commit，无损坏）
run.py --check = 16/16
```

## 引用存储缺陷（本会话查实并修复）

**症状**：推送成功后 `git status` 显示 `## main...origin/main [ahead 23]`，
但 `git ls-remote origin refs/heads/main` 与本地 `HEAD` **完全一致** —— 两个说法互相矛盾。

**取证链**（全部可复现）：

- `.git/packed-refs` = **66 字节、mtime 2026-09-14 08:52**，**只有一行、缺 git 必写的
  `# pack-refs with:` 头** ⇒ 不是 git 正常写出来的文件；内容把
  `refs/remotes/origin/main` 钉在 `6828e3a`（旧的 WebGL→ECharts 提交）。
- `.git/refs/remotes/origin/` **目录不存在** ⇒ 跟踪引用只能由那份陈旧 packed-refs 提供。
- `git update-ref refs/remotes/origin/main <新值>` ⇒ **RC=0 但文件没生成**，读回仍是旧值。
- 分层对照：`refs/remotes/aaa`（直接一层）**成功** · `refs/xyz/aaa`（git 新建一级目录）
  **成功** · `refs/remotes/origin/bbb`、`refs/remotes/zzz/aaa`、`refs/tags/yyy/aaa`
  （**二级子目录**）**全部失败**。
  ⇒ git 在本环境里建不了 `.git/refs/` 下的**二级子目录**；而 bash 的
  `mkdir -p .git/refs/remotes/origin` **能建**。
  排除项：`icacls` 显示 `refs/remotes` 与 `refs/heads` 的 ACE **逐条相同**
  （不是权限）；`fsutil reparsepoint query` 确认**不是 junction**。
- `git fetch origin` 会把**整个** `refs/remotes/origin/` 目录**删掉**（不是改错值），
  于是回落到陈旧 packed-refs ⇒ **每次 fetch 都复现**。
- 反常点：reflog `.git/logs/refs/remotes/origin/main` **却正常更新**（记到了 `21293a1`）
  —— 写得了日志行，写不了引用本体。

**修复**：`git pack-refs --all`（**标准命令，不是手工改 `.git` 文件**）⇒ packed-refs 重写为
**169 字节、带正确头**，两条条目（`refs/heads/main` 与 `refs/remotes/origin/main`）
均为 `21293a1`；`git rev-parse origin/main` = `21293a1`，`git status` 变回
`## main...origin/main`。修后 `git fetch` 复测**不再复现**。
（修复前的 packed-refs 备份在 `tmp/_packed-refs.bak`，`tmp/` 按 `.gitignore` 不入库。）

⚠️ **未定论的部分**：git 建不了二级子目录的**原因没有查明** —— 只查到"是 git 进程被拦、
不是文件系统权限/重解析点"。**本会话未在沙箱外复跑**，无法排除是运行环境的沙箱所致。

⚠️ **已确认会复现**（不是推测）：本会话第 3 个提交 `3c6d5ad` 推送后，
`git rev-parse origin/main` **又回落到 `21293a1`**（推送前的值），`git status` 又变
`[ahead 1]`；此时 `refs/remotes/origin/` 是一个**空目录**、里面没有 `main`。
⇒ **在本环境里，每一次 push / fetch 只要需要更新跟踪引用，就会把它变陈旧。**
所以 `pack-refs` 只是"把当前值改对"，**不是根治**。

### 同族的第二个症状：`git commit` 触发自动维护会挂住

第 5 个记录提交时，整条命令被 **SIGTERM** 打断 —— 提交本身成功了，但**推送没执行**。
现场证据：`.git/objects/maintenance.lock`（0 字节，09:14）残留，且事后**无任何 git 进程**。
⇒ 是 `git commit` 的 **auto maintenance（auto-gc）在本环境里挂住**，把整条命令拖到超时。
**处置**：删掉这个**死锁**（确认无 git 进程后），后续 git 操作加
`-c gc.auto=0 -c maintenance.auto=false` 绕开，随即推送成功。
⚠️ 这是**记录**，不是长期方案 —— 是否要在本仓库配置里永久关掉 auto-gc，
**留给 KAI 决定**（本会话未擅自改仓库配置）。

## Closed in session

- 五轮改动入库并推送；工作区干净（`porcelain` = 0）
- `notes/context/*` 里五处**已不成立**的「未提交」当前态断言清掉
  （小标题改「已提交 `ab853d3`」；四句「工作区现…」改「**该会话结束时**工作区…」
  —— 原文会被读成"现在还是脏的"，与顶部直接矛盾）
- 远端跟踪引用修复

## OPEN-RISKS

- **git 建不了 `.git/refs/` 二级子目录的原因未查明**（疑为运行环境沙箱）。
  ⚠️ **已确认每次 push/fetch 都会让 `origin/main` 变陈旧**（`3c6d5ad` 推送后当场复现）。
  **未在沙箱外验证。**
- **`git commit` 的 auto maintenance 在本环境会挂住**（第 5 次提交被 SIGTERM 打断，
  留下 `maintenance.lock` 死锁）。临时绕法：`-c gc.auto=0 -c maintenance.auto=false`。
  **是否永久关掉 auto-gc 待 KAI 决定。**
- **提交 ≠ KAI 逐轮验收**：五轮改动均为各会话自证，KAI 未逐轮复核。
- `notes/analysis/` 归属仍未定（本提交只是**保全**证据）。
- `notes/context/*` 三件套在**堆积历史**（`handoff.md` 已叠 5 段会话），与
  `notes-session-records` 要求的 "latest-state-only" 不符 —— **未清理**（非本会话职责）。
- 五轮的既有残留照旧：`web/heatmap.js` 397 行贴上限、`lagCols > 0` 只有单元断言、
  探针无回归保护、触屏未接、热力图纵轴仍不可交互。
