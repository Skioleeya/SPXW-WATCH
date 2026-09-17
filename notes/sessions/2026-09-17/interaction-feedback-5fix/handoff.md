TASK-ID: interaction-feedback-5fix
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec 变更（KAI 直接指令）

# Handoff — 五项交互缺陷修复（KAI 点的 2 / 4 / 5 / 6 / 7）

## 一句话

把 KAI 从交互诊断"大白话版"里点名的五项补上：**全宽横拖不再静默**（弹瞬时徽标）、
**Skew 被锁那一侧纵轴变色 + 锁定徽标**、**两图都有复位按钮和 `Esc`/`R` 快捷键**、
**Skew 四个手势区有游标语义和高亮框**、**热力图有十字线 + 命中格描边 + 提示框跨重建存活**。

## 需求与边界

- KAI 原话：*"把 2 4 5 6 7 这 5项进行修复"* —— 指交互诊断文档"大白话版"里的序号。
- 对照关系：**2 → A2**（全宽横拖静默空操作）· **4 → B2**（双轴锁定看不出）
  · **5 → C1/C4**（复位只有双击）· **6 → C2/D1**（四手势区不可见、游标不变）
  · **7 → D2/D3**（悬停无反馈、无十字线、提示框"得正好停上去才有数"）。
- **只改前端交互层**：不动后端、不动帧字段、不改 `filterMode: "none"` 语义。
- **第 2 项只加"响"，不改语义** —— 全宽横拖**仍然不生成窗口**，只是不再沉默。
- 新增配置键一律 **fail fast**：`heatmap.hover` / `heatmap.xZoom.hintPx` /
  `skew.pan.hintPx` / `skew.feedback` / `ui.flashMs` / `ui.resetKeys`，缺键即抛错。

STARTUP-PROOF: N/A:本轮直接进入实现，改动前未落 `startup.md`。
改动前的行为由四模式对照等价复现（`nofb` / `nohover` / `nohint` 各只翻一个开关）。

## 本轮确立的通用不变量（**最重要**）

> **凡必须在帧间持续存在的反馈，都不能建在 ECharts 内部状态上。**
> 两个面板每 ≤400ms 一次 `setOption(opt, true)`（`notMerge`），实测摧毁：
> ① 悬停 / emphasis —— 指针**静止不动**也在 **+450ms 消失**；
> ② 原生 `axisPointer`（cross / root / axis 三种挂法 × 5 种变体）—— **一次都没画出来**；
> ③ ECharts 自带 `moveOnMouseMove` 拖拽 —— 8 段拖拽只有**前 3 段**生效。

⇒ 常驻可见的反馈一律走 **DOM 覆盖层**（与重建无关，也不吃 `setOption` 的 p50 = 27ms 预算）。
每帧重建后按**像素**补提示框：`dispatchAction({type:"showTip", x, y})`
—— **不能用 `dataIndex`**，列每帧在追加、索引会漂。

CHANGED-PATHS
- web/heatmap_hover.js（**新增**，185 行：十字线 + 命中格描边 + 提示框跨重建存活；
  `findHover` 取真图元包围盒，`reapply()` 在每帧 `_render` 末尾补提示框）
- web/skew_regions.js（**新增**，155 行：四区游标语义 + 轴区高亮框 + 空操作提示钩子）
- web/view_chips.js（**新增**，85 行：面板头徽标的**唯一写入者**，含 `set` / `flash` / `button`）
- web/heatmap.js（383 行：`_panStart` 记 `live`、新增 `_panNoop` / `setNoopHook`；
  `_render` 末尾 `reapply()`；`resetXZoom` 挪到 `_render` 旁）
- web/skew.js（357 行：`_yPatch` 上锁定色、`_applyDecimals` 合并进既有 `axisLabel`
  以免抹掉锁定色、`viewState()`、`setNoopHook`）
- web/skew_zoom.js（394 行：`leftHeld` 迁出到 `skew_helpers`；`yAxisPatch` 携带 `locked`）
- web/skew_helpers.js（390 行：`regionOf` 改为**单一矩形定义** `regionsOf()`，
  手势层与反馈层共用；`leftHeld` 迁入）
- web/app.js（214 行：两个 `setNoopHook`、复位按钮绑定、`Esc`/`R` 键盘复位）
- web/app_render.js（215 行：新增 `syncViewChips()` / `lockText()`；
  窗口与锁定状态**从 meta 行移出**，归徽标）
- web/config.js（310 行：新增 `heatmap.hover` / `heatmap.xZoom.hintPx` /
  `skew.pan.hintPx` / `skew.feedback` / `ui`）
- web/index.html（120 行：两图面板头加徽标与复位按钮；提示文案改写；三个新 script）
- web/style.css（394 行：`.chip` / `.vbtn` / `.xhair` / `.region-hint` / 游标类；
  合并了 `.sessions button` 与 `.periods button` 两处重复规则）
- tmp/_probe_feedback.js（**新增**探针：四模式 `prod|nofb|nohover|nohint`）
- tmp/_probe_skew_drag.js（改读数来源：窗口/复位断言改读 `#skew-mode` 徽标）
- tmp/_shot_feedback.js（**新增**：截图取证 + 面板头溢出实测）

COMMAND-EVIDENCE
- `run.py --check` → `16/16 项全部通过`，`exit 0`（**最终字节上重跑**）
- `tools/check_web_contract.py --offline` → `全部通过`，`exit 0`（id 20 / CFG 54）
- `tools/check_web_contract.py`（在线）→ `全部通过`，`exit 0`（载荷字段 59 条全在发）
- `node tmp/_probe_feedback.js prod` → `mode prod → PASS 49 / FAIL 0`，`exit 0`
- `node tmp/_probe_feedback.js nofb` → `mode nofb → PASS 43 / FAIL 0`，`exit 0`
- `node tmp/_probe_feedback.js nohover` → `mode nohover → PASS 41 / FAIL 0`，`exit 0`
- `node tmp/_probe_feedback.js nohint` → `mode nohint → PASS 48 / FAIL 0`，`exit 0`
- `node tmp/_probe_feedback.js nofbb`（**故意传错模式**）→
  `Error: 未知模式 "nofbb" —— 只支持 prod / nofb / nohover / nohint`，`exit 1`
  ⇒ 守卫非空转
- `node tmp/_probe_skew_drag.js` → `PASS 26 / FAIL 0  (mode=prod)`，`exit 0`
- `node --check web/*.js` → 全部干净，`exit 0`
- `wc -l web/*.js web/style.css` → 最大 `style.css` / `skew_zoom.js` = **394 < 400**
- 关键断言原样（不变量型，比"变了没变"强）：
  - `[ok] 十字线穿过命中格（v.left=1376px ∈ 格子 x 区间；h.top=311px ∈ 格子 y 区间）`
  - `[ok] 提示框锚在指针旁（与命中格的间隙 16,9 px；翻转不翻转都算）`
  - `[ok] 左轴刻度变成警示色 #ffb020`
  - `[ok] 右轴刻度色**没有**跟着变（仍是 #5d6874）—— 两侧可区分`
  - `[ok] 瞬时提示 2600ms 后回到持久态：跟随最新`
  - `[ok] 跨过 400ms 重建后提示框仍在：06:19 · 7560PΔIV +0.11 波动率点`

VALIDATION-SUMMARY
- 门禁：`run.py --check` 16/16 · `check_web_contract.py` 离线 + 在线均通过（**最终字节**）
- 非空转：同一份 `web/*.js`、只翻一处配置 ⇒ prod 49/0 · nofb 43/0 · nohover 41/0 ·
  nohint 48/0；**断言数故意不同**（关掉某功能后只验"它确实不出现"）⇒ 判定相反
- 探针守卫：故意传错模式会抛错（exit 1）
- 肉眼复核：两张截图（见下），面板头 `metaClipped: false`、1662px 无溢出
- 未做：像素级复核、真实物理鼠标验证、触屏

NOTES-PATHS
- notes/analysis/2026-09-17-main-chart-interaction-audit.md（新增 **§3 五项修复的落地与取证**）
- .workbuddy-ai/memory/2026-09-17.md（本轮段落）
- .workbuddy-ai/memory/MEMORY.md（索引时间戳更新）
- notes/sessions/2026-09-17/interaction-feedback-5fix/{handoff,project_state}.md（本目录）

OPEN-RISKS
- **A1 热力图纵轴仍不可交互** —— 诊断里的最大功能缺口，本轮**没做**（需新增交互通道）。
- **E1 触摸未接**；**C3 两图不联动**（KAI 的明确取舍，代价被全额保留）。
- 三个探针在 `tmp/`，按 KAI 明令**不建常驻检查器** ⇒ **无回归保护**。
- 第 2 项是**瞬时徽标**不是图形引导；`heatmap_hover.js` 未做像素级复核。
- 工作区**脏且未提交**，且与 `skew-drag-interaction` / `heatmap-pan-drag` /
  `skew-dual-axis-zoom` 三轮改动混在一起。

## Closed in session

- **A2** 全宽横拖静默空操作 → 两图瞬时徽标提示（2600ms，阈值 `hintPx`）
- **B2** Skew 双轴锁定不可辨 → 锁定侧刻度/轴线/轴名警示色 + 锁定徽标
- **C1 · C4** 复位路径单一 → 面板头复位按钮（脏态点亮）+ `Esc` / `R`
- **C2 · D1** 四手势区不可见、游标缺失 → 游标语义 + 轴区高亮框
- **D2 · D3** 悬停无反馈、无十字线 → 十字线 + 命中格描边 + 提示框跨重建存活
