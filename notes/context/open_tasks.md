# Open Tasks

Archive: notes/context/archive/open_tasks_2026-09.md

## Active

- [ ] **[中] 假 0 带残留：bucket 0 本身仍被恢复**（2026-09-14）——
  重启后实测：假 0 带已从 **1308 列缩到 20 列**（= `heatmap_max_ffill_buckets` 上限），
  但 `features/persistence.py::recover()` 仍读 `heatmap_buckets` **全部行**
  （无时间窗/运行期过滤）⇒ 那条带**没归零**，只是从 ~9 小时变成 ≤10 分钟。
  彻底消除需在 `recover()` 只取**最后一段连续桶**；KAI 上一轮**未选**该方案
  （理由与两条被否选项见 `notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/project_state.md`）。
  ⚠️ 判据不是"带上还有颜色"，而是活帧最低几档的**非空列分段**是否恰好等于上限桶数
  （实测 `[(1,20),(449,554),(706,726),(1065,1331)]` ⇒ 20 ✓）。

- ~~**[中] 细档位纵线（自适应步长）未做高 dpi 实测**~~ —— **已作废**（2026-09-14）。
  热力图渲染器换回 ECharts 后，网格线改走轴 `splitLine`，`cellBorderMinPx` 的单位随之
  由**物理像素**变为 **CSS px**（ECharts 的坐标单位），"高 dpi 下 stride 翻倍"的问题**不再存在**。
  新语义见速查卡 L。

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

- [ ] **[中] 交易日 RTH 段实盘验证（B2b 落地的最后一块）**（2026-09-14）——
  GTH 段已由端到端冒烟证明（现货 = 合成值 7620.26，指数冻结 7656.98）。
  待验：① 09:30 后指数是否真的恢复实时（而非继续冻结）；② 09:25 交班切源是否平滑、
  窗口是否按预期重建；③ RTH 段是否确实走指数而非合成。
  无自动化验收（承接 KAI 既有决策：**不设验收自动任务**，由 KAI 手动在盘中确认）。

- [ ] **[中] `check_period_aggregation.py` 既有失败 —— 根因已定位**（2026-09-14）——
  `RC=1`，报 `TypeError: P.sliceZones is not a function`。根因：`sliceZones` 已在
  2026-09-13 的前端拆分中从 `web/period.js` 挪到 `web/period_align.js`，
  而该回归的 node 驱动仍只加载 `period.js`。
  已用 `git worktree add -f tmp/head_tree HEAD` 复现 ⇒ **HEAD 上同样 RC=1，非本轮引入**。
  修法明确（驱动补加载 `period_align.js`），但属"重构现有工具"，**未获指令不擅自动**。
  同族：`check_page_render` / `check_skew_alignment` / `check_skew_viewport` /
  `check_web_contract` / `check_ws_compression` 共 6 个既有失败，均已 HEAD 对照确认。

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

- [ ] **[中] 实盘首次出图未验证** —— **部分验证完成**（2026-09-13）。
  KAI 启动 IB Gateway，系统实际跑通：
  - ✅ `mode=delayed`（周日正确）
  - ✅ **48 条订阅**（±12 档 × Put/Call）
  - ⚠️ SPX 现价 **7591.70** —— **该数字作废**（2026-09-14 更正：那是被驳回算法的产物）。
    探针实测 IBKR 在 GTH 给的 SPX 指数 = **7656.98**（周五收盘，恒定）。
  - ✅ WS 帧流正常（seq 1→5，0 缺口）
  - ✅ `health.rate_limit` 四要素（桶 45/s）
  - ✅ 网格 **2370 桶**，3 区段（GTH/空档/RTH），铺满无缝隙
  - ⚠️ 热力图出图、Skew 数据、按钮切换、横轴对齐 —— **需浏览器肉眼确认**
  - ⚠️ 周日市场关闭，`Skew=None` / 热力图 0 格 = **预期行为**，不是缺陷
  ✅ **由 KAI 在 GTH 时段手动验证前端渲染**（2026-09-13 KAI 明确：不要设置自动任务）。

- [ ] **[中] 4 个需服务的检查 — 1/4 已跑通** —— 
  - ✅ `ws_probe`（2026-09-13）：23/27 通过，4 项失败全部是周日市场关闭预期行为
  - ❌ `check_web_contract` / `check_page_render` / `check_ws_compression` —— 仍需盘中复跑
  ⚠️ 2026-09-13 `multi-session-grid` 会话中，`check_web_contract` 的**三段**都已用
  **离线等价物**补验（第 1、2 段用桩模块绕过顶层 `import aiohttp`：
  DOM id 22 个 / CFG 路径 32 条全存在；第 3 段用真实流水线造帧：
  **61/61** 载荷路径命中，含新增的 `session.zones` 及其 5 个子路径）。
  ⇒ 三段都覆盖过，**但走的都不是它自己的入口**（被顶层 `import aiohttp` 挡住）。
  盘中仍应用它本身的入口复跑一次。

- [ ] **[低] `check_web_contract.py` 顶层 `import aiohttp`** 使第 1、2 段
  （纯静态对照）也无法在无 aiohttp 的环境运行。是否把 import 挪进函数内
  **待 KAI 定** —— 改动小，但属"重构现有工具"，未获指令不擅自动。

- [ ] **[低] `~/.workbuddy-ai/tmp/` 下约 40 个历史探针未迁移** ——
  新约定落点已是 `<项目根>/tmp/`，但历史文件仍在用户级目录（被所有项目共用）。
  KAI 2026-09-13 拍板：**下一个会话做**（"代办"）。本轮不动用户目录。
  ⇒ 开始前先列清单（按 mtime / 大小 / 是否含 `import`），让 KAI 一眼能拍"全迁/部分迁/只登记不动"。

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
  单位坑见速查卡 L；高 dpi 实测仍是待办。

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
