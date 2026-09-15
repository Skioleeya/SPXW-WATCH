# Project State

ACTIVE_SESSION: 2026-09-15/persistence-session-files
LAST_UPDATED: 2026-09-15 03:5x —— **持久化落点改为一交易日一文件 + 历史归档不删**，
已提交并推送（`HEAD = 53da940`，工作区干净）。见
`notes/sessions/2026-09-15/persistence-session-files/handoff.md`。
⚠️ **本文件正文（§10 之前）仍是 2026-09-14 的快照**，其中"改动未提交"等陈述
指的是当时那一刻，**不是现状**；现状以上面这行与 `notes/context/handoff.md` 为准。
ARCHIVE: notes/context/archive/project_state_2026-09.md

<!-- ↓↓↓ 以下为 2026-09-14 webgl-to-echarts 会话的历史快照，不 retro-fit ↓↓↓ -->

**本会话（webgl-to-echarts，2026-09-14）**：热力图渲染器换栈。
① **根因**（KAI 报"绿色周围黑色色块"）：`web/gl_heatmap.js:157-165` 把调色板绑在 TEXTURE1；
`:261-270` 首次 `update()` **未先 `activeTexture(TEXTURE0)`** 就 `bindTexture(_dataTex)`
⇒ 数据纹理顶掉调色板，此后 `pal` 再未被绑回 ⇒ `texture2D(u_palette, vec2(t,0.5))` 采到的是
**数据纹理中间行**：有效格 `(R,255,0)` 绿、落在空格 `(0,0,0)` 黑 —— 一个根因同时解释绿与黑，
也解释"换色不改渲染"。**这不是 WebGL 的 bug，是我方绑定顺序写错。**
② 另查明 `web/config.js:28-34` 的 `palette` **本来就是**逐色抄自参考项目
`live-volatility-surface` 的 Plotly `Turbo` ⇒ **颜色配置一直是对的**，坏的是渲染器没采样它。
③ **KAI 裁定换掉原生 WebGL**；库定为 **ECharts**（已内置且 Skew 在用 ⇒ 零新增依赖；
`af2e2e4` 之前的热力图本就是 ECharts；Plotly 要新增 ~3.5MB 且同为逐格绘制，不占优）。
`web/heatmap.js` 整文件重写（266 行，公共接口不变 ⇒ `app.js`/`app_render.js` 零改动，
手写 overlay 全删）；`web/gl_heatmap.js` **删除**（283 行）；`web/index.html` 去 script 标签；
`web/test_gl.html` → `web/test_heatmap.html`；`web/test_sync.html` 补 echarts；
`web/config.js` 网格线注释改写为 ECharts/splitLine 语义。
④ **关键映射（避免被当成自创）**：参考项目用 Plotly `xgap=1/ygap=1` 做格子间隙，ECharts 无等价项
⇒ 改用轴 `splitLine` + `interval = stride-1` 抽样画线；`cellBorderMix` → 线的 **opacity**
（`opacity m` 叠在数据色上 ≡ 旧 shader 的 `mix(color,border,m)`，数学等价 ⇒ 两个键都非死配置）。
`yAxis.inverse: true` 保证帧行序（降序行权价）第 0 行落在屏幕最上方。
⑤ **代价（实测、KAI 知情接受）**：ECharts 单次重绘 630 列 65.7ms / 1352 列 159.9ms /
2370 列 188.1ms，旧 WebGL 0.6/1.0/1.3ms；节拍 2.5Hz ⇒ 宽档位吃 **40–47% 单核**。
原始画布 `fillRect` 地板 9.5/21.3/40.5ms ⇒ 额外开销在 JS 侧逐格处理，**换 GPU 降不下来**。
`progressive` 是负优化（2370 列 424ms > 不开 188ms）⇒ 恒设 0。
⑥ **验证**：`run.py --check` `RC=0`；`check_web_syntax` / `check_web_contract` `RC=0`；
`check_page_render --budget 60000` 全 ok；真实页面取色 `nearBlackPixels: 0` / 516 色桶 / 2 canvas；
截图 `tmp/after_echarts_final.png`。**非空转**：palette 15 色改 `#ff00ff` ⇒ 色桶 553→37、绿色全消失，
还原后 md5 逐字节回到 `eae7e64f694a2f15679be190b936e0f0`。
⑦ ⚠️ **事故**：执行 `git rm -f web/gl_heatmap.js && git mv ...` 期间**整个 `web/` 目录从工作区消失**
（`git status` = ` D web/*.js` ×17 + `D  web/gl_heatmap.js`），`git mv` 报 `fatal: bad source`；
**无任何命令显式删除目录，成因未查明**。`git checkout -- web/` 从索引恢复，但未提交的
`web/config.js` / `web/skew.js` 改动丢失、只能**按记录重建**（`skew.js` 以 `grep -c itemStyle`=8、
`itemStyle`/`lineStyle` 5/5 同值收口；`config.js` 重建版比原版长 142 字节，**非逐字节还原，不作宣称**）。
⇒ **纪律：本仓库禁用 `git rm` / `git mv`，改用 `rm` / `mv` + `git add`。**
完整记录见 `notes/sessions/2026-09-14/webgl-to-echarts/`。

CURRENT_STATE: **spxw_swatch 纯实盘已落地，`ib_async`/`aiohttp` 已装，Gateway 链路验证通过；
`[1]`–`[13]` 全绿；Skew 面板无限制缩放 + 视口自适应；`web/*.js` 全部 < 400 行**。
模拟盘（`simulator/` + `config/simulator.json`）已物理删除，无特性开关、无兼容分支、无回退路径。
**交易日网格 = GTH 20:15→次日 09:25 + 空档 09:25–09:30 + RTH 09:30→16:00**，跨午夜，
71100s ÷ 30s = **2370 桶**；会话真相只有一处（`config/app.json::sessions`），
区段表随帧下发到 `session.zones`。
**Skew 纵轴量程 = 当前可见列内极值 ∪ {0} + 留白**（`web/skew.js::axisRange`）——
`skew.scale_policy` / `skew_scale_window_seconds` 已**全链路删除、无兼容分支**；
修掉"缩放到早盘段 ⇒ 整屏空白且不报错"的静默失效（改前 21/21 点越界 → 改后 0/21）。
同一轮另收三项：**图例补全**（两条 skew 曲线改用不同 series name + `legend.formatter`
同名显示 ⇒ 图例上两条 `25Δ Skew`，一暖一冷）、**刻度精度收进
`web/config.js::skew.axisDecimals`**（原硬编码 `toFixed(1)`）、**meta 读数随视口收窄**
（`_readout()` 按可见列算 + `setViewportHook` 让缩放立刻重写 meta）。
浏览器稽核 **26 项全绿**；4 条变异逐条摘掉修复**全部被抓**。

**本会话（heatmap-mirror-ffill-grid，2026-09-14）**：热力图渲染三处修正。
① **上下镜像**（KAI 未报，排查中挖出）—— `web/gl_heatmap.js::update()` 写
   `var tr = rows - 1 - r;`（注释称 "inverse Y"），而 shader 的天然映射是"屏幕顶 = texture 行 0"、
   HTML overlay 的标签/现货线也从索引 0 起 ⇒ **行序被反了两次**，整张图上下镜像。
   修法：去掉 `tr`，按帧行序直写 texture + 契约注释"帧行序 ≡ texture 行序，**不要再反转**"。
② **20:15 起满宽"假 0 带"**（KAI 报）—— `features/persistence.py::recover()` 读
   `heatmap_buckets` **全部行** → `load_snapshot()` → `_row_values()` 的 `carried`
   **无上限前向填充** ⇒ 孤桶被一路沿用，拉出满宽 `ΔIV=0` 的亮黄绿带，与真"IV 没变"无法区分。
   修法：新增 `config/serialization.json::heatmap_max_ffill_buckets`(20 = 10 分钟，
   取 `heatmap_feed_gap_s`(300s) 的 2×)，`HeatmapEngine` 加 `_max_ffill` slot，
   `_row_values()` 用 `last_seen` 记账、超限输出 `None`。
③ **细档位无纵线**（KAI 报，看着是长条）—— 1 分档 630 列 ⇒ 格宽 2.40px，
   被上一轮 `>= 3.0` 的**双侧**阈值判为"太窄"、纵线整方向跳过。
   修法：单侧**自适应步长** `stride = ceil(u_borderMinPx / cellPx)`（线仍落**真实格边界**，
   `stride=1` 退化为旧行为），新增 `web/config.js::heatmap.cellBorderMinPx = 5`（**物理像素**）。
两处非空转：镜像改回 `rows-1-r` ⇒ 满宽行跑回顶部（`tmp/mut_mirror.png`）；
纵线置 `minPx=0` ⇒ 塌成密纹、扫描线仅检出 0–9 条。
`check_reconnect_gap.py` 新增 `case_long_gap_is_blanked`（阈值从 config 读），
`--selftest` 扩为两处注入 ⇒ 实测两例变红。1 分档实测 **653 条纵线 / 中位线距 5.0 px**。
**重启（KAI 指令，07:19）**：`run.py` 是**父子两进程**（venv 存根 ~8MB 父 + 真实解释器 ~100MB 子），
只认 Ctrl-C（`Pipeline.stop()` 打印 `已停止`），**无 HTTP / 文件 / 信号停机入口** ⇒ 硬杀。
硬杀安全（SQLite `journal_mode=delete` + `_batch_write()` 每批 commit ⇒ 最多丢一批；
`recover()` 会把已提交桶捞回），停后 `integrity_check=ok`、334 行不变。
重启 `07:19:49` → 恢复 **335** 个历史桶 → `07:19:59 流水线已就绪`。
**上限生效实测**（活帧逐行非空列分段）：row 19（7575）由 `first=1 / nonnull=1308`
变为 `[(1,20),(449,554),(706,726),(1065,1331)]` ⇒ 假 0 带 **1308 列 → 20 列**（= 上限）；
对照 row 2（7660）无 `(1,20)` 段 ⇒ 修的是**带**，真实数据未动。
流程已沉淀进 `spxw-live-verify`（SKILL.md §5 + `references/pitfalls.md` 第 11 条）。
**残留**：`recover()` 未过滤 ⇒ bucket 0 本身仍在，带**未归零**（≤10 分钟）。
完整记录见 `notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/`。

**上一会话（frontend-render-fix-and-skill-split，2026-09-14）**：修掉 KAI 报的两个前端渲染缺陷。
① **热力图"网格线"消失** —— 真正的"网格线"是旧 ECharts 版每格的
   `itemStyle: { borderWidth: 1, borderColor: CFG.theme.grid }`，`af2e2e4` 的 WebGL 重写把它删掉
   且未在新引擎实现 ⇒ `theme.grid` 成**死配置**（`grep -rn "theme\.grid" web/` 零引用）。
   修法：fragment shader 补逐格边框（新增 `u_cellBorder`/`u_resolution`/`u_borderMix` +
   `setCellBorder()`），`config.js` 新增 `heatmap.cellBorderMix: 0.55`，边框色复用 `theme.grid`。
   ⚠️ **两个方向必须独立判断**：某方向格子 < 3 物理像素时不画 —— 否则
   `bw = 1/cellPx ≥ 0.5` 会让 `localX<bw || localX>1-bw` 覆盖整格、热力图糊成一片深灰。
   ⚠️ **该"< 3 物理像素即整方向不画"已被本会话推翻**（1 分档 2.40px ⇒ 纵线全消失），
   现为自适应步长。
   坐标轴 `splitLine` 旧版就是 `show: false`，**不是**这个问题。
② **Skew 图例色与曲线色系统性不符** —— ECharts legend 图标取 `series.itemStyle.color`
   （否则按 series 索引取默认调色板），**不读 `lineStyle.color`**；而 5 条 series 当时只设了后者。
   实测图例 `#5470c6/#91cc75/#fac858/#ee6666/#73c0de` vs 曲线
   `#ff5a5a/#4ea8ff/#5d6874/#ff5a5a/#4ea8ff` ⇒ **5 项中 3 项不符**。
   修法：5 条 series 补 `itemStyle.color` 同值 + 在 `skew.js` 钉成契约注释
   （同值**看似冗余**，后人极易当重复配置删掉 —— 那正是本次缺陷的成因）。
两处均做**非空转验证 2/2 被抓**（`cellBorderMix=0` → 网格完全消失；`itemStyle` 还原 → 图例第 1 项变回蓝紫），
4 个 `web/` 文件事后逐字节还原。另把 `spxw-live-verify` skill 从 703 行拆为 **209 行 + 6 份 `references/`**。
完整记录见 `notes/sessions/2026-09-14/frontend-render-fix-and-skill-split/`。

**上一会话（b2b-spot-synthesis，2026-09-14）**：GTH 段现货基准落地 —— KAI 5 条拍板全部实现。
① 新增 `config/spot.json`（独立文件，已登记 `selfcheck_core::REQUIRED_KEYS`）；
② `acquisition/spot_synthesis.py`：`ĉ = (ln F2 − ln F1)/(T2 − T1)`、`S = F1·e^(−ĉ·T1)`，
   两层闸门（`max_abs_carry` fail-closed / `max_carry_jump` 拒收该桶、**基准照常跟上**防死锁）；
③ `acquisition/spot_source.py`：按区段选源 —— 合成区段**丢弃**指数 tick，`rth` 直读指数；
④ `core/session_grid.py`：从 `clock.py` 拆出网格几何纯函数（`clock.py` 414 → ~340 行）；
⑤ `--check` 的 venv 识别改按 `pyvenv.cfg`（与目录名解耦）。
**09:25 交班窗口重建无需额外代码** —— 锚跳 8.15 档 > `recenter_trigger_strikes` 3 档，
既有 `WindowFollower` 自动重建。
期货合约月与到期日**全部来自 IBKR**（`ContractDetails.realExpirationDate`），代码零推算。
新回归 `check_spot_synthesis` **16/16** + `check_spot_source` **11/11**，非空转 **5/5 变异被抓**。
端到端冒烟（GTH 正在交易）：`帧 137 | 客户端 1 | 分片 48 | 现价 7620.26 | 订阅 48/92`
—— **现价 = 合成值**，同期 IBKR 指数冻结在 **7656.98**。
⚠️ **改动未提交**（全树 **18 M + 7 ??**，基线 `HEAD=92a516c`），待 KAI 决定。

`run.py --check` **`RC=0`**：**90 个 Python + 14 个前端脚本全部合规**（最长 398 行）。
全量 **19** 个 `check_*.py`（实测 `ls tools/check_*.py | wc -l`）：**13 `RC=0` / 6 `RC=1`** ——
6 个失败经 `git worktree add -f tmp/head_tree HEAD` 对照，**HEAD 上同样 `RC=1` ⇒ 既有，非本轮引入**；
其中 `check_period_aggregation` 根因已定位（node 驱动未加载拆分后的 `web/period_align.js`）。

本会话完整记录见 `notes/sessions/2026-09-14/frontend-render-fix-and-skill-split/`；
上一会话（B2b 现货合成落地）见 `notes/sessions/2026-09-14/b2b-spot-synthesis/`；
更早（GTH 现货基准调研 + B2/B3 判别实验）见
`notes/sessions/2026-09-14/gth-spot-basis-research/`；
更早见 `notes/sessions/2026-09-13/web-js-gate-and-probe-governance/`。

## 仍然有效（跨会话结论，未受本轮影响）

- **冷数据键序 = 降序**（2026-09-13 统一）：`dump_bucket()` 输出前
  `sorted(..., reverse=True)`，由 `tools/check_persistence.py::_case_key_order_descending`
  守着（含非空转证伪）。**与对外帧的 `strikes` 同向**（高行权价在前）。
  ⚠️ `data/` 已于 2026-09-13 清空（KAI 指令，不备份）：无历史桶，下次启动
  `recover()` 冷启动。上述"降序"是**代码行为**，不是现存数据。
- **热力图纵轴：帧 `strikes` 与屏幕自上而下统一为降序**（高行权价在前/在上）——
  由**两处成对**保证，**缺一即上下翻转**：
  ① `HeatmapEngine.build()` 的 `sorted(..., reverse=True)`（帧行 0 = 最高行权价）；
  ② `web/gl_heatmap.js::update()` **按帧行序直写 texture**（屏幕顶 = texture 行 0）。
  标签与现货线走 HTML overlay（`web/heatmap.js:156`/`:209`，`y = g.y+(i+0.5)/rows*g.h`，索引 0 在最上）。
  ⚠️ **`web/heatmap.js` 已无任何 ECharts yAxis**（`yAxis.inverse` 的旧说法已作废）——
  2026-09-14 前 `update()` 里那句 `tr = rows-1-r` 把行序**反了两次**，即本会话修掉的镜像缺陷。
  判据写成等式（"帧第 r 行写在 texture 第 r 行"），**不要写成"要反转"这类方向性描述**。
- **端口 `4002`**（IB Gateway 模拟盘）；TWS 实盘 7496 / 模拟 7497；Gateway 实盘 4001。
- **`ibkr.json::market_data_type` 必须写 3** —— 写 1 时指数无权限 → Error **354**、
  一个 tick 都不推 → `_await_spot` 20s 超时 → `SpotUnavailableError` 退出（fail-closed）。
  ⚠️ `health.mode` **派生自本键**，不能用来判断某合约是否实时 —— 看
  `ticker.marketDataType`。行情权限**按合约分档**：SPXW 期权 `1`（实时）、
  SPX 指数 `3`（延迟）。
- **106 模型 Greeks 已证实** —— `generic_tick_list: "106"` 推 `tickOptionComputation`，
  四档 greeks 并存且值不同。⚠️ `ib_async` 把 tickType 13/83 合并到同一属性，
  属性层无法区分，`TickRouter.source_tick_type` 恒为 13（**名义值**）。
- **限速桶在 `ib_async` 库层**（45 msg/s = 官方 50 的 90%），项目**只观测不重建**；
  `health.rate_limit`（库层消息速率）与 `health.sub_limit_backoff`（Error 300
  行数退避）是**两个东西**，别混。
- **热力图配色 = Plotly `Turbo` 15 色顺序色阶**；基线桶宽 30s，聚合在前端
  （`web/period.js`）。
- ⚠️ **前端脚本语法无门禁的盲区已封**（2026-09-13）：由
  `tools/check_web_syntax.py`（**按目录枚举**，新增文件自动纳入）覆盖全部 `web/*.js`。
- ⚠️ **ECharts 版本 = 5.5.1，zrender = 5.6.0**（`web/vendor/echarts.min.js` 里
  `t.version="5.5.1"` / `t.dependencies={zrender:"5.6.0"}`）。**别把两者搞混。**
- **线格式**：`enc`/`scale`/`bm`/`i16`/`filled`；位序/字节序/遍历顺序只以
  `serialization/bitmap_codec.py` 的 docstring 为准。permessage-deflate 已显式化
  （`transport.json::ws_compression`）。
- ⚠️ **JS 里 `""` 是 falsy** —— 判"字段在不在"必须用 `=== undefined`。
- ⚠️ **`tools/` 的自检豁免范围（实测，勿假设）**：豁免 [2] 分层 / [9] 单一职能 /
  [10] 硬编码；**不豁免 [1] 行数与 [8] `__slots__`**。
- **记录体系**：`notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`，
  三件套上限），`memory/` 为根路由器；**同一事实只写一处**。

## 多会话网格的口径（2026-09-13，本轮定稿）

- **网格几何**：会话时长 + 会话之间的空档，**必须能被桶宽整除**，否则
  `SessionClock` 构造即抛错（fail-fast，不静默补一截）。判据由
  `tools/check_session_grid.py` 从 `config` 推出来，**不写死 20:15 / 09:25 / 2370**。
- **区段起点桶必须留白**：跨过 09:25–09:30 空档的第一笔 IV 若与空档前最后一笔做差，
  整段空档的变化被压进一个 30 秒桶，画出一堵**与真冲量无法区分的假墙**
  （与断线恢复是同一类假信号）。落点在 `features/heatmap_engine.py`。
- **环形缓冲容量必须覆盖整个网格**：`heatmap_max_buckets` / `skew_series_max_points`
  780 → **2370**。否则最早的桶被静默裁掉，图上表现为"左端凭空少一截"。
  由 `check_session_grid.py` 核对。
- **`maxColumns` 400 → 2370**（`web/config.js`）：**在一个交易日之内这个截断永不生效**，
  这是刻意的 —— 横轴是时间轴，从尾部截掉历史段在图上看不出来（没有滚动条也没有
  提示），GTH 开盘那段会静默消失。密度交给周期选择器。由
  `check_period_aggregation.py` 的跨文件不变量核对。
- **时段切列 = 切掉，不是涂白**：`web/period.js::sliceZones` 把空档的列整段移除
  （填 `null` 只是不画颜色，那几列照样占宽度 = 告诉人"这里本该有数据"）。
  **顺序是契约**：先切列再并组，否则一个组会横跨空档。
- **切列映射只有一份**：`sliceZones` 产出 `index`（基线桶号 → 切后列号，-1 = 已切掉），
  **热力图与 Skew 共用**；`alignSkew` 先查表再整除平移。
  ⚠️ 本会话修的就是它没消费这份映射 —— 切掉 10 列空档后 RTH 段每点左移 10 列，
  两块图横轴指向不同时刻，**不报任何错**。
- **`index` 为 null 是契约的另一条入口**（序列里的桶号已是切后位置），不是兜底分支：
  由 `check_period_aggregation.py` [6] 组的"时段映射路径 ≡ 预映射路径"钉住。

NEXT:
0. ~~**[高] 重启 PID 896**~~ —— **已完成**（2026-09-14 07:19，KAI 指令）。
   重启后实测上限生效：假 0 带 **1308 列 → 20 列**。
   **残留**：`recover()` 未过滤 ⇒ bucket 0 本身仍在（带未归零，只是 ≤10 分钟）。
   彻底消除需在 `recover()` 只取最后一段连续桶 —— KAI 上一轮**未选**，见
   `notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/project_state.md`。
   ⚠️ 另注意：**改后端参数（`features/` / `config/*.json`）不重启就不生效，
   而 `run.py --check` 照样全绿**（它不读活进程）。前端 `web/` 静态 + `no-store` ⇒ 刷新即生效。
1. **[中] RTH 段（09:30–16:00）实盘验证**（**只能盘中做**）—— B2b 落地的最后一块。
   GTH 段已冒烟通过（合成值 7620.26 出图、48 订阅、帧流正常）。
   待验：① 09:30 后 SPX 指数是否**真恢复实时**（而非继续冻结）；② 09:25 交班切源是否平滑、
   窗口是否按既有机制重建；③ RTH 段确实走指数而非合成。
   前端仍需肉眼确认：热力图纵轴高行权价在上、两块图横轴按同一周期对齐、
   GTH / RTH / 全时段三按钮切换正常、**GTH 时段的列确实画出来了**。
   ✅ **由 KAI 手动在盘中验证 —— 不设任何自动任务**（2026-09-13 KAI 明确）。
2. **[中] 6 个既有失败回归待修**（2026-09-14 登记）—— `check_page_render` /
   `check_skew_alignment` / `check_skew_viewport` / `check_web_contract` /
   `check_ws_compression` / `check_period_aggregation`，均已 `HEAD` worktree 对照确认
   **非本轮引入**。其中 `check_period_aggregation` 根因已定位（node 驱动未加载
   拆分后的 `web/period_align.js`），修法明确，但属"重构现有工具"，**未获指令不擅自动**。
   其中 4 个需服务的检查**只能盘中跑**（`check_web_contract` / `check_page_render` /
   `check_ws_compression` / `ws_probe`）；`check_web_contract` 三段已用**离线等价物**补验
   （桩模块跑第 1、2 段；真实流水线造帧跑第 3 段，61/61 路径命中），
   **但走的不是它自己的入口**。⚠️ 判据是 `/health` 的 `frames > 0`，不是 HTTP 200。
3. ~~**`web/*.js` 拆分方案待 KAI 拍板**~~ —— **已完成拆分**（2026-09-13 本会话）。
   `app.js` → `app.js` + `app_sessions.js` + `app_periods.js` + `app_render.js`；
   `skew.js` → `skew.js` + `skew_helpers.js` + `skew_option.js`；
   `period.js` → `period.js` + `period_align.js`。
   全部 14 个前端脚本 ≤ 400 行；`--check` `[1]` 全绿 `RC=0`。
4. ~~**`check_period_aggregation` / `check_skew_alignment` 缺分组完整性守卫**~~ ——
   **2026-09-13 第二轮一并修**：两文件已接入 `tools/group_guard.py`，
   `--selftest` 各自抓全守卫 2 条 + 全部变异（period: 5 条 / alignment: 4 条）。
5. **[低] `~/.workbuddy-ai/tmp/` 40 个历史探针未迁移**（KAI 第二轮拍板本轮不做，
   下一会话代办）—— 动用户目录需明令。开始前先列清单（按 mtime / 大小 / 是否含
   `import`），让 KAI 一眼能拍"全迁 / 部分迁 / 只登记不动"。

低优先（记录但不阻塞）：
- ~~**色板缺机械回归**~~ —— **已剔除**（前端空壳，色彩映射由后端驱动）
- ~~**`check_clock_protocol.py` 是否并入 `--check` 常驻**~~ —— **已完成**（`[12]`）
- ~~**联通与限速无常驻回归**~~ —— **已完成**（`[13]`，`selfcheck_connectivity.py`）
- **换账户 / 换机器后确认实时数据权限**；**本机缺 `ib_async` 与 `aiohttp`**
  ⇒ `check_reconnect_flow` 与 `check_web_contract` 在本环境跑不了。
- **`check_web_contract.py` 顶层 `import aiohttp`** 使它的第 1、2 段（DOM id、
  CFG 路径，均为纯静态对照）也无法在无 aiohttp 的环境运行。2026-09-13 复核时
  KAI **未选**内移，保持原样。
- **`web/*.js` 已纳入 `[1]` 且拆分完成**（2026-09-13）—— `[1]` 现扫 **104** 个文件
  （**90 `.py` + 14 `web/*.js`**，2026-09-14 更新：新增 6 个 `.py`），全部合规。
  最长文件 `tools/check_period_aggregation.py` = 398 行。`--check` **`RC=0`**。
- **[约束] 临时探针一律写 `<项目根>/tmp/`**（2026-09-13 KAI 定）——
  旧约定"写在工程目录之外（`…/.workbuddy-ai/tmp/`）"**路径含糊且理由错误**
  （只有用户级那个真实存在、被所有项目共用）。必须在 `.gitignore` +
  `NON_SOURCE_DIRS` **两处**登记：缺前者探针入库，缺后者被 `[1][2][9][10]` 误报。

**已决策不再重提（KAI）**：限速桶读数**不上前端**；**IV 热力图 ΔIV ≈ 0 不退回中性色**
（维持 Turbo 顺序色阶）；**纵轴高行权价在上**（帧与屏幕同向降序）；
**冷数据键序也统一为降序**（2026-09-13）；`notes/` 为记录落点、`memory/` 为根路由器。
**RTH 收盘 = `16:00`**（2026-09-13 KAI 明确：他只在正股 RTH 09:30–16:00 交易，
与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**，不要再提）；
**不设任何验收自动任务**（由 KAI 手动在 GTH 时段验证；"定时任务不见了"是
**预期行为**，不要再当 bug 排查或重建）；
**`web/*.js` 已拆分完成**（2026-09-13）—— `app.js` / `skew.js` / `period.js` 三文件
拆分为 9 个模块（含原文件重写），全部 < 400 行。`--check` `[1]` 全绿 `RC=0`。
`.js` 只进 `[1]`，不进 AST 类检查（`[2][9][10]`）。
**临时探针落点 = `<项目根>/tmp/`**（2026-09-13 KAI 拍板，不再写用户级
`~/.workbuddy-ai/tmp/`；必须在 `.gitignore` + `NON_SOURCE_DIRS` 两处登记，
探针用完即弃、判据要落成常驻回归）。
- **`check_clock_protocol.py` 已并入 `--check` 常驻 `[12]`**（2026-09-13 KAI 批准）——
  验证时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
- **联通与限速已并入 `--check` 常驻 `[13]`**（2026-09-13 KAI 批准）——
  `selfcheck_connectivity.py`：8060 有服务则连 WS 抓帧校验；无服务跳过（warning，
  非交易日预期），不视为失败。

**记录教训（累积，五条同族）**：
1. 2026-09-13 复核 —— **"记录里写了"不等于"系统里有"**：把"已设一次性验收定时任务"
   写进了 `open_tasks.md` 与 `project_state.md`，但系统里查无此任务。
2. 2026-09-13 本会话 —— **"检查里写了"不等于"检查里跑了"**：
   `check_period_aggregation` 的 [5][6] 两组对照函数存在、`GROUPS` 有标题、
   README 说"七组对照"，但 `evaluate()` 没串进去，**一次都没执行**，
   而报告照样打印"全部通过"。
3. 更早 —— `check_page_render` 拿到 Chrome 自己的错误页也算"画出来了"（假通过）。
4. 2026-09-13 本会话（**误判，已修正**）—— **"系统里没有"不等于"系统坏了"**：
   上一轮"已设"的验收定时任务查不到，我直接定性为工具缺陷并**重建了两次**；
   KAI 澄清那是他**有意为之**（手动在 GTH 验收，不要自动任务），创建的已删除。
   ⇒ 下"这是缺陷"的结论之前，先问一次"**是不是有人故意这么设的**"。
5. 2026-09-13 本会话 —— **"守卫的期望集合不能从被守卫的对象自推"**：
   `check_skew_viewport.py` 的完整性守卫用 `known = [p for _, ps in GROUPS …]`
   推出期望前缀 ⇒ **删掉 `[G4]` 那一组，期望集合跟着变小、守卫失明**，而该组判据
   **连报告都进不去** ⇒ 3 条失败被静默吞掉、`RC` 仍 0（探针留档见本会话 `artifacts/`）。
   ⇒ 期望值必须来自**独立常量**，且"分组表是否恰好覆盖它"要**单独查**。

⇒ 凡"已设 / 已开 / 已生效 / 有 N 组对照 / 全绿"这类状态，判据都是**去系统里读一次 /
数一遍实际执行了几个**，不是读记录、不是读代码里有没有这个函数；
而"读到的东西与记录不符"时，**先排除"这是有意为之"**再定性为缺陷。
