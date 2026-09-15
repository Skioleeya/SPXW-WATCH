# handoff — 2026-09-15 / period-wallclock-semantics

- **task-id**: `period-wallclock-semantics`
- **日期**: 2026-09-15（EDT，GTH 段）
- **基线 commit**: `2db39eb`（起点为**脏工作区**：6 文件未提交，承上一会话）
- **范围**: `web/period.js`（注释）· 会话记录。**未改任何业务逻辑。**

```text
TASK-ID: period-wallclock-semantics
DATE: 2026-09-15
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change
```

---

## 1. 结论（一句话）

**KAI 裁定的"按挂钟整点分对齐"，在本项目已经成立 —— 桶分组与时间分组数值等价，
不需要删任何逻辑、不需要新增字段。** 唯一产出是把这条等价性钉进 `web/period.js`
注释，防止后人重走。KAI 另有一条真缺陷（跨空档那两列）明确裁定**不修**。

## 2. 需求与裁定（KAI 原话要点）

> "必须基于时间，时间是系统最重要的，21:00 21:03 21:06……时间周期才是第一，
> 桶无效，必须删除这个错误逻辑！"

查证结论：**该裁定的目标状态已达成**。依据两级，均可复现：

1. 网格起点 `20:15:00` = **72900 秒**，而 `72900 % {30,60,180,300,900}` **全为 0**
   ⇒ 组边界必然落在挂钟整点（20:15 / 20:18 / … / 21:00 / 21:03）。
2. `core/session_grid.py::_make_zone`（第 71-76 行）**强校验**区段边界落在桶边界上
   （不满足直接抛错），而 `parse_hm` 只接受 `HH:MM` ⇒ "整分钟 ∪ 桶宽整除"必然成立。

⇒ `floor(cols / g)` ≡ `floor((t − 20:15) / period秒)`。**改成分组按时间是恒等变换。**

### 2.1 裁定表

| 轮次 | KAI 裁定 | 落地 |
|---|---|---|
| 对齐口径 | 挂钟整点分（12:00 / 13:01 / 15:45） | 与现状一致 |
| 补字段 vs 后端算 | 选"后端算" | **作废：前提不成立，无需后端算** |
| 档位是否告诉后端 | 选"告诉后端" | **作废：同上** |
| 跨空档那两列 | **"不用"** | 不改分组基准 |

> ⚠️ "作废"不是 KAI 选错，而是**提方案时我们还不知道边界已对齐**。事实澄清后方案失去对象。
> **将来不得照着去实现那个双向通道。**

### 2.2 KAI 裁定"不修"的真缺陷（备将来）

空档（桶 1580–1589）被切进两组：组 263 = 桶 1578–1583（09:24–09:27，混算 GTH 尾 + 空档）、
组 264 = 桶 1584–1589（09:27–09:30，整组在空档内 ⇒ **该列永远无颜色**）。
修法是"让每个会话从自己起点起算分组"—— **已被明确否决，勿自作主张。**

## 3. 改动清单

CHANGED-PATHS:
- `web/period.js`（**仅注释**：新增一节论证"按桶分组 ≡ 按挂钟整点分分组"，
  含 72900 % 各档位 = 0 的实测与 `session_grid` 强校验的指针）
- `notes/sessions/2026-09-15/period-wallclock-semantics/startup.md`（新增）
- `notes/sessions/2026-09-15/period-wallclock-semantics/project_state.md`（新增）
- `notes/context/handoff.md`（索引）
- `notes/context/open_tasks.md`（新增一条：`cols % g` 复现法教训）
- `.workbuddy-ai/memory/2026-09-15.md`（追加）

> **继承自上一会话、本轮未回退的文件**：`tools/period_reference.py` /
> `tools/period_selftest.py` / `tools/skew_reference.py` /
> `tools/check_skew_colors.py` / `tools/check_skew_viewport.py`（其中
> `skew_reference.py` 的 `DOM_STUB` 是修"三个回归一起崩"的既存缺陷）。

## 4. 证据

VALIDATION-SUMMARY:
- `tools/check_period_aggregation.py --selftest` → `exit 0`（24 判据 + 守卫 2 + **6 变异全抓**）
- `run.py --check` → `exit 0`（`[13]` 走真实联通：24 档 × 1489 桶 / Skew 815 点）
- `tools/check_*.py` 全量矩阵 → **21 绿 / 2 红**，两红经 `git stash -u` 证为**既存**
- `web/period.js` 行数 → **391**（< 400 上限）

COMMAND-EVIDENCE:
- `venv/Scripts/python.exe tools/check_period_aggregation.py --selftest` → `RC=0`；
  变异命中明细：`未走满的末组也出列（回到旧语义）→ aggregate 抓 24 项`、
  `末组丢弃后标签序列未同步 → aggregate 抓 5 项`、另 4 条各抓 2/10/19 项。
- `venv/Scripts/python.exe run.py --check` → `RC=0`；
  `[ok] 热力图 24 档 × 1489 桶`、`[ok] Skew 序列 815 点`、`[ok] 连接状态 connected / mode=delayed`。
- 矩阵扫描（`for f in tools/check_*.py`）→ 仅 2 个 `RC=1`：
  `check_page_render.py`（`[FAIL] 有且仅有一个周期处于选中态 选中: 全时段、1分`）、
  `check_ws_compression.py`（`[FAIL] 线上压缩比 ≥ 80% 实测 71.2%`）。
- **非空转复核**：`git stash push -u` 后两者仍 `RC=1`（压缩比 71.4%）⇒ 确属既存缺陷；
  `git stash pop` 恢复，6 文件 diff 完整。
- 挂钟对齐实测（离线，`build_zones` 直接调用）→ `start_min=1215 (20:15)`、
  `bucket_seconds=30`、区段 `GTH 20:15→09:25 [0,1579]` / `空档 [1580,1589]` /
  `RTH 09:30→16:00 [1590,2369]`。

NOTES-PATHS: `notes/sessions/2026-09-15/period-wallclock-semantics/handoff.md`（本文件）·
同目录 `startup.md` · `project_state.md` · `notes/context/handoff.md` ·
`notes/context/open_tasks.md` · `.workbuddy-ai/memory/2026-09-15.md`

## 5. ## Closed in session

- **"桶 vs 时间"是否为两种方案**：判定为**同一种**，附两级可复现依据；已钉进 `period.js` 注释。
- **上一会话遗留缺口**（"旧语义漂移未复现"）：定位为**采样位置问题**而非缺陷不存在 ——
  触发条件是 `cols % g == 1`（末组恰 1 桶 = 刚跨周期那一帧），按 3s 抽间隔帧必然跳过。
  已记录复现法，见 `open_tasks.md`。
- **`tmp/` 探针清理**：删 12 个一次性探针 + `frames_seq.jsonl`(4.7MB) + `edge_cross*.log`。
- 非空转自测与门禁全量复核（含两红灯的既存性证明）。

OPEN-RISKS:
- **`web/period.js` 已 391 行**（上限 400，`check_file_sizes` 判据是 `>=`）⇒ 余量 9 行。
  再往里加内容**必须拆分**，否则 `run.py --check` 会真判红（本项目自踩过一次，见
  `heatmap-topn-skew-yzoom` 的 ⚠️ 记录）。
- **两个既存红灯未修**（`check_page_render` 周期选中态、`check_ws_compression` 压缩比
  71.2% < 80%）。均与本次改动无关，但会持续污染"全绿"结论 —— **引用"21/2"时必须带上
  它们的既存性证据**，否则读者会误判为本轮引入。
- **跨空档两列（组 263/264）语义不纯**：KAI 已裁定不修，但该列**永远无颜色**是可见现象，
  若 KAI 日后追问"为什么 09:25 附近有列没颜色"，答案在本文件 §2.2。
- **未做浏览器取像素**：本轮结论全部来自离线算术与后端帧，未在真实浏览器验证渲染。

NO-PATCH-BANDAGE: 是 —— 未为"看起来对齐"加任何补丁；查证后确认无需改动。
NO-FALLBACK-BEHAVIOR: 是 —— 未引入兜底分支。
