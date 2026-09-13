# Project State

ACTIVE_SESSION: 2026-09-13/live-verify-and-release
LAST_UPDATED: 2026-09-13（硬切已提交并推送 `2f2794f`；实盘链路连通性已验证，出图待交易日）
ARCHIVE: notes/context/archive/project_state_2026-09.md

CURRENT_STATE: **spxw_swatch 已是纯实盘系统，且已入库** —— 模拟盘（`simulator/`
4 文件 582 行 + `config/simulator.json`）物理删除，无特性开关、无兼容分支、
无回退路径；**已提交并推送 `2f2794f`（远端已核实）**，工作树干净。
78 个 Python 文件（最长 `tools/smoke_test.py` 363 行；产品代码最长
`acquisition/ibkr_gateway.py` 360 行）；`run.py --check` **11/11**
（9 个模块配置 / 37 个关键键 / 137 处取键 / 9 条硬编码例外）。
⚠️ **实盘只验证到连通性**：2026-09-13 是周日，无当日 SPXW 到期 ⇒
`ChainResolveError`（fail-closed 正确），**72 条订阅与热力图出图至今未在任何
交易日跑过**。

## 2026-09-13 本轮要点

- **CLI 收敛**：`run.py` 只剩 `--check`（63 行）；`--sim` / `--live` 与
  `_resolve_simulate()` 一并删除。`Pipeline(simulate=…)` → `Pipeline()`。
- **`app/pipeline.py` 367 → 341 行**：删 `simulate` 形参、`_cfg["simulator"]`、
  SimClock 分支、SyntheticFeed 分支、`FeedMode` import。
- **`FeedMode.SIM` 移除**；枚举本身保留（对应 IBKR `marketDataType`，是跨层契约）。
- **`tools/fixtures.py`（新增，188 行）** —— 从被删模拟源抽出最小确定性内核
  （`FakeClock` 实现 `ClockPort` + `SyntheticSurface`），让 4 个原本依赖模拟盘的
  离线回归活下来。`FakeClock` 完全不碰 `time.monotonic()`，**比 `SimClock` 更确定**。
- **自检登记项同轮清理** —— `LAYER_OF["simulator"]` / `REQUIRED_KEYS["simulator"]` /
  `EXEMPT_CONSTANTS["simulator/scenario.py"]`。漏删不会报错，只会**静默少查一层**。
- **`README.md` 同步** —— 去 `--sim`/`--live`、L6 表与配置清单去 `simulator`、
  §8 改写为「离线回归」、修正过期数字（配置 10→9、关键键 41→37）。
- **备份在仓库之外**：`E:\US.market\SPXW SWATCH\simulator_removed_20260913\`。
- **记录体系拓扑（本会话第二部分）**：
  - skill `notes-session-records` 导入 workbuddy 用户级并**按 KAI 要求放宽**
    （160 → 133 行；27 个强制 marker → **5 个核心**：`CHANGED-PATHS` /
    `VALIDATION-SUMMARY` / `COMMAND-EVIDENCE` / `NOTES-PATHS` / `OPEN-RISKS`；
    验证"跑该仓库真实提供的检查即可，没有可跑的写 `N/A:<原因>`，不是失败"）；
    删除 `agents/openai.yaml`。
  - **5 条工程要求提升到用户级 `MEMORY.md`**（所有项目通用）；
    项目级 `MEMORY.md` 改为**指针**，不复述条文。
  - **`notes/` 按 KAI 决策复活**（52 文件，自 `notes_backup_20260911/`），
    记录落点回到 `notes/sessions/YYYY-MM-DD/<task-id>/`。
- ⚠️ **`tools/` 的自检豁免范围（实测确认，勿假设）**：豁免 [2] 分层 /
  [9] 单一职能 / [10] 硬编码；**不豁免 [1] 行数与 [8] `__slots__`** ——
  这直接决定 `tools/fixtures.py` 必须 < 400 行。

## 仍然有效（2026-09-11 结论，未受本轮影响）

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

NEXT: 2 项（**都只能在交易日盘中做**）
1. **实盘首次出图验证** —— 硬切后系统只剩实盘路径，至今未在任何交易日跑过。
   应确认：`mode` 正确、72 条订阅、热力图出图、`health.rate_limit` 四要素。
2. **4 个需服务的检查补跑** —— `check_web_contract` / `check_page_render` /
   `check_ws_compression` / `ws_probe`。⚠️ 删掉模拟盘后**服务无法在非交易日常驻**
   （无当日到期即 fail-closed 退出）⇒ 这 4 项从此**只有盘中能跑**，
   "回归全绿"在盘前/盘后/周末永远不成立。这是取舍的必然结果，不是回归破坏。

低优先（记录但不阻塞）：
- **色板缺机械回归** —— 色值被误改没有任何检查会红。
- **`check_clock_protocol.py` 是否并入 `--check` 常驻** —— 目前靠"有人记得跑"。
- **换账户 / 换机器后确认实时数据权限** —— `marketDataType = 1` 是**账户侧配置**，
  不是代码保证。
- **[约束] 临时探针一律写在工程目录之外**（`C:/Users/Lenovo/.workbuddy-ai/tmp/`）——
  工程内任何 `.py` 都会被 `iter_py_files()` 扫到。

**已决策不再重提（KAI）**：限速桶读数**不上前端**；**IV 热力图 ΔIV ≈ 0 不退回中性色**
（维持 Turbo 顺序色阶）；`notes/` 为记录落点、`memory/` 为根路由器。

本会话完整记录见 `notes/sessions/2026-09-13/live-verify-and-release/`；
上一会话见 `notes/sessions/2026-09-13/simulator-hard-cut/`（硬切本体与提交内容）。
