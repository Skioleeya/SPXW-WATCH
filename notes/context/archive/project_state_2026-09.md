# Project State Archive — 2026-09

历史状态摘要归档。当前最新状态见 `notes/context/project_state.md`。

---

## 2026-09-11 / session-rollover-and-render-fix

CURRENT_STATE（当时）：spxw_swatch 61 个 Python 文件（最长 386 行）；
`run.py --check` 7/7；7 个回归全过；`ws_probe` 20/20。

- **Skew 面板从未渲染成功过**：`visualMap` 的 `pieces` 模式必抛
  `reading 'coord'`。已改为双同名序列按正负着色。
- **跨会话数据污染**：桶序号跨会话复用 + 旧会话 tick 被判为 `STALE` 后写入新会话
  的桶。已在 `FeatureEngine` 加 `_sync_session()` 与 `_session_refs()`。
- 新增四个回归：`check_tick_router.py` / `check_session_rollover.py` /
  `check_web_contract.py` / `check_page_render.py`（后三者已验证非空转）。
- 遗留：实盘"连上之后能否收到数据"未验证；`notes/` 与既有证据体系是否并行未定。

---

## 2026-09-11 / 当日全部会话的末态摘要

CURRENT_STATE（当时）：70 个 Python 文件（最长 397 行）；`run.py --check` **11/11**
且死键归零；本地回归 5 个 + `smoke_test` + 服务端 3 个全过。
**当日 7 个会话**：`dead-key-resolution` / `ibkr-rate-limit-audit` /
`iv-heatmap-turbo-palette` / `model-greeks-landing-verified` /
`record-reconciliation` / `selfcheck-hardening` / `session-rollover-and-render-fix`。

- **端口 4002 实测联通** —— `7497` 是 TWS 模拟盘口，实测 `ConnectionRefusedError`；
  IB Gateway 模拟盘 = 4002。首次实盘联通成功（11～14 秒就绪，仅 72 × Error 10090）。
- **106 模型 Greeks 已证实** —— `generic_tick_list="106"` 确实推
  `tickOptionComputation`；四档 greeks 并存且值不同 ⇒ MODEL_OPTION 独立通道。
  残留：ib_async 把 tickType 13/83 合并到同一属性，`source_tick_type` 恒为 13（名义值）。
- **行情权限按合约分档** —— SPXW 期权 ticker `marketDataType=1`（实时），
  SPX 指数 ticker `=3`（延迟）⇒ 期权 IV 实时、现价滞后 15–20 分钟。
  故 `ibkr.json::market_data_type` **必须写 3**（写 1 → Error 354 → 启动即死）。
- **限速桶显式化 + 可观测** —— `rate_limit_max_requests=45` / `rate_limit_interval_s=1.0`
  由 `RateLimitWatch.apply()` 写入 `ib.client`；读数贯通到帧 `health.rate_limit`。
  实测冷启动桶事件 0 次。
- **热力图配色 = Plotly `Turbo` 15 色顺序色阶**；KAI 决策 **ΔIV ≈ 0 不退回中性色**。
- **7 个死配置键** —— 4 接线 / 3 删除；`UNWIRED_IS_FAILURE` 收紧为 `True`。
- **`iter_py_files()` 改用排除表 `NON_SOURCE_DIRS`**（`notes`/`.workbuddy-ai`/`logs`/`web`）。
- **记录校正** —— 此前的 `396 行`/`69 文件`/`10 项检查`/`40 个关键键` 均为过期值；
  README §10「实盘未验证」已改为「已实测联通」。
- 遗留：现价延迟（需 CBOE 指数实时权限或换 spot 来源）；色板无机械回归；
  联通与限速无常驻回归。

## 2026-09-13 硬切实盘 / live-verify 会话要点（迁自 notes/context/project_state.md）

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

---

## 2026-09-13 冷数据键序 / cold-data-strike-order（迁自 notes/context/project_state.md）

- **冷数据（`data/session.db`）不记录排序方法** —— 表只有
  `bucket_index / ivs_json / is_break`。键序此前是 `_buckets` 的**首次出现顺序**，
  即上游不变量（`StrikeWindow.rows()` 升序）的副作用，无回归守着。
- **非单调可达且已实测复现**（±12 档，spot 7700→7820→7600）：现价回落到会话初
  低点之下时，更低的档位被**追加到字典末尾** ⇒ 键序乱；落盘与 `recover()` 都原样继承。
  现有 40 桶实测仍全升序（**可达但未触发**）。
- **修法**：`dump_bucket()` 输出前按行权价 `sorted()` —— 不变量收回到 `ivs_json`
  的唯一产出点；`recover()` / `load_snapshot()` **刻意不动**（读侧重排 = 第二处真相）。
  非空转证伪已做：摘掉 `sorted()` → 新用例 FAIL / `EXIT=1`，还原后 5/5。
- **消费者审计**：全工程无任何模块/工具直接读 `session.db`；唯一消费者是
  `pipeline.recover() → load_snapshot()`，不关心顺序 ⇒ 改动对系统行为零影响。
- **前端顺序定案**：`web/heatmap.js:93` 只做 `strikes.map(String)`，`yAxis` 无
  `inverse` ⇒ 不排序、不反转，逐字照抄帧；ECharts category 轴把索引 0 画在
  **最下方** ⇒ 屏幕自上而下 = 帧 strikes 的**逆序**。
- **纵轴方向 KAI 裁定**：保持现状（高行权价在上）。⚠️ 该裁定已在同日更晚的
  `frame-strike-order-descending` 会话中进一步统一为「帧与屏幕**同向降序**」，
  以 `web/heatmap.js::yAxis.inverse = true` 实现 —— 本条的"无 inverse"描述**已过期**。
