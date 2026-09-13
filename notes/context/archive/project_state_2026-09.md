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
