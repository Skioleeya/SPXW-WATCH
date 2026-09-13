# Project State

ACTIVE_SESSION: 2026-09-13/multi-session-grid
LAST_UPDATED: 2026-09-13（多会话交易日网格收口：修 4 处缺陷 + 全量复验）
ARCHIVE: notes/context/archive/project_state_2026-09.md

CURRENT_STATE: **spxw_swatch 已是纯实盘系统 + 多会话交易日网格**。
模拟盘（`simulator/` 4 文件 582 行 + `config/simulator.json`）已物理删除，
无特性开关、无兼容分支、无回退路径。
**交易日网格 = GTH 20:15→次日 09:25 + 空档 09:25–09:30 + RTH 09:30→16:00**，
锚在首个会话开盘、**跨午夜**，71100s ÷ 30s = **2370 桶**；会话真相只有一处
（`config/app.json::sessions`），区段表随帧下发到 `session.zones`。
`run.py --check` **11/11**；13 个本地回归全 `rc=0`；4 个 `--selftest` 变异全抓。
✅ **已提交并推送**（2026-09-13，KAI 指令）—— 含多会话网格全套 + 本会话的 4 处缺陷
修复与记录；远端已核实（`git ls-remote` == 本地 HEAD）。提交号见 `notes/context/handoff.md`。
⚠️ **实盘只验证到连通性**：2026-09-13 是周日，无当日 SPXW 到期 ⇒
`ChainResolveError`（fail-closed 正确），**订阅与热力图出图至今未在任何
交易日跑过**，多会话网格与时段切列也**只做过离线验证**。
⇒ 由 **KAI 手动在 GTH 时段**验收（**不设自动任务**，见下「已决策」）。

本会话完整记录见 `notes/sessions/2026-09-13/multi-session-grid/`；
上一会话见 `notes/sessions/2026-09-13/recheck-keyorder-memory/`（冷数据键序降序）。

## 仍然有效（跨会话结论，未受本轮影响）

- **冷数据键序 = 降序**（2026-09-13 统一）：`dump_bucket()` 输出前
  `sorted(..., reverse=True)`，由 `tools/check_persistence.py::_case_key_order_descending`
  守着（含非空转证伪）。**与对外帧的 `strikes` 同向**（高行权价在前）。
  ⚠️ `data/` 已于 2026-09-13 清空（KAI 指令，不备份）：无历史桶，下次启动
  `recover()` 冷启动。上述"降序"是**代码行为**，不是现存数据。
- **热力图纵轴：帧 `strikes` 与屏幕自上而下统一为降序**（高行权价在前/在上）——
  由 `HeatmapEngine.build()` 的 `sorted(..., reverse=True)` 与
  `web/heatmap.js::yAxis.inverse = true` **成对**保证（缺一即翻转）。
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
1. **[中] 实盘首次出图验证**（**只能盘中做**）—— 除原有清单（`mode` 正确、
   48 条订阅、热力图出图并肉眼确认纵轴高行权价在上、`health.rate_limit` 四要素）外，
   本轮新增：**两块图横轴按同一周期对齐**、**GTH / RTH / 全时段三个按钮切换正常**、
   **GTH 时段的列确实画出来了**（这是整个网格改造的目的）。
   ✅ **由 KAI 手动在 GTH 时段验证 —— 不设任何自动任务**（2026-09-13 KAI 明确）。
2. **[中] 4 个需服务的检查补跑**（**只能盘中做**）—— `check_web_contract` /
   `check_page_render` / `check_ws_compression` / `ws_probe`。
   ⚠️ 硬切后服务无法在非交易日常驻 ⇒ 这 4 项从此只有盘中能跑。
   本轮已用**离线等价物**覆盖 `check_web_contract` 三段（桩模块跑第 1、2 段；
   真实流水线造帧跑第 3 段，61/61 路径命中），**但走的不是它自己的入口**。
   ⚠️ 判据是 `/health` 的 `frames > 0`，不是 HTTP 200。

低优先（记录但不阻塞）：
- **色板缺机械回归**；**`check_clock_protocol.py` 是否并入 `--check` 常驻**；
  **换账户 / 换机器后确认实时数据权限**；**本机缺 `ib_async` 与 `aiohttp`**
  ⇒ `check_reconnect_flow` 与 `check_web_contract` 在本环境跑不了。
- **`check_web_contract.py` 顶层 `import aiohttp`** 使它的第 1、2 段（DOM id、
  CFG 路径，均为纯静态对照）也无法在无 aiohttp 的环境运行。2026-09-13 复核时
  KAI **未选**内移，保持原样。
- **`skew_scale_window_seconds = 3600.0` 待盘中校准**。
- **[约束] 临时探针一律写在工程目录之外**（`C:/Users/Lenovo/.workbuddy-ai/tmp/`）——
  工程内任何 `.py` 都会被 `iter_py_files()` 扫到。

**已决策不再重提（KAI）**：限速桶读数**不上前端**；**IV 热力图 ΔIV ≈ 0 不退回中性色**
（维持 Turbo 顺序色阶）；**纵轴高行权价在上**（帧与屏幕同向降序）；
**冷数据键序也统一为降序**（2026-09-13）；`notes/` 为记录落点、`memory/` 为根路由器。
**RTH 收盘 = `16:00`**（2026-09-13 KAI 明确：他只在正股 RTH 09:30–16:00 交易，
与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**，不要再提）；
**不设任何验收自动任务**（由 KAI 手动在 GTH 时段验证；"定时任务不见了"是
**预期行为**，不要再当 bug 排查或重建）。

**记录教训（累积，四条同族）**：
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

⇒ 凡"已设 / 已开 / 已生效 / 有 N 组对照"这类状态，判据都是**去系统里读一次 /
数一遍实际执行了几个**，不是读记录、不是读代码里有没有这个函数；
而"读到的东西与记录不符"时，**先排除"这是有意为之"**再定性为缺陷。
