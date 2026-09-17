# Open Tasks

Archive: notes/context/archive/open_tasks_2026-09.md

## Active —— 提交推送 + 引用存储修复（`commit-and-push`，2026-09-17 完成）

会话：`notes/sessions/2026-09-17/commit-and-push/`

- [x] **[高] 五轮改动提交并推送** —— `ab853d3` `feat(web)`（19 文件 / +2151 −346）+
  `21293a1` `docs(notes)`（15 文件）；`git status --porcelain` = **0**；
  本地 `HEAD` = 远端 `ls-remote` = 本地 `origin/main`。
  **五轮合并为一个提交**（`web/index.html` / `web/config.js` 被五轮共同改动；
  中间态 `heatmap.js` 会 import 尚未入库的 `heatmap_roll.js` ⇒ 拆出来的中间提交
  **跑不起来**），沿用 `0d30943` / `53da940` 先例。
- [x] **[高] 陈旧远端跟踪引用已修** —— `origin/main` 被一份缺 `# pack-refs with:` 头、
  mtime 2026-09-14 的 66 字节 `packed-refs` 钉在 `6828e3a` ⇒ `git status` 谎报 `[ahead 23]`。
  用**标准命令** `git pack-refs --all` 修复（**非**手工改 `.git`）；fetch 复测不复现。
- [ ] **[高] ⚠️ 根因未定论：git 建不了 `.git/refs/` 下的二级子目录** ——
  `refs/remotes/zzz/`、`refs/tags/yyy/` 全失败，而一层 `refs/remotes/aaa` 与
  新建一级目录 `refs/xyz/` 成功；bash 的 `mkdir -p` 却能建。
  `git update-ref` **RC=0 但文件不生成**；`git fetch` 会把整个 `refs/remotes/origin/`
  **删掉**。已排除权限（`icacls` 两目录 ACE 逐条相同）与 junction（`fsutil` 否）。
  **未在沙箱外复跑** ⇒ 无法排除是运行环境沙箱所致。
  ⚠️ **已确认会复现**（`3c6d5ad` 推送后当场复现：`origin/main` 回落到 `21293a1`、
  `refs/remotes/origin/` 变成空目录）⇒ **本环境里每次 push/fetch 都会让跟踪引用陈旧**；
  `pack-refs` 只是"把当前值改对"，**不是根治**。修复命令：
  `git pack-refs --all`（标准命令）或手工建目录后直写松散引用。
- [ ] **[中] ⚠️ 提交 ≠ KAI 逐轮验收** —— 五轮改动均为各会话自证，KAI 未逐轮复核。
- [ ] **[中] `notes/analysis/` 归属仍待 KAI 裁** —— 本次提交只是**保全**证据，
  不等于把它定为永久库成员（按"答不出类别的不进永久库"纪律）。
- [ ] **[低] ⚠️ `notes/context/*` 三件套在堆积历史**（`handoff.md` 已叠 5 段会话），
  与 `notes-session-records` 要求的 "latest-state-only" 不符 —— **未清理**。
- [ ] **[低] 候选新条目待 KAI 裁** —— "git 建不了 `.git/refs/` 二级子目录 ⇒ 跟踪引用
  静默陈旧"属**静默错值**类，按纪律候选进 `notes/memory/QUICKREF.md`；
  但 KAI 明令**清单只减不增 / 禁止自行追加** ⇒ **故未落清单，待裁定**。

---

## Active —— 热力图横轴「自动滚动」(auto roll)（2026-09-17 起）

会话：`notes/sessions/2026-09-17/heatmap-auto-roll/`

- [x] **[高] auto roll 落地 —— 2026-09-17 08:4x 完成。**
  **触发**：`heatmap.xRoll.enabled` ∧ 有窗口 ∧ 处于跟随态（**全宽不需要滚**）。
  **方向**：只有时间正方向（永不自动往回走）。
  **速度**：数据驱动不插值 —— 每帧把右缘移到 `cols-1-lagCols`，
  即"前进量 = 该帧新增列数"；`lagCols` 是唯一调节量（默认 0）。
  新增 `web/heatmap_roll.js`（策略层）；面板头新增「回到最新」按钮
  （**保住缩放跨度**，与「复位」分工不同）。
- [x] **[高] 非空转对照已做** —— 同一份 `web/*.js`、只翻一处配置：
  `tmp/_probe_heatmap_roll.js` prod ⇒ `44/0`（RC=0）· noroll ⇒ `39/0`（RC=0）。
  **关键判定相反**：prod「新列到达 ⇒ 窗口前进 Δto=1 == Δcols=1」vs
  noroll「新列到达 ⇒ 窗口原地不动 dTo=0」。集成部分是**真机 + 真等新列到达**
  （切最细 30 秒档，等 `cols` 真增）。
- [x] **[高] 契约检查器 id 覆盖缺口已补** —— `_ID_CALL` 原只认
  `el/setText/setClass`，`bindButton("…")` 与 `ViewChips.*("…")` 的 id 完全不在
  覆盖内（打错字就静默失效）。已补两分支（引用 20 → 27），`--selftest` 扩成
  三条取法各注入一个假 id。**变异验证**：摘掉 `bindButton` ⇒ 自检 `exit 1`。
- [x] **[中] 布局回归已修** —— 加第二个按钮后 `metaClipped` 变 true（差 17px）；
  徽标文案压紧（不报总数，总数已在 meta 的「× N 桶」里）+ 回退加长的提示行
  ⇒ chip 153 → 102px、`metaClipped: false`。
- [ ] **[高] ⚠️ `web/heatmap.js` 397 行（上限 400，只剩 3 行）** ——
  下次动它几乎必然要先拆分。可拆的缝：左键拖拽手势整块
  （`_panStart` / `_panMove` / `_panNoop` / `_panRender` / `_panEnd`）下沉成
  `heatmap_pan.js`（按 `heatmap_hover.js` / `heatmap_roll.js` 的既有模式）。
  `web/style.css` 395 行同样贴上限。已写进 `README §9 工程余量`。
- [ ] **[中] ⚠️ 拖动方向被自动滚动耦合** —— 跟随态下右缘就在最新列，
  所以**向左拖是空操作**（被 `clampCols` 夹住）。这是**正确**行为，但老探针与
  新读者都会踩（三个 pan 探针已各留注释）。
- [ ] **[中] `lagCols > 0` 只有单元断言覆盖**，没有真机跑过（默认 0）。
- [ ] **[中] 探针停在 `tmp/`，无回归保护** —— 按 KAI 明令留在 `tmp/`。
- [ ] **[低] 未做像素级复核、真实物理鼠标验证、触屏未接**。

---

## Active —— 五项交互缺陷修复（2026-09-17 起，KAI 直接点名 2 / 4 / 5 / 6 / 7）

会话：`notes/sessions/2026-09-17/interaction-feedback-5fix/`

- [x] **[高] 五项全部修完（2026-09-17 07:5x EDT）。**
  2→A2 全宽横拖弹瞬时徽标（**语义不变**，全宽仍不生成窗口）·
  4→B2 锁定侧纵轴刻度/轴线/轴名变警示色 `#ffb020` + 锁定徽标 ·
  5→C1/C4 两图复位按钮（脏态点亮）+ `Esc`/`R` 快捷键 ·
  6→C2/D1 Skew 四手势区游标语义 + 轴区高亮框 ·
  7→D2/D3 热力图十字线 + 命中格描边 + 提示框跨重建存活。
  新增 `web/heatmap_hover.js` / `skew_regions.js` / `view_chips.js`；另改 9 个 `web/` 文件。
- [x] **[高] 非空转对照已做** —— 同一份 `web/*.js`、只翻一处配置：
  `tmp/_probe_feedback.js` prod ⇒ `49/0`（RC=0）· nofb ⇒ `43/0` · nohover ⇒ `41/0` ·
  nohint ⇒ `48/0`。**断言数故意不同**（关掉某功能后只验"它确实不出现"）⇒ 判定相反。
  `run.py --check` **16/16**（最终字节上重跑）；`check_web_contract` 离线 + 在线全通过。
- [x] **[高] 探针模式守卫已补** —— 模式原本只读环境变量，按位置参数传会**静默退回 prod**
  ⇒ 三次"单开关翻转"差点跑成同一份代码（假绿）。现已加守卫：未知模式抛错
  （实测传 `nofbb` 会 `exit 1`）。
- [ ] **[中] ⚠️ A1 热力图纵轴仍不可交互** —— 诊断里**最大的功能缺口**，本轮**没做**
  （需新增一条交互通道，成本中等）。见
  `notes/analysis/2026-09-17-main-chart-interaction-audit.md` §2.1 维度 A。
- [ ] **[中] 三个探针停在 `tmp/`，无回归保护** —— 按 KAI 明令留在 `tmp/`。
- [ ] **[中] `web/style.css` 与 `web/skew_zoom.js` 都到 **394** 行（上限 400）** ——
  下一次动这两个文件几乎必然要先拆分。可拆的缝：`skew_zoom.js` 手势状态机 / 视图状态导出；
  `style.css` 按面板分文件。
- [ ] **[低] 未做像素级复核；未用真实物理鼠标验证；触屏未接** ——
  与热力图那轮同一批缺口。
- [ ] **[低] 第 2 项的提示是瞬时徽标，不是图形引导** —— 若 KAI 要更重的引导，
  需另设计（本轮按"最小改动、只消除误判"处理）。

---

## Active —— Skew 图交互改版：删滚轮、改按住拖动（2026-09-17 起）

会话：`notes/sessions/2026-09-17/skew-drag-interaction/`

- [x] **[高] Skew 图删滚轮、改三种按住拖动 —— 2026-09-17 11:1x 完成。**
  左 / 右 Y 轴区上下拖 = **只缩那一侧**纵轴；底部 X 轴区左右拖 = 缩 / 放时间窗；
  网格内按住拖 = 自由平移（纵向两条轴一起移、横向挪时间窗）；双击复位三条轴。
  滚轮**整条删除**（三模式探针都验了"滚轮 6 格三条轴一动不动"）。
  新增 `web/skew_zoom.js` 重写 + `skew_helpers.js` 六个纯函数；
  配置 `skew.zoom` 删滚轮语义加 `stepPx`/`minCols`，新增 `skew.drag` / `skew.pan`。
- [x] **[高] 顺带查实并修掉两条本轮**自己引入**的缺陷**：
  ① `skew.js::_count` 被赋成窗口列数（应为总列数）⇒ `_cols` **逐帧自我折叠**，
  实测 654 列被折成 4 列。② `view()` 越界一律复位太破坏性 ⇒ 改**先夹后复位**。
  探针已补两条断言守着：窗口宽度 ≥ `minCols`、宽度逐级收窄不反弹。
- [x] **[中] 非空转对照已做** —— 同一份代码、只翻一个开关：
  `tmp/_probe_skew_drag.js` prod ⇒ `PASS 26 / FAIL 0`；`SWATCH_MODE=nozoom` ⇒
  `PASS 24 / FAIL 0`（轴区拖动零变化、但网格垂直平移照常）；`SWATCH_MODE=nopan` ⇒
  `PASS 25 / FAIL 0`（网格拖动零变化、但三种轴区拖动照常）。三次都先断言
  "开关真的翻到位了"。`run.py --check` **16/16**；`check_web_contract` 离线 + 在线全通过。
- [ ] **[中] 探针停在 `tmp/`，无回归保护** —— 按 KAI 明令留在 `tmp/`。
- [x] ~~**[中] `skew_zoom.js` 已 **399** 行，距上限只剩 1 行**~~ ——
  2026-09-17 五项修复那轮把 `leftHeld` 迁到 `skew_helpers.js`，现 **394** 行
  （**结构性压力仍在**，只是没那轮紧；接手见本文件顶部那条）。
- [ ] **[低] 未做像素级 / 肉眼复核；未用真实物理鼠标验证；触屏未接** ——
  与热力图那轮同一批缺口。
- [x] **[中] 交互体验缺口已成体系** —— 见
  `notes/analysis/2026-09-17-main-chart-interaction-audit.md`。
  **2026-09-17 五项修复那轮已闭合其中 5 项**（A2 / B2 / C1 / C2 / D1 / D2 / D3）；
  **只剩 A1（热力图纵轴不可交互）**，已提到本文件顶部 Active 块。

---

## Active —— 热力图左键拖拽平移（2026-09-17 起）

会话：`notes/sessions/2026-09-17/heatmap-pan-drag/`

- [x] **[高] 热力图横轴「左键按住拖拽 = 平移」—— 2026-09-17 05:0x 完成。**
      左键在**网格内**按住左右拖动 = 平移横轴窗口；与既有滚轮缩放**共用同一个
      窗口状态** `_xWin`（列下标），双击仍复位回全宽。新增配置
      `heatmap.xZoom.panOnDrag`（开）与 `panThrottleMs: 100`（重绘节流）。
      **不是**打开 ECharts 自带开关 —— 实测那一条不可用（见下条）。
- [x] **[高] 顺带查实：ECharts 自带 `dataZoom.inside.moveOnMouseMove` 在本面板不可用。**
      根因：它把"正在拖"存在自己的 `RoamController._dragging` 里，而本面板每 400ms
      用 `notMerge` 重建整份 option ⇒ 控制器与状态一起重建。
      实测（`tmp/_diag_pan_drag.js`）：8 段拖拽只有**前 3 段**生效，停点正好落在
      一次 `setOption` 上；反方向拖只剩 1 段。⇒ 改为面板自己做平移。
- [x] **[中] 非空转对照已做** —— 同一份代码、只翻 `panOnDrag` 一个开关：
      `tmp/_probe_pan_drag.js` 生产配置 ⇒ 8 段位移、跨帧后仍继续、落点顶到右端夹住
      （`RC=0`）；`SWATCH_PAN=off` ⇒ **零位移**（`RC=0`）。边界条件
      `tmp/_probe_pan_guards.js` **8/8**（全宽不动 / 右键不动 / 网格外不动 /
      左键网格内动 / 双击复位 / 0 报错）；拖拽中途复位
      `tmp/_probe_pan_reset.js` **6/6**（不报错、不卡死、可再拖）。
      `run.py --check` **16/16 `RC=0`**；`check_web_contract` 离线 + 在线均 `RC=0`；
      真机渲染 `tmp/_dom_check.js` **PASS 15 / FAIL 0**。
- [ ] **[中] 三个拖拽探针停在 `tmp/`，无回归保护** —— 按 KAI 明令
      （"不额外搭检查/校验模块"）留在 `tmp/`。代价：日后改 `web/heatmap.js` 的
      拖拽段不会被自动跑到。要纳入 `tools/` 需先申请。
- [ ] **[低] 未做像素级 / 肉眼复核** —— 判据读的是 `dataZoom` 百分比与面板 `_xWin`，
      不是"屏幕上的窗口确实跟着指针走"；`panThrottleMs: 100` 的**手感**未看。
- [ ] **[低] 未用真实物理鼠标验证** —— 三个探针都是 Playwright 合成事件，
      只证明事件语义一致，不证明手感一致。触屏 / 触控板（zrender touch）**未接**。

---

## Active —— Skew 双纵轴缩放（2026-09-17 起）

会话：`notes/sessions/2026-09-17/skew-dual-axis-zoom/`

- [x] **[高] Skew 图双纵轴纵向缩放 —— 2026-09-17 04:3x 完成。**
      左轴 25Δ Skew 与右轴 IV 同一格滚轮一起缩，X 轴时间范围不动；双击复位两者。
      新增 `web/skew_zoom.js`（交互与锁定态的唯一出口）；配置块
      `skew.yZoom` → `skew.zoom`（`step 1.15` / `minSpan 0.05` / `maxSpan 500` /
      `minCols 8` / `anchorAtPointer`）。
- [x] **[高] 顺带查实并修掉一条老缺陷 —— 2026-09-15 那版纵轴滚轮缩放从未执行过。**
      根因：监听绑在图表容器上，而 zrender 在容器内部另建 viewport root 并在自己的
      wheel 处理里 `stopPropagation()`。实测计数 `zr=1 / 容器=0 / document=0`。
      旧检查器只调 `SKEW` 的纯函数（`grep -rn "wheel" tools/*.py` **0 命中**）
      ⇒ 死绑定一路全绿。现绑在 `chart.getZr()` 上，由真机探针驱动真实滚轮事件守着。
- [x] **[中] 删掉 `skew_helpers.js::FALLBACK_YCFG`** —— 配置的第二份真相，
      配置改名后会**静默**按旧值夹取。改为缺键即抛错。
- [ ] **[中] 两条轴共用一组 `minSpan/maxSpan` ⇒ 下限会先后触底** ——
      左轴自然量程小（实测约 4.4），先夹到 `0.05`；此后继续放大只有右轴在动，
      "同步"在极端缩放下名不副实。**属设计取舍，未改**。
      要严格同步需改成"按比例缩放"而非"按倍率"。**待 KAI 定**。
- [ ] **[中] 探针 `tmp/_probe_skew_yzoom.js` 无回归保护** ——
      按 KAI 明令（"不额外搭检查/校验模块"）留在 `tmp/`。代价：日后改
      `web/skew_zoom.js` 不会被自动跑到。要纳入 `tools/` 需先申请。
- [ ] **[低] 未做浏览器取像素** —— 判据读的是 ECharts 的 extent 与 dataZoom 百分比，
      不是肉眼观感（缩放后的刻度可读性、曲线粗细）。
- [ ] **[低] 未在盘中 RTH 段复验** —— 本轮是 GTH 段（现价基本不动），
      缩放对"移动中的曲线"的观感（是否闪、是否跳）**未观察**。

---

## Active —— 热力图双窗口（2026-09-17 起）

会话：`notes/sessions/2026-09-17/heatmap-two-window/`

- [x] **[高] 真机联调补验 —— 2026-09-17 03:09 已完成（RC=0）**。
      IB Gateway PID 1232（`:4002`）+ 后端 PID 7784（`:8060`）起来后：
      ① `tmp/_dom_check.js` ⇒ **PASS 15 / FAIL 0**（40 行 / `yAxis 8..31` /
      `convertToPixel` 复核恰好 24 行落在网格内 / series 194 点行号全合法 /
      Top-N 描边格 3 个全在可视区内 / 读数「可见 24/40 档」/ Skew 已渲染 / 无 JS 报错）；
      ② `tools/check_web_contract.py` **在线** ⇒ RC=0（载荷 59 条，含新路径）；
      ③ `tmp/_probe_window_sweep.js` ⇒ FAIL 0，宽度恒 24、单调、两端夹边。
      **残留缺口（已缩小）**：窗口**确实随真实现价移动**（现价 7614 ⇒ 区间 `[8..31]`；
      7618 ⇒ `[7..30]`，整体上移一行、现价仍居中），但**单次采样内现价没动**
      ⇒ 「移动**过程中**不闪不空」只有**扫描**证据 + 两次不同稳态的对照，
      **没有"移动途中逐帧观察"的证据**。想彻底钉死：在现价连续穿越行权价的那几十秒里
      连续采样（把 `_probe_window_follow.js` 的 `SWATCH_SAMPLES` 加大即可）。
- [x] **[中] 按新形状重测渲染性能 —— 2026-09-17 03:5x 已测。**
      真机 1680×1000 视口、纵轴 **40 行**、每帧 1554–1581 点、周期 1 分（446 桶），
      探针 `tmp/_probe_render_perf.js` 包 `setOption` 计时 40 帧：
      **min 21.8 / p50 27.4 / p90 35.3 / max 44.6 / avg 28.2 ms**
      ⇒ 最大 44.6ms **远低于 400ms 推送间隔**，不会积压。
      ⚠️ 与 `web/heatmap.js` 头部那组（65.7/159.9/188.1 ms）**不是同一口径**
      （那组是 headless Chrome 153 + SwiftShader、按列数分档、含 WebGL 对照；
      这次是 Playwright Chromium、单周期、只计时 `setOption` 本身），**不可直接比较**。
      两处口径已在 `web/heatmap.js` 头部写清。
- [ ] **[中] 重建 `tools/check_window_tolerance.py`**（白纸重写中被删）。
      窗口那三条不变量目前**只有静态门禁**（`[6]`），行为侧回归缺失。
      见 `QUICKREF.md` 卡 P 与 `RULES.md §6.6`。
- [x] **[低] 清理 `tmp/mut14/` —— 2026-09-17 03:5x 已办。**
      它是 2026-09-15 留下的**整棵源码副本**（2.3 MB / **144 文件**、无 `.git`）。
      办前先确认**全项目无任何东西引用它**（`mut14` 只在两条笔记里出现过），
      再按项目自身惯例（`references/pitfalls.md` 第 14 条：工程内"删除"用 `mv` 不用 `rm`）
      **移出项目**，未删除：
      `tmp/mut14/` → `C:\Users\Lenovo\AppData\Local\Temp\spxw_mut14_20260915`（144 文件已核）。
      ⇒ 移后 `run.py --check` 仍 **16/16**；grep `heatmap_rows_each_side`
      已不再命中 `tmp/mut14/`。**要还原**：`mv` 回 `tmp/mut14` 即可。
      ⚠️ 顺带纠正一条我自己的错误判断：`tmp/` **并没有**被 ripgrep 自动跳过
      （Grep 工具同样会搜到 `tmp/mut14/...`）。所以"用对工具就没污染"是错的；
      真正的排除法是 `glob: "!tmp/mut14/**"`（已验证有效）—— 现在文件已移走，不再需要。
- [ ] **[低] `favicon.ico` 返回 404**：浏览器自动请求，`web/` 下无此文件、
      无任何代码引用 ⇒ 功能无影响，只是控制台留一条红字。放个空 favicon 即可消除。
- [ ] **[低] 客户端硬关时后端打一条未捕获异常**：
      `ERROR asyncio Exception in callback _ProactorBasePipeTransport._call_connection_lost()`
      → `ConnectionResetError [WinError 10054]`。位置在 **asyncio 自己的 proactor 实现**里
      （`_sock.shutdown()`），不是本项目代码；不影响流水线（后续照常出帧）。
      属噪声；若嫌吵可在启动处装一个只吞这一条的 asyncio 异常处理器。
- [x] **[中] `TickStore.refs()` 是否保留"已退订但曾有过 tick"的档 —— 2026-09-17 03:45 已定性：**
      **会保留**（`prune()` 只按时间裁样本、**不删键**，`state/tick_store.py:203`；
      只有 `clear()` 才清，而它只在整会话重置时调）。
      **但不构成用户可见缺陷**，两条理由：
      ① 可视区（现价 ±12）**永远落在当前订阅区之内** ——
      订阅中心 C 与现价差 ≤ `T`=2 档（≥3 就重建），故
      `现价 ± 12 ⊆ C ± 14 ⊂ C ± 20`；所以看得见的 24 行**必然有实时订阅**。
      ② 可能冻住的行只出现在**绘制窗口最外侧**（距现价 ≥18 档），
      比可视区（±12）外扩 6 行以上 ⇒ 用户看不到。
      **实测**：`tmp/_probe_stale_rows.js` 按"每行最后一个非空格所在桶号"判，
      39 行 **0 行落后**（全部落在全局最新桶 448）⇒ 当前无冻住行。
      ⚠️ **真正的守卫就是 `S − V ≥ T`** —— 若有人把 `V` 调大或 `S` 调小到
      `S − V < T`，冻住的行就会**移进可视区**。这条已在 `[6]` 里。

> ⚠️ **本轮实测纠正一条文档错值**：「每帧发 40 行」是**上限不是保证**。
> 当帧行数 = `min(20, 池内≤现价) + min(20, 池内>现价)`，池 = `TickStore.refs()`
> （"至少收到过一个 tick 的合约"，`state/tick_store.py:133` +
> `features/feature_engine.py:243`）。**两种情形不足 40**：
> ① **现价漂移**（常态，订阅窗口锚在上次重建中心、热力图窗口锚在实时现价）
> —— 实测现价 7614 ⇒ 40 行、现价 7618 ⇒ 39 行；
> ② **冷启动** —— 实测约 1 分钟内 33 行。
> 可视 24 行不受影响（`S − V ≥ T` 保证）。已修 `README.md §4` 与
> `config/features.json::_heatmap_window_comment`。


---

## Active —— 重写（2026-09-15 起，**已收尾**）

- [ ] **[高] 按 L0→L8 顺序完成白纸重写**（会话：`rebuild-from-original`）
  - [x] **#8 设计定稿** → `notes/memory/ARCHITECTURE.md`
  - [x] **#9 L0/L1** `config/` + `contracts/` + `core/`（已实测：import 自检 + fail-fast 7/7）
  - [x] **#11 L4** `models/`（原版移植，差分对拍零差异；拆 12 文件；33 常量进 `config/surface.json`）
  - [x] **#10 L3 `state/` + L2 `acquisition/`（`ib_async`）** —— 整目录移植，逐行 diff
        归类确认**零内容改动**（57 条全是层号/措辞）；冒烟 **37/37** + 变异反证
        （`max_iv` 3.0→0.05 ⇒ 4 条 FAIL）；`ib_async` 边界实测 **14 个模块里 3 个拉起**；
        行数门禁全库复扫 **0 违规**（详见 `ARCHITECTURE.md §12`）
  - [x] **#12 L5 `features/`** —— 整目录移植（只改层号引用，脚本化 `tmp/port_features_layer_refs.py`
        全部命中）+ 三个入口约束全部落地：
        ① `features/surface_engine.py`（273 行）把 L3 存储翻译成 `SurfaceInputPort`
        的真形状（**按 reqId 索引的三张平行表**，见下条契约缺陷）；
        ② `residuals` 上限**刻意未做** —— 属 L6 载荷预算决策，现在加就是死配置键；
        ③ `heatmap_engine` 守住"只含已走满的桶"：列取 `0..current-1`，参数改名
        `current → last_done`（漏改即 `NameError`），`skew_engine.series(moment)` 同步过滤。
        实测：冒烟 **PASS 32 / FAIL 0**；变异反证（`last_done = current` + `[:current+1]`）
        ⇒ 失败判据 **0 → 7 条**、**「颜色锁定」变红**（差异格数 21）⇒ 非空转成立；
        行数门禁全库 **61 文件 / 0 违规**。
        ⚠️ 过程中解决一个**结构冲突**（KAI 拍板「只订阅 0 DTE」）：原版曲面层写死
        `num_expiries >= 2`，而本项目只订阅一个到期日 ⇒ SVI 永不拟合且**不抛异常**。
        门槛搬进 `config/surface.json`（`min_expiries: 1`），配置对照实测
        Q1 `fitted=1/1` vs Q2 `fitted=0/1`。
        ⚠️ 另修一个**真契约缺陷**：`contracts/ports.py::SurfaceInputPort` 的 docstring
        形状与消费方代码不符（照错形状写 ⇒ 曲面恒为空且不报错）。
        详见 `ARCHITECTURE.md §13`（含 13.4「判据全绿其实空转」的根因与修法）
  - [x] **#13 L6 `serialization/` + L7 `transport/` + L8 `app/` + `run.py`** ——
        来源 = **旧项目 HEAD** `_ref_spxw_head`（原版 `live-volatility-surface`
        **没有**这三层，只有 `models/` + 单体脚本）。层号改写用通用脚本
        `tmp/port_layer_refs.py`（占位符双阶段 + `tmp/.ported_dirs.json` 防重复跑）：
        `serialization` 31 处 / `transport` 14 处 + 措辞 1 处 / `app` 16 处，
        逐行 diff 确认**零逻辑改动**。
        ⚠️ 补了三处**静默缺口**（旧版 `build()` 是逐字段搬运，而新 `Frame` 多了字段
        ⇒ 漏传不报错，只让字段恒为 `None`）：
        ① `bundle.surface` 没搬 ⇒ 帧里 surface 恒为 `null`；
        ② `Frame` 缺 `skew` 字段（实时点），`build()` 也没搬；
        ③ `skew.latest` 取 `skew_series[-1]` —— 新语义下序列只含已走满的桶
        ⇒ 顶栏读数滞后一整个桶（30 s）。修法：`Frame` 加 `skew` 字段 + 编码器取它。
        实测：`tmp/l6_smoke.py` **39/0**（变异 `surface` ⇒ 7 红、`latest` ⇒ 2 红）；
        `tmp/l8_smoke.py` **30/0**（变异 `session_key` ⇒ 2 红）；
        `l2l3` 37/0 + `l5` 32/0 回归全绿；**全库 71 模块 import 全通**；
        层号一致性核对（模块头 / 带模块名的引用 / 依赖行）**错配 0**；
        行数门禁 **79 文件 / 0 违规**（`pipeline.py` 拆出 `persistence_boot.py`：
        381 + 曲面接线 ≈ 394 → **364 行**）。详见 `ARCHITECTURE.md §14`
  - [x] **#14 `web/` 前端（ECharts）** —— 来源 `_ref_spxw_head/web/`（18 个文件）。
        **改动性质：零改动** —— `git status --short web/` 为空 ⇒ 与 `HEAD`（`bedbf11`）
        **逐字节一致**。本轮 KAI 报的两个缺陷（整点触发 / 颜色锁定）在 `HEAD` 里已修完
        （`bedbf11 fix(web): 周期只出已走满的组 + 论证「桶分组 ≡ 挂钟整点分分组」`）。
        实测：13 个 JS 全部 `node --check` 通过，最大 `period.js` 391 行（< 400）；
        **跨语言端到端对拍 `tmp/web_e2e.py` PASS 34 / FAIL 0**，4 个变异
        （`codec_scale` / `codec_bitmask` / `period_null` / `volumes_agg`）**全部被抓到**；
        四个离线冒烟复跑全绿（`l2l3` 37 / `l5` 32 / `l6` 39 / `l8` 30 = 138 条）。
        详见 `ARCHITECTURE.md §15`。
        ⚠️ **本条原写的「聚合不得有 `g == 1` 恒等短路」是错的，已推翻**：
        `g=1` 时短路路径与聚合路径**数值恒等**（`floor(cols/1) = cols`，元字段换算同样
        恒等），实测 120 格全等、误差 0。原禁令描述的是**修复前状态**（后端含未定稿桶），
        真正保证末列定稿的是**后端**。**`check_grid_contract.py` 不得断言"没有 `g==1`
        短路"** —— 会把正确代码判违规。
        ⚠️ 另发现**第二类空转**：真实帧按绝对桶号索引、夹具只喂最后 7 桶 ⇒ `g=5` 时
        **可比格数 = 0**，"最大误差 0"恒真。修法 = 比较函数报**实际比较格数** +
        聚合语义改用**稠密合成帧**（仍走真实编码器）。
        ⚠️ **`web/matrix_codec.js` 与 `serialization/heatmap_matrix.py` 是成对契约**
        （`enc` / `scale` / `bm` / `i16` / `filled` / `vol_bm` / `vol_i16`），
        改一侧必须改另一侧。`vol_bm`/`vol_i16` 是**可选字段**（`matrix.volumes`
        非空时才发）⇒ 契约检查器**不得当必填**。
        ⚠️ 帧里新增了 `surface` 段，且 **`skew.latest` 语义已变**（取**实时点**
        `frame.skew`，不再是序列末项）—— 前端若要显示曲面残差/顶栏读数，按 §7 契约接。
  - [x] **#15 `tools/` 门禁 + `run.py --check` + 非空转验证** —— **完成，覆盖 16/16**
        （KAI 2026-09-15 明令「**必须重写，禁止移植失败品**」⇒ 全部按新架构重写，
        **未从 `HEAD` 移植**）。详见 `ARCHITECTURE.md §16`。

        ```text
        [1]  文件长度（+余量 < 5 行警告）      [2] 分层（+层表覆盖核对）
        [2b] 反向越界（层不得 import tools/）  [3] 配置 JSON 合法性（含**重复键**）
        [4]  配置注释交叉引用                  [5] 配置键级完整性
        [6]  配置不变量（订阅容量 / 显示窗口 / 窗口容差 / 网格容量 / use_model_greeks）
        [7]  读取点 ↔ 声明键**双向推导**        [8] __slots__ 一致性
        [9]  单一职能                          [9b] 依赖白名单
        [10] 禁止硬编码（含待接线包清单）       [11] 限速桶 5 条不变量
        [12] 时钟协议与裁剪路径                [13] 帧契约一致性 + 活链路
        [14] TickRouter 语义（32 条判据）
        结果: 16/16 项全部通过                                 RC=0
        ```

        **非空转**：`tools/selfcheck.py --selftest` ⇒ **16/16 全部被抓到**
        （RC=0，2m06s），且**先跑未变异的对照（RC=0）**证明红可归因。
        ⚠️ 判据已升级：**不再看"退出码非 0"**，而是要求**目标检查项自己那一段**
        （`^\[\d+b?\]` 定位）出现 `[FAIL]` —— 否则任一无关检查项变红就会让
        "抓住了"的结论变成假绿。三处 docstring 写明理由：**段落标题必须打在
        `run_*_checks()` 里**，只在 `main()` 里打会让 `_section_failed()` 切不出该段
        ⇒ **恒判为"抓住"**（判据恒真 = 空转）。

        **对旧版的六处改进**（重写而非移植）：
        ① `[3]` 补 **JSON 重复键**检测（`json.loads` 静默取最后一个 = 配置版的静默错值，
        必须用 `object_pairs_hook` 才数得出来）；
        ② `[5]` 改为**键级完整性**（空键名 / 空白键名 / null 值），**刻意不重建**
        旧版那份会腐烂的手工 `REQUIRED_KEYS` 清单；
        ③ `[13]` 帧字段清单**从 `dataclasses.fields(Frame)` 派生**，不写手工清单
        —— 旧版那份已腐烂（漏了 `surface`，正是本轮修掉的静默缺口）；
        ④ `[2]` 层表覆盖核对（旧版对未登记的包直接 `continue` ⇒ 新增包时该包的
        跨层 import **一行都不检查**且不报错）；
        ⑤ `--selftest` 判据从"RC 非 0"升级为"**目标检查项自己报了 FAIL**"；
        ⑥ `[12]` 内建**反证**（同一组未来样本改用墙钟裁剪 ⇒ 丢弃 0 条），
        证明前一条判据验的是"注入的时钟"而非"墙钟"。

        ⚠️ **本轮抓到的真缺陷（重写过程中新发现，非移植遗留）**：
        `config/transport.json::bucket_seconds_s` 是**真死键 + 描述不存在机制的注释**
        —— 全工程零读取点，注释却写"推送必须对齐世界时间桶边界"，而 `PushLoop`
        只按固定节奏 + 帧序号变化触发，**从来没有桶对齐逻辑**。该键**在旧项目 `HEAD`
        的 `transport.json` 里根本不存在**（是上一轮移植时凭空补的）。已删键，注释改写为
        "**不对齐是刻意的**（差 ≤ 1 个推送周期 = 400ms，相对 30s 桶 = 1.3%）"。
        ⚠️ 另修 `[7]` 的**覆盖盲区**：`models/surface_params.py::_param_pairs(cfg, key, ...)`
        把键名**当参数转发**给 `loader.get()`，字面量收集器跳过 ⇒ 5 个活键被误报为死键。
        修法 = 新建 `tools/selfcheck_reads.py` 做**两遍 AST 扫描**追踪"键转发器"
        （当轮 5 个假红消失）。⚠️ 读取点**计数随代码变化**，要引用一律实跑 `[7]`，
        **不得抄写** —— 本轮就抄错过一次（`ARCHITECTURE.md` 曾写 176，当时真值 185）。
        ⚠️ `--selftest` 一度报 `[14] 没抓住` —— 查下来是**变异本身写错了**（`return None`
        改成 `continue`，而循环里后续 bid/ask 槽位通常为空 ⇒ 最终仍 `return None`
        ⇒ **行为等价**），不是判据空转。**这两个结论必须分得清。**

        **拆分**（`selfcheck_core.py` 逼近 400 行门禁）：新建 `fixtures.py` /
        `selfcheck_reads.py` / `selfcheck_clock.py` / `selfcheck_router.py` /
        `selfcheck_connectivity.py` / `selfcheck_config.py` /
        `selfcheck_config_invariants.py` / `selfcheck_code.py`。

        **本轮交付证据**（全部用 `venv/Scripts/python.exe`）：
        `run.py --check` **16/16 RC=0** · `selfcheck.py --selftest` **16/16 RC=0** ·
        `l2l3` 37/0 · `l5` 32/0 · `l6` 39/0 · `l8` 30/0 · `web_e2e` 34/0 ·
        `check_web_contract --offline --selftest` RC=0。

        ⚠️ **未做**：`tools/` 下 8 个独立检查器仍**待建**
        （`check_matrix_codec` / `check_grid_contract` / `check_period_aggregation` /
        `check_session_grid` / `check_surface_payload` / `check_reconnect_gap` /
        `check_window_tolerance` / `check_ws_compression` / `ws_probe`），
        状态表见 `README.md §6`。
        ⚠️ **配置注释里已引用其中 6 个**，本轮已把这些引用逐条标注"**待建**"
        （`serialization.json` ×3 处 / `subscription.json` ×1 / `transport.json` ×1）
        —— 在它们建出来之前，那些引用是**设计意图而非既成事实**。
        **（本项曾是 `bucket_seconds_s` 同类问题：注释断言"已有东西守着"，而东西不存在。）**

  - [x] **[中] `README.md` 已重写**（2026-09-15）—— 按 **9 层新架构**（L0 `config`/
        `contracts` … L8 `app`）+ **实际存在的检查器名** + 已知边界，共 10 节
        （快速开始 / 架构 / 目录 / 配置 / 数据流 / 门禁 16 项矩阵 / 回归 /
        仓库纪律 / 已知边界 / 深入阅读）。
        旧版在清空时被删（` D`），**刻意未恢复**：它描述的是 6 层结构与旧检查器名，
        恢复即制造"两份真相"。
        ⚠️ §6 的「独立检查器」表**逐条标了状态**（✅ / ⬜ 待建），并明写警告：
        **配置注释里已引用其中几个（如 `transport.json` 提到 `check_ws_compression`），
        在它们建出来之前，那些引用是设计意图而非既成事实 —— 别把注释当成"已经有东西守着"。**
        ⚠️ 对照：`.gitignore` 是**功能性**的（与 `selfcheck_core::NON_SOURCE_DIRS`
        的 `tmp` 条目成对），已按 `HEAD` 恢复 —— **两者不可同样对待**。
  - [ ] **[中] L8 完成后的在线验证**（L2/L3 目前**只有离线冒烟**）：`IbkrFeed` 连真实
        Gateway / `SubscriptionManager` 的 300 退避 / `SpotSourceSelector` 区段切换 /
        `WindowFollower` 窗口重建 —— 四项全部未跑（没有服务、也还出不了帧）
  - [x] **[高] ✅ 曲面残差无方向字段 —— 已修复（2026-09-16，KAI 选方案 B）**
        ⚠️ 原登记「**待 KAI 拍板**」，现已裁定并落地。

        **方案 B（KAI 2026-09-16 选定）**：`SurfaceResidual` 加 `right` 字段；
        `SurfaceInputPort.id_map` 改**三元组** `(expiry, strike, right)`，
        把方向一路透传到帧。**保持了原版的全部数值口径**（见下方"未变"）。

        **改动链（6 个文件，全部为增量、无行为改写）**：
        1. `contracts/feature.py::SurfaceResidual` —— 新增 `right: str = ""`
           （默认空串 ⇒ 老实现不填也不报错，但本项目恒填）；
        2. `features/surface_engine.py::_build_snapshot()` ——
           `id_map[rid]` 由 `(expiry, strike)` 改为 `(expiry, strike, right.value)`
           （与已有的 `rid` 三元组同形）；
        3. `models/raw_cleaning.py::build_clean_surface()` —— 用**切片**解包
           `mapped[0], mapped[1]` + `mapped[2] if len(mapped) > 2 else ""`
           （不是三元组硬解包，否则老实现给两元时 `ValueError`）；
           `raw_rows` 新增 `Right` 列；
        4. `models/svi_reporting.py::residuals()` —— `keep_cols` 与空表列清单
           都加 `Right`；
        5. `models/surface_adapter.py::_residuals()` —— 搬 `Right` 进
           `SurfaceResidual`（`str(row.get("Right", "") or "")`）；
        6. `serialization/surface_encoder.py::_residual()` —— 输出 `"right"` 键。

        **未变（关键）**：`Right` 不参与任何 IV 过滤、离群剔除、pivot 构造、
        平滑 —— 它只是一列随行下行的标记。`pivot_table` 仍对同档两侧取
        **mean**（原版语义），残差仍报**单侧** IV 与它的差。

        **实测证据**（`tmp/verify_residual_right.py`，**新建**；全部用
        `venv/Scripts/python.exe`）：
        - 夹具喂 **Put IV 比 Call 高 0.005**（真实微笑形状，非恒等）⇒
          25 档 × 2 = **50 条**残差，`right ∈ {P, C}`，`(strike, right)` **50/50 唯一**；
        - 同档两侧残差**实测不等**（最小差 **1.0000 波动率点**）—— 修复前这两条
          数值相同/相消、前端无法区分；
        - **拟合未受影响**：同 strike 的 `model_iv` 两侧**完全一致（25/25 档）**；
        - 帧载荷 `surface.residuals[*].right` 存在且覆盖 P/C。
        **合计 PASS 15 / FAIL 0。**
        - **非空转（两处变异，各抓）**：① `id_map` 改回二元组 ⇒ **4 条 FAIL**
          （降级为空串而非崩溃）；② 编码器删 `"right"` 键 ⇒ **1 条 FAIL**；
          两者还原后**逐字节**回到原状（`diff -q` 确认）。
        - `tmp/l6_smoke.py` 的那条旧断言「契约无 right 字段 ⇒ 待 KAI 定」
          **已改写**为三条（逐 reqId 两条 / 每条带 right / (strike,right) 唯一）
          ⇒ L6 从 **39 → 41** 条判据。
        - 全量回归：门禁 **16/16 RC=0**；`l2l3` 37/0 · `l5` 32/0 · `l6` **41/0** ·
          `l8` 30/0 · `web_e2e` 34/0。
        - 行数：6 个文件全部 < 400（最长 `features/surface_engine.py` 282）。

        ⚠️ **前端尚未消费**（`web/` 目前完全不读 `surface` 段）⇒ 残差图是
        **另一件未开始的任务**，不在本次范围内。后端契约现已就绪。
        ⚠️ **在线验证仍未做**（无服务在跑）—— 本项只做了离线端到端。

        **实测事实链**（不是推测；**以下描述的是修复前的状态，2026-09-16 已按方案 B 修复**）：
        1. `contracts/ports.py::SurfaceInputPort.id_map = {req_id: (expiry, strike)}`
           —— **不带方向**；`models/raw_cleaning.py:96-112` 逐 reqId 攒一行，
           `clean_df` 的列是 `Expiry/Strike/IV/Bid/Ask/...`，**没有 right**。
        2. `models/raw_cleaning.py:241` 的 `df.pivot_table(index="Expiry",
           columns="Strike", values="IV")` **未指定 aggfunc ⇒ 默认 mean**
           ⇒ 曲面拟合用的是同 strike 的 **Put/Call 平均 IV**。
        3. `models/svi_reporting.py:171-203` 的 `residuals()` 用的是 **`clean_df`
           （未平均的原始行）**，逐行减去 `self.iv(Expiry, Strike)`
           ⇒ 报的是**单侧** IV 与**双侧平均**拟合值的差。

        实测（L6 冒烟）：`residual_count = 50`，`len(distinct strike) = 25`
        ⇒ **恰好 2×**，且同一 strike 两条数值完全相同（因为夹具给 Put/Call 喂了
        同一个 IV）。真实行情下 Put IV ≠ Call IV ⇒ 同一 strike 会出现**一正一负**
        两条残差，而 `SurfaceResidual` 没有 `right` 字段 ⇒ **前端无法区分**，
        残差图上同 strike 两个点会互相抵消/重叠。

        ⇒ 对"残差是本项目产品指标之一"的定位（`ARCHITECTURE.md §1`），这是真问题。
        **保真移植的结论不受影响**（差分对拍零差异），这是**原版设计在本项目输入下的
        固有性质**，不是移植引入的。

  - [ ] **[低] `acquisition/ibkr_gateway.py` = 399 行，距门禁仅剩 1 行** ——
        Task #15 的门禁建议把"余量 < 5 行"的文件列为**警告**，否则下次加两行注释就违规
- [ ] **[中] 跑原版 `test_models.py`（1589 行，已复制到 `tmp/`）**，用来回答一个对拍
  答不了的问题：**pandas 3.0.5 是否改变了原版行为**。对拍用的是同一个 venv，
  只证明了"移植没引入差异"。已知 `surface_adapter` / `dashboard_config` 相关用例
  针对已删除的旧 API，**预期失败**。
- [ ] **[低] `models/forecasting/`（ewma / garch / har_rv / snapshot_history）已移植但未接线**
  —— 本项目是否需要尚未确定（原版是 RV 信号引擎用的）。
- [ ] **[低] 清 `_ref_spxw_head` worktree**（`E:/US.market/SPXW SWATCH/_ref_spxw_head`，
  `HEAD = bedbf11` 只读参照），重写完再清。
- [ ] **[低] 逐条复核 `notes/memory/{QUICKREF,RULES,TROUBLESHOOTING}.md`** ——
  三份是从 `HEAD` 恢复的旧实现记录，已加横幅；推进到对应层时复核并标 `[已复核 2026-09-15]`。

---

## Active —— 运行状态探针（2026-09-16 起）

- [x] **[高] 前后端运行状态监听探针**（会话：`runtime-monitors`）
  四项要求全部验证成立，后端已重启生效。见
  `notes/sessions/2026-09-16/runtime-monitors/handoff.md`。

- [ ] **[中] 两个变异未激活，判据真违例路径未验** ——
  ① 后端 T3「挂钟对齐」判据恒真；② 前端 T4「把不一致故意不标记」。
  本轮观测期内确实不存在真违例（无未对齐的列、无不一致的格），
  ⇒ 变异体没被执行到。**要验它们必须先构造一个"真违例"输入，本轮未构造。**
  残留风险：这两条判据若本身写错，当前探针**报不出来**。
- [ ] **[中] 两只探针停在 `tmp/`，无回归保护** ——
  按 KAI 明令（"不额外搭检查/校验模块"）它们就该留在 `tmp/`。
  代价：产品代码日后改动，这两只探针不会被自动跑，出列定稿/挂钟对齐/
  周期独立**没有持续回归**。若 KAI 日后要纳入 `tools/`，需先申请。
- [ ] **[低] 前端从未消费 `surface` 残差段** ——
  `web/` 读不到 `surface`，残差只留在帧数据里。KAI 已驳回"加副图"（"前端会变得很挤"）。
  属独立未开工任务。

---

## 历史 Active（重写前，保留作教训；路径/检查器名可能已变）

⚠️ **2026-09-15 白纸重写 —— 以下正文是重写前的记录。**
`spxw_swatch` 源码已被清空，正在基于 `live-volatility-surface`（原版）重写。
本文件正文（旧实现的状态/待办/交接）**保留作历史**：其中的纪律与教训继续有效，
但文件路径、检查器名、模块名可能已变。**重写进度以本文件顶部的新块为准。**

新架构 → `notes/memory/ARCHITECTURE.md`（旧 → `notes/context/archive/ARCHITECTURE_pre_rewrite.md`）
本轮会话 → `notes/sessions/2026-09-15/rebuild-from-original/handoff.md`


- [ ] **[低] 复现"未定稿末组"类缺陷时，必须对准边界帧而非抽间隔帧**（2026-09-15 08:4x
  `period-wallclock-semantics` 会话沉淀的**方法学**教训，非缺陷本身）。

  上一会话留了句"新语义稳定，但旧语义的漂移未再抓到实例"，看着像"缺陷也许不存在"。
  本会话动手前先证伪：**缺口出在采样位置，缺陷确实存在。**

  实测：`cols = bi + 1`，连续 60 帧采样中 `cols = 1462`，而 `1462 = 6 × 243 + 4`
  ⇒ 末组**已有 4 个桶**（桶 1458–1461），且**早已走满** ⇒ 该组与"完整组"数值相同
  ⇒ 旧语义此刻**本就不该漂移**。旧语义真正的触发条件是 **`cols % g == 1`**
  （末组恰 1 个桶 = **刚跨周期的那一帧**），而非笼统的"末组不满组"。

  - ⚠️ 原探针按 `gap = 3.0s` 抽间隔帧，而帧间隔是 **400ms** ⇒ **必然跳过边界帧**。
    复现该类缺陷必须连抓相邻帧。
  - [ ] 若日后仍需复现旧语义漂移（例如审计历史行为）：用 `cols % g == 1` 作筛选条件，
    连抓相邻帧，并对**每一条行**取末列（单抽"最密行"可能在边界那一刻恰好 ΔIV=None）。
  - 结论出处：`notes/sessions/2026-09-15/period-wallclock-semantics/project_state.md` §4。

- [ ] **[中] 热力图 Top-3 高亮在细档位下是亚像素，等于看不见 —— 待 KAI 定视觉规格**
  （2026-09-15 07:xx，提交 `c0cfa8f` 之后用**实盘完整帧**复核时实测发现）。

  `heatmap.volumeTop` 的边框宽度是**格短边的比例**（`maxRatio=0.30` / `minRatio=0.10`），
  这两个比值是从上一版"**逐格按成交量分级描边**"直接搬来的 —— 那版语义是
  **连续编码**（满屏都有边，细无所谓）；而现在 KAI 定的语义是**只标记 Top-3**
  （总共 3 格，看不见就完全失效）。**语义变了，量纲没跟着变。**

  > 实测（实盘帧、`getBoundingClientRect` 取 1200×600）：

  | 档位 | 列数 | 格短边 | 最粗 `hiPx` | 1px 可见? |
  |---|---|---|---|---|
  | 30 秒 | 1332 | 0.788px | **0.236px** | ✗ |
  | **60 秒（当前默认）** | 666 | 1.577px | **0.473px** | ✗ |
  | 3 分 | 333 | 3.153px | 0.946px | ✗ 临界 |
  | 5 分 | 111 | 9.459px | 2.838px | ✓ |

  窗口 1920×900 时默认档仍 **0.797px**；2560×1000 才勉强 1.086px。

  **为什么回归全绿**：`tools/check_heatmap_topn_skew_zoom.py` 用 6×8 合成矩阵
  （`cellShort ≈ 130px`），比值派生的宽度当然够粗 ⇒ **合成夹具的几何与真实档位
  差两个数量级**。这是"判据全绿 ≠ 实盘可用"的典型。

  - [ ] 待 KAI 裁定方向（**未自行改配置**，属视觉规格）：
    **A** 用绝对像素 `minPx`/`maxPx`（配置已支持，`>0` 时优先于比值）；
    **B** 上调比值（30 秒档仍只有 0.79px，治标）；**C** 细档位改用别的标记手法。
  - [ ] 裁定后补一条**档位相关**的判据进 `check_heatmap_topn_skew_zoom.py`
    （如"任一档位下 Top-3 的最粗边 ≥ 1 CSS px"），让合成夹具也能覆盖真实几何。
  - ⚠️ 全部数字来自 node 沙箱几何计算，**未做浏览器取像素**；真实窗口尺寸由 KAI 的
    浏览器决定。

- [ ] **[中] ΔIV 公式缺一个"端到端逐格对拍"的检查器**（2026-09-15 04:5x 审计，
  探针已写在 `tmp/verify_delta_iv.py`，**未落成常驻回归**）。

  **审计结论（全部实测，无一处是"看代码觉得对"）**：

  | 环节 | 结论 | 证据 |
  |---|---|---|
  | `ImpulseEngine` ΔIV(N) = `(IV_now − IV_{now−N}) × 100` | ✅ 正确 | 同一个合约的 buffer 内做差，`OptionRef` 带方向 ⇒ 结构上不可能串边 |
  | `HeatmapEngine` ΔIV = `(value − previous) × 100` | ✅ 正确 | 端到端逐格对拍 **1272/1272 格一致** |
  | 热力图按**行权价**分键（不带方向）是否引入 Put/Call 混淆 | ✅ 不引入 | 实测两侧 model IV **逐位相同**（4 档 × 8 采样 = 32 次比对，`|ΔIV|` 全 0.0000；两侧 conId 不同，确属两张合约） |
  | `SkewEngine` | ✅ 正确 | `put_samples`/`call_samples` 按 `cell.right` 分开；`skew = (put25.iv − call25.iv) × 100` |
  | `_atm_iv` / `_straddle` | ✅ 正确 | 是回 `store.latest_option()` 取**另一侧**，不是从单侧的 `cells` 里凑 |
  | `use_model_greeks=true` 这个**前置条件** | ✅ **已有守卫且非空转** | `tools/selfcheck_config.py::_check_model_greeks_prerequisite`（`--check` 的 `[6]`）：正常态 `[ok]`+`RC=0`；**变异为 false ⇒ `[FAIL]` + `RC=1`**，还原后两次输出完全一致（54 ok / 0 fail / 0 warn） |

  **缺口**：以上第 2 行那条"逐格对拍"目前**只在 `tmp/` 里、是一次性的**。现有
  `tools/check_matrix_codec.py` 只做 **pack/unpack 往返**（编解码自洽），
  `check_persistence.py` 只管键序 —— **没有任何常驻检查器断言"帧里那个数 = 库原始
  IV 差分 × 100"**。少乘/多乘 100、行序反了、单位换成百分数，三者都会让图**照常
  渲染**（典型的静默错值）。

  - [ ] 把 `tmp/verify_delta_iv.py` 提为 `tools/check_heatmap_delta.py`
    （形态参考已有的 `tools/period_reference.py` / `skew_reference.py` 的"参考实现
    对拍"族），并登记进 `--check` 矩阵与 `NON_SOURCE_DIRS`。
    ⚠️ 它需要**在线的 8060 + 当日库**，属"需服务"类检查 ⇒ 盘中才能跑，
    盘前/盘后应记 `N/A`，不要判成回归破坏。

- [ ] **[高] 空图真根因已定性：IBKR `modelGreeks` **间歇缺失**，不是"GTH 结构性"**
  （2026-09-15 04:3x 查清，KAI 提供两条网关日志后收口）。

  **证伪**：当天 `data/sessions/20260915.db` 的空洞史显示 **GTH 段内 IV 连续跑了好几小时**
  （bucket 527–806 = 00:38:59→02:46、852–927 = 03:21→03:58:56，GTH = bucket 0..1579）。
  每个空洞都对齐一次连通性/重启事件（807–851 ↔ `1100` 丢失 → `1102` 恢复；
  928–994 ↔ 服务重启 + 网关重启），**没有一次对齐 GTH 边界**。
  ⇒ 我 04:1x 写进 skill 的"GTH 段热力图必然为空是结构性的"**是错的，已改写**
  （`spxw-live-verify/references/pitfalls.md` §5b，同条目重写、未新增清单项）。

  **量化指纹（可直接复现，比看热力图强）**：`health.ticks_dropped` = `router.rejected`
  （`acquisition/feed_service.py:120`）。`use_model_greeks = true` ⇒
  `tick_router._pick_computation` 只收 tick 13 ⇒ 模型缺失窗口留下巨大拒绝计数：
  ```text
  失效窗口 04:12→04:32（20 min）：received 80,207  dropped 317,621
  恢复后   04:36:40→04:37:00（20 s）：received +127  dropped **+0**
  ```
  ⇒ **判据**：抓两帧间隔 10–20 s 比增量。`dropped` 增量为 0 ⇒ 模型正常；
  若此时仍空图，才该怀疑项目自己。**实测 04:32:55 自愈**（`atm_iv 17.22`、
  `heatmap.filled 8543`），未做任何代码改动。

  **网关那条日志不是客户端的锅**（已排除）：`Client 71 Output exceeded limit
  (was: 100010), removed first half` —— 同窗口内 ① 帧计数**精确 149–150 帧/分钟**
  （= 400ms 间隔，事件循环有大量空闲）② `现价` 每分钟都在变（期货 tick 走同一条
  socket、同一个 `pendingTickersEvent`）③ `ticks_received` 持续增长 ⇒ 客户端在读在排空。
  读侧结构也支持：`ib_async` 读路径纯事件驱动（`Connection.data_received` →
  `Client._onSocketHasData` 同步解完缓冲区内**全部**消息 → `tcpDataProcessed` 发
  `pendingTickersEvent`），**没有会被卡住的读循环**。`netstat` 亦确认 4002 只有
  **一条**连接（PID 8504），无僵尸进程占 `clientId`。

  **待 KAI 定（二选一）**：
  - [ ] 前端是否加提示。⚠️ 提示**不能写"夜盘无 IV"**（已证伪）—— 必须是**数据驱动**的
    "model IV 不可用"（判据：`ticks_received` 在涨 + `store_cells == 0` +
    `ticks_dropped` 在涨）。现状：帧里已有这三个数，但前端未据此给原因。
  - [ ] 是否把 `ticks_dropped` 的**增量**纳入健康判据（当前它只被 `feed_service` 计数，
    没有任何检查器/日志在盯它；317,621 这个量级此前无人看见）。

- [ ] **[中] 三条卡片是"欠账"：能机械守、但没写检查器**（2026-09-15 02:5x 审计；
  判据见 `notes/memory/QUICKREF.md` 的"收录判据"节：**每条卡片必须能报出"谁守着它"
  或"为什么守不住"**）。这三条两样都报不出 ⇒ 不是永久卡片，是欠账：

  | 卡 | 现状（实测） | 该补的断言 |
  |---|---|---|
  | A | `grep inverse tools/*.py` **0 命中** | 帧行序降序 ↔ `web/heatmap.js::yAxis.inverse = true` 必须**成对**（静态可判） |
  | E | `selfcheck_core` 只查 `market_data_type` **键在不在、不查值** | `config/ibkr.json::market_data_type` **必须 = 3**（写 1 会 fail-closed 退出，但没人拦） |
  | L | `grep 'splitLine\|cellBorder' tools/*.py` **0 命中** | `cellBorderMinPx` 单位是 **CSS px** + 网格线走轴 `splitLine` 抽样 |

  ⚠️ 目标不是"再加三张卡"，而是**把这三条降级**：细节归检查器 docstring，
  卡片只留一行指针。⚠️ **本文件所在清单「只减不增」**（KAI 2026-09-15 明令
  **"禁止新增速查卡"**，判据写在 `notes/memory/QUICKREF.md` 的"收录判据"节）
  ⇒ 这三条补完是 **23 → 20 条，净减**，不是"持平"。

- ~~**[中] 持久化落点：单库 → 一交易日一文件**~~ —— **已完成**（2026-09-15，
  会话 `notes/sessions/2026-09-15/persistence-session-files/`）。
  KAI 目标原话："第一天就写第一天的数据，重启后接着写第一天的；第二天新开一份，
  第二天重启，继续写第二天的"。落地：`config/persistence.json` 的 `db_path` 改为
  `db_dir: data/sessions` + `db_filename: {session_key}.db`；新增
  `features/persistence_store.py` 承载"文件与表"，`features/persistence.py` 只留队列
  与调度（384 → 310 行，改动前余 16 行放不下）。旧库当前会话 88+88 行已迁移。
  回归 `check_persistence` 7/7 + 新增 `check_persistence_sessions` 4/4；
  `run.py --check` `RC=0`；`ws_probe` 25/25；非空转两个变异各抓 2 条。
  ⚠️ 两个坑已写进 README §5 与 `project_state.md`：
  ① `_batch_write` 必须**逐条**按会话切文件（跨日批次里混着两个会话）；
  ② `SessionFileStore.close()` **必须先提交再关闭** —— SQLite 的 `close()` 对未提交
  事务是**回滚**，实测丢掉旧会话那一行。

- ~~**[中] 旧会话文件的保留策略未定 —— 当前只增不删**~~ —— **已定并落地：归档不删**
  （2026-09-15 02:2x 首版 → **03:1x 按 KAI 明令改为"归档"**，会话
  `notes/sessions/2026-09-15/persistence-session-files/`）。

  **KAI 2026-09-15 03:0x 两条明令**：
  ① 原话 **"这就是历史数据，有用。"** ⇒ `data/sessions/<到期日>.db` **不是"残留垃圾"，
  是逐交易日的 ΔIV / Skew 原始记录**（回看、对拍、做数据集的唯一来源）。
  ② 原话 **"'不留档、不备份' 只针对旧单库 `data/session.db`"** ⇒ 我在 02:2x 把这句话
  的适用范围**从旧单库扩大到了全部逐日文件**，是**误读**（已按此更正，见下）。

  实现（**移动，不删除**）：`SessionFileStore.archive_other_sessions(keep_key)` 把 db_dir
  内所有非当前会话的库文件 `rename()` 到 `archive_dir`（`persistence.json::archive_dir`，
  默认 `data/archive`）；`AsyncPersistenceWriter.start()` 在打开本会话文件后调用它，并把
  `(已归档, 未归档)` **两组**返回给调用方（`features/` 整层不写日志，由 `app/pipeline.py`
  **各记一行** —— 动数据不允许静默，"没归档成功"更不允许）。
  **三道闸门 + 一道构造期校验**：① 只在 `db_dir` 之内 glob；② 只匹配 `db_filename`
  模板派生的名字；③ 归档目录**同名不覆盖**（跳过并上报，源文件留 db_dir 下次再试）；
  ④ `archive_dir` 落在 `db_dir` 之内 ⇒ **构造时抛错**。
  回归 `check_persistence_sessions` **6/6 → 7/7**；非空转 3 个变异（摘掉归档 / glob 越界
  到上一级 / 同名无条件覆盖）各抓 1–3 条，还原后全绿。
  ⚠️ **未做**：跨日那一刻产生的旧文件留到**下次启动**才归档（`features/` 无日志可记）
  ⇒ **未归档数 = 自上次启动以来的交易日数**（实测 `tmp/probe_rollover_residue.py`：
  不重启跨 5 个交易日 ⇒ 5 个文件 ≈ 9.4 MB；每天重启一次则最多 1 个文件 ≈ 2.35 MB）。
  未归档文件**永不会被读到**，只是还没归位。
  ✅ **实盘验证**（2026-09-15 03:18:42）：合成 `data/sessions/20990101.db` → 用新代码
  重启 → 日志 `已归档 1 个历史会话文件到 data\archive（db_dir 只留当前会话）: 20990101.db`；
  `data/sessions/` 只剩 `20260915.db`，`data/archive/20990101.db`（20,480 B）在。

- ~~**[低] `data/session.db` 是否删除 —— 待 KAI 定**~~ —— **已删除**
  （2026-09-15 02:2x，**KAI 明令：禁止备份，必须删**）。
  删除前实况：1,064,960 B，`heatmap_buckets` / `skew_points` 各 88 行，
  mtime 停在 01:22:07（已停写）。删除后 `data/` 只剩 `sessions/`，
  `data/sessions/20260915.db` 未受影响（当刻 290,816 B 且在长）。
  `data/` 在 `.gitignore` 里 ⇒ **不可恢复、无备份**（按明令执行）。
  引用同步：`notes/context/handoff.md` 两处"留作迁移前存档"、
  `tmp/migrate_session_files.py` 与 `tmp/repro_holes.py` 的横幅均已改口。

- ~~**[低] `notes/memory/ARCHITECTURE.md §4` 目录约定系统性过期**~~ —— **已完成**
  （2026-09-15 01:5x，会话 `notes/sessions/2026-09-15/persistence-session-files/`）。
  按目录枚举重写 §4（列**全部实际模块**）；同批更正 §2 的 Python 版本
  （3.13.12 → **3.13.14**，项目 `venv/`）、§5 的 `10 个 JSON` → **11** /
  `关键配置项 40` → **50**、§6 四处类名（`SkewSeries`/`ImpulseTracker`/`FrameBuilder`/
  `WSBroadcaster`）与 `TickStore (SQLite)` → **内存环 `RingBuffer`**、§7 的
  "`run.py` 只剩 `--check`" → **不带参数即启动服务**。改后 `run.py --check` 仍 `RC=0`。

- ~~**[低] `tmp/` 残留探针清理**~~ —— **已完成（改为加"已失效"横幅，未删）**
  （2026-09-15 01:5x，同上会话）。实测校准横幅措辞：`tmp/repro_holes.py`
  **rc=0、静默打印冻结值**（危险的一类）、`tmp/probe_mutation_cross_session.py`
  **rc=1 `AttributeError`**（响的一类，首炸点是已消失的 `_fetch_session_rows`）。
  不删的理由：`tmp/` 是 gitignore 的一次性脚本区，且 `tmp/migrate_session_files.py`
  仍是本轮迁移的证据。

- ~~**[中] 假 0 带残留：bucket 0 本身仍被恢复**~~ —— **已关闭**（2026-09-15，
  会话 `notes/sessions/2026-09-15/persistence-session-identity/`）。
  本条登记的根因（`features/persistence.py::recover()` 读 `heatmap_buckets` **全部行**、
  无任何过滤）**就是**修复对象：`bucket_index` 是**日内坐标、每个交易日复用**，
  而表里**没有会话身份** ⇒ 跨会话的行落进同一键空间。
  修法：`session_key`（= 当日到期日）进主键 `(session_key, bucket_index)`，
  `recover()` / `recover_skew()` 按会话过滤；**缺列的旧表整张丢弃并报出行数**
  （实测 `丢弃 1830 行`）。重启后**假 0 带一并消失**（截图对照：
  `tmp/startup_panel_20260915_0030.png` → `tmp/fixed_panel_0041.png`）。
  回归 `tools/check_persistence.py` 8/8（含跨会话隔离 / 旧表迁移 / 空身份拒绝），
  非空转：摘掉会话过滤 ⇒ 跨会话用例报 `今日会话应只有 1 个桶，实际 3`。
  ⚠️ **本轮只关了上面这一条**：同一根因还有三种更严重的表现（帧的 `skew.latest`
  取 `skew_series[-1]` ⇒ 报出**昨天**的点；`skew.series` 混入昨天的点、label 用今天的
  网格算 ⇒ 曲线画到未来；热力图把昨天 RTH 的数据画在今天 GTH 的时刻上）——
  它们由同一次修复一并消除，但**之前从未登记**，故记在这里而非当作"旧残留"。
  ⚠️ "`recover()` 只取最后一段连续桶"这条**仍未被选**（KAI 2026-09-14 未选，
  2026-09-15 仍未选）：会话身份修好后它**不再是错值来源**（别的交易日的行读不进来），
  只剩"同一会话内孤桶被前向填充沿用 ≤ `heatmap_max_ffill_buckets`(20) 桶"这个形状，
  由 `check_reconnect_gap.py::case_long_gap_is_blanked` 守着。

- ~~**[中] 细档位纵线（自适应步长）未做高 dpi 实测**~~ —— **已作废**（2026-09-14）。
  热力图渲染器换回 ECharts 后，网格线改走轴 `splitLine`，`cellBorderMinPx` 的单位随之
  由**物理像素**变为 **CSS px**（ECharts 的坐标单位），"高 dpi 下 stride 翻倍"的问题**不再存在**。
  新语义见 `notes/memory/QUICKREF.md` 卡 L。

- [ ] **[高] 热力图换 ECharts 后宽档位持续占用 40–47% 单核**（2026-09-14，**KAI 已知情并接受**）——
  实测（headless + SwiftShader，1400×520、24 行）：ECharts 单次重绘 630 列 65.7ms /
  1352 列 159.9ms / 2370 列 188.1ms；同环境旧 WebGL 0.6 / 1.0 / 1.3 ms。
  节拍 `web/ws_client.js:137` = 200ms、后端推送 400ms ⇒ **2.5Hz**。
  可选缓解（**均未实施，需 KAI 指令**）：热力图重绘节流到 ~1Hz（与推送解耦，占用 → ~19%）、
  或给 `maxColumns` 降档。注意 `progressive` 是负优化（2370 列 424ms > 不开 188ms）。

- [ ] **[高] 本仓库禁用 `git rm` / `git mv`**（2026-09-14 事故）——
  执行 `git rm -f web/gl_heatmap.js && git mv web/test_gl.html ...` 期间**整个 `web/` 目录
  从工作区消失**（`git status` = ` D web/*.js` ×17 + `D  web/gl_heatmap.js`），`git mv` 报
  `fatal: bad source`；**无任何命令显式删除目录，成因未查明**。靠 `git checkout -- web/` 恢复，
  但未提交的 `web/config.js` / `web/skew.js` 改动丢失、只能按记录重建（非逐字节还原）。
  ⇒ 一律改用 `rm` / `mv` + `git add`。证据见
  `notes/sessions/2026-09-14/webgl-to-echarts/handoff.md::事故`。

- [ ] **[中] 图例两项同名 `25Δ Skew` —— 待 KAI 定名**（2026-09-14）——
  `web/skew_helpers.js::displayName()` 把 `25Δ Skew·负` 也显示成 `25Δ Skew`（正负分段渲染的设计），
  图例上因此出现两条同名项（一暖一冷）。**改名属产品决策，未获指令不动。**
  注意：已修的是**颜色**（`itemStyle.color`），**不是**命名 —— 别把两件事混为一件。

- [ ] **[低] `check_page_render` 默认 budget 下必失败 —— 根因已定位**（2026-09-14）——
  该检查用 `--virtual-time-budget=14000` + `--dump-dom`（`tools/check_page_render.py:91-110`）。
  **虚拟时间跑在真实 WebSocket 帧之前** ⇒ 抓到的 DOM 是"还没收到第一帧"的状态：
  `meta 为空` ×2、`0 个 canvas`、`现价 --`。`--budget 60000` 即恢复
  （热力图 22 档 × 741 桶、Skew、canvas≥2、现价 7603.7 全 ok）。
  另有**断言本身过期**一条："有且仅有一个周期处于选中态" —— 会话按钮（`app_sessions.js`）
  与周期按钮各有一个 `on` ⇒ 恒为 2 个。**仅记录，未改**。

- ~~**[高] `现货 7591.70` 来源未定位**~~ —— **已关闭**（2026-09-14）。KAI 更正：7591.70 是上一轮
  被驳回算法自己算出来的产物，**不是** IBKR 给的值。探针实测（`tmp/probe_spot_basis.py`）：
  IBKR 在 GTH 给的 SPX 指数 = **7656.98 = 周五官方收盘，恒定**。
  ⇒ "IBKR 给的是冻结的 RTH 收盘价"这个说法是对的。残余风险转为下一条（新鲜度判不出）。

- [ ] **[低] `marketDataType` 判不出指数新鲜度 —— 危害已消除，机制缺口保留**（2026-09-14 实测）——
  GTH 期间 SPX 指数恒定 7656.98（周五收盘），但 `marketDataType = 1`（报"实时"）。
  ⇒ `ibkr.max_underlying_age_s = 10.0`（`acquisition/feed_reconcile.py::_spot_stale`）
  **结构上拦不住这类值**。
  **危害已由 B2b 结构性消除**：`SpotSourceSelector` 在合成区段**直接丢弃**指数 tick，
  冻结值不再进入下游 ⇒ 原先"比真实现货高 40.4–42.0 点 ≈ 8.1–8.4 档"不再发生。
  机制缺口仍在（判新鲜只能看"值有没有变过"，`marketDataType` 无此语义），
  但当前**无已知受影响路径** ⇒ 降为低。**未获指令不改闸门判据。**

- ~~**[中] 交易日 RTH 段实盘验证（B2b 落地的最后一块）**~~ —— **已闭合**（2026-09-14 09:45 EDT，
  会话 `notes/sessions/2026-09-14/live-render-verify/`）。三项全部实测通过：
  ① 指数在 09:30 后确实恢复实时 —— 冻结值 7656.98（09:27 日志）→ 09:30 `现价 7611.44`，
     独立探针实测 `last=7611.27 ≠ close=7656.98`；
  ② 09:25 交班平滑 —— 帧内 messages 依次出现
     `现货源切换：区段 rth → 指数直读` → `现价恢复更新，窗口跟随继续` →
     `窗口跟随现价重建 ±12 档 (+22 / -22, 共 48)`，窗口按既有 `WindowFollower` 自动重建；
  ③ RTH 段走**指数直读**而非合成（同上第 1 条 message）。

- ~~**[中] `check_period_aggregation.py` 既有失败 —— 根因已定位**~~ —— **已关闭**
  （2026-09-15 复扫，会话 `notes/sessions/2026-09-15/persistence-session-identity/`）。
  本条列的 6 个"既有失败"（`check_period_aggregation` / `check_page_render` /
  `check_skew_alignment` / `check_skew_viewport` / `check_web_contract` /
  `check_ws_compression`）**现只剩 1 个**：2026-09-15 用 `venv/Scripts/python.exe`
  全量复扫 **21 个 `tools/check_*.py` ⇒ 20 `RC=0` / 1 `RC=1`**，唯一红 =
  **`check_page_render`**（其两处成因见下条，**本轮未动**）。
  ⚠️ **判据必须用 venv 解释器**：裸 `python` 缺 `ib_async`/`aiohttp`，
  `check_web_contract` 等会在 import 阶段崩成假红。
  🆕 本轮另修一个**不在本清单里**的假红：`check_session_grid.py` 的"交易日推导"
  用例隐含"锚点必须是周一"，只在周一通过、其余六天报 4 条红（详见会话记录
  `handoff.md::第二个缺陷`）。**⇒ 这张清单本身漏了它，说明"按清单清点"不可靠。**

- ~~**[中] B2b 实现待启动**~~ —— **已完成**（2026-09-14，会话
  `notes/sessions/2026-09-14/b2b-spot-synthesis/`）。5 条拍板全部落地：
  ① `config/spot.json` 独立文件；② 09:25 交班下线 GTH 锚定、切回指数（窗口重建由既有
  `WindowFollower` 自动完成，锚跳 8.15 档 > trigger 3 档，**未加特殊代码**）；
  ③ `ĉ` 两层闸门（`max_abs_carry` fail-closed + `max_carry_jump` 拒收该桶、基准跟上）；
  ④ 不做 09:30 单点对拍；⑤ `--check` 按 `pyvenv.cfg` 识别 venv。
  新回归 `check_spot_synthesis` 16/16 + `check_spot_source` 11/11，非空转 5/5 变异被抓。

- ~~**[中] `run.py --check` 基线已漂移：RC=1，2582 项误报**~~ —— **已修**（2026-09-14）——
  根因：`.venv/` 与 `venv/` 未登记 `NON_SOURCE_DIRS`，`ROOT.rglob("*.py")` 收了 site-packages。
  修法按 KAI 拍板：`iter_py_files()` 新增 `_in_virtualenv()`，**按 `pyvenv.cfg` 识别**
  （与目录名解耦，不再补两条目录名）。
  非空转验证：`mv .venv/pyvenv.cfg .venv/pyvenv.cfg.off` → `RC=1 / 1291 项`；
  恢复后复跑 → `RC=0`。终态 `RC=0`（90 个 Python + 14 个前端脚本全部合规）。

- ~~**[中] 残留进程 PID 15612 占用 8060**~~ —— **已中断**（2026-09-14 KAI 指令）。
  `MSYS_NO_PATHCONV=1 taskkill /F /PID 15612` → SUCCESS，`netstat :8060` 已无监听。
  教训保留：它跑的是已撤回构建（日志字段 `公允` 在 HEAD 代码中不存在），
  **实盘验证前必须先确认 8060 上没有别的进程**。

- ~~**[中] 实盘首次出图未验证**~~ —— **已闭合**（2026-09-14 09:45 EDT RTH 段，
  会话 `notes/sessions/2026-09-14/live-render-verify/`）。四项逐条取证：
  - ✅ `health.mode = delayed`（推导值，非观测）；**期权与 SPX 指数实测 `marketDataType=1`**
    （任务书预期的"指数 = 3"是过期预期，实测为准）；`modelGreeks` 与 bid/ask/last Greeks
    并存且值不同
  - ✅ **48 条订阅**（±12 档 × Put/Call），`projected_subscriptions()` = 49
  - ✅ 热力图出图：`ws_probe` 全部通过（帧 18059→18068、**24 档**、1624 桶、15,420 格）；
    真 Chrome 截图 185,973 字节，顶栏 `connected`，热力图 + Skew 双面板出图
  - ✅ `health.rate_limit` 四要素（45 / 1.0s）+ 两条非空转证伪
    （非默认 12/0.5s 生效 + 突发 200 条 ⇒ `events` 0→1、`throttling` 翻真后复位）
  - 2026-09-13 遗留的 ⚠️「SPX 现价 7591.70」仍**作废**（那是被驳回算法的产物，非 IBKR 值）。

- ~~**[中] 4 个需服务的检查 — 1/4 已跑通**~~ —— **已关闭**（2026-09-15 盘中，
  会话 `notes/sessions/2026-09-15/persistence-session-identity/`）。
  服务在跑（GTH 段，`connected` / `last_tick_age_s 0.0` / 80-92 订阅）时全量复扫：
  - ✅ `ws_probe` —— **25/25 全部通过**（修复前 26/27；唯一 FAIL 是跨会话持久化污染，
    已修）。24 档 × 532 桶、Skew 5 点。
  - ✅ `check_web_contract` —— **`RC=0`**（**用 venv 解释器走它自己的入口**，
    不再是"离线等价物"）。此前它红是**裸 `python` 缺 `aiohttp`**，不是产品问题。
  - ✅ `check_ws_compression` —— **`RC=0`**（压缩比阈值不再漂红）。
  - ❌ `check_page_render` —— 仍 `RC=1`，**既有缺陷、本轮未动**：
    ① 断言「有且仅有一个周期处于选中态」把页面上**所有** `<button>` 收成一个列表，
    而页面有**两组**独立按钮（会话 `全时段/GTH/RTH` + 周期 `30秒/1分/…`）各有一个 `on`
    ⇒ `len(chosen) == 1` **恒不成立**；② 虚拟时间窗口随首帧体积漂移
    （`--budget 14000` 无 canvas / `20000` 报数据陈旧 / `120000` 报数据中断）。
    要修得先改断言语义、再换掉虚拟时间方案，**不是调个数**。

- [ ] **[低] `check_web_contract.py` 顶层 `import aiohttp`** 使第 1、2 段
  （纯静态对照）也无法在无 aiohttp 的环境运行。是否把 import 挪进函数内
  **待 KAI 定** —— 改动小，但属"重构现有工具"，未获指令不擅自动。

- [ ] **[低] `~/.workbuddy-ai/tmp/` 历史探针 —— 清单已列，待 KAI 拍"全迁 / 部分迁 / 只登记不动"**
  （2026-09-15，会话 `notes/sessions/2026-09-15/persistence-session-identity/`）——
  新约定落点已是 `<项目根>/tmp/`，但历史文件仍在用户级目录（被所有项目共用）。
  KAI 2026-09-13 拍板：**下一个会话做**，且"开始前先列清单"。
  🆕 **清单已出**：`notes/sessions/2026-09-15/persistence-session-identity/artifacts/user-tmp-probes.md`
  —— 共 **72** 项（13 目录 / 35 个带 `import` 的脚本 / 24 个非脚本产物），
  其中 **38 项**与 SPXW 相关（判据：文件名或内容含 `spxw`/`8060`/`4002`）。
  本轮**未移动、未删除任何文件**（动用户目录需 KAI 明令）。
  ⚠️ 清单的 `proj` 列是**关键词判定，未逐一人工确认归属** —— 拍板前若要更准，
  可按 mtime 分段人工过一遍。

- ~~**[中] 热力图格子边框（"网格线"）在 WebGL 重写时丢失**~~ —— **已修**（2026-09-14）——
  根因：旧版 ECharts `heatmap.js` 有 `itemStyle: { borderWidth: 1, borderColor: CFG.theme.grid }`
  （每格 1px 边框），`af2e2e4` WebGL 重写时删掉且未在新引擎实现；
  `gl_heatmap.js` 的 shader 只画填充 + volume 高亮白边 ⇒ `theme.grid` 成**死配置**。
  修法：在 fragment shader 里补逐格边框（1 物理像素，**两个方向独立判断**，
  某方向格子 < 3 物理像素时不画 —— 否则 `bw = 1/cellPx ≥ 0.5` 会让判定区间覆盖整格，
  热力图糊成一片深灰）。`config.js` 新增 `heatmap.cellBorderMix`（0.55），
  边框色复用 `theme.grid`（死配置复活）。
  实测：1 分档（~570 列）横向网格线可见；5 分档（115 列）完整双向网格。
  非空转：`cellBorderMix=0` → 网格**完全消失**（截图 `mut-mix0.png`），改回后恢复。
  注意：坐标轴 `splitLine` 旧版就是 `show: false`，**不是**这个问题。
  ⚠️ **本条的"某方向 < 3 物理像素即整方向不画"已被 2026-09-14 后一会话推翻** ——
  1 分档 630 列时格宽 2.40px，纵线因此整条消失（KAI 报"长条状"）。
  现改为**单侧自适应步长**（见下条）。

- ~~**[高] 热力图上下镜像（屏幕行序 = 帧行序的反向）**~~ —— **已修**（2026-09-14）——
  根因：`web/gl_heatmap.js::update()` 写 `var tr = rows - 1 - r;`（注释称 "inverse Y"），
  而 shader 的天然映射是"屏幕顶 = texture 行 0"、HTML overlay 的标签/现货线也从索引 0 起
  ⇒ 行序被**反了两次**，整张图上下镜像（满宽的行跑到屏幕顶部）。
  修法：去掉 `tr`，按帧行序直写 texture（`var i = (r * cols + c) * 4`）+ 契约注释
  "帧行序 ≡ texture 行序，**不要再反转**"。
  非空转：改回 `rows-1-r` 重截 ⇒ 满宽行跑回顶部（`tmp/mut_mirror.png`）；
  复原后逐行对上帧（`706/706`、`450/449`、`2/1`）。

- ~~**[高] 20:15 起满宽"假 0 带"（系统非 20:15 启动，前端首列却落在 20:15）**~~ —— **已修**（2026-09-14）——
  根因链：`features/persistence.py::recover()` 读 `heatmap_buckets` **全部行**
  → `app/pipeline.py:175-177` → `HeatmapEngine.load_snapshot()` → `_row_values()` 的
  `carried` **无上限前向填充** ⇒ 一个孤立旧桶被一路沿用，拉出满宽 `ΔIV=0` 的亮黄绿带，
  与真"IV 没变"无法区分。
  修法：新增 `config/serialization.json::heatmap_max_ffill_buckets`(20 = 30s×20 = 10 分钟，
  取 `heatmap_feed_gap_s`(300s) 的 2×)；`HeatmapEngine` 加 `_max_ffill` slot，
  `_row_values()` 用 `last_seen` 记账，跨度超限输出 `None`（留白）。
  回归 `tools/check_reconnect_gap.py::case_long_gap_is_blanked`（阈值从 config 读，不写死）；
  `--selftest` 扩为两处注入（吞 `break_now` + 上限推到无穷）⇒ 实测两例变红。
  ⚠️ ~~**需重启进程才生效**~~ —— **已重启并实测生效**（见下条）；**残留**见 Active 段第一条。

- ~~**[高] PID 896 需重启，前向填充上限才生效**~~ —— **已完成**（2026-09-14 KAI 指令）——
  `run.py` 只认 Ctrl-C（`Pipeline.stop()` 打印 `已停止`），**无 HTTP / 文件 / 信号停机入口**
  ⇒ 沙箱内只能硬杀。实测 `venv/Scripts/python.exe run.py` 是**父子两进程**
  （venv 存根 ~8MB 父 + 真实解释器 ~100MB 子，同秒创建）。
  `taskkill /T /PID 8908` 报 `8908 not found`，但 `tasklist` 复核两个都已消失；
  日志**无 `已停止` 行** ⇒ 属硬杀。
  硬杀安全性核过三条：`journal_mode=delete`（不损坏）· `_batch_write()` 每批 commit
  （最多丢一个未提交批次）· `recover()` 会把已提交桶捞回；停后 `integrity_check` = `ok`、334 行不变。
  重启：`07:19:49` 启动 → 恢复 **335** 个历史桶 → `07:19:59 流水线已就绪`。
  **生效判据**（活帧逐行非空列分段）：row 19（strike 7575）由 `first=1 / nonnull=1308`
  变为 `[(1,20),(449,554),(706,726),(1065,1331)]` ⇒ 假 0 带 **1308 列 → 20 列**（= 上限）。
  对照 row 2（7660）无 `(1,20)` 段 ⇒ 修的是**带**，真实数据未动。
  流程已沉淀进 `spxw-live-verify`（SKILL.md §5 + `references/pitfalls.md` 第 11 条）。

- ~~**[中] 细档位（30秒/1分）没有纵线，看着是长条状**~~ —— **已修**（2026-09-14）——  根因：默认周期 1 分 ⇒ 630 列 ⇒ 格宽 2.40px，被上一轮 `>= 3.0` 的**双侧**阈值判为"太窄"，
  纵线整方向跳过；5 分档（126 列 / 12px）本来就有完整网格 ⇒ **档位相关**，非损坏。
  修法：换成**单侧自适应步长** `stride = ceil(u_borderMinPx / cellPx)`，线仍落在**真实格边界**
  （只取子集），`stride = 1` 退化为旧行为；新增 uniform `u_borderMinPx` +
  `web/config.js::heatmap.cellBorderMinPx = 5`（**物理像素**），`web/heatmap.js` 透传。
  实测 1 分档：**653 条纵线、间距中位 5.0 px**（`tmp/grid_final.png`）。
  非空转：`cellBorderMinPx = 0` ⇒ `stride = 1` ⇒ 纵线塌成密纹、四条扫描线仅检出 0–9 条、无周期。
  单位坑见 `notes/memory/QUICKREF.md` 卡 L；高 dpi 实测仍是待办。

- ~~**[中] Skew 图例色与曲线色系统性不符**~~ —— **已修**（2026-09-14）——
  根因：5 条 series 只设 `lineStyle.color`，而 ECharts 的 legend 图标**不读**它，
  退化为默认调色板按索引分配。
  修法：给 5 条 series 补 `itemStyle.color`（与 `lineStyle.color` 同值），
  并在 `skew.js` 注释里写明"两处必须一起改"的理由，防止后人当冗余删掉。
  实测：`itemStyle` 与 `lineStyle` **5/5 一致**；图例色块由 `蓝紫/绿/黄/红/浅蓝`
  变为 `红/蓝/灰/红/蓝`，与曲线对应。
  非空转：把 `series[0].itemStyle` 改回调色板色 `#5470c6` → 图例第 1 项立刻变回蓝紫。
  ⚠️ **附带问题仍未处理**：图例有两项同名 `25Δ Skew`
  （`skew_helpers.js::displayName()` 把 `25Δ Skew·负` 也显示成 `25Δ Skew`）——
  这是正负分段渲染的设计，改名属产品决策，**待 KAI 定**。

- ~~**[低] 本机缺 `ib_async` 与 `aiohttp`**~~ —— **已解决**（2026-09-13 KAI 启动 Gateway 后安装）。
  `check_reconnect_flow` / `check_web_contract` / `ws_probe` 现在都能跑。

- ~~**[中] 网格粗细「受成交量无级调节」未实现**~~ —— **已实现**（2026-09-15 05:3x，KAI 拍板方案）。

  **丢失与发现**（2026-09-15 04:5x）：该特性原在旧 `web/gl_heatmap.js` 的 fragment shader
  （`float vol = s.b/255.0; float border = vol*0.35;`），`6828e3a`（WebGL→ECharts 重写）
  删掉该文件时一并消失。此后数据链"三跳掉在最后一跳"：后端在发（`heatmap_engine.py::_row_volumes`
  → `heatmap_matrix.py` 打包 `vol_bm`/`vol_i16`）、前端在解（`matrix_codec.js` → `block.volumes`）、
  **但没有任何渲染器消费**（`heatmap.js` 全文零引用 `volumes`）。
  ⚠️ 本条与上方「格子边框在 WebGL 重写时丢失（已修）」是**两件事**：那条修的是**固定 1px 网格线**，
  并在描述里把 shader 的 volume 白边当成"要替换的旧实现"抹掉 —— 丢失点就在这里。

  **KAI 定的方案**（2026-09-15 05:1x）：① 数据源唯一 = **30 秒桶**的 tick 计数，更粗周期在组内聚合；
  ② 视觉 = **统一黑色边框**，成交量越大越粗（不做白边、不做圆点）。

  **实现**：
  - `web/config.js` 新增 `heatmap.volumeBorder{enabled,color,maxRatio:0.35,minPx}`
  - `web/heatmap.js::buildOption` 读 `block.volumes` → 逐格 `itemStyle.borderWidth`，
    `volMax` 取**本视口内**最大值，宽度锚在格子**短边**（锚长边时窄行上下边框会吃穿）
  - **补齐三条变换链路的 volumes 传递**（此前三处都丢，只有 `app_render.js::applyViewport` 保留了）：
    `period_align.js::sliceZones`（复用同一 `picked`）、`period.js::aggregate`（组内求和）、
    `period.js::clipTail`（同一个 `drop`）
  - 注释去重：`contracts/feature.py` 原写"tick 数多 = **圆点大**"、`matrix_codec.js` 写"不画圆点"、
    shader 画白边 —— 三种说法已统一为"黑色边框越粗"

  **实测（`tmp/vol_border_probe/`，Playwright + Chrome 153，像素级）**：
  受控设计 = 同一列内 volume 随行递增（vol 0→10）、**水平位置固定** ⇒ 排除位置伪影；`values` 全 0。

  | 模式 | 带宽（vol 0→2→…→10） | 极差 | 判定 | RC |
  |---|---|---|---|---|
  | `on`（生产配置） | 1.00 → 2.81 → 5.13 → 7.38 → 9.56 → 11.81 px | **11.00 px** | PASS | 0 |
  | `off`（只关 `volumeBorder.enabled`） | 恒定 1.00 px | 0.00 px | FAIL | 1 |

  **非空转**：两份跑的是**同一份 `web/heatmap.js`**，唯一差异是一个开关 ⇒ 相反判定。
  另有**真帧端到端**（`real.html`）：用后端 `HeatmapSerializer` 铸帧 → `SWATCH_MATRIX.decode`
  → 渲染，断言 `volumes` 逐值一致、`values` 往返误差 < 1e-6 ⇒ 全过。

  **回归已补**（这是本条的重点：此前"没有任何回归守着"）：
  `tools/check_period_aggregation.py` + `tools/period_reference.py` 新增 13 条 volumes 逐值对拍
  （aggregate 7 档 × / clipTail / sliceZones 4 组）。**变异验证**：从 `period.js` 删掉 2 处传递
  ⇒ `aggregate(g2…g200)` 与 `clipTail` 全转 FAIL；从 `period_align.js` 删 1 处 ⇒ `sliceZones(gth/rth/gth+rth)`
  全转 FAIL；还原后复绿。`g1` 与 `keep=none` 变异后仍 ok 属正确（走恒等分支，原样返回整块）。

  **性能代价（实测，画布 1400×520 / 24 行 / 27% 填充）**：

  | 列数 | off | on | 增量 |
  |---|---|---|---|
  | 630（默认 1 分档） | 57.4 ms | 88.0 ms | +53% |
  | 1352 | 86.1 ms | 140.7 ms | +63% |
  | 2370（30 秒档全时段） | 135.9 ms | 273.5 ms | **+101%** |

  节拍 = 后端推送 400 ms ⇒ 最坏 273.5 ms 仍**在预算内**（占用 68%，此前 34%）。
  ⚠️ 若日后把推送提到 2 Hz 以上，这里会先撞线。

  **契约清单为何没加 volume 字段**：`vol_bm`/`vol_i16` 是**可选字段**（后端只在 `matrix.volumes`
  非空时才发），而 `check_web_contract.py` 的语义是"键缺失算失败" ⇒ 加进去会让合法帧误报。
  已在 `PAYLOAD_PATHS` 处写明理由，并指向上面那两个守它的检查器。

  **同类排查（2026-09-15 05:0x 顺带做完，已封口）**：`tmp/audit_dead_payload.py`
  把 `serialization/` 的 82 个键名逐个在 `web/` 里按词边界搜 ⇒ 17 个零命中。
  逐个定性后 **16 个是"前端从不解码的诊断元数据"，属设计**：
  - `health.rate_limit.*` / `health.sub_limit_backoff` —— skill `spxw-live-verify/references/live-link.md`
    第 53-58 行明写这是**抓帧排查读数**（`f["health"]["rate_limit"]`），前端本就不显示
  - `health.ticks_received` / `ticks_dropped`、`session.date` / `is_open`
  - `cells.quality` / `delta_iv` / `primary_impulse` —— 前端不画 cells 表格
  - `skew.series.put25_strike` / `call25_strike` / `atm_delta` / `quality` —— 前端只画曲线

  **判据（唯一可靠）**：看**前端是否为它写过代码** ——
  写了却不用 = 掉地；从没写 = 不需要。按这条判据，**`volumes` 是唯一一处**：
  `matrix_codec.js:101-126` 专门解码它、`app_render.js:27` 在 viewport 缩放时专门
  切片搬运它 —— 数据流一路维护到最后，却没有任何渲染器接。
  ⇒ **本项是同类缺陷里的孤例，不是普遍现象。**
  ⚠️ 反向检查（"后端发的字段前端是否都读"）**不可**固化成常驻门禁 ——
  上面 16 个合法的不读会让它满屏误报（同 `frontend.md` 文末"不要把前端探针
  固化成常驻回归"的理由）。该排查是**一次性取证**，脚本留 `tmp/`。

  **遗留**：`splitLine` 抽样网格**保留**（细档位 30 秒档格宽约 0.44 px，逐格边框等比缩到
  亚像素必然不可见，去掉它等于回归掉 2026-09-14 修的"密集区看不见网格"）。两套线颜色都在
  深色端，粗档位下逐格边框在上层盖住 splitLine，不冲突。**待盘中肉眼确认**实际观感。

  **同类排查（2026-09-15 05:0x 顺带做完，已封口）**：`tmp/audit_dead_payload.py`
  把 `serialization/` 的 82 个键名逐个在 `web/` 里按词边界搜 ⇒ 17 个零命中。
  逐个定性后 **16 个是"前端从不解码的诊断元数据"，属设计**：
  - `health.rate_limit.*` / `health.sub_limit_backoff` —— skill `spxw-live-verify/references/live-link.md`
    第 53-58 行明写这是**抓帧排查读数**（`f["health"]["rate_limit"]`），前端本就不显示
  - `health.ticks_received` / `ticks_dropped`、`session.date` / `is_open`
  - `cells.quality` / `delta_iv` / `primary_impulse` —— 前端不画 cells 表格
  - `skew.series.put25_strike` / `call25_strike` / `atm_delta` / `quality` —— 前端只画曲线

  **判据（唯一可靠）**：看**前端是否为它写过代码** ——
  写了却不用 = 掉地；从没写 = 不需要。按这条判据，**`volumes` 是唯一一处**：
  `matrix_codec.js:101-126` 专门解码它、`app_render.js:27` 在 viewport 缩放时专门
  切片搬运它 —— 数据流一路维护到最后，却没有任何渲染器接。
  ⇒ **本项是同类缺陷里的孤例，不是普遍现象。**
  ⚠️ 反向检查（"后端发的字段前端是否都读"）**不可**固化成常驻门禁 ——
  上面 16 个合法的不读会让它满屏误报（同 `frontend.md` 文末"不要把前端探针
  固化成常驻回归"的理由）。该排查是**一次性取证**，脚本留 `tmp/`。

## Stale / Needs Verification

- [ ] **`check_reconnect_gap.py` 的假冲量场景未在真实断线下复现** ——
      "断线 >900s 时两道毛刺闸门因样本被裁双双失效"仍是静态分析结论。
      （`reset_feature_state_on_reconnect=false` 是**刻意默认值**，不是缺陷。）
- [ ] **`ibkr.max_underlying_age_s` 与重连清状态的真实断线场景未确认** ——
      2026-09-11 接线时只在单元/生命周期层面验证过，需 TWS / IB Gateway 实测。
- [ ] **`tools/fixtures.py::SyntheticSurface` 是简化曲面** —— 只保证确定性，
      不保证与真实 IV 曲面同形。依赖它的 `check_side_flip` 只验结构性事实，
      但**后续若有人拿它做数值断言会得到与实盘不符的结论**。
- [ ] **ib_async 合并 tickType 13/83** —— `TickRouter.source_tick_type` 恒为 13
      （名义值），属性层无法区分实时模型与延迟模型 greeks。
- [ ] **`git fetch` 在本环境不落地 remote-tracking ref（根因未定位）** ——
      `git fetch` 退出 0、输出 `[new branch] main -> origin/main`、并写了
      `.git/logs/refs/remotes/origin/main`，但 `refs/remotes/origin/main` **不存在**；
      手动建好后**下次 fetch 又被删**。全环境**无任何 prune 配置**；
      对照仓库 `live-volatility-surface` 正常。**不影响提交/推送**
      （`git ls-remote` 已核实远端 = 本地 HEAD），只让 `git status -sb` 显示 `[gone]`。
      需 KAI 在自己终端复现一次才能判定是否为工具沙箱侧现象。

## 已决策（KAI）—— 不要再当待办重提

- **RTH 收盘 = `16:00`，不是 Cboe 官方页写的 `4:15 PM`**（2026-09-13 KAI 明确）——
  理由：**KAI 只在正股的 RTH 时间（09:30–16:00）交易**，网格按自己的交易时段切。
  与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**，不要再提。
- **不设任何验收自动任务**（2026-09-13 KAI 明确）—— 由 KAI **手动在 GTH 时段验证**。
  此前记录的"定时任务不见了"**是预期行为**（KAI 有意不让它存在），
  不是工具缺陷，不要再当 bug 排查、也不要再重建。
- **限速桶读数不上前端**（数据已到帧 `health.rate_limit`，`web/` 刻意不动）。
- **IV 热力图 ΔIV ≈ 0 不退回中性色** —— 维持 `Turbo` **顺序**色阶
  （0 = 亮黄绿 `#a4fc3b`）。理由：忠实参考项目截图 + 原指令就是"只改色调"。
- **冷数据键序也统一为降序**（2026-09-13 复核时 KAI 选定）—— 与帧 `strikes` 同向。
  `dump_bucket()` 改 `sorted(..., reverse=True)`，回归
  `check_persistence.py::_case_key_order_descending`。
- **`web/*.js` 已拆分完成**（2026-09-13）—— `app.js` / `skew.js` / `period.js` 三文件
  拆分为 9 个模块，全部 < 400 行；`--check` `[1]` 全绿 `RC=0`。
  `.js` 只进 `[1]`，不进 AST 类检查（`[2][9][10]`）。
- **同族守卫缺口已修**（2026-09-13）—— `check_period_aggregation.py` 与
  `check_skew_alignment.py` 已接入 `tools/group_guard.py`，`--selftest` 各自抓全
  守卫 2 条用例 + 全部变异。`group_guard.py::prefixes` 契约 = `tuple[str, ...]`
  （不要传 `str`）。
- **`~/.workbuddy-ai/tmp/` 40 个历史探针推迟到下一个会话**（2026-09-13 KAI 拍板）—— 动
  用户目录需明令。已登记 `Active` 段，待下一会话开清单。
- **临时探针落点 = `<项目根>/tmp/`**（2026-09-13 KAI 拍板）—— 不再写用户级
  `~/.workbuddy-ai/tmp/`（那个被所有项目共用、已串味）。配套：**必须在
  `.gitignore` 与 `NON_SOURCE_DIRS` 两处登记**；探针用完即弃，判据要落成常驻回归。
- **`check_web_contract.py` 的 `import aiohttp` 不内移**（2026-09-13 复核时 KAI
  未选）—— 保持顶层 import 原样，静态两段仍靠桩模块离线补跑。
- **`notes/` 与 `.workbuddy-ai/memory/` 的分工**（2026-09-13）：
  `notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`），
  `memory/` 为根路由器（只留指针与跨项目约定）。**同一事实只写一处。**
- **色板缺机械回归 = 不做**（2026-09-13 KAI 明确）—— 前端是空壳，色彩映射由后端值驱动；
  色值变更的责任在后端，不需要前端做机械回归。从 Active 剔除。
- **`check_clock_protocol.py` 已并入 `--check` 常驻**（2026-09-13 KAI 批准）——
  作为 `[12]` 检查项，验证三个时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
- **联通与限速已并入 `--check` 常驻**（2026-09-13 KAI 批准）—— 作为 `[13]` 检查项，
  `selfcheck_connectivity.py`：若 8060 有服务则连 WS 抓帧校验结构；无服务时跳过（warning，
  非交易日预期），不视为失败。
