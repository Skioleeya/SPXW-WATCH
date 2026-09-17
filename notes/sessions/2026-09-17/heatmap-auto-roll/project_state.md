# Project State — heatmap-auto-roll（2026-09-17）

## 一句话

热力图横轴自动滚动已落地并全绿：缩出窗口后右缘自动跟着最新列走、往历史拖即停滚、
「回到最新」按钮保跨度回到最新列。工作区**脏且未提交**。

## 仓库状态

- `HEAD = 390ac6e`（已推送远端）
- 工作区**脏**：本轮新增 1 个 `web/` 文件（`heatmap_roll.js`）+ 改 6 个 `web/` 文件
  + `tools/check_web_contract.py` + `README.md` + 7 个 `tmp/` 探针/诊断 + `notes/`，
  **外加上四轮改动**（`interaction-feedback-5fix` / `skew-drag-interaction` /
  `heatmap-pan-drag` / `skew-dual-axis-zoom`）—— **五轮混在同一工作区**，
  本会话未替它们背书、也未一并提交。

## 文件行数（`run.py --check [1]`，上限 400 严格小于）

| 文件 | 行数 | 说明 |
|---|---|---|
| web/heatmap.js | **397** | ⚠️ 只剩 3 行 —— 下一次动它几乎必然要先拆 |
| web/style.css | **395** | 本轮新增 `.chip.paused`，同样贴上限 |
| web/skew_zoom.js | 394 | 上一轮 |
| web/heatmap_option.js | 378 | |
| web/config.js | 327 | 本轮新增 `heatmap.xRoll` |
| web/app_render.js | 234 | 本轮改徽标文案 |
| web/app.js | 216 | 本轮 `bindReset` → `bindButton` |
| web/heatmap_roll.js | 159 | **本轮新增** |
| web/index.html | 122 | 本轮新增「回到最新」按钮 |

⚠️ **`web/heatmap.js` 是新的头号瓶颈**。可拆的缝很明确：左键拖拽手势整块
（`_panStart` / `_panMove` / `_panNoop` / `_panRender` / `_panEnd`）下沉成
`heatmap_pan.js` —— 与既有的 `heatmap_hover.js` / `heatmap_roll.js` 同一模式。
已写进 `README §9 工程余量`。

## 服务状态（2026-09-17 08:0x–08:4x EDT 实测）

- `:8060` 后端**在跑** —— 本轮全部 Playwright 探针（roll ×2 / feedback / pan ×4 /
  skew）+ 在线契约检查全部连上
- `:4002` IB Gateway **在跑**
- 重启后端：`venv/Scripts/python.exe run.py`

## 已验证 / 未验证

**已验证**
- `run.py --check` 16/16
- `check_web_contract.py` 离线 + 在线 + `--selftest` 全通过
- `tmp/_probe_heatmap_roll.js` 两模式：prod 44/0 · noroll 39/0（均 RC=0），
  **关键断言判定相反**（真机 + 真等新列到达）
- 契约检查器变异：摘掉 `bindButton` 分支 ⇒ 自检 `exit 1`
- 回归：`_probe_feedback.js prod` 49/0 · pan_drag on/off 均 PASS ·
  pan_guards PASS · pan_reset PASS · skew_drag 26/0
- 布局实测：`metaClipped: false`、无溢出、三态类名正确
- 三态截图 + 面板头放大图肉眼复核

**未验证 / 未做**
- `lagCols > 0` 只有**单元断言**覆盖，没有真机跑过（默认 0）
- 像素级复核、真实物理鼠标验证、触屏（E1）
- 探针在 `tmp/` **无回归保护**（按 KAI 明令不建常驻检查器）

## 设计取舍与已否决的选项（**理由留在这里，别在别处复述**）

1. **跟随态存布尔位，不现算。** 现算做不到：列一追加任何窗口的右缘都不再贴最新列，
   "拖回去 5 列"与"过了 5 列"无法区分。**否决**"用 `lag > 0` 当跟随判据"。
2. **速度 = 数据驱动，不插值。** **否决**"定时每 N 毫秒滚一列"与"平滑动画"：
   一次 `setOption` p50 27.4ms，插到 60fps 需要 16.7ms 一次，做不到。
3. **用户指令不受自动化开关管。** 「回到最新」走 `snap()`，不看 `xRoll.enabled`。
   **否决**"关掉功能就连按钮一起废掉" —— 那会让按钮亮着却点了没用（静默无操作）。
4. **方向只向前。** **否决**"自动往回走"（会让"它自己退回去了"成为常态）。
5. **全宽不滚。** 全宽天然含最新列，滚是多余状态。**否决**"全宽也维护一个滚动窗口"。
6. **拖动期间自动滚动必须让位**（`_panStart` 立刻 `takeOver`）。
   **否决**"两者并存" —— 会互相拉扯，症状是"拖到一半自己被拽回右边"，且只在
   400ms 边界上偶发。
7. **徽标不报总数**（「自动滚动 a–b」而不是「a–b/N」）：总数已在 meta 的
   「× N 桶」里，写两处是重复真相；而徽标一宽就把 meta 挤到省略号。

## 本轮踩的坑

1. **⚠️ 自动滚动把"拖动方向"的含义改了，我一度以为改坏了拖动。**
   跟随态下右缘**就在最新列** ⇒ **向左拖**（朝更新的方向）被 `clampCols`
   **原地夹住** —— 那是**正确**的边界行为（不能越过最新列）。
   三个老探针（`_probe_pan_drag` / `_probe_pan_guards` / `_probe_pan_reset`）
   全报 FAIL 就是拖错了方向。⇒ 三个探针改向（`DX: -60 → +60` 等）并各留注释。
2. **诊断先问状态，别猜。** `tmp/_diag_pan_state.js` 一次就定位：mousedown 后
   `_pan` 建立了、`takeOver()` 也生效了，但 mousemove 后 `_pan.x` 没变 ⇒
   问题在"窗口已在最新列、拖左被夹住"，而不是"事件没到"。
3. **404 是噪声**：`favicon.ico` 必得 404，且 Playwright 的 `response` 事件
   **不报它**（只有 console 报）⇒ 只看响应状态会漏、只看 console 会误报。
   探针里按项目既有约定显式过滤。
4. **布局回归是自己引入的**：加第二个按钮后 `metaClipped` 变 true（差 17px）。
   面板头的 meta 是 `flex:1`，**右缘由后面几个元素决定** ⇒ 徽标一宽就挤它。
5. **契约检查器的覆盖缺口**：`_ID_CALL` 原只认 `el/setText/setClass` ⇒
   `bindButton("…")` 与 `ViewChips.*("…")` 的 id 不在覆盖内。已补并做变异验证。
