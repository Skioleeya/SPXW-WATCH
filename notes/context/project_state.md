# Project State

ACTIVE_SESSION: 2026-09-13/frame-strike-order-descending
LAST_UPDATED: 2026-09-13（帧 `strikes` 与屏幕纵轴统一为**降序**）
ARCHIVE: notes/context/archive/project_state_2026-09.md

CURRENT_STATE: **spxw_swatch 已是纯实盘系统** —— 模拟盘（`simulator/` 4 文件
582 行 + `config/simulator.json`）物理删除，无特性开关、无兼容分支、无回退路径；
**已提交并推送 `2f2794f`（远端已核实）**。`run.py --check` **11/11**。
**热力图纵轴：帧 `strikes` 与屏幕自上而下统一为降序**（高行权价在前/在上）——
由 `HeatmapEngine.build()` 的 `sorted(..., reverse=True)` 与
`web/heatmap.js::yAxis.inverse = true` **成对**保证（缺一即翻转），
回归在 `tools/smoke_test.py`「矩阵 strikes 降序」。
⚠️ **实盘只验证到连通性**：2026-09-13 是周日，无当日 SPXW 到期 ⇒
`ChainResolveError`（fail-closed 正确），**订阅与热力图出图至今未在任何
交易日跑过**。
⚠️ **未提交改动共 8 个文件**（两轮会话累积：冷数据键序 + 帧降序）。

本会话完整记录见 `notes/sessions/2026-09-13/frame-strike-order-descending/`；
上一会话见 `notes/sessions/2026-09-13/cold-data-strike-order/`（冷数据键序升序）。

## 仍然有效（跨会话结论，未受本轮影响）

- **冷数据键序 = 升序**（2026-09-13 cold-data 会话）：`dump_bucket()` 输出前
  `sorted()`，由 `tools/check_persistence.py::_case_key_order_ascending` 守着。
  ⚠️ **与帧的降序方向相反** —— 两者是不同层（内部恢复产物 vs 对外契约），
  不要串味；是否统一待 KAI 定（见 `open_tasks.md`）。
  ⚠️ **`data/` 已于 2026-09-13 清空**（KAI 指令，不备份）：无历史桶，下次启动
  `recover()` 冷启动。上述"升序"是**代码行为**，不是现存数据。
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
- **线格式**：`enc`/`scale`/`bm`/`i16`/`filled`；位序/字节序/遍历顺序只以
  `serialization/bitmap_codec.py` 的 docstring 为准。permessage-deflate 已显式化
  （`transport.json::ws_compression`）。
- ⚠️ **JS 里 `""` 是 falsy** —— 判"字段在不在"必须用 `=== undefined`。
- ⚠️ **`tools/` 的自检豁免范围（实测，勿假设）**：豁免 [2] 分层 / [9] 单一职能 /
  [10] 硬编码；**不豁免 [1] 行数与 [8] `__slots__`**。
- **记录体系**：`notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`，
  三件套上限），`memory/` 为根路由器；**同一事实只写一处**。

NEXT: 2 项（**都只能在交易日盘中做**）
1. **实盘首次出图验证** —— 硬切后系统只剩实盘路径，至今未在任何交易日跑过。
   应确认：`mode` 正确、订阅条数、热力图出图（**并顺带肉眼确认纵轴是高行权价
   在上**）、`health.rate_limit` 四要素。
2. **4 个需服务的检查补跑** —— `check_web_contract` / `check_page_render` /
   `check_ws_compression` / `ws_probe`。⚠️ 删掉模拟盘后**服务无法在非交易日常驻**
   ⇒ 这 4 项从此**只有盘中能跑**。

低优先（记录但不阻塞）：
- **色板缺机械回归**；**`check_clock_protocol.py` 是否并入 `--check` 常驻**；
  **换账户 / 换机器后确认实时数据权限**（`marketDataType = 1` 是账户侧配置）；
  **本机缺 `ib_async`** ⇒ `check_reconnect_flow` 跑不了。
- **[约束] 临时探针一律写在工程目录之外**（`C:/Users/Lenovo/.workbuddy-ai/tmp/`）——
  工程内任何 `.py` 都会被 `iter_py_files()` 扫到。

**已决策不再重提（KAI）**：限速桶读数**不上前端**；**IV 热力图 ΔIV ≈ 0 不退回中性色**
（维持 Turbo 顺序色阶）；**纵轴高行权价在上**（同日统一为帧与屏幕同向降序）；
`notes/` 为记录落点、`memory/` 为根路由器。
