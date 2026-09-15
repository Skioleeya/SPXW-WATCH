# 架构与目录约定

> 本文件 = T1 层：系统架构、分层、目录、技术栈、数据流。
> 更新时同步改 `MEMORY.md` §2 的时间戳。

---

## 1. 项目目标

SPXW 0DTE（当日期权）IV 变化速度盯盘雷达。
- 核心指标：ΔIV 热力图 + 25Δ Skew（RR25 / BF25）
- 数据来源：IBKR Gateway → `ib_async` → 多层流水线 → ECharts 前端

## 2. 技术栈与版本

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | **3.13.14**（项目 `venv/`） | 托管运行时是 3.13.12；**回归必须用 venv**（见 RULES §6.1） |
| `ib_async` | 2.1.0 | IBKR 接口 |
| `aiohttp` | — | HTTP + WS 服务 |
| ECharts | **5.5.1** | `web/vendor/echarts.min.js` |
| zrender | **5.6.0** | ECharts 内置 painter，别跟主版本搞混 |
| SQLite | — | 旁路持久化（冷数据） |

## 3. 严格分层单向依赖

```
L0 契约/枚举/端口      contracts/          → 任何人可 import
L1 IBKR 订阅/限速       acquisition/        → 只能 import L0
L2 Tick 存储/时间源     state/, core/       → 只能 import L0-L1
L3 特征计算             features/           → 只能 import L0-L2
L4 序列化/帧编码        serialization/      → 只能 import L0-L3
L5 WS 广播/HTTP 服务    transport/          → 只能 import L0-L4
L6 组装/生命周期        app/pipeline.py     → 唯一可 import 全层
```

**下层不得 import 上层**。检查器：`selfcheck_structure.py` [2]。

## 4. 目录约定（模块名省略 `.py`；2026-09-15 按目录枚举逐条核对）

```
config/           11 个 JSON + 2 个 Python 加载器（loader / __init__）。禁止跨文件引用。
contracts/        L0：enums, feature, frame, ports, tick
acquisition/      L1：chain_resolver, contract_factory, feed_errors, feed_reconcile,
                  feed_service, ibkr_gateway, rate_limit_watch, spot_source,
                  spot_synthesis, spot_tap, subscription_manager, tick_router
state/            L2：market_state, tick_store
core/             L2：clock, errors, logging_setup, ring_buffer, session_grid
features/         L3：delta_locator, feature_engine, glitch_filter, heatmap_engine,
                  impulse_engine, persistence, persistence_store, skew_engine, strike_window
serialization/    L4：bitmap_codec, cell_encoder, frame_encoder, heatmap_matrix, numeric,
                  payload_builder, skew_series
transport/        L5：http_static, push_loop, server, ws_broadcaster
app/              L6：pipeline（唯一组装根）
web/              前端：13 个 JS + 3 个 HTML + 1 个 CSS（ECharts 5.5.1 在 vendor/）
```

> `tools/` 是离线回归与探针（不受 400 行门禁），见 README §8；
> `tmp/` 是 gitignore 的一次性脚本区（`selfcheck_core.py::NON_SOURCE_DIRS` 含它）。

## 5. 配置体系

- **11 个独立 JSON**，禁止 `$ref` / `include` / `extends`
- 缺键即抛 `ConfigError`（fail fast，不静默兜底）
- 关键配置项 **51** 个，由 `selfcheck_config.py` [3][5][7] 校验
  （2026-09-15 实测：`run.py --check` 报 `[3] 11 个模块配置全部可读`、
  `[5] 51 个关键配置项齐备`）
- `UNWIRED_IS_FAILURE = True` —— 死配置键即失败

核心配置文件：
- `ibkr.json` —— 连接参数、`generic_tick_list: "106"`、`market_data_type`
- `transport.json` —— `ws_compression`, `host`
- `serialization.json` —— `heatmap_bucket_seconds` (30s), `heatmap_encoding`
- `features.json` —— `glitch_max_iv`, `glitch_min_iv`

## 6. 数据流

```
IB Gateway (port 4002)
    ↓ ib_async tickOptionComputation (tickType 106)
TickRouter → TickStore（**内存环 `RingBuffer`，不是 SQLite**）
    ↓ 每 30s 桶
HeatmapEngine.build() →  ΔIV 矩阵 (strikes 降序)
SkewEngine.update()   →  RR25 / BF25
ImpulseEngine         →  冲量事件
FrameEncoder          →  位图编码 (bm + i16)
WsBroadcaster         →  ws://127.0.0.1:8060/ws
ECharts               →  热力图 + Skew 曲线
```

**旁路（与上链并行，L3 出口）**：原始 IV 桶 → `AsyncPersistenceWriter`（队列）
→ `SessionFileStore`（文件与表）→ `data/sessions/<到期日>.db`；
启动时 `recover()` / `recover_skew()` 回灌 `HeatmapEngine` / `SkewEngine`，
并把非当前会话的库文件**移动**到 `data/archive/`（`archive_other_sessions()`，
db_dir 只留当前会话；历史**归档不删** —— 那是逐交易日的原始记录）。
结果由 `app/pipeline.py` 各记一行（已归档 / 未归档），`features/` 整层不写日志。

## 7. 纯实盘

- `simulator/` + `simulator.json` 已全删（2026-09-13 硬切）
- `run.py` **不带参数 = 启动服务**；唯一的开关是 `--check`（自检，不启动）。
  `--sim` / `--live` 两个开关已删 —— 别把"只剩 `--check`"读成"只能自检"。
- 离线回归夹具：`tools/fixtures.py`（`FakeClock`, `SyntheticSurface`）
