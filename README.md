# SPXW SWATCH

SPX 当日期权（0DTE）**IV 变化速度盯盘雷达**：ΔIV 热力图 + 25Δ Skew + 曲面残差。
数据来自 IBKR Gateway，经九层流水线，前端用 ECharts 渲染。

> **纯实盘**：没有模拟分支、没有特性开关、没有兼容分支、没有回退路径。
> 拿不到当日到期链就 fail-closed 退出，而不是"降级成某个默认值继续跑"。

---

## 1. 快速开始

```bash
# 1. 依赖（项目自带 venv，在 E 盘）
venv/Scripts/python.exe -m pip install -r requirements.txt   # 若存在
# 实际依赖：ib_async 2.1.0 / aiohttp 3.14.3 / numpy 2.5.3 / pandas 3.0.5 / scipy 1.18.1 / tzdata

# 2. 自检（不启动服务）
venv/Scripts/python.exe run.py --check

# 3. 启动（需要 IB Gateway 在 127.0.0.1:4002 上，见 config/ibkr.json）
venv/Scripts/python.exe run.py
# 然后浏览器打开 http://127.0.0.1:8060/
```

⚠️ **回归必须用 `venv/Scripts/python.exe`**，裸 `python` 缺 `ib_async` / `aiohttp`，
会在 import 阶段崩成**假红**。

## 2. 架构：九层单向依赖

```
L0  contracts/      契约 / 枚举 / 端口          ┐
    config/         配置（12 个 JSON + loader）  ┘ 任何人可 import，纯标准库
L1  core/           时钟、会话网格几何、环形缓冲、错误、日志      纯标准库
L2  acquisition/    IBKR 接入（ib_async）                        纯标准库
L3  state/          TickStore、行情状态                          纯标准库
L4  models/         曲面模型 Raw / SVI / SSVI                     ★唯一允许 numpy/pandas/scipy
L5  features/       ΔIV 热力图、Skew、冲量、曲面引擎、毛刺闸门、持久化
L6  serialization/  位图编解码、帧编码、载荷组装
L7  transport/      WS 广播、推送循环、HTTP 静态
L8  app/            唯一可 import 全层的组装根
```

**下层不得 import 上层。** 机械守卫：`tools/selfcheck_structure.py` 的 `[2]` / `[2b]`。
**只有 `models/` 能 import 数值库** —— 否则 numpy 类型会顺着返回值漏进帧里，
而帧必须只有普通 dataclass。守卫：`tools/selfcheck_duty.py` 的 `[9b]`。

## 3. 目录

```
config/         12 个 JSON（彼此独立，禁止跨文件引用）+ loader.py
contracts/      enums, tick, feature, frame, ports
core/           clock, session_grid, ring_buffer, errors, logging_setup
acquisition/    ibkr_gateway, chain_resolver, contract_factory, feed_errors,
                subscription_manager, tick_router, feed_reconcile, feed_service,
                spot_source, spot_synthesis, spot_tap, rate_limit_watch
state/          tick_store, market_state
models/         曲面模型（原版移植 + 按 400 行拆分 + 全量去硬编码）
features/       热力图、Skew、冲量、曲面引擎、毛刺闸门、持久化
serialization/  numeric, bitmap_codec, cell_encoder, heatmap_matrix,
                skew_series, surface_encoder, frame_encoder, payload_builder
transport/      server, ws_broadcaster, http_static, push_loop
app/            pipeline（组装根）、persistence_boot
web/            前端 JS/HTML/CSS（ECharts 5.5.1 在 vendor/）
tools/          机械门禁与回归。**不属于任何运行时层**：可 import 任何层，
                但任何层都不得 import tools/（`[2b]` 守着）
notes/          知识库：架构、速查卡、排错、会话记录
tmp/            gitignore 的一次性脚本区（`.gitignore` 与
                `selfcheck_core.py::NON_SOURCE_DIRS` 两处都有它的条目，缺一即误报）
```

## 4. 配置

12 个独立 JSON，**禁止 `$ref` / `include` / `extends`**，一个文件不跨层级、不跨模块。
缺键即抛 `ConfigError`（fail fast，加载器**不含任何业务默认值**）。

| 文件 | 层 | 关键键 |
|---|---|---|
| `app.json` | L0 | `symbol` `option_trading_class` `zero_dte_only` `timezone` `sessions[]` |
| `logging.json` | L0 | `level` `file` |
| `surface.json` | L0 | `active_model` `risk_free_rate` + 曲面清洗/标定的全部可调常量 |
| `ibkr.json` | L2 | `host` `port` `generic_tick_list` `market_data_type` `use_model_greeks` `rate_limit_max_requests` |
| `subscription.json` | L2 | `num_strikes_each_side` `max_total_subscriptions` `recenter_trigger_strikes` |
| `spot.json` | L2 | `future_symbol` `synthesised_zones` `max_abs_carry` `max_carry_jump` |
| `state.json` | L3 | `option_buffer_seconds` `prune_interval_s` `health_stale_tick_s` |
| `features.json` | L5 | `impulse_windows_seconds` `glitch_*` `skew_target_delta` `heatmap_rows_each_side` `surface_refit_interval_s` |
| `persistence.json` | L5 | `db_dir` `db_filename` `archive_dir` `queue_maxsize` |
| `serialization.json` | L6 | `heatmap_bucket_seconds` `heatmap_max_buckets` `heatmap_encoding` `surface_residuals_limit` |
| `transport.json` | L7 | `http_port` `ws_path` `push_interval_ms` `ws_compression` |
| `pipeline.json` | L8 | `compute_interval_ms` `log_stats_every_s` `shutdown_timeout_s` |

**跨文件数值不变量**（单个值都合法、组合起来才成立）由
`tools/selfcheck_config_invariants.py` 读多份文件核对 —— 配置文件之间仍然零引用。
例：`4 × num_strikes_each_side + 1 ≤ max_total_subscriptions ≤ 100`；
`heatmap_max_buckets ≥ 网格桶数`（否则最早那段被静默裁掉）。

## 5. 数据流

```
IB Gateway (4002)
  → ib_async tickOptionComputation（tickType 13 = MODEL_OPTION）
  → TickRouter → TickStore（内存环 RingBuffer）
  → 每 30s 一个桶
  → HeatmapEngine（ΔIV 矩阵，strikes 降序，**只含已走满的桶**）
    SkewEngine（RR25 / BF25）· ImpulseEngine · SurfaceEngine（models/ 出曲面与残差）
  → FrameEncoder（位图 bm + i16）
  → WsBroadcaster → ws://127.0.0.1:8060/ws
  → ECharts
```

**旁路**：原始 IV 桶 → `AsyncPersistenceWriter`（队列）→ `SessionFileStore`
→ `data/sessions/<到期日>.db`。启动时回灌，并把非当前会话的库文件**移动**到
`data/archive/`（**归档不删** —— 那是逐交易日的原始记录）。

## 6. 门禁：`run.py --check`（16 项）

| 编号 | 检查 | 编号 | 检查 |
|---|---|---|---|
| `[1]` | 文件长度（`.py` + `web/*.js` < 400 行） | `[9]` | 单一职能 |
| `[2]` | 依赖方向（L0–L8 单向） | `[9b]` | 依赖白名单（只有 `models/` 用数值库） |
| `[2b]` | 反向越界（层不得 import `tools/`） | `[10]` | 禁止硬编码 |
| `[3]` | 配置可读性（**含 JSON 重复键**） | `[11]` | 出站限速桶容量与 IBKR 配额 |
| `[4]` | 配置零耦合 | `[12]` | 时钟协议与裁剪路径 |
| `[5]` | 键级完整性（空键名 / null 值） | `[13]` | 联通与数据通道（帧契约 + 活链路） |
| `[6]` | 订阅容量 / 显示窗口 / 网格容量 | `[14]` | TickRouter 语义 |
| `[7]` | 配置键归属与接线（双向推导） | `[8]` | `__slots__` 一致性 |

```bash
venv/Scripts/python.exe run.py --check                    # 16 项全跑
venv/Scripts/python.exe tools/selfcheck.py --selftest     # 证明 16 项都不是空转
```

**覆盖率写在结果行里**（`16/16`）—— 少跑一项却报"全部通过"，是静默错值的门禁版。

### 非空转是怎么证明的

`--selftest` 把工程复制到临时目录，注入 **16 条"静默错值"型缺陷**（改完照常运行、
不报任何错，只有机械门禁能发现），逐条验证**目标检查项自己**打印了 `[FAIL]`。

⚠️ 判据是"目标检查项自己那一段有 `[FAIL]`"，**不是"退出码非 0"**：一个变异若同时
触发别的检查项，退出码照样非 0，于是"抓住了"这个结论是假的。

⚠️ **变异必须真的改变行为**。第一版 `[14]` 的变异把 `return None` 写成 `continue`，
而循环里后续槽位通常是空的 ⇒ 最终仍然 `return None` ⇒ 行为等价 ⇒ 报"没抓住"。
查下来是**变异无效**，不是判据空转 —— 这两个结论必须分得清。

### 独立检查器（不在 `--check` 里）

| 检查器 | 覆盖 | 状态 |
|---|---|---|
| `tools/check_web_contract.py` | 前端引用 → 定义（DOM id / `CFG.*` / 载荷字段） | ✅ 离线两项 + `--selftest` |
| `tools/check_matrix_codec.py` | 位图编解码往返 + `web/matrix_codec.js` 逐值对拍 | ⬜ 待建 |
| `tools/check_grid_contract.py` | 网格单元 = 已走满的桶（见架构 §8） | ⬜ 待建 |
| `tools/check_period_aggregation.py` | 前端周期聚合（含 `volumes` 传递） | ⬜ 待建 |
| `tools/check_session_grid.py` | 会话定义 ↔ 网格桶数 ↔ 环形缓冲容量 | ⬜ 待建 |
| `tools/check_surface_payload.py` | 曲面残差载荷（含抽样形状） | ⬜ 待建 |
| `tools/check_reconnect_gap.py` | 断流后的第一桶留白 | ⬜ 待建 |
| `tools/check_window_tolerance.py` | 现价往返不掉档（行为侧） | ⬜ 待建 |
| `tools/check_ws_compression.py` | WebSocket 压缩比 | ⬜ 待建 |
| `tools/ws_probe.py` | 连活服务抓帧的结构核对 | ⬜ 待建 |

⚠️ **配置注释里已引用其中几个检查器**（例如 `transport.json` 提到
`check_ws_compression`）。在它们建出来之前，那些引用是**设计意图而非既成事实** ——
别把注释当成"已经有东西守着"。

## 7. 回归

```bash
venv/Scripts/python.exe tools/selfcheck_clock.py            # [12]
venv/Scripts/python.exe tools/selfcheck_router.py           # [14]
venv/Scripts/python.exe tools/selfcheck_connectivity.py     # [13]
venv/Scripts/python.exe tools/check_web_contract.py --offline --selftest
```

临时探针一律写在 `<项目根>/tmp/`（**不要**写 `~/.workbuddy-ai/tmp/`），且必须在
`.gitignore` 与 `selfcheck_core.py::NON_SOURCE_DIRS` **两处**登记。

## 8. 仓库纪律

- **禁用 `git rm` / `git mv`**（2026-09-14 事故：执行期间整个 `web/` 从工作区消失，
  未提交改动丢失）。一律改用 `rm` / `mv` + `git add`。
- **同一文件的多个 `Edit` 必须串行**：并行发出会竞态，后来的静默覆盖先前的且不报错。
- 行数门禁是 **< 400**（严格小于）。余量 < 5 行会报警告。

## 9. 已知边界

**验证覆盖**

- ⚠️ **在线链路未验证**：`IbkrFeed` 连真实 Gateway、`SubscriptionManager` 的 300 退避、
  `SpotSourceSelector` 区段切换、`WindowFollower` 窗口重建 —— 四项都只有**离线冒烟**。
- ⚠️ **`pandas 3.0.5` 未验证**：移植保真度用"差分对拍"证明（同一份行情喂两套 `models/`，
  逐字段零差异），但那证明的是"**移植没引入差异**"，**没有**证明"pandas 3 没改变原版行为"。
  要回答后者得跑原版 `test_models.py`（已复制到 `tmp/`，**未跑**）。
- ⚠️ **`web/` 是零改动移植**（与 `HEAD` 逐字节一致）⇒ 只验证了"与 HEAD 一致"，
  不是"改对了"。补偿：跨语言端到端对拍（`tmp/web_e2e.py`，PASS 34 / FAIL 0 + 4 变异全抓）
  —— 但它仍是 `tmp/` 里的一次性探针，**未提为常驻回归**。

**已知未决**

- **曲面残差无方向字段**：`SurfaceInputPort.id_map` 不带 `right`，而 `pivot_table`
  默认按 strike 求均值拟合、`residuals()` 用未平均的原始行 ⇒ 同一 strike 出**两条**残差，
  前端无法区分（真实行情下 Put/Call IV 不同，两个点会一正一负、互相抵消）。待拍板。
- **前端 Top-3 高亮在细档位下是亚像素**（30 秒档最粗边 0.236px）—— 视觉规格待定。
  注意：既有的合成夹具几何与真实档位差两个数量级，所以那条回归**全绿也不能说明实盘可用**。
- **`models/forecasting/`**（EWMA / GARCH / HAR-RV）已移植但**未接线**，是否需要尚未确定。
  其中的可调常量（`TRADING_DAYS_PER_YEAR`、`_MIN_HISTORY`）因此**尚未配置化** ——
  属"无法验证的改动"，接线时必须一并处理（`[10]` 每次运行都会打印这条提醒）。

**工程余量**

- `acquisition/ibkr_gateway.py` = **399 行**，距 400 行门禁只剩 1 行。下次加两行
  （哪怕只是注释）就会违规。
  （`features/persistence_store.py` 于 2026-09-15 拆出 `persistence_archive.py` 后
  由 398 降到 365，**不再是瓶颈**。⚠️ 行数是**会腐烂的派生量** —— 要真值请实跑
  `run.py --check` 的 `[1]`，**别抄本节**。）

## 10. 深入阅读

| 想了解 | 去哪 |
|---|---|
| 架构、分层、目录、数据流、帧契约、各层实测证据 | `notes/memory/ARCHITECTURE.md` |
| 改代码前必扫的静默错值速查卡 | `notes/memory/QUICKREF.md` |
| 开发规范、接口约定、回归纪律 | `notes/memory/RULES.md` |
| 已踩的坑、IBKR 限速/行情权限、会立刻报错的陷阱 | `notes/memory/TROUBLESHOOTING.md` |
| 当前待办 / 已知缺陷 | `notes/context/open_tasks.md` |
| 某次会话做了什么 | `notes/sessions/YYYY-MM-DD/<任务ID>/handoff.md` |

> `notes/memory/MEMORY.md` 是**纯路由器**：只放"去哪找"和当前状态指针，
> 不承载内容。速查卡与清单类内容一律在独立文件里，由它指过去。
