# Project State

ACTIVE_SESSION: 2026-09-13/recheck-keyorder-memory
LAST_UPDATED: 2026-09-13（交接复核 + 冷数据键序统一降序 + MEMORY 蒸馏）
ARCHIVE: notes/context/archive/project_state_2026-09.md

CURRENT_STATE: **spxw_swatch 已是纯实盘系统** —— 模拟盘（`simulator/` 4 文件
582 行 + `config/simulator.json`）物理删除，无特性开关、无兼容分支、无回退路径。
`run.py --check` **11/11**；12 个本地回归全 `rc=0`。
**冷数据键序 = 降序，与帧同向**（2026-09-13 本会话统一）——
`HeatmapEngine.dump_bucket()` 产出前 `sorted(..., reverse=True)`，此前它与帧方向
相反；回归 `check_persistence.py::_case_key_order_descending`（双向证伪）。
**热力图纵轴：帧 `strikes` 与屏幕自上而下统一为降序**（高行权价在前/在上）——
由 `HeatmapEngine.build()` 的 `sorted(..., reverse=True)` 与
`web/heatmap.js::yAxis.inverse = true` **成对**保证（缺一即翻转），
回归在 `tools/smoke_test.py`「矩阵 strikes 降序」。
**Skew 与热力图按同一周期标签对齐** —— 列网格只有一份来源（`app.js` 强制先算
热力图，`period.js::alignSkew` 消费它，取组内末值）；Skew 纵轴量程 = 后端下发的
`skew.scale_policy.window_s`（3600s）窗口内极值，`skew_min`/`skew_max` 已**删除**。
⚠️ **实盘只验证到连通性**：2026-09-13 是周日，无当日 SPXW 到期 ⇒
`ChainResolveError`（fail-closed 正确），**订阅与热力图出图至今未在任何
交易日跑过**。
✅ **已提交并推送 `792e4a3`**（33 文件，+3967/−97）—— 含 skew 周期一致性会话
（`web/` 3 文件 + 两个新门禁 + P0 修复）与冷数据键序统一降序；远端已核实
（`git ls-remote` == 本地 HEAD = `792e4a3`），工作区干净。

本会话完整记录见 `notes/sessions/2026-09-13/recheck-keyorder-memory/`；
上一会话见 `notes/sessions/2026-09-13/skew-period-consistency/`（周期对齐）。

## 仍然有效（跨会话结论，未受本轮影响）

- **冷数据键序 = 降序**（2026-09-13 统一）：`dump_bucket()` 输出前
  `sorted(..., reverse=True)`，由
  `tools/check_persistence.py::_case_key_order_descending` 守着（含非空转证伪：
  不排序与退回旧升序两种变异都报 FAIL、`EXIT=1`）。
  **与对外帧的 `strikes` 同向**（高行权价在前）—— 此前两者方向相反，同一个
  系统里两处行序相反迟早串味；现同向。冷数据仍是内部恢复产物（键序不影响
  `_buckets` 查找，`build()` 自己显式排序），统一只为消除反向语义。
  ⚠️ **`data/` 已于 2026-09-13 清空**（KAI 指令，不备份）：无历史桶，下次启动
  `recover()` 冷启动。上述"降序"是**代码行为**，不是现存数据。
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
- **热力图配色 = Plotly `Turbo` 15 色顺序色阶**；`maxColumns = 400`；
  基线桶宽 30s，聚合在前端（`web/period.js`）。
- **周期一致性 = 两块图共用一套列网格**（2026-09-13 本会话）—— 热力图先算
  （`aggregate` 并组 → `clipTail` 截尾），`period.js::alignSkew` 消费它：
  热力图聚合 ΔIV（**可加**，组内求和，望远镜相消是恒等式），Skew 是**水平量**，
  取**组内末值**。⚠️ **`alignSkew` 的 `label` 是复制自热力图网格的**，所以
  "两块图逐列标签相同"是**恒真断言**，不可用作回归判据；有效判据是**时间域**
  （每列 `ts` 落在该列时间区间内）。回归 `tools/check_skew_alignment.py`。
- **Skew 纵轴量程口径**：后端下发窗口长度（`serialization.json::
  skew_scale_window_seconds = 3600.0` → 帧 `skew.scale_policy.window_s`），
  前端在窗口内取极值 ∪ {0} 加留白。⚠️ 3600s 是**经验值，未经盘中校准**。
- ⚠️ **前端脚本语法无门禁的盲区已封**（2026-09-13）：`web/skew.js` 曾因 docstring
  提前闭合而整文件语法错误、`window.SkewPanel` 不存在，而 13 个回归全绿 ——
  因为 `check_period_aggregation` 只加载 `period.js`、`check_matrix_codec` 只加载
  `matrix_codec.js`、`check_web_contract` 只加载 `config.js`。现由
  `tools/check_web_syntax.py`（**按目录枚举**，新增文件自动纳入）覆盖全部 `web/*.js`。
- ⚠️ **ECharts 版本 = 5.5.1，zrender = 5.6.0**（`web/vendor/echarts.min.js` 里
  `t.version="5.5.1"` / `t.dependencies={zrender:"5.6.0"}`；另有一处
  `version:"5.6.0"` 属于内部 painter）。**别把两者搞混。**
- **线格式**：`enc`/`scale`/`bm`/`i16`/`filled`；位序/字节序/遍历顺序只以
  `serialization/bitmap_codec.py` 的 docstring 为准。permessage-deflate 已显式化
  （`transport.json::ws_compression`）。
- ⚠️ **JS 里 `""` 是 falsy** —— 判"字段在不在"必须用 `=== undefined`。
- ⚠️ **`tools/` 的自检豁免范围（实测，勿假设）**：豁免 [2] 分层 / [9] 单一职能 /
  [10] 硬编码；**不豁免 [1] 行数与 [8] `__slots__`**。
- **记录体系**：`notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`，
  三件套上限），`memory/` 为根路由器；**同一事实只写一处**。

NEXT: 2 项（**都只能在交易日盘中做**，已设一次性定时任务 `8b4fe600-…`，
2026-09-14 09:45 ET）
1. **实盘首次出图验证** —— 硬切后系统只剩实盘路径，至今未在任何交易日跑过。
   应确认：`mode` 正确、订阅条数（应 48 = ±12 档 × Put/Call）、热力图出图
   （**并顺带肉眼确认纵轴是高行权价在上**）、`health.rate_limit` 四要素，以及
   **两块图横轴按同一周期对齐**（`skew-period-consistency` 会话新改，只做过离线验证）。
2. **4 个需服务的检查补跑** —— `check_web_contract` / `check_page_render` /
   `check_ws_compression` / `ws_probe`。⚠️ 删掉模拟盘后**服务无法在非交易日常驻**
   ⇒ 这 4 项从此**只有盘中能跑**。已改 3 个前端文件，
   `check_page_render` 的覆盖价值比以往更高（且它现在带**页面哨兵**，
   拿到 Chrome 自己的错误页会中止而不是假通过）。
   ⚠️ **判据是 `/health` 的 `frames > 0`，不是 HTTP 200**；冷启动 <1 分钟
   `ws_probe` 报「0 格」不是缺陷（ΔIV 需 ≥2 个桶）。

低优先（记录但不阻塞）：
- **色板缺机械回归**；**`check_clock_protocol.py` 是否并入 `--check` 常驻**；
  **换账户 / 换机器后确认实时数据权限**（`marketDataType = 1` 是账户侧配置）；
  **本机缺 `ib_async` 与 `aiohttp`** ⇒ `check_reconnect_flow` 与
  `check_web_contract` 在本环境跑不了。
- **`check_web_contract.py` 顶层 `import aiohttp`** 使它的第 1、2 段（DOM id、
  CFG 路径，均为纯静态对照）也无法在无 aiohttp 的环境运行。2026-09-13 复核时
  KAI **未选**内移，保持原样（属"重构现有工具"，未获指令不擅自动）。
- **`skew_scale_window_seconds = 3600.0` 待盘中校准**（太短则量程频繁跳，
  太长则退化成旧的全序列极值）。
- **[约束] 临时探针一律写在工程目录之外**（`C:/Users/Lenovo/.workbuddy-ai/tmp/`）——
  工程内任何 `.py` 都会被 `iter_py_files()` 扫到。

**已决策不再重提（KAI）**：限速桶读数**不上前端**；**IV 热力图 ΔIV ≈ 0 不退回中性色**
（维持 Turbo 顺序色阶）；**纵轴高行权价在上**（统一为帧与屏幕同向降序）；
**冷数据键序也统一为降序**（2026-09-13，与帧同向）；`notes/` 为记录落点、
`memory/` 为根路由器。

**记录教训（2026-09-13 复核）**：**"记录里写了"不等于"系统里有"** ——
上一轮把"已设一次性验收定时任务"写进了 `open_tasks.md` 与 `project_state.md`，
但系统里**查无此任务**（`automation list` 空、`view` not found），
"开盘后补验收"当时没有任何触发点。凡"已设 / 已开 / 已生效"这类状态，
判据必须是**去系统里读一次**，不是读记录。
