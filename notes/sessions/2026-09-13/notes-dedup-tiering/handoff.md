# Handoff — notes-dedup-tiering

TASK-ID: notes-dedup-tiering
DATE: 2026-09-13
TIER: T2（就地升级：会话前半段为 T1 只读审计，删减决策后触及 3 个文件）
STATUS: complete
CHANGE-ID: N/A:该仓库未使用 OpenSpec

STARTUP-PROOF: N/A:本 root 由 T1 就地升级 —— 会话以只读审计开始，第一个写动作
就是改 skill，不存在"改动前基线"可捕获。**刻意不回填 `startup.md`**（skill 明令
禁止回填）。仓库零改动由 `git status --short` 20 项与任务前同值证明。

## 结论

KAI 两问的答案，合一：

**（1）一个会话原为 5 件套，重复成立，根因是 skill 自己要求双写。**

| 事实 | 原双写位置 | 命中 |
|---|---|---|
| `STARTUP-PROOF` | `startup.md` + `handoff.md`（近乎逐字） | 7/8 会话 |
| 验证命令 | `meta.yaml::validation_commands` + `handoff.md::COMMAND-EVIDENCE` | 8/8 |
| `scope` | `startup.md::## Scope Understanding` + `meta.yaml::scope` | 7/8 |
| `change_id` | `meta.yaml` + `handoff.md::CHANGE-ID` | 8/8 |

单会话内事实 × 文件：`fixtures.py` 5/5 文件、`582`/`188`/`341` 各 4/5、`8060` 5/5。
全局：`4002` 22 文件 51 次、`Turbo` 15 文件 34 次、`11/11` 19 文件 36 次。

**未发现"一个会话拆成多个 root"** —— 7 个 2026-09-11 root 各有独立 KAI 触发
（逐个读 `## Session` 段确认）。是**跨会话复述**，最大复制源是 `## Prior Context Read`。

**（2）可以删减为 3 件套，且三件套已有最优解。**

| 原文件 | 独有载荷 | 复述部分 | 裁决 |
|---|---|---|---|
| `handoff.md` | 命令证据、core markers、fail-closed 标记块 | 无（它是归属方） | **留** |
| `startup.md` | 改动前基线、改动前识别的风险、读了哪些前置源 | scope 与 meta 重复 | **留** |
| `project_state.md` | 设计取舍理由（"为什么不留 `--live`"）、踩到的坑 | §1/§2/§3/§5/§7 与 handoff 重复 | **留（瘦身）** |
| `open_tasks.md` | 本会话 Closed 项 | Active/Stale 与 `context/open_tasks.md` 重复 | **删** |
| `meta.yaml` | `status` / `deliverables` 机器索引 | scope / validation / change_id 三处均与别处重复 | **删** |

两条硬证据支撑这个取舍顺序（而不是反过来砍 `project_state.md`）：

- **仓库内 `meta.yaml` 的消费者为零** —— `grep -rn "meta\.yaml\|notes/sessions\|notes/context"`
  在全部 `.py` / `.js` / `.json` 中**零命中**（`notes/` 自身除外）。"机器可读"目前是空头支票。
- **`startup.md` 的载荷事后不可复现** —— 改动前基线一旦漏捕，就再也证不了"没有事后补绿"。
  这是唯一必须**先于**改动存在的文件。

## skill 改动

`C:\Users\Lenovo\.workbuddy-ai\skills\notes-session-records\SKILL.md` —— 137 → 188 行。
行数上升，但**文件数上限从 5 降到 3**，且新增的全是简化/去重规则：

1. **分级收敛为两级** —— T1（单文件/文档）= 只要 `handoff.md`；T2（其余）= `startup.md`
   + `project_state.md` + `handoff.md`。原 T3 五件套已废除，**三件为上限**。
2. **`## Single Home for Every Fact`** —— 9 行归属表，每个事实恰好一个归属文件。
   新增"会话身份 → `handoff.md` 的 key header"、"本会话关闭项 → `## Closed in session`"。
3. **key header 取代 `meta.yaml`** —— `TASK-ID` / `DATE` / `TIER` / `STATUS` / `CHANGE-ID`
   五行，写在 `handoff.md` 顶部，仍可 grep。
4. **`### Shrinking the evidence`** —— 明确**允许缩减**验证文档：默认一行一条命令、
   同因多命令合并成一行、同一结果不得写两遍。
5. **`## Prior Context Read` 定为最大跨会话复制源** —— 只写"读了哪个源 + 它施加的约束"。
6. **`## Final Check`** —— 新增"上限三件"与"任何事实不得写两遍"两条。
7. 同步 frontmatter `description`（移除 `open_tasks.md` / `meta.yaml`）。
8. **新增 forward-only 规则**（KAI 2026-09-13 裁定后写入）—— 禁止把旧 root 改造成
   新形状，也**禁止提出回溯**。这条把"要不要回溯历史会话"从待议项变成规则，
   避免下个会话重新来问。

`C:\Users\Lenovo\.workbuddy-ai\MEMORY.md` —— 路由表第 28 行改为三件套，
并加一句删减说明。字符数 1431/4000（上限内）。

CHANGED-PATHS: 3 个（改 3 / 增 0 / 删 0）
- `C:/Users/Lenovo/.workbuddy-ai/skills/notes-session-records/SKILL.md` — 137 → 188 行
- `C:/Users/Lenovo/.workbuddy-ai/MEMORY.md` — 路由表第 28 行 + 删减说明
- `notes/sessions/2026-09-13/notes-dedup-tiering/handoff.md` — 本文件，改写为 key header 形制

VALIDATION-SUMMARY: 仓库自检 `run.py --check` **11/11 全部通过**；
skill 关键段落逐条 grep 复核通过、无旧五件套残留；仓库工作树 20 项与任务前同值
（本任务仓库零改动）。

COMMAND-EVIDENCE:
- `python run.py --check` → `结果: 全部通过`（11 项；[10] 显式例外 9 条）
- `wc -l SKILL.md` → `188`（本轮改动前 171，最初 137）
- `grep -n "meta\.yaml\|T3\|five files\|open_tasks" SKILL.md` → 6 处命中，
  **逐条核对均为有意保留**：3 处否定句（"no `meta.yaml`"）+ 3 处
  `notes/context/open_tasks.md`（该文件保留）。**无 `T3`、无五件套残留。**
- `grep -rn "meta\.yaml\|notes/sessions\|notes/context" --include=*.py --include=*.js
  --include=*.json .` → **零命中**（`notes/` 除外）⇒ 仓库内无 `meta.yaml` 消费者
- `wc -m C:/Users/Lenovo/.workbuddy-ai/MEMORY.md` → `1431`（上限 4000）
- `git status --short | wc -l` → `20`（与任务前同值）

## Closed in session

- [x] **[高] 查清一个会话的记录件数** —— 5 件套，8 个会话五件套合计 278–881 行，
      全 `notes/` 3740 行。
- [x] **[高] 重复记录审计** —— 4 类双写（7/8、8/8、7/8、8/8），根因是 skill 双写要求；
      另排除"一个会话拆多 root"嫌疑，定位真病灶为跨会话复述。
- [x] **[高] skill 放宽 + 去重** —— 新增归属表、分级、证据缩减规则、Final Check 两条。
- [x] **[定] 记录体系形态** —— KAI 2026-09-13 裁定：**保持 A**，即三件套
      = `handoff.md` + `startup.md` + `project_state.md`；**方案 B 作废**
      （不恢复 `meta.yaml`）。理由见 `project_state.md` §1。
- [x] **[定] 历史会话不回溯** —— KAI 2026-09-13 裁定：8 个历史 root 保持
      5 件套原样，**不改写**。已把该裁定提升为 skill 通用规则
      （"Changing this shape is forward-only"），避免下个会话重新提出。
- [x] **[高] 五件套 → 三件套** —— 删 `meta.yaml`（零消费者）与 session 级
      `open_tasks.md`（与 `context/open_tasks.md` 重复）；`handoff.md` 加 key header
      承接身份信息。

NOTES-PATHS: 2 个
- `notes/sessions/2026-09-13/notes-dedup-tiering/handoff.md`
- `notes/sessions/2026-09-13/notes-dedup-tiering/project_state.md`

OPEN-RISKS: 2 条
1. **[低] 现行上下文索引未滚动** —— `notes/context/handoff.md` 的 `Latest session`
   仍指 `simulator-hard-cut`。**刻意不动**：该索引跟踪"最近一次改动项目状态的会话"，
   本任务仓库零改动。
2. **[低] 仓库外存在会腐烂的第二副本** —— `notes_backup_20260911/`（52 文件），
   其中 `sessions/2026-09-11/` 35 个文件与现行 `notes/` **逐字节相同**。未删除。

已裁定不再重提（KAI 2026-09-13）：方案 B（保 `meta.yaml`）；回溯历史 8 个会话。
