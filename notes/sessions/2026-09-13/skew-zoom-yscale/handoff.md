TASK-ID: skew-zoom-yscale
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（KAI 直接指派）

# Handoff — skew-zoom-yscale

STARTUP-PROOF: N/A:本轮由 KAI 连续三步指派起手（先"首点位置不同 + 无限制 X 轴缩放" →
再"标签与绘图一致性稽核" → 最后"取消最近一小时判定、Y 轴按视口自适应"），
`startup.md` 未在改动前建，按 skill 规定**不回填**。改动前的基线读数落在
`COMMAND-EVIDENCE` 的 `[pre]` 行（引自 `skew-period-consistency` 会话记录），
不在本文件另开一节复述。

## Scope Understanding

- In scope（一个会话内的三段，同一 task-id）：
  1. **首点不顶左边缘** —— Skew X 轴 `boundaryGap: false → true`，与热力图同向；
  2. **X 轴无限制缩放** —— `dataZoom`(inside)，窗口按**列索引**保存，双击复位；
  3. **标签 ↔ 绘图一致性稽核** —— 24 项判据，产出 4 项发现；
  4. **纵轴量程改为按视口自适应** —— 删掉 `skew.scale_policy` / `skew_scale_window_seconds`
     全链路，量程 = 当前可见列内极值 ∪ {0} + 留白。
- Out of scope: 后端 Skew **算法本体**（`features/skew_engine.py`）一行未动；
  **热力图不跟着缩放**（KAI 只要求 skew，见 `project_state.md`）；
  ECharts 版本升级；本轮报出但 KAI 未答复的 #2/#3/#4 三项（见 `OPEN-RISKS`）。

CHANGED-PATHS:
- `web/skew.js` — 332 → **540** 行。docstring 重写"纵轴按眼前这一段自适应"章节并记录
  旧行为的空白屏后果；`boundaryGap: true`；新增 `dataZoom`(inside) + `_zoom`/`_labelInterval`/
  `_series`/`_viewportHook` 字段 + `windowOf()` / `labelInterval()` / `_visibleSpan()` /
  `_captureZoom()` / `_resetZoom()` / `setViewport()` / `_applyViewport()` / `axisRange()` /
  `_readout()` / `setViewportHook()`；`update(series)` 去掉 `policy` 参数、末尾改为
  `return this._readout()`；两条 skew 曲线改用**不同 series name**（`NAME_POS`/`NAME_NEG`）
  + `displayName()` 统一显示名；`legend.formatter` 与 tooltip 都过 `displayName`；
  两个纵轴的刻度 formatter 改读 `CFG.skew.axisDecimals`。
- `web/config.js` — 新增 `skew.xLabelCount: 14`（原硬编码在 skew.js）、`skew.padRatio: 0.18`、
  `skew.axisDecimals: 1`（刻度标签位数，原硬编码 `toFixed(1)`）。
- `web/app.js` — `skewPanel.update(aligned, block.scale_policy)` → `update(aligned)`；
  抽出 `writeSkewMeta(info)` 并注册为 `skewPanel.setViewportHook(writeSkewMeta)`；
  缓存 `lastSkewLatest` 供缩放回调复用。
- `config/serialization.json` — 删 `_skew_scale_comment` + `skew_scale_window_seconds`。
- `serialization/skew_series.py` — `__slots__` 去 `_scale_window_s`；删 `scale_policy` property。
- `serialization/frame_encoder.py` — 帧 `skew` 块删 `scale_policy`。
- `tools/selfcheck_core.py` — `REQUIRED_KEYS["serialization"]` 去 `skew_scale_window_seconds`。
- `tools/check_web_contract.py` — 必需帧键去 `skew.scale_policy` / `skew.scale_policy.window_s`。
- `tools/skew_reference.py` — echarts 替身补 `.on()`/`.getOption()`/`.getZr()`；
  window 段落重写为三档视口；夹具帧删 `scale_policy`。
- `tools/check_skew_alignment.py` — `[C6]` 判据改为视口自适应三档；
  第 4 条变异改为"量程不吃视口（退回全序列极值）"。
- `README.md` — §383–391 改述为"纵轴量程 = 当前视口内极值"，并补"读数与量程同口径"
  与"刻度精度来自 `skew.axisDecimals`"；§579–588 把"两条同名曲线"更正为
  "不同 series name + `legend.formatter` 同名显示"。

VALIDATION-SUMMARY:
- `python run.py --check` → `RC=0`，11/11 全通过（关键配置项 **40**，最长 `.py` 399 行）
- `python tools/check_skew_alignment.py` → `RC=0` 全部通过（`[C6]` 5 项）
- `python tools/check_skew_alignment.py --selftest` → `RC=0`，**4 条变异全抓**
- `python tools/check_web_syntax.py` → `RC=0`（7 个文件）
- 全部 17 个本地工具：**13 个 `RC=0`**；4 个 `RC=1`，原因与基线一致（见 `COMMAND-EVIDENCE`）
- 浏览器稽核（headless Chromium + CDP，探针在工程目录外）→ **26 项全绿、0 失败**
- 非空转：4 条变异（逐条摘掉三项修复）→ **全部被抓**，见 `COMMAND-EVIDENCE`

COMMAND-EVIDENCE:
- `[pre]` 基线（引自 `notes/sessions/2026-09-13/skew-period-consistency/handoff.md`）：
  自检 11/11、本地回归 `rc=0`
- `python run.py --check` → `RC=0`
  ```
  [1] 文件长度  82 个文件全部合规，最长 tools/check_period_aggregation.py = 399 行
  [5] 关键配置项  40 个关键配置项齐备
  结果: 全部通过
  ```
- `python tools/check_skew_alignment.py` → `RC=0`，`[C6]` 纵轴量程（随视口）：
  ```
  [ok] 全宽时尖峰 9.0 在可见列内，必须算进量程      上界 10.620
  [ok] 视口移到尖峰之外时，尖峰必须被排除在量程外  上界 0.884
  [ok] 视口只框住尖峰时，量程必须覆盖尖峰          上界 10.620
  [ok] 视口移开后量程显著收窄（12.0×，证明量程确实跟着视口走）  10.620 → 0.884
  ```
- `python tools/check_skew_alignment.py --selftest` → `RC=0`：
  ```
  [ok] 取组内首值而非末值        → 已抓住 [C4]（4 项）
  [ok] aggregate 空转（不聚合）  → 已抓住 [C1]（8 项）
  [ok] alignSkew 漏掉 clipTail 偏移 → 已抓住 [C2]（1 项）
  [ok] 量程不吃视口（退回全序列极值）→ 已抓住 [C6]（2 项）
  ```
- 17 个本地工具逐个跑（`tools/check_*.py` + `smoke_test.py`）：
  `RC=0` 13 个 —— `clock_protocol` / `matrix_codec` / `period_aggregation` / `persistence`(5/5) /
  `reconnect_gap` / `session_grid` / `session_rollover` / `side_flip` / `skew_alignment` /
  `subscription_qualify` / `tick_router` / `web_syntax`(7 文件) / `smoke_test`。
  `RC=1` 4 个，**与基线一致，非本次引入**：
  `page_render`（页面不是本项目面板）、`reconnect_flow`（`ModuleNotFoundError: ib_async`）、
  `web_contract`（`ModuleNotFoundError: aiohttp`）、`ws_compression`（`ConnectionRefusedError`
  → 8060 无服务）。
- 浏览器稽核 I1（原 #1「缩放与量程不联动」）：
  改前 视口 0–20 列量程 `[-0.18, 0.84]`、**21/21 点越界**；
  改后 量程 `[-1.55, 10.17]`、**越界 0/21**。
- 浏览器稽核 26 项（`~/.workbuddy-ai/tmp/skew_label_audit.mjs`）→ **全绿**。三项修复
  各自的判据：
  ```
  [ok] C2 图例上有两条 25Δ Skew（暖 + 冷，显示名归一后）  ⇒ 2 条
  [ok] C3 图例色板 == 实际曲线颜色集合  图例 ["#ff5a5a","#4ea8ff"] vs 曲线 同
  [ok] C4 图例带里暖冷两色都出现（图例不再是半张色板）  图例带 暖 39px / 冷 12px
  [ok] E1 纵轴刻度小数位 == CFG.skew.axisDecimals（左右两个纵轴都是）  左 1.2 / 右 1.2
  [ok] E2 变异：axisDecimals 改 3 ⇒ 刻度变 3 位（证明 E1 真读配置，非恒真）  1.235
  [ok] G4 meta 的 points 计数随缩放收窄  meta points=21，可见列=21
  [ok] G5 缩放后面板回调宿主（meta 才会跟着收窄，不必等下一帧）  hook points=21 cols=21
  [ok] H2 曲线双色时图例带也双色（在负值夹具上复核 #2 的修复）  暖 39px / 冷 12px
  [ok] H3 图例 2 条 25Δ Skew == 实际曲线 2 色（图例色板完整）
  ```
- **非空转（摘掉修复必须红）** —— 逐条变异、跑完自动还原：

  | 变异 | 抓住的判据 |
  |---|---|
  | `#2` 冷色段改回同名 | C2 / C3 / C4 / H2 / H3（**5 项**） |
  | `#3` 刻度改回硬编码 `toFixed(2)` | E1 / E2（**2 项**） |
  | `#4a` 读数退回全序列 | G4 / G5（**2 项**） |
  | `#4b` 去掉视口回调 | G5（**1 项**） |

  还原后基线复跑：**26 项全绿**（脚本 `~/.workbuddy-ai/tmp/falsify_skew_fixes.py`）。

NOTES-PATHS:
- `notes/sessions/2026-09-13/skew-zoom-yscale/handoff.md`（本文件）
- `notes/sessions/2026-09-13/skew-zoom-yscale/project_state.md`
- `notes/context/handoff.md`（index 指向本会话）
- `notes/context/open_tasks.md`、`notes/context/project_state.md`（清掉已删除的
  `skew_scale_window_seconds` 待办，登记 web 门禁缺口）
- `.workbuddy-ai/memory/MEMORY.md`（修 3 处与代码不符的旧值）、`memory/2026-09-13.md`（当日日志）

## Closed in session

- **首点不顶左边缘**（`boundaryGap: true`）—— 实测偏移 2.25px = 0.50 带宽；变异改回 `false` → 0.00px。
- **X 轴无限制缩放** —— 可缩到单列；连打 50 帧 `_zoom` 一字未变（扛住 `notMerge` 全量重画）；
  tail 窗口随列数增长跟随、非 tail 冻结。
- **纵轴量程改为按视口自适应** —— `scale_policy` / `skew_scale_window_seconds` **全链路删除、无兼容分支**；
  `[C6]` 三档视口 + 12.0× 收窄倍率；`--selftest` 第 4 条变异可抓。
- **稽核产出的 4 项发现全部闭环**：#1 随"量程按视口"修掉，#2/#3/#4 见下。
- **#2 图例色板补全**（KAI 选定"补一条冷色同名条目"）—— 两条 skew 曲线改用
  **不同 series name**，`legend.formatter` + `displayName()` 统一显示成同名；
  图例上因此出现两条 `25Δ Skew`（一暖一冷），点选各自独立。
- **#3 刻度精度收进配置** —— 新增 `web/config.js::skew.axisDecimals`（值 1），
  两个纵轴的刻度 formatter 都改读它，硬编码 `toFixed(1)` 清零。
- **#4 读数随视口收窄（硬切，不兼容原逻辑）** —— `_readout()` 按**可见列**算
  `points`/`cols`，旧的"按全序列计数"直接删除；新增 `setViewportHook`，
  缩放时面板回调宿主立刻重写 meta（缩放不经过 `update()`，没有回调读数会停在
  上一帧的全量数字）。
- **`MEMORY.md` 三处静默错值**：`heatmap_max_buckets` 780 → **2370**；
  `maxColumns` 400 → **2370**；"行数最长 `ibkr_gateway.py` 360/400" → 实为
  `tools/check_period_aggregation.py` 399。并把 `MEMORY.md` 从 8197 压回 **7985**（≤8000）。

OPEN-RISKS:
- **门禁缺口（本次新发现）**：`[1]` 文件长度只扫 `.py`（`iter_py_files()` 用
  `NON_SOURCE_DIRS` 排除 `web`），而 `web/` 现有 **3 个 JS 超 400 行**
  （`app.js` 524 / `skew.js` 540 / `period.js` 490）。`run.py --check` 报
  "82 个文件全部合规"对这 3 个**无覆盖** —— 是**门禁缺口**，不是合规。
  是否把 `web/*.js` 纳入 [1] **待 KAI 定**。
- **三项修复的判据只在一次性探针里** —— `#2`/`#3`/`#4` 现由工程目录之外的
  `~/.workbuddy-ai/tmp/skew_label_audit.mjs` 守着，**没有常驻回归**。
  `tools/skew_reference.py` 已有 node 驱动基础设施，落成
  `tools/check_skew_viewport.py` 成本低。**待 KAI 定**（属"重构现有工具"，
  未获指令不擅自动）。
- **跨面板像素对齐仍差 ≈7.9px**（skew 首点 vs 热力图首列中心），根因是两块图 `grid`
  内边距不同（skew 58/62，heatmap 66/84，后者右侧要给色标条留位）。**改动前就存在**。
- **既有缺陷（非本次引入）**：`setOption(..., {notMerge:true})` 每帧重建组件，把**图例开关冲掉**
  （实测 `legendToggleSelect("ATM IV")` → `{"ATM IV":false}`，再走一帧 → `{}` 复位）。
- **本轮全部改动未提交**（11 个产品文件 + 3 个 `notes/context` 记录 + 本会话目录）。
- **真实链路渲染仍未验证**（周日 fail-closed）—— 由 KAI 手动在 GTH 时段验收，不设自动任务。
