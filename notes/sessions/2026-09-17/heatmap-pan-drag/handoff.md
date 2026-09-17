TASK-ID: heatmap-pan-drag
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec 变更（KAI 直接指令）

# Handoff — 热力图横轴「左键按住拖拽 = 平移」

## 一句话

热力图（IV 冲量热力图）**左键在网格内按住左右拖拽 = 平移横轴窗口**，与既有滚轮缩放
共用同一个窗口状态 `_xWin`，双击仍复位。ECharts 自带的 `moveOnMouseMove` 平移
**实测不可用**（每 400ms 的 `notMerge` 重建会把它正在拖的状态冲掉），故改为面板自己做。

## 需求与边界

- KAI 原话：*"实现鼠标左键按住后左右拖拽以平移查看热力图不同区域的效果，
  代码中不添加任何注释与说明"*。
- **只加交互，不改数据链**：不动后端、不动帧字段、不动 `dataZoom` 的
  `filterMode: "none"` 语义（仍只改坐标轴范围，不重建 series 数据）。
- 新增代码段**无注释**（按明令）；被改动的**既有**注释按事实改写（旧注释写着
  "拖拽在本图也不平移"，不改就是留一句假话）。

STARTUP-PROOF: N/A:本轮直接进入实现，改动前未落 `startup.md`。
改动前的横轴行为由对照跑等价复现 —— `SWATCH_PAN=off` 只把开关置 false，
其余同一份文件 ⇒ 实测零位移（见 `COMMAND-EVIDENCE` 第 2 条）。

CHANGED-PATHS
- web/config.js（`heatmap.xZoom` 新增 `panOnDrag: true` / `panThrottleMs: 100`）
- web/heatmap.js（250 → 342 行：新增 `clampCols` / `leftHeld` 两个模块级函数、
  `_gridRect` / `_panStart` / `_panMove` / `_panRender` / `_panEnd` 五个原型方法；
  构造函数按开关挂 zr 监听；`resetXZoom` / `clear` 一并清拖拽态）
- web/heatmap_option.js（**值未变**：`moveOnMouseMove` 仍是 `false`；改的只是注释 ——
  旧注释写着"拖拽在本图也不平移"，与新增行为相反，必须改写为"为什么必须为 false"）
- web/index.html（面板头手势提示加"按住左键拖动 = 左右平移"）
- tmp/_probe_pan_drag.js（主判据：开关 on/off 两次跑，相反判定）
- tmp/_probe_pan_guards.js（边界：全宽 / 右键 / 网格外 / 左键网格内 / 双击复位）
- tmp/_probe_pan_reset.js（拖拽途中窗口被复位：不报错、不卡死、可再次拖）
- tmp/_diag_pan_drag.js（定位用：证明自带平移死在 setOption 上）

COMMAND-EVIDENCE

1. **自带 `moveOnMouseMove: true` 为什么不行**（`tmp/_diag_pan_drag.js`，实现前）：
   8 段拖拽里只有**前 3 段**生效，`datazoom` 事件时间戳 `rel 122 / 237 / 344`，
   紧接着 `setOption` 在 `rel 338` ⇒ 拖拽态在**一次重建**上被清掉；
   第二段拖拽（反方向）只剩 **1 段**生效。
2. **非空转对照**（`tmp/_probe_pan_drag.js`）：
   - 生产配置 ⇒ `distinctStarts 8`、`movedDuringDrag true`、`changesAfterFirstFrame 7`、
     落点 `xWin 202-536`（顶到右端后**夹住**，不是穿出去）⇒ `PASS`，`RC=0`
   - `SWATCH_PAN=off`（只把 `panOnDrag` 置 false，其余同文件）⇒ `distinctStarts 1`、
     `movedDuringDrag false`、窗口停在 `18.91–81.09` 不动 ⇒ `PASS`，`RC=0`
   - 两次跑都要求先滚轮缩进去（`zoomedOk=true`，span 62%），否则"平移"本就无处可去
3. **边界条件**（`tmp/_probe_pan_guards.js`）⇒ 8 条判据全 `[ok]`、`RC=0`：
   全宽时拖拽不动 / 右键拖拽不动（左键专属）/ 网格左外侧不动 / 网格右外侧不动 /
   左键网格内 300px ⇒ `19.07→31.40`（`xWin 102-433 → 168-499`，+66 列）/
   双击复位回 `0–100` 且 `xWin=null` / 全程 0 报错
4. **拖拽途中窗口被复位**（`tmp/_probe_pan_reset.js`）⇒ 6 条判据全 `[ok]`、`RC=0`：
   中途复位 ⇒ 立刻回全宽且拖拽态清空；继续移动鼠标**不报错、不平移**；松手后
   `_pan === null`；再次滚轮 + 拖拽仍生效（**无卡死**）；0 报错
5. `run.py --check`（`./venv/Scripts/python.exe`）⇒ **16/16 全通过，`RC=0`**
   （含 `[1]` 行数门禁：`heatmap.js` 342 / `heatmap_option.js` 378 / `config.js` 252）
6. `tools/check_web_contract.py --offline` ⇒ 三项全通过、`RC=0`
   （DOM id 20 个 / CFG 路径 **47 条** —— 新增两个配置键被解析到）
7. `tools/check_web_contract.py`（**在线**，服务 `:8060` PID 7784 在跑）⇒
   `[3]` 前端声明读取 59 条路径后端全部在发、`RC=0`
8. 真机渲染未回归：`tmp/_dom_check.js` ⇒ **PASS 15 / FAIL 0 / NOTE 0**，`RC=0`
   （38 行 / `yAxis 6..29` / 像素复核恰好 24 行在网格内 / Top-N 描边 3 个全在可视区 /
   读数「可见 24/38 档」/ Skew 已渲染 / 0 JS 报错）

VALIDATION-SUMMARY
- `tmp/_probe_pan_drag.js`（on）→ `PASS`，`RC=0`
- `tmp/_probe_pan_drag.js`（`SWATCH_PAN=off`）→ `PASS`（零位移），`RC=0`
- `tmp/_probe_pan_guards.js` → `PASS`（8/8），`RC=0`
- `tmp/_probe_pan_reset.js` → `PASS`（6/6），`RC=0`
- `./venv/Scripts/python.exe run.py --check` → `16/16`，`RC=0`
- `./venv/Scripts/python.exe tools/check_web_contract.py --offline` → `RC=0`
- `./venv/Scripts/python.exe tools/check_web_contract.py`（在线）→ `RC=0`
- `node tmp/_dom_check.js` → `PASS 15 / FAIL 0`，`RC=0`
- 非空转证据 = 第 2 条（同一份代码，只翻一个开关 ⇒ 相反判定）；
  以及实现前的第 1 条（自带平移在同一页面里实测断掉，证明"接了开关就完事"是错的）

NOTES-PATHS
- notes/sessions/2026-09-17/heatmap-pan-drag/handoff.md（本文件）
- notes/sessions/2026-09-17/heatmap-pan-drag/project_state.md
- notes/context/open_tasks.md（新增本轮 Active 块）
- notes/context/handoff.md（索引置顶）
- .workbuddy-ai/memory/2026-09-17.md（日志追加）

OPEN-RISKS
- **三个探针停在 `tmp/`，无回归保护**（按 KAI 2026-09-17 明令"不额外搭检查/校验模块"）。
  日后改 `web/heatmap.js` 的拖拽段不会被任何常驻检查跑到 —— 与
  `tmp/_probe_skew_yzoom.js` 同一处境。要纳入 `tools/` 需先申请。
- **未做像素级 / 肉眼复核**：判据读的是 `dataZoom` 百分比与面板 `_xWin`，
  不是"屏幕上的窗口确实跟着手指走"。手感（`panThrottleMs: 100` 的顿挫感）**未看**。
- **未用真实物理鼠标验证**：三个探针都是 Playwright 合成的
  `mousedown/mousemove/mouseup`。真实设备的拖拽节拍与合成事件不同，
  只能保证"事件语义一致"，不能保证"手感一致"。
- **全宽（未缩放）时拖拽是空操作**（窗口无处可移）。这是设计选择，不是缺陷 ——
  但用户若先拖后缩，会以为功能没生效；提示文字已写在面板头。
- **触屏 / 触控板未处理**：只挂 `mousedown/mousemove/mouseup`，zrender 的 touch
  事件没接。本机是桌面鼠标场景，未做。
- **本会话未提交任何东西**：工作区仍含**另一会话**（`skew-dual-axis-zoom`）的未提交
  改动与未跟踪目录，本轮**未替它背书、也未一并提交**。`notes/context/*` 三个索引文件
  在编辑前**已经是脏的**（含该会话内容），本轮的追加只写自己的事实。

## Closed in session

无 —— 本会话只新增一条功能，未关闭 `notes/context/open_tasks.md` 里的任何既有条目。
