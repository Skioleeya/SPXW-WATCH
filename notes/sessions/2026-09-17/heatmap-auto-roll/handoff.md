TASK-ID: heatmap-auto-roll
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec 变更（KAI 直接指令）

# Handoff — 热力图横轴「自动滚动」(auto roll)

## 一句话

热力图缩出横轴窗口后，窗口右缘**自动跟着最新列走**（不再越看越旧）；
手动往历史里拖 ⇒ 停滚；面板头「回到最新」按钮把右缘拉回最新列并恢复跟随，
**保住当前缩放跨度**（与「复位」不同 —— 复位是丢掉缩放回全宽）。

## 需求与边界

- KAI 原话：*"当前 IV 热力图需要支持 auto roll（自动滚动）功能。请实现该自动滚动能力，
  明确滚动的触发条件、滚动方向与速度."*
- **只改前端交互层**：不动后端、不动帧字段、不改 `filterMode: "none"` 语义。
- **全宽不滚**（全宽天然含最新列）；自动滚动只在**有窗口**时有意义。
- 新增配置键 `heatmap.xRoll` 一律 **fail fast**：缺块 / `enabled` 非布尔 /
  `lagCols` 为负 都抛错。

## 触发条件 / 方向 / 速度（KAI 要的三个量）

- **触发条件**（三条同时成立才滚）：① `heatmap.xRoll.enabled` 为真；
  ② 存在横轴窗口（已缩放）；③ 处于「跟随」态。
- **方向**：**只有时间正方向**（列下标增大，朝更新的列）。永不自动往回走 ——
  往回走会让"我没动它，它自己退回去了"变成常态，比不滚更难理解。
- **速度**：**数据驱动，不插值**。每帧把右缘移到 `cols - 1 - lagCols`，
  即"前进量 = 该帧新增的列数"；帧节拍由后端推送（400ms）决定。
  `lagCols` 是**唯一**的调节量（默认 0 = 右缘就是最新列）。
  **不设"每秒滚几列"这类定时速度** —— 那是插值动画：一次 `setOption` 实测
  p50 27.4ms / max 44.6ms（见 `web/heatmap.js` 文件头），插到 60fps 需要 16.7ms 一次，
  做不到，硬做会把单核打满并让帧积压。

## 设计要点（**本轮最关键的一条**）

> **「跟随」态必须显式存一个布尔位，不能现算。**

直觉上可以现算"右缘是否贴着最新列"，但**列一追加，任何窗口的右缘都不再贴着最新列**
⇒ "用户往回拖了 5 列"与"过了 5 列"完全无法区分（两者 `to` 都差 5）。
所以跟随态只由四件事改写：按下拖动 ⇒ 立刻接管；一段拖动结束 / 复位 ⇒ 按右缘位置结算；
全宽 ⇒ 跟随；列数不够（跨度 ≥ 全部列）⇒ 退化为全宽。
**滚轮缩放不改这一位**：缩放改的是跨度，不是"想不想跟"的意图。

STARTUP-PROOF: N/A:本轮直接进入实现，改动前未落 `startup.md`。
改动前的行为由两模式对照等价复现（`noroll` 只翻 `heatmap.xRoll.enabled=false`）。

CHANGED-PATHS
- web/heatmap_roll.js（**新增**，159 行：策略层。纯函数 + 一个布尔状态位；
  `advance` 每帧推窗口、`snap` 供用户显式"看最新"、`takeOver` / `settle` / `reengage`
  管跟随态、`state` 给 UI 读快照。只吃 (窗口, 列数)，不碰 ECharts / DOM / 帧）
- web/config.js（327 行：新增 `heatmap.xRoll = {enabled, lagCols}`）
- web/heatmap.js（**397 行**：构造函数建 `_roll`；`update()` 把原来的"越界复位"整块
  换成 `this._xWin = this._roll.advance(this._xWin, cols)`（越界告警一并搬进 roll 模块，
  **净减行数**）；`_panStart` 加 `takeOver()`、`_panEnd` 加 `settle()`；
  `resetXZoom` / `clear` 加 `reengage()`；新增 `xRoll()` / `rollToLatest()`）
- web/app_render.js（234 行：`syncViewChips()` 报「自动滚动 a–b」/「已停滚 a–b」/
  「窗口 a–b」/「跟随最新」；「回到最新」按钮按 `state.atTail` 点亮）
- web/app.js（216 行：`bindReset` 更名 **`bindButton`**（它不只绑复位）并接上
  `heatmapPanel.rollToLatest()`）
- web/index.html（122 行：新增「回到最新」按钮 + `heatmap_roll.js` script）
- web/style.css（395 行：新增 `.chip.paused`）
- tools/check_web_contract.py（**修覆盖缺口**：`_ID_CALL` 补 `bindButton` 与
  `ViewChips.set|flash|button` 两个分支；`--selftest` 扩成三条取法各注入一个假 id，
  漏扫任一条即 FAIL）
- README.md（§9 工程余量：记下 `web/heatmap.js` 与 `web/style.css` 贴上限，
  并写明 `heatmap.js` 该往哪拆）
- tmp/_probe_heatmap_roll.js（**新增**探针：两模式 `prod|noroll`，13 条策略单元 +
  真机集成）
- tmp/_probe_pan_drag.js · _probe_pan_guards.js · _probe_pan_reset.js
  （**改拖动方向**，理由见下）
- tmp/_shot_roll.js（**新增**：三态截图 + 面板头溢出实测）
- tmp/_diag_pan_state.js · _diag_404.js · _diag_head.js（一次性诊断，留档）

COMMAND-EVIDENCE
- `run.py --check` → `16/16 项全部通过`，`exit 0`
- `tools/check_web_contract.py --offline` → `全部通过`，`exit 0`
  （DOM id **引用 20 → 27 个**，HTML 定义 34；CFG 路径 55 条）
- `tools/check_web_contract.py`（在线）→ `全部通过`，`exit 0`（载荷字段 59 条）
- `tools/check_web_contract.py --selftest` → 三项全 `[ok]`（含新增的
  `id 三条取法都被扫到 → el / bindButton / ViewChips 全命中`），`exit 0`
- **变异**：把 `bindButton` 从 `_ID_CALL` 摘掉 → `--selftest` 打印
  `[FAIL] id 三条取法都被扫到 → 漏: __selftest_missing_btn__`，`exit 1`
- `node tmp/_probe_heatmap_roll.js prod` → `mode prod → PASS 44 / FAIL 0`，`exit 0`
- `node tmp/_probe_heatmap_roll.js noroll` → `mode noroll → PASS 39 / FAIL 0`，`exit 0`
- 关键相反判定（真机、真等新列到达）：
  - prod：`新列到达：{"dCols":1,"dTo":1,"dFrom":1}` →
    `[ok] 速度 = 新增列数（Δto 1 == Δcols 1）`、`[ok] 新列到达后右缘仍钉在最新列`
  - noroll：`新列到达：{"dCols":1,"dTo":0,"dFrom":0}` →
    `[ok] [noroll] 新列到达后窗口原地不动（dTo=0 dFrom=0）—— 开关真的在管`
- 回归复跑：`_probe_feedback.js prod` `49/0` · `_probe_pan_drag.js` on `PASS`
  （`distinctStarts: 8` / `movedDuringDrag: true`）· off `PASS`
  （`distinctStarts: 1` / `movedDuringDrag: false`）· `_probe_pan_guards.js` `PASS` ·
  `_probe_pan_reset.js` `PASS` · `_probe_skew_drag.js` `PASS 26 / FAIL 0`
- 布局实测（`tmp/_shot_roll.js`）：chip 153 → **102px**、`metaClipped: false`、
  `overflow: []`；三态类名 `chip window` / `chip paused` / `chip window`
- 行数：最大 `web/heatmap.js` **397** < 400

VALIDATION-SUMMARY
- 门禁：`run.py --check` 16/16 · 契约离线 + 在线 + `--selftest` 全通过
- 非空转：同一份 `web/*.js`、只翻一处配置 ⇒ prod 44/0 · noroll 39/0，
  **关键断言判定相反**（窗口前进 Δto=Δcols=1 vs 原地不动 dTo=0）
- 变异验证：契约检查器摘掉 `bindButton` 分支 ⇒ 自检 `exit 1`
- 回归：feedback / pan_drag(on+off) / pan_guards / pan_reset / skew_drag 全部 RC=0
- 肉眼复核：三态截图 + 面板头放大图
- 未做：像素级复核、真实物理鼠标验证、触屏；`lagCols > 0` 只有单元断言覆盖

NOTES-PATHS
- .workbuddy-ai/memory/2026-09-17.md（本轮段落）
- .workbuddy-ai/memory/MEMORY.md（索引时间戳更新，删掉两段过期状态块）
- README.md §9 工程余量
- notes/sessions/2026-09-17/heatmap-auto-roll/{handoff,project_state}.md（本目录）

OPEN-RISKS
- **`web/heatmap.js` 397 行（上限 400，只剩 3 行）** —— 下次动它几乎必然要先拆分。
  可拆的缝：左键拖拽手势（`_panStart` / `_panMove` / `_panNoop` / `_panRender` /
  `_panEnd` 一整块）按 `heatmap_hover.js` / `heatmap_roll.js` 的既有模式下沉成
  `heatmap_pan.js`。**`web/style.css` 395 行**同样贴上限。
- **拖动方向被自动滚动"耦合"了**：跟随态下右缘就在最新列 ⇒ **向左拖是空操作**
  （被 `clampCols` 夹住）。这是正确行为，但**老探针与新读者都会踩**，
  已在三个 pan 探针各留注释。
- `lagCols > 0` 这条路径只有**单元断言**覆盖，没有真机跑过（默认 0）。
- 探针在 `tmp/`，按 KAI 明令**不建常驻检查器** ⇒ **无回归保护**。
- 未做：像素级复核、真实物理鼠标验证、触屏（E1）。
- 工作区**脏且未提交**，与另外四轮改动叠在一起（共五轮）。

## Closed in session

- **auto roll 本体**：触发条件 / 方向 / 速度三个量按 KAI 要求明确并落地
- **「回到最新」按钮**：保住缩放跨度回到最新列（与「复位」分工明确）
- **契约检查器 id 覆盖缺口**：补 `bindButton` + `ViewChips.*` 两个分支，
  `--selftest` 扩成三条取法各自的非空转验证
- **布局回归**：加按钮导致 meta 行被挤到省略号（差 17px）⇒ 徽标文案压紧 +
  回退我加长的提示行 ⇒ `metaClipped: false`
