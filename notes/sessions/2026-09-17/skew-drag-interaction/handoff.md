TASK-ID: skew-drag-interaction
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec 变更（KAI 直接指令）

# Handoff — Skew 图交互改版：删滚轮、改按住拖动

## 一句话

Skew 图**删掉滚轮缩放**，改成三种按住拖动：**左 / 右 Y 轴区上下拖 = 只缩那一侧纵轴**、
**底部 X 轴区左右拖 = 缩 / 放时间窗**、**网格内按住拖 = 自由平移**；
双击复位三条轴。三种手势**互不冲突**（归属在按下那一刻按位置定死，三个开关彼此独立）。

## 需求与边界

- KAI 原话：*"在 skew 图（偏斜图）中移除现有的滚轮缩放功能。改为以下交互方式：
  当鼠标左键按住图表左侧或右侧的 Y 轴区域时，通过上下移动鼠标实现 Y 轴缩放，
  且左右两侧的 Y 轴都需支持该缩放操作。此外，在 skew 图上按住鼠标左键拖动时，
  应能自由平移（拖拽）该 skew 图。请实现上述交互调整并确保两侧 Y 轴缩放与图表拖拽互不冲突。"*
- KAI 三处补充裁定（AskUserQuestion）：网格内横向拖 → **也要平移时间窗**；
  轴区拖 → **拖哪侧只缩哪侧**；时间窗来源 → **底部横轴区拖动缩放**。
- **只改交互层**：不动后端、不动帧字段、不改 `filterMode: "none"` 语义。
- **不给 Skew 图加滚轮**（与热力图相反）：滚轮在本图被整条删除。

STARTUP-PROOF: N/A:本轮直接进入实现，改动前未落 `startup.md`。
改动前的行为由三模式对照等价复现（`SWATCH_MODE=nozoom|nopan` 只翻一个开关）。

CHANGED-PATHS
- web/skew_zoom.js（**重写**；399 行。滚轮监听删除；新增 `_region` 归属判定 →
  已下沉 `skew_helpers.js::regionOf`；三种手势 `_pan` / `_zoomY` / `_zoomX`；
  `view()` 越界改"先夹后复位"并回报 `clamped`）
- web/skew_helpers.js（226 → 348 行：新增 `gridRect` / `regionOf` / `valueAt` /
  `axisExtents` / `nearRange` / `nearWindow` 纯函数，以及手势配置访问器
  `dragCfg` / `zoomCfg` / `panCfg` / `zoomLimits`）
- web/skew_option.js（156 行：新增 `buildDataZoom(patch)`，自带手势
  `zoomOnMouseWheel` / `moveOnMouseWheel` / `moveOnMouseMove` **全关**；
  `buildFullOption` 签名 `count` → `view`）
- web/skew.js（290 → 310 行：`_yRange(view)` 收可见窗口；新增 `_view(count)` 与
  `resetZoom()`；`_readout(view)` 增报时间窗）
- web/config.js（252 → 270 行：`skew.zoom` 删滚轮语义、加 `stepPx` / `minCols`；
  新增 `skew.drag.throttleMs` 与 `skew.pan.enabled`）
- web/index.html（Skew 提示改写：删滚轮措辞，改为三种拖动 + 双击复位）
- web/app_render.js（`writeSkewMeta` 增报时间窗「时间窗 a–b/N 列」/「全宽」）
- web/app_periods.js / web/app_sessions.js（切周期 / 换时段时调 `skewPanel.resetZoom()`）
- tmp/_probe_skew_drag.js（主判据：三模式，同一份代码只翻一个开关）
- tmp/_diag_skew_xzoom.js（定位用：底部轴区拖动为何不生效）
- tmp/_diag_cols_drift.js（定位用：证伪"列数帧间抖动"这个假设）

COMMAND-EVIDENCE

1. **非空转对照**（`tmp/_probe_skew_drag.js`，真机 Playwright + 真实帧）：
   - **prod** ⇒ `PASS 26 / FAIL 0`，`RC=0`
   - **nozoom**（只翻 `skew.zoom.enabled=false`）⇒ `PASS 24 / FAIL 0`，`RC=0`
     —— 轴区拖动与底部轴区拖动**零变化**；而网格内垂直平移**照常生效**（开关独立）
   - **nopan**（只翻 `skew.pan.enabled=false`）⇒ `PASS 25 / FAIL 0`，`RC=0`
     —— 网格内拖动**零变化**；而三种轴区拖动**照常生效**
   - 三次都先断言"开关真的翻到位了"（读 `SWATCH_CONFIG` 实际值），
     否则"零变化"可能是配置没生效而非代码正确
2. **滚轮确已移除**（三模式都跑）⇒ 网格内滚轮 6 格后 `lock0/lock1/xWin` 全不变
3. **归属互不重叠**（prod）⇒ 四个落点分别判为 `y0 / y1 / x / pan`，
   由纯函数 `SKEW.regionOf()` 直接问出，不靠"试了才知道"
4. **两侧各自独立**（prod）⇒
   左轴区上拖：`25ΔSkew` 跨度 `5.231 → 3.439`，`lock1 = null`、`xWin = null`
   右轴区上拖：`IV` 跨度 `6.000 → 3.945`，`lock0 = null`
5. **时间窗**（prod）⇒ 底部轴区右拖：`656 列 → 214 列（161–374）`，
   `dataZoom 0.0–100.0 → 24.4–56.9`；宽度轨迹 `[545,451,375,312,258,214]`
   逐级收窄、不反弹（累计缩到 39%）
6. **平移**（prod）⇒ 网格内水平拖：窗口 `[160,373] → [204,417]`；
   网格内垂直拖：两条纵轴中心各移 `2.227 / 2.547`，**跨度不变**（`5.247 → 5.247`）
7. **纯水平拖不锁纵轴**（prod）⇒ `lock0/lock1` 仍为 `null`
8. **全宽时不凭空长窗**（prod）⇒ `xWin` 仍为 `null`（横轴继续跟随最新列）
9. **跨帧不被重建打断**（prod）⇒ 6 步拖拽、每步间隔 450ms（> 一帧 400ms），
   量程逐级在变 `4.893 → 4.563 → 4.255 → 3.967 → 3.700 → 3.450`；
   松手后保持落地值
10. `./venv/Scripts/python.exe run.py --check` ⇒ **16/16 全通过**（含 `[1]` 行数门禁）
11. `./venv/Scripts/python.exe tools/check_web_contract.py --offline` ⇒ 全通过
12. `./venv/Scripts/python.exe tools/check_web_contract.py`（**在线**）⇒
    `[3]` 前端声明读取 59 条路径后端全部在发，全通过

VALIDATION-SUMMARY
- `tmp/_probe_skew_drag.js`（prod）→ `PASS 26 / FAIL 0`，`RC=0`
- `tmp/_probe_skew_drag.js`（`SWATCH_MODE=nozoom`）→ `PASS 24 / FAIL 0`，`RC=0`
- `tmp/_probe_skew_drag.js`（`SWATCH_MODE=nopan`）→ `PASS 25 / FAIL 0`，`RC=0`
- `./venv/Scripts/python.exe run.py --check` → `16/16`，`RC=0`
- `./venv/Scripts/python.exe tools/check_web_contract.py --offline` → `RC=0`
- `./venv/Scripts/python.exe tools/check_web_contract.py`（在线）→ `RC=0`
- 非空转证据 = 第 1 条（同一份代码，只翻一个开关 ⇒ 相反判定）

NOTES-PATHS
- notes/sessions/2026-09-17/skew-drag-interaction/handoff.md（本文件）
- notes/sessions/2026-09-17/skew-drag-interaction/project_state.md
- notes/analysis/2026-09-17-main-chart-interaction-audit.md（本轮同会话产出：
  主流产品主图交互逻辑分析 + 本项目两主图交互缺陷诊断）
- notes/context/open_tasks.md（新增本轮 Active 块）
- .workbuddy-ai/memory/2026-09-17.md（日志追加）

## 本轮查实并修掉的两条**自己引入**的缺陷

1. **`skew.js::_count` 被写成窗口列数** ⇒ `_cols` 逐帧**自我折叠**。
   `_applyZoom()` 拿 `_count` 去 `setCols()`，而 `_count` 被赋成了 `view.count`
   （窗口列数）⇒ 拖一次窗口 → 下一帧 `_cols` = 窗口宽 → 再拖按这个小列数算窗口
   → 再下一帧更小。**实测：654 列被折成 4 列**（`tmp/_probe_skew_drag.js` 首次跑
   报出"时间窗 654 列 → 4 列"）。已改为 `count`（总列数）。
   探针已补两条断言守着：**窗口宽度 ≥ `minCols`**、**宽度逐级收窄不反弹**。
2. **越界一律复位太破坏性** ⇒ 改为**先夹、后复位**（`skew_zoom.js::view()`）。
   能夹回范围就夹（窗口活着、只被裁到边界），夹完真没宽度了才复位；
   两条路都经 `_view()` 打 `console.warn`，都不是静默的。
   列数的**语义**变化（切周期 / 换时段）由调用方显式 `resetZoom()`，不靠这条兜底。

## 已证伪的假设（不要再写回注释）

- ❌ **"`_cols` 会帧间抖动（638 → 555 → 638），来源是 Skew 序列对齐后比热力图列数短"**
  —— 这是本轮**错误归因**。那个 555 就是缺陷 1 的产物（窗口列数被当成总列数），
  不是数据层现象。`tmp/_diag_cols_drift.js` 在**没有拖动**时 20s / 50ms 采样
  只看到 `638 → 639`（单调 +1，无抖动）。相关注释已改正。

OPEN-RISKS
- **探针停在 `tmp/`，无回归保护**（按 KAI 2026-09-17 明令"不额外搭检查/校验模块"）。
  代价：日后改 `web/skew_zoom.js` 的拖拽段不会被自动跑到。要纳入 `tools/` 需先申请。
- **未做像素级 / 肉眼复核** —— 判据读的是 ECharts `scale.getExtent()`、
  `dataZoom` 百分比与面板 `_xWin`，不是"屏幕上的窗口确实跟着指针走"；
  `throttleMs: 100` 的**手感**未看。
- **未用真实物理鼠标验证** —— 全是 Playwright 合成事件，只证明事件语义一致，
  不证明手感一致。
- **触屏 / 触控板未接** —— 全项目无 `touch*` 监听；pinch、长按、阻止页面滚动均未实现。
- **`skew.zoom.minSpan/maxSpan` 两条轴共用一组** —— 左轴自然量程小（实测约 5.2），
  极端缩放下会先触底，"同步"在那一档名不副实。**属设计取舍，未改，待 KAI 定。**
- **无复位按钮 / 无快捷键 / 无游标语义** —— 双击是唯一复位路径。
  这一批属交互体验缺口，已在
  `notes/analysis/2026-09-17-main-chart-interaction-audit.md` 逐条编号（C1 / C4 / D1 / B1）。
