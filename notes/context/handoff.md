# Handoff Index
- Latest session: 2026-09-14/webgl-to-echarts
- Current session handoff: notes/sessions/2026-09-14/webgl-to-echarts/handoff.md
- Archive: notes/context/archive/handoff_2026-09.md
- Status: **热力图渲染器由原生 WebGL 换成 ECharts；改动未提交** ——
  ① **根因**（KAI 报"绿色周围黑色色块"）：`gl_heatmap.js:157-165` 把调色板绑在 TEXTURE1，
  `:261-270` 首次 `update()` 未先 `activeTexture(TEXTURE0)` 就 `bindTexture(_dataTex)`
  ⇒ **数据纹理顶掉调色板** ⇒ `u_palette` 采到数据纹理中间行：有效格 `(R,255,0)` 绿、
  落在空格 `(0,0,0)` 黑。**"换任何色都不生效"由此解释。**
  （另查明 `web/config.js:28-34` 的 palette **本来就是**逐色抄自参考项目的 Plotly Turbo
  ⇒ 颜色配置一直是对的，坏的是渲染器没采样它。）
  ② **KAI 裁定换掉原生 WebGL**；库定为 **ECharts**（已内置且 Skew 在用 ⇒ 零新增依赖；
  `af2e2e4` 之前本就是 ECharts）。`web/heatmap.js` 整文件重写（266 行，公共接口不变 ⇒
  `app.js`/`app_render.js` 零改动，手写 overlay 全删）；`web/gl_heatmap.js` **删除**；
  `web/index.html` 去标签；`web/test_gl.html` → `web/test_heatmap.html`；`web/test_sync.html` 补 echarts；
  `web/config.js` 网格线注释改写为 ECharts/splitLine 语义。
  ③ **代价（实测、KAI 知情接受）**：ECharts 单次重绘 630 列 65.7ms / 1352 列 159.9ms /
  2370 列 188.1ms，旧 WebGL 0.6/1.0/1.3ms；节拍 2.5Hz ⇒ 宽档位吃 **40–47% 单核**。
  `progressive` 是负优化（2370 列 424ms）⇒ 恒设 0。
  ④ **验证**：`run.py --check` **`RC=0`**；`check_web_syntax` / `check_web_contract` `RC=0`；
  `check_page_render --budget 60000` 热力图/Skew/canvas≥2/现价全 ok；真实页面取色
  `nearBlackPixels: 0` / **516** 色桶 / 2 canvas；**非空转**：palette 改品红 ⇒ 色桶 553→37、绿色全消失，
  还原后 md5 逐字节回到 `eae7e64f694a2f15679be190b936e0f0`。
  ⑤ ⚠️ **事故**：执行 `git rm` / `git mv` 期间**整个 `web/` 目录从工作区消失**（成因未查明），
  `git checkout -- web/` 恢复；未提交的 `config.js` / `skew.js` 改动为**按记录重建**（非逐字节还原）。
  ⇒ **本仓库禁用 `git rm` / `git mv`，改用 `rm` / `mv` + `git add`。**
- Previous: 2026-09-14/heatmap-mirror-ffill-grid
- Previous handoff: notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/handoff.md
- Previous status: **热力图渲染三处修正已落地，且已重启进程、实测生效；改动未提交（21 M + 7 ??）** ——
  ① **上下镜像**（KAI 未报，排查中挖出）：`gl_heatmap.js::update()` 里 `tr = rows-1-r`
  把行序反了两次 ⇒ 屏幕第 i 行 = 帧第 rows-1-i 行。已改为按帧行序直写 texture + 契约注释。
  ② **20:15 起满宽假 0 带**（KAI 报）：`persistence.py::recover()` 读全部桶 → `load_snapshot()`
  → `_row_values()` **无上限**前向填充 ⇒ 孤桶被一路沿用。新增
  `config/serialization.json::heatmap_max_ffill_buckets`(20 = 10 分钟)，超限留白；
  常驻回归 `check_reconnect_gap.py::case_long_gap_is_blanked` + `--selftest` 两处注入，实测两例变红。
  ③ **细档位无纵线**（KAI 报）：1 分档 630 列 ⇒ 格宽 2.40px，被上一轮 `>=3.0` 双侧阈值整方向跳过。
  改为单侧**自适应步长** `stride = ceil(u_borderMinPx / cellPx)`（线仍落真实格边界），
  新增 `web/config.js::heatmap.cellBorderMinPx = 5`（当时语义为**物理像素**；换 ECharts 后改为 **CSS px**）。
  实测 1 分档中位线距 5.0px / 653 条；变异置 0 ⇒ 塌成密纹。
  ④ **重启进程**（KAI 指令，2026-09-14 07:19）—— `run.py` 是父子两进程、只认 Ctrl-C
  ⇒ 硬杀；停后 `integrity_check=ok`、334 行不变；重启 `07:19:59 流水线已就绪`。
  **上限生效实测**：row 19（7575）由 `first=1 / nonnull=1308` → `[(1,20),(449,554),(706,726),(1065,1331)]`
  ⇒ 假 0 带 **1308 列 → 20 列**。
  `run.py --check` **`RC=0`**（13/13）；`check_reconnect_gap` 正常 + `--selftest` 均 `RC=0`。
  ⚠️ **残留**：`recover()` 未过滤 ⇒ bucket 0 本身仍在（带未归零，只是 ≤10 分钟）。
  详见会话根。
- Previous: 2026-09-14/b2b-spot-synthesis
- Previous handoff: notes/sessions/2026-09-14/b2b-spot-synthesis/handoff.md
- Previous status: **实现完成，未提交（14 M + 7 ??）** —— KAI 5 条拍板全部落地：新增 `config/spot.json`、
  `acquisition/spot_synthesis.py`（B2b 反解 `ĉ` + 两层闸门）、`acquisition/spot_source.py`
  （按区段选源）、`core/session_grid.py`（从 `clock.py` 拆出几何以守住 <400 行）。
  09:25 交班切回指数、窗口重建由既有 `WindowFollower` 自动完成（锚跳 8.15 档 > trigger 3 档），
  未加特殊代码。`--check` 基线回绿 **RC=0**（修复前 RC=1 / 2582 项，venv 改按 `pyvenv.cfg` 识别）。
  端到端冒烟：实盘现货 = 合成值 **7620.26**，同期 IBKR 指数冻结在 7656.98 ⇒ 合成确实生效。
  6 个既有失败回归经 HEAD worktree 对照确认非本轮引入。详见会话根。
- Previous: 2026-09-14/gth-spot-basis-research
- Previous handoff: notes/sessions/2026-09-14/gth-spot-basis-research/handoff.md
- Previous status: **只读调研，未改代码** —— GTH 现货基准业界做法调研 + B2/B3 判别实验，
  输出 KAI 拍板依据（主口径 B2b）。当时遗留的 `--check` RC=1 已在本轮修复。
- Previous: 2026-09-13/web-js-gate-and-probe-governance
- Previous handoff: notes/sessions/2026-09-13/web-js-gate-and-probe-governance/handoff.md
- Previous status: **`web/*.js` 已拆分完成 + `[1]`–`[13]` 全绿 + Skew 三项修复落成常驻回归 + 探针落点治理 + 时钟/联通并入常驻**：
  ①`app.js`/`skew.js`/`period.js` 三文件拆分为 9 个模块，全部 < 400 行；
  `iter_web_scripts()` 按目录枚举，`[1]` 扫 **98** 个文件（84 `.py` + 14 `web/*.js`）
  全部合规；②新建 `tools/check_skew_viewport.py`（394 行，`[G1]`–`[G4]`
  共 21 项判据 + 6 条变异），把上一轮只在一次性探针里的三项修复固化成常驻回归；
  ③删除死代码 `SkewPanel.prototype.stats()`（`skew.js` 540 → 536 → 拆后 239）；
  ④临时探针落点定为 **`<项目根>/tmp/`**，在 `.gitignore` + `NON_SOURCE_DIRS` 两处登记。
  ⑤**自查中抓到一个真缺陷并修掉**：`check_skew_viewport.py` 的"判据集合不完整"守卫
  期望集合由 `GROUPS` **自推** ⇒ 删掉一组后该组失败被**静默吞掉、`RC` 仍 0**
  （实测删 `[G4]` ⇒ 3 条失败被吞）；抽出 `tools/group_guard.py`（期望前缀 = 独立常量
  + 三条都查 + `guard_cases` 自证）。同族缺口已修：`check_period_aggregation` /
  `check_skew_alignment` 已接入 `group_guard.py`，`--selftest` 各自抓全。
  ⑥**`check_clock_protocol.py` 并入 `--check` 常驻 `[12]`**（KAI 批准）——
  验证时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
  ⑦**联通与限速并入 `--check` 常驻 `[13]`**（KAI 批准）——
  `selfcheck_connectivity.py`：8060 有服务则连 WS 抓帧校验；无服务跳过（warning）。
  终态：`run.py --check` **`RC=0`**（13 项全通过、关键配置项 **40**）；
  全量 **18** 个工具 **14 `RC=0`** / 4 `RC=1`（与基线一致：缺 `ib_async`/`aiohttp`/无 8060/非本项目页面）；
  `check_skew_viewport --selftest` **6 条变异 + 守卫 2 条用例全抓**；
  `check_skew_alignment --selftest` 4 条变异全抓（沙箱抽出未破坏既有回归）。
  ⚠️ **本会话改动未提交**；真实链路渲染仍未验证（周日 fail-closed），
  由 KAI 手动在 GTH 时段验收。
- Previous: 2026-09-13/skew-zoom-yscale（notes/sessions/2026-09-13/skew-zoom-yscale/handoff.md）
- Previous: 2026-09-13/recheck-keyorder-memory（notes/sessions/2026-09-13/recheck-keyorder-memory/handoff.md）
- Previous: 2026-09-13/skew-period-consistency（notes/sessions/2026-09-13/skew-period-consistency/handoff.md）
- Previous: 2026-09-13/frame-strike-order-descending（notes/sessions/2026-09-13/frame-strike-order-descending/handoff.md）
- Previous: 2026-09-13/cold-data-strike-order（notes/sessions/2026-09-13/cold-data-strike-order/handoff.md）
- Previous: 2026-09-13/live-verify-and-release（notes/sessions/2026-09-13/live-verify-and-release/handoff.md）
- Previous: 2026-09-13/notes-dedup-tiering（notes/sessions/2026-09-13/notes-dedup-tiering/handoff.md）
- Previous: 2026-09-13/simulator-hard-cut（notes/sessions/2026-09-13/simulator-hard-cut/handoff.md）
- Previous: 2026-09-11/model-greeks-landing-verified（notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md）
- Previous: 2026-09-11/record-reconciliation（notes/sessions/2026-09-11/record-reconciliation/handoff.md）
- Previous: 2026-09-11/iv-heatmap-turbo-palette（notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md）
- Previous: 2026-09-11/ibkr-rate-limit-audit（notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md）
