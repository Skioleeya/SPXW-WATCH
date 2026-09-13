# 架构与目录约定

> 本文件 = T1 层：系统架构、分层、目录、技术栈、数据流。
> 更新时同步改 `MEMORY.md` §1-2 的时间戳。

---

## 1. 项目目标

SPXW 0DTE（当日期权）IV 变化速度盯盘雷达。
- 核心指标：ΔIV 热力图 + 25Δ Skew（RR25 / BF25）
- 数据来源：IBKR Gateway → `ib_async` → 多层流水线 → ECharts 前端

## 2. 技术栈与版本

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.13.12 (managed) | 隔离 venv |
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

## 4. 目录约定

```
config/           10 个 JSON + 2 个 Python 加载器。禁止跨文件引用。
contracts/        L0：枚举、端口协议（`ClockPort`, `FeedPort` 等）
acquisition/      L1：`ibkr_gateway.py`, `rate_limit_watch.py`, `feed_service.py`
state/            L2：`tick_store.py`, `session_clock.py`
core/             L2：`clock.py`, `numeric.py`
features/         L3：`heatmap_engine.py`, `skew_series.py`, `impulse_tracker.py`
serialization/    L4：`frame_builder.py`, `bitmap_codec.py`
transport/        L5：`ws_broadcaster.py`, `http_server.py`
app/              L6：`pipeline.py`（唯一组装根）
web/              前端：8 JS + 1 HTML + 1 CSS。ECharts 5.5.1 vendor
```

## 5. 配置体系

- **10 个独立 JSON**，禁止 `$ref` / `include` / `extends`
- 缺键即抛 `ConfigError`（fail fast，不静默兜底）
- 关键配置项 **40** 个，由 `selfcheck_config.py` [3][5][7] 校验
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
TickRouter → TickStore (SQLite)
    ↓ 每 30s 桶
HeatmapEngine.build() →  ΔIV 矩阵 (strikes 降序)
SkewSeries.update()   →  RR25 / BF25
ImpulseTracker        →  冲量事件
FrameBuilder          →  位图编码 (bm + i16)
WSBroadcaster         →  ws://127.0.0.1:8060/ws
ECharts               →  热力图 + Skew 曲线
```

## 7. 纯实盘

- `simulator/` + `simulator.json` 已全删（2026-09-13 硬切）
- `run.py` 只剩 `--check`
- 离线回归夹具：`tools/fixtures.py`（`FakeClock`, `SyntheticSurface`）
