# Handoff — record-reconciliation

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: 加载后**当场实测**当前现实（不采信记录里的数字）：`python run.py
--check` → **11/11**，其中 `[1] 70 个文件全部合规，最长 acquisition/feed_service.py
= 397 行`；`wc -l acquisition/feed_service.py` → 397；`git ls-files '*.py' | wc -l`
→ 61（+ 9 未跟踪 = 70）；`ls tools/check_*.py | wc -l` → 7。与活文档记载比对后
定位 **4 处不一致**，见下。

## 结论

KAI 指令「加载项目记忆」已执行完毕（`notes/context/*` 3 件 + `.workbuddy-ai/memory/*`
2 件 + 5 个会话根全部读入）。加载过程中按惯例做了"记录 vs 现实"核对，
发现并改正 **4 处不一致** —— 全部是事实性错误，**零生产代码改动**。

| # | 位置 | 记录写的 | 实测事实 | 性质 |
|---|---|---|---|---|
| 1 | `README.md` §9 状态行 / `notes/context/project_state.md` / `notes/context/open_tasks.md` / `.workbuddy-ai/memory/MEMORY.md` | `feed_service.py` **396 行**（余 4 行） | **397 行**（余 3 行） | 数字腐烂 |
| 2 | `README.md` §9 状态行 | 69 个文件 / 最长 395 行 / **10 项**检查 | **70 / 397 / 11 项** | 数字腐烂（落后两轮） |
| 3 | `README.md` §9 检查表 | 只列到 `[10]`；`[5]` 写 40 个关键键 | 缺 `[11]` 行；实测 **41** 个 | 数字腐烂 |
| 4 | `README.md` §10 已知边界 | **「实盘未验证」**；端口默认 `7497`（TWS 模拟） | **已实测联通**（11～14 秒就绪、仅 72 × Error 10090）；端口默认 **4002**（IB Gateway 模拟） | 结论被后续实测推翻 |

第 4 条最要紧：README 对外声称"连上之后能否收到数据尚未验证"，而事实是
2026-09-11 已双路实测收到数据（`ws_probe` 72/92 订阅、热力图 36 档 × 25 桶、
36 格有效数值、25Δ 与现价均有值）。**这条会主动误导读者**，且方向是"欠吹"——
同样是不实陈述。

CHANGED-PATHS: 4 个文件（0 新增 + 4 改；另新增会话根 5 件）
- `README.md`（改，6 处）——
  §9：`10 项` → `11 项`；`40 个关键配置项` → `41 个`；补 `[11]` 表格行；
  `69 个 Python 文件，最长 395 行…10 项检查` → `70 个…397 行…11 项`。
  §10：端口默认 `7497`/TWS 模拟 → `4002`/IB Gateway 模拟；
  「**实盘未验证**」整条重写为「实盘链路已实测联通（2026-09-11），但
  **Greeks 落地**仍未验证」。
- `notes/context/project_state.md`（改，2 处）—— `最长 396 行` → `397 行`；
  `396/400（余 4 行）` → `397/400（余 3 行）`。
- `notes/context/open_tasks.md`（改，1 处）—— `当前 396/400（余 4 行）`
  → `当前 397/400（余 3 行）`。
- `.workbuddy-ai/memory/MEMORY.md`（改，2 处）—— `396/400（余 4 行）`
  → `397/400（余 3 行）`；`check_*` **8 个** → **7 个**（并列出 5 本地 + 2 需服务）。

**刻意不改**：`notes/sessions/2026-09-11/{dead-key-resolution,ibkr-rate-limit-audit}/**`
里出现的 395 / 396 是**历史快照**（dead-key-resolution 轮确实拆到 395 行），
回改等于伪造历史。

VALIDATION-SUMMARY: 全部通过。本次无生产代码改动，验证目标是"记录与现实是否
一致"，用 4 条可复现命令交叉核对；改正后再跑一次 `run.py --check` 确认
**11/11** 未受影响。

COMMAND-EVIDENCE: 明细见下
- `python run.py --check` → `结果: 全部通过`（**11/11**）。关键摘录：
  - `[1] 文件长度（上限 400 行）` → `[ok] **70 个文件**全部合规，最长
    acquisition/feed_service.py = **397 行**`
  - `[3] 配置文件可读性` → `[ok] 10 个模块配置全部可读`
  - `[5] 关键配置项存在` → `[ok] **41 个**关键配置项齐备`
  - `[6] 订阅容量` → `[ok] 档位 ±18 → 73 条行情（自设上限 92，IBKR 上限 100）`
  - `[11] 出站限速桶容量与 IBKR 配额` → `[ok] 桶 45 条 / 1s = 45 条/s
    （官方上限 50；qualify 单批 40 条；订阅节奏 20 条/s）`
  - `[7]` 160 处取键调用全落位 / `[8]` `__slots__` 一致 / `[9]` 单一职能 /
    `[10]` 无模块级硬编码（8 条例外） → 全 ok
- `python -c "len(Path('acquisition/feed_service.py').read_text().splitlines())"`
  → `splitlines = 397`、`newline count = 397`、`endswith newline = True`、
  `bytes = 15778`
  → **排除口径差**：自检 [1]（`selfcheck_structure.py:38`）与 `wc -l` 同口径，
  397 就是 397，记录里的 396 是错的，不是"少算末尾换行"。
- `git ls-files '*.py' | wc -l` → `61`；未跟踪 `.py` 9 个 → 61 + 9 = **70**，
  与自检口径吻合
- `git ls-files '*.py' | xargs wc -l | sort -rn | head -6` → 最长
  `397 acquisition/feed_service.py`，其后 360 / 350 / 344 / 335
- `ls tools/check_*.py | wc -l` → **7**
  （`clock_protocol` / `page_render` / `session_rollover` / `side_flip` /
  `subscription_qualify` / `tick_router` / `web_contract`）
- `git log --oneline -3` → 仅 `755b221 Initial commit: SPXW SWATCH — 0DTE IV
  impulse heatmap & 25Δ skew radar`
- `git status --short` → 31 个 `M` + 9 个未跟踪 `.py` + 4 个未跟踪会话根
  → **全部多轮工作仍在工作区，尚未提交**

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 一条
1. **"数字类记录"缺少单一真相源，正在持续腐烂。** 本次 4 处不一致里 3 处是
   纯数字（文件数 / 最长行数 / 检查项数 / 关键键数），且**同一事实散落在 4 个
   文件里**（`README.md`、`notes/context/project_state.md`、
   `notes/context/open_tasks.md`、`.workbuddy-ai/memory/MEMORY.md`）——
   改一处必须记得改四处，漏一处就制造新的不一致。
   可收敛方向：① 让 `README.md` §9 的状态行**只写"跑 `run.py --check` 看输出"**，
   不再复述具体数字（自检输出本身就是唯一真相源）；② 把
   `notes/` 与 `.workbuddy-ai/memory/` 收敛为一套（本项是 `open_tasks.md`
   的既有未决项，本会话再次以实例证明其代价）。
   **本次未擅自实施** —— 属结构性改动，须 KAI 定。

NOTES-PATHS: 8 个文件（会话根 5 件 + 上下文索引 3 件）
- `notes/sessions/2026-09-11/record-reconciliation/startup.md`
- `notes/sessions/2026-09-11/record-reconciliation/project_state.md`
- `notes/sessions/2026-09-11/record-reconciliation/open_tasks.md`
- `notes/sessions/2026-09-11/record-reconciliation/handoff.md`
- `notes/sessions/2026-09-11/record-reconciliation/meta.yaml`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 3 条，明细见下
1. **数字类记录会继续腐烂（中）** —— 见 HARNESS-IMPROVEMENT。只要"同一事实写
   在四个地方"的结构不变，下次改动还会重现本次的不一致。`--check` 的输出可以
   当唯一真相源，但目前没人以它为基准回改文档。
2. **`README.md` §10「实盘未验证」曾长期与事实相反（中，已修正）** —— 这条
   存在了一段时间（至少从 `port` 改成 4002 那轮起就与事实冲突）。它不会让任何
   检查变红，只能靠人读出来。**同类风险**：任何"未验证"结论在验证之后都需要
   人工回改，目前无机制提醒。
3. **全部工作未提交（低）** —— 31 个 `M` + 9 个未跟踪 `.py` 只在工作区存在，
   `git show HEAD:` 里是旧版本。若工作区损坏，多轮改动会一起丢失。
   是否提交由 KAI 决定（本会话未执行任何 git 写操作）。

FAST-FAIL-CHECK: N/A:本次为文档事实校正，未触碰任何背压 / 失败路径
NO-COMPAT-BRANCH: 通过 —— 直接改正文字，未保留"新旧两说"、未加条件分支
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径
NO-PATCH-BANDAGE: 通过 —— 改的是事实陈述本身，不是在别处补一句"以最新为准"
  来掩盖过期内容
NO-FALLBACK-BEHAVIOR: 通过 —— 未新增静默降级；未把"实盘未验证"改成模糊措辞
  了事，而是写清"哪部分已实测、哪部分仍未验证"

TRIGGER-PATHS: N/A:本项目为 Python/JS，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check`（11/11），已在上方
  COMMAND-EVIDENCE 记录
