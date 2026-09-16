# 架构与目录约定

> 本文件 = T1 层：系统架构、分层、目录、技术栈、数据流、**帧契约**。
> 本次为 **2026-09-15 白纸重写**（`notes/sessions/2026-09-15/rebuild-from-original/`）。

---

## 0. 这次重写的两个来源（必须先读）

| 来源 | 取什么 | 不取什么 |
|---|---|---|
| `live-volatility-surface`（原版） | **`models/` 曲面模型层**（Raw / SVI / SSVI + `svi_math` + adapter）、`build_clean_surface()` 的 IV 清洗与异常值剔除语义、曲面快照 + baseline 差分 | `live_surface.py` 的 **`ibapi` + 线程回调**实现、`dash_surface.py` 的 8006 行单体 Dash |
| `spxw_swatch` 旧版（`HEAD = bedbf11`，只读参照在 `../_ref_spxw_head`） | 分层纪律、每文件 < 400 行、配置零耦合、fail-closed、检查器 + 非空转、雷达功能（ΔIV 桶×行权价时间序列 / 25Δ Skew / GTH+RTH 会话网格 / 位图帧 / WS 推送） | 旧代码逐行照抄（本次是白纸重写） |

**一条有意偏离原版的地方**（不是分歧，是规则落地）：

> 原版把曲面模型的全部可调常量（清洗阈值、SVI/SSVI 标定超参、优化器区间、
> RNG seed）**写死在 `models/*.py` 的模块顶**。本项目第 3 条「禁止硬编码」不允许
> 这样 —— 旧项目的 `tools/selfcheck_hardcode.py` 明确判定：模块级字面量常量要么
> 来自配置，要么逐条登记进 `EXEMPT_CONSTANTS`，而**"调大调小会改变行为"的值不许
> 进例外表**。
> ⇒ 全部搬进 `config/surface.json`，由 `models/surface_params.py` 翻译成 frozen
> dataclass。**数值逐字一致，行为不变** —— 已用差分对拍证明（见 §11）。

**两条已拍板的分歧**（KAI 2026-09-15）：

1. **acquisition 用 `ib_async`，不用 `ibapi`。** `ib_async` 本身就是 `ibapi` 的
   asyncio 封装 —— **同一协议、同一个 Gateway**。而本项目的帧循环、WS 广播、
   HTTP 服务全部建在 asyncio 上（`aiohttp`），换成 `ibapi` 的线程回调模型要把
   `transport/` 整层重写，且丢掉旧采集层已实盘验证的行为。
   ⇒ 原版 `live_surface.py` **只取语义**（链解析、`marketDataType` 处理、
   清洗阈值、现货/已实现波动率请求），不逐行搬实现。
2. **numpy / pandas / scipy 只允许出现在 `models/` 层。** 旧项目刻意"数值计算
   全部用标准库"（理由：每层都能被单独读懂），但曲面拟合（SVI 的
   `scipy.optimize.minimize(SLSQP)`）本来就属于模型层。
   ⇒ L0–L3 仍为**纯标准库**，由 `selfcheck_duty.py` 机械守住。

---

## 1. 项目目标

SPXW 0DTE（当日期权）IV 变化速度盯盘雷达 + 曲面残差。

- 核心指标：**ΔIV 热力图**（桶 × 行权价的时间序列）+ **25Δ Skew**（RR25 / BF25）
  + **曲面残差**（`RawIV − ModelIV`，由 `models/` 提供）
- 数据来源：IBKR Gateway → `ib_async` → 多层流水线 → ECharts 前端

## 2. 技术栈与版本

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | **3.13.14**（项目 `venv/`，放在 E 盘） | 回归必须用 venv，见 `notes/memory/RULES.md §6.1` |
| `ib_async` | **2.1.0** | IBKR 接口（asyncio） |
| `aiohttp` | **3.14.3** | HTTP + WS 服务 |
| `numpy` / `pandas` / `scipy` | **2.5.3 / 3.0.5 / 1.18.1** | **只允许 `models/` 层 import** |
| `tzdata` | 2024.1+ | Windows 上 `zoneinfo` 必需 |
| ECharts | **5.5.1** | `web/vendor/echarts.min.js`（zrender 5.6.0，别跟主版本搞混） |
| SQLite | 标准库 | 旁路持久化（冷数据） |

> 版本号是 2026-09-15 实测（`venv/Scripts/python.exe -V` + `import ...; __version__`），
> 不是"预期版本"。⚠️ `pandas 3.0.5` 是相对原版编写年代的大版本跳跃，边界见 §11 末。

## 3. 严格分层单向依赖

```
L0  contracts/        契约/枚举/端口           → 任何人可 import          （纯标准库）
L1  core/             时钟、会话网格几何、环形缓冲、错误、日志          （纯标准库）
L2  acquisition/      IBKR 接入（ib_async）                            （纯标准库）
L3  state/            TickStore、行情状态                              （纯标准库）
L4  models/           曲面模型 Raw/SVI/SSVI + svi_math + adapter   ★原版移植（numpy/pandas/scipy）
L5  features/         ΔIV 热力图、Skew、冲量、曲面引擎、毛刺闸门、持久化  （纯标准库）
L6  serialization/    位图编解码、帧编码、载荷组装                       （纯标准库）
L7  transport/        WS 广播、推送循环、HTTP 静态                      （纯标准库）
L8  app/pipeline.py   唯一可 import 全层的组装根
```

**下层不得 import 上层。** 检查器：`tools/selfcheck_structure.py` `[2]`。
**依赖白名单**：`tools/selfcheck_duty.py` 机械守住"只有 `models/` 能 import
numpy/pandas/scipy"这条 —— 否则第 0 节的决策会在一周内被无声破坏。

## 4. 目录约定

```
config/           12 个 JSON + 2 个 Python（loader / __init__）。禁止跨文件引用。
contracts/        L0：enums, tick, feature, frame, ports
core/             L1：clock, session_grid, ring_buffer, errors, logging_setup
acquisition/      L2：ibkr_gateway, chain_resolver, contract_factory, feed_errors,
                  subscription_manager, tick_router, feed_reconcile, feed_service,
                  spot_source, spot_synthesis, spot_tap, rate_limit_watch
state/            L3：tick_store, market_state
models/           L4：base_surface_model, raw_surface_model, raw_cleaning, svi_math,
                  svi_fit, svi_reporting, svi_surface_model, ssvi_math,
                  ssvi_surface_model, market_params, surface_params, surface_adapter
                  （原版移植 + 按 400 行拆分 + 按第 3 条去硬编码，见 §0 注）
features/         L5：strike_window, delta_locator, glitch_filter, impulse_engine,
                  heatmap_engine, heatmap_snapshot, skew_engine, atm_reader,
                  surface_engine, feature_engine, persistence, persistence_store, persistence_archive
serialization/    L6：numeric, bitmap_codec, cell_encoder, heatmap_matrix, skew_series,
                  surface_encoder, frame_encoder, payload_builder
transport/        L7：server, ws_broadcaster, http_static, push_loop
app/              L8：pipeline（唯一组装根）、persistence_boot（启动期持久化接回）
web/              前端：JS + HTML + CSS（ECharts 5.5.1 在 vendor/）
tools/            机械门禁与回归。**不属于任何运行时层**：可 import 任何层，
                  但任何层都不得 import tools/（由 selfcheck_structure.py 守）。
tmp/              gitignore 的一次性脚本区（`selfcheck_core.py::NON_SOURCE_DIRS` 含它）
```

**落盘进度**（2026-09-15）：**L0–L8 九层 + `web/` + `tools/` 门禁 16/16 全部落盘并实测**；
`run.py --check` 覆盖 **16/16**，`--selftest` 注入 16 条变异**全部被抓到**（见 §16）。
`features/` 里有两个**拆分产物**（不在原版目录里）：`atm_reader.py`（116 行，从
`feature_engine` 拆出 ATM 读数）与 `heatmap_snapshot.py`（90 行，从 `heatmap_engine`
拆出快照导出/载入）—— 拆的理由只有一个：**撞 400 行门禁**（拆前 407 / 432 行）。
`app/` 同理拆出 `persistence_boot.py`（81 行，启动期打开 / 归档 / 恢复会话库）——
`pipeline.py` 旧版就 381 行，加完曲面接线必然撞门禁。
`acquisition/` 里有一个**设计清单之外但必需**的文件 —— `spot_tap.py`（50 行）：
`IbkrFeed` 算 ATM 窗口需要现价，去读 L3 存储就构成 L2→L3 反向依赖，
故用一个"就地留存现价 + 时间戳"的薄壳切断它。`acquisition/__init__.py` **刻意空壳**
（理由见该文件 docstring 与 §12）。

## 5. 配置体系

- **12 个独立 JSON**，禁止 `$ref` / `include` / `extends`；一个文件不跨层级、不跨模块
- 缺键即抛 `ConfigError`（fail fast，不静默兜底）；加载器**不含业务默认值**
- 死配置键 = 失败（`UNWIRED_IS_FAILURE = True`）
- 由 `selfcheck_config.py` + `selfcheck_config_invariants.py` 校验

| 文件 | 层 | 关键键 |
|---|---|---|
| `app.json` | L0 | `symbol` `option_trading_class` `zero_dte_only` `timezone` `sessions[]` |
| `logging.json` | L0 | `level` `file` |
| `ibkr.json` | L2 | `host` `port` `client_id` `generic_tick_list` `market_data_type` `use_model_greeks` `rate_limit_max_requests` |
| `subscription.json` | L2 | `num_strikes_each_side` `max_total_subscriptions` `recenter_trigger_strikes` |
| `spot.json` | L2 | `future_symbol` `synthesised_zones` `max_abs_carry` `max_carry_jump` |
| `state.json` | L3 | `option_buffer_seconds` `prune_interval_s` `health_stale_tick_s` |
| `persistence.json` | L5 | `db_dir` `db_filename` `archive_dir` `queue_maxsize` |
| `features.json` | L5 | `impulse_windows_seconds` `glitch_*` `skew_target_delta` `heatmap_rows_each_side` |
| `serialization.json` | L6 | `heatmap_bucket_seconds` `heatmap_max_buckets` `heatmap_encoding` `heatmap_max_ffill_buckets` `surface_residuals_limit` |
| `transport.json` | L7 | `http_port` `ws_path` `push_interval_ms` `ws_compression` |
| `pipeline.json` | L8 | `compute_interval_ms` `log_stats_every_s` `shutdown_timeout_s` |
| `surface.json` | L0 | `active_model` `risk_free_rate` `dividend_yield` + 曲面清洗/标定的全部可调常量 |

> ⚠️ **`transport.json::bucket_seconds_s` 已删除**（2026-09-15，`--check` 的 `[7]` 抓出）。
> 它是我在移植 L7 时**凭空补的键**：注释写着"推送必须对齐世界时间的桶边界"，但那个
> 机制**从未实现**（`PushLoop` 只按 `push_interval_ms` 固定节奏 + 帧序号变化触发），
> 旧项目 `HEAD` 的 `transport.json` 里也没有这个键。一个没人读的键 + 一段描述不存在
> 行为的注释 = 一份过期的真相，会误导下一个会话去"实现"它。**推送不对齐桶边界是刻意
> 的**：热力图新列出现的时刻由 L6 的 `heatmap_bucket_seconds` 决定，与本键无关，两者
> 相差最多一个推送周期（400ms，相对 30s 桶 = 1.3%）。

## 6. 数据流

```
IB Gateway (port 4002)
    ↓ ib_async tickOptionComputation (tickType 106 / modelGreeks)
TickRouter → TickStore（内存环 RingBuffer）
    ↓ 每 30s 桶
HeatmapEngine.build() → ΔIV 矩阵（strikes 降序，**只含已走满的桶**）
SkewEngine.compute()  → RR25 / BF25
ImpulseEngine         → 冲量事件
SurfaceEngine         → models/ 出曲面与残差（RawIV − ModelIV）
FrameEncoder          → 位图编码（bm + i16）
WsBroadcaster         → ws://127.0.0.1:8060/ws
ECharts               → 热力图 + Skew 曲线
```

**旁路（与主链并行，L5 出口）**：原始 IV 桶 → `AsyncPersistenceWriter`（队列）
→ `SessionFileStore` → `data/sessions/<到期日>.db`；启动时 `recover()` /
`recover_skew()` 回灌，并把非当前会话的库文件**移动**到 `data/archive/`
（**归档不删** —— 那是逐交易日的原始记录）。

## 7. 帧契约（对外唯一接口）

- `strikes` **降序**（高行权价在前 = 屏幕在上），由 `HeatmapEngine.build()` 的
  `sorted(..., reverse=True)` 保证；前端 `yAxis.inverse = true` **成对**存在。
  缺一即上下翻转 —— 两处必须一起改。
- `bucket_labels` 与 `values` 的列一一对应；**列数 = `current`**（见 §8）。
- `bucket_index` = **时间读数**（`bucket_index_of_ts(now)`），不是矩阵列数 ——
  前端进度条依赖它。**矩阵列数 = `bucket_index`**，不要混。
- 位图编码：`enc` / `scale` / `bm` / `i16` / `filled`；位序、字节序、遍历顺序
  **只以 `serialization/bitmap_codec.py` 的 docstring 为准**。
- `vol_bm` / `vol_i16` 是**可选字段**（`matrix.volumes` 非空时才发）——
  契约检查器不得把它当必填。
- ⚠️ **`skew` 与 `skew_series` 是两个不同的东西** —— 别合并，也别用序列末项代替前者。
  `skew` 是**实时**读数（本轮刚算出的那个点）；`skew_series` 只含**已走满的桶**
  （见 §8）⇒ 序列末项最多比 `skew` 旧**一整个桶**（30 s）。
  折线图用序列（定稿才画，否则最后一个点在桶内抖动），顶栏读数用 `skew`。
  `frame_encoder` 里 `skew.latest` **取 `frame.skew`**，不是 `skew_series[-1]`
  —— 后者是旧语义下的写法（那时序列含正在走的桶），在新语义下会让顶栏滞后半分钟。
- `surface` 段是**曲面摘要**（`model` / `fitted` / `avg_rmse` / `residuals` / …），
  首轮拟合完成前为 `null`。`residuals` 的条数上限由
  `serialization.json::surface_residuals_limit` 控制（超限按**等间隔抽样**，
  保序、确定性 —— 不取绝对值最大的 N 个，那会让点全堆在翼部）。

## 8. 核心契约：网格单元 = 一个**已走满**的时间桶

> 这条是 2026-09-15 重写的**唯一新契约**，也是最容易再次写错的一条。

- 矩阵列取 `0 .. current-1`（`last_done = current - 1`）。**未走满的桶不得出列。**
- `SkewEngine.series(moment)` 只返回 `bucket <= last_done` 的点；
  `latest()` 不受影响（顶栏实时读数，不是网格）。
- 前端聚合只保留**完整组**：`outCols = floor(cols / g)`（`g > 1` 时末尾凑不满的
  那组整组丢弃 —— 这正是"周期只出已走满的组"）。
  ⚠️ **修正（2026-09-15，移植 `web/` 时核对）**：本条原先写作"**不得**有 `g == 1`
  的恒等短路（那会让默认 30 秒档 100% 中招）"—— **那是修复前状态的描述，是错的**。
  `g == 1` 时 `floor(cols / 1) = cols`，且元字段换算（`bucket_index / g`、
  `bucket_seconds * g`）同样恒等 ⇒ **短路返回原块与走聚合路径数值恒等，合法**。
  真正保证"末列定稿"的是**后端**（矩阵只含已走满的桶）；前端在 `g == 1` 时
  不做任何丢列是**对的**（每个基线桶自成一组，而后端已保证每个桶都走满）。
  `web/period.js::aggregate` 的 `if (!(g > 1)) { return block; }` 因此**保留**，
  它是"g 无效即不聚合"的保护，不是绕过语义的捷径。
  ⇒ **`tools/check_grid_contract.py` 不得断言"没有 `g == 1` 短路"** —— 那会把
  正确代码判成违规。该守的是"`g > 1` 时确实丢掉了末尾不满的组"。
- **颜色锁定不需要额外机制**：数据源头不再产生变化值 ⇒ 颜色是数据的纯函数 ⇒
  天然恒定。**加缓存 = 第二份真相**，不做。
- 守住它的检查器：⚠️ **`tools/check_grid_contract.py` 尚未建**
  （**#15 已于 2026-09-15 完成 `--check` 16/16，但这 8 个独立检查器仍待建**，
  状态表见 `README.md §6` 与 `notes/context/open_tasks.md`）。在那之前，这条契约
  **没有任何机械守卫** ——
  L5 的 `tmp/l5_smoke.py` 里有一条"颜色锁定"判据（变异反证：差异格数 0 → 21），
  但那是**一次性探针**，不是常驻回归。**这是当前最大的已知门禁缺口。**
- ⚠️ **写回归夹具时也要守这条**：夹具把"正在走的桶"当定稿，会与产品犯同一个错
  （旧项目的三个夹具就是这么错的，见 `notes/sessions/2026-09-15/grid-rebuild/`）。

## 9. 纯实盘

- 无模拟分支、无特性开关、无兼容分支、无回退路径
- `run.py` **不带参数 = 启动服务**；唯一开关是 `--check`（自检，不启动）
- 离线回归夹具：`tools/fixtures.py`（`FakeClock` 可推进时钟、`FakeTicker` /
  `FakeComputation` / `FakeContract` 对 `ib_async` 结构的忠实模拟、`RecordingSink`）
  ⚠️ 夹具锚定日在**远期**（`ANCHOR_DAY`，2030-01-01 起第一个工作日）——
  这不是随便挑的：锚在过去会让 `[12]` 的裁剪判据对"注入时钟"与"墙钟回落"
  给出相同结论，判据即空转。理由写在该常量上方。

## 10. 已知边界

见 `README.md` §9「已知边界」（验证覆盖 / 已知未决 / 工程余量）。

---

## 11. models/ 移植保真度证据（2026-09-15 实测）

**方法：差分对拍，不是"跑原版测试"** —— 同一个合成行情喂给两套 `models/`，
把 `stats() / diagnostics() / surface() / clean_df() / residuals() / iv()` 规范化
成 JSON 后逐字段比对。探针：`tmp/port_probe.py`（一次性工具，见其 docstring）。

关键点：**探针必须冻结时钟**（`time.time` 与 `pd.Timestamp.now`），否则
`raw_cleaning` 的 tick 年龄与 `year_fraction_from_expiry` 的 TTE 会随"跑的那一天"
变，金标准隔天即失效 —— 那不是移植有差异，是探针自己漂移。

```
原版   E:/US.market/SPXW SWATCH/live-volatility-surface/models/   → 金标准
移植版 E:/US.market/SPXW SWATCH/spxw_swatch/models/               → 待测

对拍结果：总差异条目 0（三个模型 × 六个输出面，全部逐字段一致）
变异反证：把 svi_n_multistart 5→1 重跑 → 差异 210 条，avg RMSE 0.001645→0.005517
          ⇒ 对拍确实在比东西，不是空转
```

其余实测（`venv/Scripts/python.exe`，numpy 2.5.3 / pandas **3.0.5** / scipy 1.18.1 /
ib_async 2.1.0 / aiohttp 3.14.3）：

| 项 | 结果 |
|---|---|
| `isinstance(SurfaceModelAdapter(), SurfaceModelPort)` | True |
| `isinstance(mock_app, SurfaceInputPort)` | True |
| 三个模型的 `summary()` 出口 | 只有 str/int/float/bool/None + tuple，**无 pandas/numpy 对象** |
| fail-fast（缺键 / 未知模型名 / 区间元数错 / 下界>上界） | **7/7 全部抛错**，无一静默兜底 |
| 全部文件 < 400 行（`>=` 判超） | 合规（最大 `models/svi_math.py` 364） |
| 多起点 RNG 流语义 | 保留：同进程内连续两次 fit 拿到不同起点（RMSE 0.001645→0.001018） |

> ⚠️ `pandas 3.0.5` 是相对原版编写年代的大版本跳跃。本次对拍用的是**同一个
> venv**，所以原版与移植版跑在同一个 pandas 上 —— 对拍证明了"移植没引入差异"，
> 但**没有**证明"pandas 3 没有改变原版行为"。后者要靠原版自己的 `test_models.py`。

---

## 12. L2 `acquisition/` + L3 `state/` 移植证据（2026-09-15 实测）

**方法：整目录 `cp` + 只改「层号引用」，然后用逐行 diff 归类证明"没有逻辑改动"。**
本轮**不做**差分对拍 —— 对拍适用于"算法被重写"，而这两层是**逐字搬运**；
对搬运而言，逐行 diff 比跑功能用例更直接（它证明的是"没动过"，用例只能证明"动的部分没坏"）。

### 12.1 差异归类：**零内容改动**

```bash
for d in acquisition state; do for f in _ref_spxw_head/$d/*.py; do diff "$f" "spxw_swatch/$d/$f"; done; done
```

57 条差异全部落在三类，无一条是逻辑改动：

| 类 | 例 | 条数 |
|---|---|---|
| ① 层号（新层图：old L1→L2 / L2→L3 / L3→L5 / L4→L6 / L5→L7 / L6→L8） | `L1 — 采集层` → `L2 — 采集层` | 55 |
| ② 措辞（**纯实盘**，无模拟分支） | `模拟模式` / `模拟器` → `离线夹具` | 含在 ① 内 |
| ③ 依赖行（写全 L1=core） | `依赖：L0。` → `依赖：L0（config / contracts）与 L1（core）。` | 含在 ① 内 |

⚠️ **层号必须按含义改，不能 `sed` 字符串替换** —— `L0、L1（rate_limit_watch）`
里的 `L1` 指的是 `rate_limit_watch` 自己（它是 L2），而 `L1（core）` 的 `L1` 是 core。
同一条 `L1` 在不同行里指向不同的层。57 条全部逐条看上下文改写。
另有 2 条藏在**代码注释**里（`feed_service.py:343-344` 的 `L1 不认识 L3`），
docstring 批量替换会漏掉 —— **注释里的层号也是层号**。

### 12.2 功能冒烟 37/37 + 非空转

```bash
venv/Scripts/python.exe tmp/l2l3_smoke.py      # PASS 37 / FAIL 0 / RC=0
```

覆盖 `TickStore`（13 项）/ `MarketState`（6 项）/ `TickRouter`（10 项，
含三条拒绝路径：IV 超 `max_iv`、低于 `min_iv`、无 computation）。

**非空转反证**：`config/features.json::max_iv` 3.0 → 0.05 ⇒ 4 条 FAIL
（接受数 2→0、sink 0 个、`rejected` 3→5、越界断言失效）+ `IndexError`，
`REAL_RC=1`；还原后复跑 37/0。

### 12.3 `ib_async` 依赖边界：14 个模块里 **3 个拉起**

```text
拉起（3）: acquisition.contract_factory（直接）/ acquisition.ibkr_gateway（直接）
           acquisition.feed_service（**传递性** —— 模块级 import 了上面两个）
安全（11）: 其余全部（含 state/ 两个）
```

⇒ **`acquisition/__init__.py` 刻意保持空壳**，不做 re-export。否则一句
`import acquisition` 就会把 `ib_async` 拉进内存，`run.py --check` 与 `tools/` 下
只跑 `state`+`features`+`serialization`+`transport` 的离线回归将无法脱依赖。
调用方按需显式 import：`from acquisition.feed_service import IbkrFeed`。

> ⚠️ 文档里曾写"L2 中仅有的两个模块 import `ib_async`" —— **实测是 3 个**。
> "直接 import 的两个"不等于"只有两个会拉起"。这类句子要写清**口径**，
> 否则下一个会话会照着它做错误的依赖假设。

### 12.4 行数门禁（全库复扫）

```text
检查文件数 = 48    超限(>=400) = 0
最接近上限: 399 acquisition/ibkr_gateway.py  ← 余量 1 行，高危
            391 acquisition/feed_service.py  364 models/svi_math.py
```

⚠️ `ibkr_gateway.py` 原版 398 行，本轮**只改 docstring** 就涨到 400 行（判据 `>=` 即超）
⇒ 是**真违规**，靠收敛重复文档才退回 399。**教训：注释也算行，
门禁要在每次落盘后跑，不能等收尾。**

## 13. L5 `features/` 移植证据（2026-09-15 实测）

### 13.1 一个必须先解决的结构冲突：单到期日 vs 曲面门槛

原版曲面层有一道硬门槛：`num_expiries >= 2`（`raw_cleaning` 里写死）。而本项目
`config/app.json::zero_dte_only = true` ⇒ **只订阅一个到期日** ⇒ SVI / SSVI
**永不拟合**、残差恒为空、**且不抛任何异常**（静默空值，不是崩溃）。

配置对照实测（`tmp/probe_surface_gate.py`：同一份代码、只翻 `min_expiries` 一个键）：

```text
Q1  本项目配置  min_expiries=1  → surface_ok=True   SVI fitted=1/1   model_iv 48/48
Q2  原版口径    min_expiries=2  → surface_ok=False  SVI fitted=0/1   model_iv  0/48
```

KAI 2026-09-15 拍板**「只订阅 0 DTE」** ⇒ 按"单到期日也做曲面"落地：
门槛字面量搬进 `config/surface.json`（`min_expiries: 1` / `min_strikes: 8`），
`raw_cleaning` 里两处写死值改为读 `CleaningParams`。
**SSVI 在本项目结构上不可用**（它要求 ≥2 个到期日做联合标定）—— 已在
`surface.json` 的 `_ssvi_comment` 里写明，默认 `active_model = SVI`。

fail-fast 实测：删掉 `min_expiries` 键 ⇒
`ConfigError: 缺少必需配置项 config/surface.json 的 'min_expiries'`。

### 13.2 核心契约落地（§8）

`heatmap_engine.build()`：

```text
last_done = current - 1                      ← 只含已走满的桶
labels    = tuple(self._clock.bucket_labels()[:current])
_row_values(bucket, last_done) / _row_volumes(tick_bucket, last_done)
```

参数名由 `current` **刻意改为 `last_done`** —— 让任何漏改的调用点立刻 `NameError`
而不是静默错一列。`skew_engine.series(moment)` 同步过滤：
`last_done = clock.bucket_index_of_ts(moment) - 1`，序列只到 `last_done`；
`latest()` **不过滤**（它本就是实时读数）。

### 13.3 冒烟 **PASS 32 / FAIL 0** + 变异反证（非空转）

```bash
venv/Scripts/python.exe tmp/l5_smoke.py            # PASS 32 / FAIL 0   RC=0
venv/Scripts/python.exe tmp/mutate_grid_contract.py # PASS 25 / FAIL 7   RC=1（变异后）
```

夹具用**带种子的随机游走**（`random.Random(20260915)`，`WALK_SIGMA = 0.004`）——
**这个 σ 不是随手选的**，见 13.4。

变异内容（`inspect.getsource` 只替换 `build` 一个方法，不动磁盘源码）：

```text
last_done = current - 1                              →  last_done = current
labels = tuple(...bucket_labels()[:current])         →  ...[: current + 1]
```

⇒ 失败判据 **0 → 7 条**，其中**「颜色锁定」那条变红**（差异格数 = 21）：

```text
PASS  两帧确实落在同一个桶（前提成立）        → 1782 / 1782
PASS  ⚠️ 自检：桶内那一跳确实被毛刺过滤器放行  → 4/25 档
FAIL  ⚠️ 矩阵逐格完全相同（颜色锁定）         → 差异格数 = 21
FAIL  volumes 也逐格相同
```

⇒ **非空转成立**：该判据确实在测"正在走的桶不得出列"这条契约。

### 13.4 ⚠️ 本轮最深的坑：判据"全绿"其实是空转

第一次跑变异反证时，「颜色锁定」**不变红**。根因不是代码，是**测试前提不成立**：

`GlitchFilter._off_baseline` 用 `4 × MAD` 判 GLITCH，而 **GLITCH 不写进时间桶**。
原夹具历史是**线性缓升**（每桶 +0.0005）⇒ `MAD ≈ 0.001` ⇒ 门槛 `0.004`
⇒ 测试用的"桶内抬 0.05"那一跳**被判 GLITCH 拦下** ⇒ `HeatmapEngine.observe()`
**根本没写进桶** ⇒ `latest_option()` 拿到的还是旧 tick ⇒ 两帧**必然**相同
⇒ "两帧矩阵相同"这条判据**恒真**，无论代码对不对。

**修法两条**：

1. 夹具改成带种子的随机游走（σ = 0.004 ⇒ `MAD ≈ 0.0027` ⇒ 门槛 ≈ 0.011，
   桶内 +0.003 能通过）—— **夹具必须按被测过滤器的量纲设计，不是按"看着合理"设计**；
2. B 段加**自检判据**：「桶内那一跳确实被毛刺过滤器放行、写进了桶（否则本段空转）」
   ⇒ 实测 `4/25 档`。**任何"两帧应该相同"的判据，都必须先证明"这一帧真的变了"。**

同类前车之鉴（本项目已有两个）：`harness-silent-pass-audit` 记的"两组对照函数写好
却没接进汇总函数"、"退出码取反"。

### 13.5 曲面的时间代价：必须限流

实测单次 SVI 拟合（48 个点、5 个多起点）：**中位 618 ms / 最坏 1439 ms**，
而推送节拍只有 **400 ms** ⇒ 曲面拟合**绝不能每轮 compute 都跑**。
新增 `config/features.json::surface_refit_interval_s = 30.0`，由
`SurfaceEngine.due(now)` 守住；L8 调用时还应放进线程，避免阻塞事件循环。
实测（冒烟 D 段）：间隔内 `refits` 13 → 13；超过 30s 后 13 → 14。

### 13.6 契约缺陷修正：`SurfaceInputPort` 的真形状

原 `contracts/ports.py` 的 docstring 写 `{expiry: {strike: iv}}` /
`{expiry: underlying_con_id}`，而**消费方 `raw_cleaning.py` L57–L105 要的是
按 `reqId` 索引的三张平行表**：

```text
iv_dict    = {req_id: point}            id_map  = {req_id: (expiry, strike)}
quote_dict = {req_id: {...}}
```

照错形状写适配器 ⇒ `if rid not in app.id_map: continue` 把每一行都跳过
⇒ `fresh_count == 0` ⇒ 曲面恒为空，**且不抛任何异常**。
已按消费方代码逐字段重写 docstring 并标行号，明确
「**形状以消费方代码为准，不以本 docstring 为准**」。
`features/surface_engine.py` 按真形状实现（reqId 键 = `(expiry, strike, right)` 元组）。

### 13.7 行数门禁（含 L5 全库复扫）

```text
检查文件数 = 61    超限(>=400) = 0
余量 <5 行的文件（建议 Task #15 列为警告）:
  399 acquisition/ibkr_gateway.py
  398 features/persistence_store.py
```

⚠️ `feature_engine.py` 拆前 **407 行**、`heatmap_engine.py` 拆前 **432 行** ——
两者都是本轮**真违规**，靠拆出 `atm_reader.py` / `heatmap_snapshot.py` 解决
（拆后 334 / 389 行）。**移植时"先搬完再收尾"必然撞门禁，要边搬边量。**

## 14. L6 `serialization/` + L7 `transport/` + L8 `app/` 移植证据（2026-09-15 实测）

### 14.1 来源与 L6 的硬事实

**原版 `live-volatility-surface/` 没有这三层**（它只有 `models/` + 单体脚本
`live_surface.py` / `dash_surface.py`）⇒ L6–L8 + `web/` 的移植来源是
**旧项目 HEAD**（`_ref_spxw_head`，`bedbf11`）。

**L6 只 import L0 + L1，零处 `features.*`**（实测 `serialization/` 全部跨层 import：
`config.loader` / `contracts.*` / `core.errors`）。`PayloadBuilder` 的入参是 L0 的
`FeatureBundle`，L8 负责把 L5 的输出喂给它 —— **L6 与 L5 完全解耦**，
这是移植时最容易"顺手"破坏的一条（加一行 `from features...` 就没了）。

### 14.2 ⚠️ L6 落地时补的三处**静默缺口**

旧版的 `PayloadBuilder.build()` 是逐字段显式搬运的，而新项目的 `Frame` 多了两个
字段 ⇒ **漏传不报错，只让那个字段恒为 `None`**（前端表现为"这个功能一直没有数据"）：

```text
1. Frame.surface  —— build() 没搬 bundle.surface ⇒ 帧里 surface 恒为 null
2. Frame.skew     —— 契约里原本没有这个字段；build() 也没搬 bundle.skew
3. skew.latest    —— 编码器取 skew_series[-1]，而新语义下序列只含已走满的桶
                     ⇒ 顶栏读数最多滞后一整个桶（30 s）
```

第 3 条是**语义性回归**（不是漏字段）：旧项目里 `skew_series` 含正在走的桶，
所以 `[-1]` 恰好是实时点；`ARCHITECTURE §8` 给序列加了 `last_done` 过滤之后，
`[-1]` 就变成了"上一个桶"。修法是**给 `Frame` 加 `skew` 字段**并让编码器取它
（`FeatureBundle` 本来就有 `skew` 与 `skew_series` 两个字段，说明设计定稿时
已经预留了，只是 `Frame` 漏了）。

`build()` 里因此写了一行注释说明**为什么不用 `dataclasses.replace` 这类自动搬运**：
显式列表让漏传在 code review 时看得见。

### 14.3 层号改写脚本**不幂等** —— 用占位符 + 标记文件兜底

`tmp/port_layer_refs.py`：旧 6 层 → 新 9 层的映射对**所有层都一样**
（`L0→L0 L1→L2 L2→L3 L3→L5 L4→L6 L5→L7 L6→L8`），所以做成了通用脚本。

⚠️ 它**不幂等**：新层号 `L2`/`L3`/`L5`/`L6` 全都落在被匹配的 `[0-6]` 范围内
⇒ 对已改过的目录再跑一次会把它们再串一遍，**而且改完语法照样合法、能 import**。
纯文本无法可靠区分"旧层号"与"已改过的新层号"，所以：
① 用**占位符双阶段**替换（把旧层号与新层号在空间上分开，替换顺序不再有约束）；
② 处理过的目录记进 `tmp/.ported_dirs.json`，重复跑被拒绝（除非 `--force`）。

命中统计（每个文件都报出来，不达标即退出码非 0）：

```text
serialization/  31 处      transport/  14 处 + 措辞 1 处      app/  16 处
```

### 14.4 冒烟 + 变异反证

```text
tmp/l6_smoke.py   PASS 39 / FAIL 0    （复用 l5_smoke 的夹具，证明 L5↔L6 接缝同源）
  --mutate=surface  ⇒ FAIL 7   （surface=bundle.surface → None）
  --mutate=latest   ⇒ FAIL 2   （frame.skew → skew_series[-1]）
tmp/l8_smoke.py   PASS 30 / FAIL 0    （真跑 Pipeline()，验装配接缝）
  --mutate=session_key ⇒ FAIL 2（session_key 不再取 clock.expiry_str()）
```

L6 冒烟覆盖：组装（6 个字段逐个断言）→ 编码（合法 JSON / 键齐全 / 无裸 NaN）→
**latest 语义**（先断言"实时点与序列末项确实不同"，否则本段空转）→ residuals
抽样（含"不取绝对值最大的 N 个"）→ 配置 fail-fast（缺键 / 值 0）→ 空 bundle 边界。

L8 冒烟覆盖：`Pipeline()` 能构造（8 个组件类型）→ 关键接缝（`surface_engine`
模型名/限流间隔/实例同一性、`is_delayed` 与 `market_data_type` 推导一致）→
10 个配置全加载 → `boot_persistence` 单元行为（假对象验"谁被调用、传了什么"）。

⚠️ L8 冒烟**不调用 `start()`**：没有 Gateway，本层也不该验在线行为。

### 14.5 全库层号一致性核对（一次性，不进机械门禁）

```text
① 模块头 'L{n} — ' 与所属目录：71 文件，不符 1（core/errors.py 写 L0，已修为 L1）
   models/ 13 个文件没有中文模块头 —— 它们是原版英文 docstring 的逐字移植
② 带模块名的层号引用（如 'L2（rate_limit_watch）'）：错配 0
③ 依赖行层号：错配 0
```

**为什么不把"模块头"做成机械门禁**：它只是文档，不影响正确性；而 `models/`
为保真对照刻意保留英文 docstring ⇒ 门禁一上就得开 13 条例外，
正是"清单越守越长"的起点。**真正该机械守的是跨层 import 的方向**
（`tools/selfcheck_structure.py`，Task #15）。

> ⚠️ 写这类核对脚本时踩了两个假阳性：① 正则 `^L(\d) — ` 忘了 `re.MULTILINE`
> ⇒ 71 个文件全报"没有模块头"；② 把 `L59–L105` 这类**行号引用**当层号
> ⇒ 14 条"越界层号"假警报。**核对脚本自己也要被核对。**

### 14.6 行数门禁（全库）

```text
检查文件数 = 79    超限(>=400) = 0
余量 < 20 行: 399 acquisition/ibkr_gateway.py   398 features/persistence_store.py
              391 acquisition/feed_service.py   389 features/heatmap_engine.py
app/pipeline.py = 364（拆出 persistence_boot.py 之后；拆前 381 + 曲面接线 ≈ 394）
```

---

## 15. `web/` 前端移植证据（2026-09-15 实测）

### 15.1 来源与改动性质：**零改动**

来源 = 旧项目 HEAD（`_ref_spxw_head/web/`，`HEAD = bedbf11`），18 个文件：
`index.html` / `style.css` / 14 个 JS / `vendor/echarts.min.js`（1.0 MB，ECharts 5.5.1）。

**证据**：`git status --short web/` 输出为空 ⇒ 工作区 `web/` 与 `HEAD` **逐字节一致**。

这不是"没做"，是**保真度证据** —— 本轮 KAI 报的两个缺陷（网格未按整点触发 /
颜色锁定不了）在 `HEAD` 里已经修完：

```text
bedbf11 fix(web): 周期只出已走满的组 + 论证「桶分组 ≡ 挂钟整点分分组」
```

> ⚠️ 但它同时意味着：**前端没有一行被验证过"改对了"**，只验证了"与 HEAD 一致"。
> 所以 §15.2 的跨语言对拍是必需的 —— 它证明的是"这份前端在**当前后端编码**下
> 解得对、聚合得对"，而不是"它以前是对的"。

语法：13 个 JS 全部 `node --check` 通过；最大 `period.js` = 391 行（< 400）。

### 15.2 跨语言端到端对拍（`tmp/web_e2e.py`）：**PASS 34 / FAIL 0**，4 变异全抓

`web/matrix_codec.js` 与 `serialization/heatmap_matrix.py` 是一对**契约的两半**：
后端编码成「位图 + 定标整数」，前端解回浮点。两侧各写一遍实现，**中间没有编译器
帮忙** —— 键名写错、字节序反了、量化步长用错，图都**照常渲染**（只是数值全错或
全空），属典型静默错值。旧项目的 `check_matrix_codec.py` 只做 Python 侧往返，
证明不了"JS 侧解出来的是同一个东西"。

**两个夹具，分工不同（别合并）**：

| 夹具 | 验什么 | 为什么不能互相替代 |
|---|---|---|
| **甲、真实帧**（真引擎 → 真编码器 → JSON → node） | **端到端接缝** | 测不了聚合数值语义：矩阵按**绝对桶号**索引，夹具只喂最后 7 桶 ⇒ 1776 列里只有尾部约 5 列有值 |
| **乙、稠密合成帧**（本文件构造 `HeatmapMatrix` → 走**真实** `HeatmapSerializer`） | **聚合语义**（组内求和 / 整组 null / volumes 跳过 null） | 24 列全填（故意留几个 None），量级与 ΔIV 同 ⇒ 三条语义都有真实数据可比 |

**⚠️ 甲在 `g=5` 下是空转的（本轮实测，第二个"假绿"）**：

```text
g=2 可比格数 48 ； g=3 可比格数 24 ； g=5 可比格数 0
```

`g=5` 时唯一的满组恰好横跨一个 null ⇒ 整组 null ⇒ 逐格比较里"两侧都是 None 就
跳过" ⇒ **比较格数 = 0**，`max(0)` 恒为 0 ⇒ "最大误差 0"照旧 PASS。
**判据恒真，不是通过。** 发现方式是 `--mutate=codec_scale`（数值应整体错 10^6 倍）
下 `g=5` 那条**仍然 PASS**。

⇒ 两条纪律：① 比较函数必须**返回实际比较格数**，并单列 `实际比较格数 > 0` 判据；
② 聚合语义必须用**稠密**夹具。

**变异反证**（`--mutate=`；改的是 `web/` 的**临时副本**，工作区零污染；锚点命中恰好 1 次）：

```text
codec_scale     /scale → *scale        ⇒ PASS 29 / FAIL 5   ✅
codec_bitmask   位序 MSB→LSB           ⇒ PASS 25 / FAIL 9   ✅
period_null     None 语义 → 跳过求和   ⇒ PASS 31 / FAIL 3   ✅
volumes_agg     求和 → 取最大          ⇒ PASS 31 / FAIL 3   ✅
```

⚠️ 变异模式下**退出码语义反转**（红了返回 0 = 判据非空转；全绿返回 1 = 空转）。
⚠️ **锚点漂移走独立退出码 3** —— 不能复用 `_report()`，它会把"有 FAIL"判成通过。

### 15.3 前端契约回归（`tools/check_web_contract.py`）

三项"引用 → 定义"对照：① JS 的 `el()/setText()/setClass()` → `index.html` 的 id；
② JS 的 `CFG.a.b` → `config.js` 的路径；③ 前端声明的载荷字段 → 后端实发帧。

```text
--offline ：[1] DOM id 20 个引用 / 27 个定义（扫描 13 个 JS） → 全存在
            [2] CFG 路径 42 条 → 全存在
            [3] N/A：--offline
--selftest：DOM id 对照 → 已抓住 ； CFG 路径对照 → 已抓住        RC=0
```

**两处对旧版的改进**：

1. **自动发现 `web/*.js`**（旧版写死 `("app.js",)` 与 6 个文件名）。新 `web/` 有 13 个
   JS，DOM 访问分布在 `app.js` + `app_render.js`，`CFG.*` 分布在 10 个文件 ⇒ 写死清单
   就是"哪些文件被检查过"有两处真相，**新增文件静默不受检查**。
2. **`--selftest` 往 `web/` 的副本注入假引用**（`el("__selftest_missing_id__")` +
   `CFG.__selftest.missing.key`），证明两项对照不是空转。
   ⚠️ 必须改副本：改工作区会污染真实代码，且中途抛异常就留下脏文件。

### 15.4 待补

- **载荷字段对照（第 3 项）需要活服务** ⇒ 属"L8 后的在线验证"，未跑。
- 旧项目 `tools/` 的 43 个文件在 `HEAD` 里完好（工作区已删，46 个 D），
  其中 `period_reference.py` / `period_node.py` / `group_guard.py` /
  `period_selftest.py` / `check_period_aggregation.py` 是**比本文件更成熟**的
  聚合回归（7 组对照 + 完整性守卫 + 变异自检）⇒ **优先移植，不要重写**。
  ⚠️ 层号口径不同（旧 `serialization` = L4，新 = L6），移植时逐个核对。

---

## 16. `tools/` 门禁（2026-09-15 **完成，覆盖 16/16**）

> ⚠️ 本节 2026-09-15 从「覆盖 5/16 · 优先从 `HEAD` 移植」**整体重写**。
> KAI 当日明令：**「必须重写，禁止移植失败品」** —— 旧版是 6 层口径
> （旧 `serialization` = L4 / 新 = L6），机械移植必然产生口径错配的失败品。
> 16 项**全部按新架构重写**，未从 `HEAD` 移植一行。

### 16.1 定位

`tools/` **不属于任何运行时层**：它可以 import 任何层，但**任何层都不得 import
`tools/`** —— 否则产品行为就依赖了测试代码。这一条由 `[2b]` 机械守住
（与 `EXEMPT_PACKAGES` 是同一枚硬币的两面，必须成对存在）。

### 16.2 入口与覆盖

`run.py --check` → `tools/selfcheck.py::run_selfcheck()`（编排器，**不含检查逻辑**）。

| 编号 | 检查项 | 实现模块 |
|---|---|---|
| [1] | 文件长度（`.py` + `web/*.js`，严格 < 400）；余量 < 5 行报警告 | `selfcheck_structure` |
| [2] | 依赖方向（L0–L8 单向）+ **层表覆盖核对** | `selfcheck_structure` |
| [2b] | 反向越界（任何层不得 import `tools/`） | `selfcheck_structure` |
| [3] | 配置文件可读性（**含 JSON 重复键**） | `selfcheck_config` |
| [4] | 配置零耦合（不得跨文件引用） | `selfcheck_config` |
| [5] | 键级完整性（空键名 / 空白键名 / null 值） | `selfcheck_config` |
| [6] | 订阅容量、显示窗口、窗口容差、**网格容量**、`use_model_greeks` 前置条件 | `selfcheck_config_invariants` |
| [7] | 配置键归属与接线（读取点 ↔ 声明键**双向推导**） | `selfcheck_config` + `selfcheck_reads` |
| [8] | `__slots__` 与实例属性赋值一致 | `selfcheck_code` |
| [9] | 单一职能（顶层公开类 ≤ 2；`__init__.py` 只做导出） | `selfcheck_duty` |
| [9b] | 依赖白名单（只有 `models/` 可用 numpy/pandas/scipy） | `selfcheck_duty` |
| [10] | 禁止硬编码（模块级字面量必须来自配置） | `selfcheck_code` |
| [11] | 出站限速桶容量与 IBKR 配额（5 条不变量） | `selfcheck_config_invariants` |
| [12] | 时钟协议与裁剪路径 | `selfcheck_clock` |
| [13] | 联通与数据通道（帧契约一致性 + 活链路） | `selfcheck_connectivity` |
| [14] | TickRouter 语义（L2 唯一被离线执行的一次，32 条判据） | `selfcheck_router` |

支撑模块（不含检查项）：`selfcheck_core.py`（`LAYER_OF` / `NON_SOURCE_DIRS` /
`_in_virtualenv()` / 配色）、`fixtures.py`（`[12][13][14]` 共用的离线替身）。

⚠️ **覆盖率写进结果行**（`结果: 16/16 项全部通过`）。
少跑一项却报"全部通过"，就是本项目头号禁忌（静默错值）的**门禁版**。

### 16.3 实测

⚠️ 下面是**节选**（段落标题 + 关键行，长段落只留首尾），**不是原样输出**。
**计数类细节刻意不在此固化**（例：`[7]` 的读取点条数）—— 它随代码变化，
写进文档就是一份**必然腐烂的第二份真相**。要真值就实跑一次，别抄文档。

```text
$ venv/Scripts/python.exe run.py --check                       RC=0
[1] 文件长度（上限 400 行，严格小于）
    [warn] acquisition/ibkr_gateway.py = 399 行，距上限只剩 1 行
    [warn] features/persistence_store.py = 398 行，距上限只剩 2 行
[2] 依赖方向（只允许 L0–L8 单向）      [2b] 反向越界（运行时层不得 import tools/）
[3] 配置文件可读性（含 JSON 重复键）    [4] 配置零耦合（不得跨文件引用）
[5] 键级完整性（空键名 / 空白键名 / null 值）
[6] 订阅容量、显示窗口与网格容量（IBKR 硬上限 100）
[7] 配置键归属与接线（读取点 ↔ 声明键双向推导）—— 取键调用全部落位，无死键
[8] __slots__ 与实例属性赋值一致
[9] 单一职能（模块不得承载多个职能）   [9b] 依赖白名单
[10] 禁止硬编码（模块级字面量必须来自配置）
    [warn] 待接线包 models/forecasting/：RV 信号引擎已移植但**未接线**
[11] 出站限速桶容量与 IBKR 配额
[12] 时钟协议与裁剪路径
[13] 联通与数据通道（帧契约一致性 + 活链路）
    [ok] 11 个契约字段全部被编码器覆盖（含 1 处显式折叠）
    [warn] 127.0.0.1:8060 无服务，跳过活链路检查（非交易日/盘前为预期）
           —— 上面三项离线判据仍然有效
[14] TickRouter 语义（L2 唯一被离线执行的一次）
结果: 16/16 项全部通过                                        RC=0

$ venv/Scripts/python.exe tools/selfcheck.py --selftest        RC=0（2m06s）
  [ok] 对照（未变异副本）→ 全绿
  [ok] [1]  → 已抓住     [ok] [2]  → 已抓住     [ok] [2b] → 已抓住
  [ok] [3]  → 已抓住     [ok] [4]  → 已抓住     [ok] [5]  → 已抓住
  [ok] [6]  → 已抓住     [ok] [7]  → 已抓住     [ok] [8]  → 已抓住
  [ok] [9]  → 已抓住     [ok] [9b] → 已抓住     [ok] [10] → 已抓住
  [ok] [11] → 已抓住     [ok] [12] → 已抓住     [ok] [13] → 已抓住
  [ok] [14] → 已抓住
变异自检: 16/16 项全部被抓到（且每一条都验的是**目标检查项自己**报了 FAIL）
```

**非空转做法**：源码目录复制到临时工程 → 注入缺陷 → `sys.executable` 在副本里跑
子进程 → **按段落编号定位目标检查项那一段**，看它有没有 `[FAIL]`。
⚠️ **必须先跑一次未变异的对照**（副本本身不绿 ⇒ 后面所有"变红"都不可归因）；
⚠️ **每条变异用独立副本**（共用会污染归因）；
⚠️ **变异锚点必须唯一**（`count != 1` 时拒绝执行并报错，防止锚点漂移后静默改错地方）。

⚠️ **判据的升级（这是本节最容易踩的坑）**：判据**不是"退出码非 0"**，而是
「**目标检查项自己那一段**出现 `[FAIL]`」：

```python
_SECTION_RE = re.compile(r"^(\[\d+b?\])", re.MULTILINE)

def _section_failed(output: str, number: str) -> bool:
    """判断 `output` 里**属于 `number` 那一段**是否出现 [FAIL]。"""
    matches = list(_SECTION_RE.finditer(output))
    for i, match in enumerate(matches):
        if match.group(1) != number:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        return "[FAIL]" in output[match.start():end]
    return True          # 找不到该段 ⇒ 视为失败（宁可报红，不可报假绿）
```

**为什么必须这样**：一个无关检查项变红就会让 RC 非 0 ⇒ 若判据只看 RC，
`[14]` 那条"抓住了"可能来自 `[1]` 的失败 —— **结论是假绿**。

⚠️ 连带要求：**段落标题必须打在 `run_*_checks()` 里，不能只在 `main()` 里打**。
编排器调用的是 `run_clock_checks()` / `run_connectivity_checks()` /
`run_router_checks()`，标题若只在 `main()` 里 ⇒ `_section_failed()` 切不出该段
⇒ 走到 `return True` 分支 ⇒ **恒判为"抓住"（判据恒真 = 空转）**。
三处 docstring 均已写明此理由。

### 16.4 对旧版的六处改进（重写，不是移植）

1. **`[3]` 补 JSON 重复键检测** —— `json.loads` 对重复键**静默取最后一个**，
   是配置版的静默错值；必须用 `object_pairs_hook` 才数得出来。
2. **`[5]` 改为键级完整性**（空键名 / 空白键名 / null 值），**刻意不重建**
   旧版那份手工 `REQUIRED_KEYS` 清单 —— 那种清单会腐烂，且 `config/loader.py`
   已 fail-fast，"声明的键必须被读、读的键必须被声明"由 `[7]` 双向推导覆盖。
3. **`[13]` 帧字段清单从 `dataclasses.fields(Frame)` 派生**，不写手工清单
   —— 旧版那份**已经腐烂**：清单是
   `("seq","ts","spot","session","health","heatmap","skew","cells","atm")`，
   **漏了 `surface`** ⇒ 帧里 `surface` 恒为 `null` 这个静默缺口它一行都查不出。
   派生式判据配 `FOLDED_FIELDS`（显式声明哪几个契约字段折叠进哪个段）+
   `EXTRA_TOP_LEVEL_KEYS`（显式声明哪些顶层键不属于契约）。
4. **`[2]` 层表覆盖核对** —— 旧版对不在 `LAYER_OF` 里的包直接 `continue`
   ⇒ 新增一个包时该包的跨层 import **一行都不检查**，输出照旧"未发现反向依赖"。
   **通用教训**：凡"查表 + 表里没有就跳过"的检查，都要配一条"表是否覆盖全集"的断言。
5. **`--selftest` 判据从"RC 非 0"升级为"目标检查项自己报了 FAIL"**（见 16.3）。
6. **`[12]` 内建反证** —— 同一组未来样本改用 `WallClock()` 裁剪 ⇒ 必须丢弃 **0** 条。
   没有这条反证，"注入时钟驱动裁剪"的判据无法排除"其实验的是墙钟"。

### 16.5 `[9]` 的两类豁免（判据是**结构性**的，不是调阈值）

1. **纯词汇表**：最终派生自 `Exception` / `Enum` 的类。
2. **纯数据载体**：`@dataclass`，且类体里只有字段声明与**纯派生读取器**
   —— 方法体只有一条 `return`，且**返回表达式里没有任何 `ast.Call`**。

第 2 类是本轮修**假阳性**时加的：`models/surface_params.py` 的 4 个 frozen
dataclass（清洗 / SVI / SSVI / 定价参数）被误判成 4 个职能，而该文件的 docstring
写着"**一个文件 = 一张参数表**"。

⚠️ 判据放宽的两步（都记在 `handoff.md` 踩坑 14）：
① "类体里一个 `def` 都没有" ⇒ 误伤 `max_iv_age()`（两字段二选一）；
② "单条 `return`" ⇒ **不够**（`return open("f").read()` 也是单条 return，却能做 I/O）；
③ 采用"单条 `return` + 返回表达式无 `Call`"。

### 16.6 本轮抓到的真缺陷（重写过程中新发现，非移植遗留）

**① `config/transport.json::bucket_seconds_s` 是真死键 + 描述不存在机制的注释。**

- 全工程**零读取点**（唯一出现在 `tmp/` 的一次性探针里，不算产品代码）。
- 注释写"推送必须对齐世界时间桶边界"，而 `PushLoop` 只按固定节奏 + 帧序号变化触发，
  **从来没有桶对齐逻辑**。
- 该键**在旧项目 `HEAD` 的 `transport.json` 里根本不存在** —— 是上一轮移植时
  **凭空补的**（凭注释描述"补"了一个从未实现的机制）。
- 处置：**删键**；注释改写为 `_push_comment`，明写"**不对齐是刻意的**"
  并给出量级（差 ≤ 1 个推送周期 = 400ms，相对 30s 桶 = 1.3%），
  同时留下"若日后确要对齐，须同时加键、实现、并在注释里写明"。
- **教训**：注释描述了一个**从未实现的机制** = 一份**过期的真相**，
  会误导下一个会话去"实现"它。这与"静默错值"同族，只是载体是注释。

**② `[7]` 的覆盖盲区：键转发器（key forwarder）。**

- 现象：`svi_bounds` / `ssvi_data_start` / `ssvi_random_start_ranges` /
  `svi_allowed_statuses` / `svi_random_start_ranges` 5 个**活键**被报"无代码读取"。
- 根因：`models/surface_params.py::_param_pairs(cfg, key, ...)` 把键名**当参数
  转发**给 `loader.get(cfg, key, ...)`，而字面量收集器只认字符串字面量。
- 修法：新建 `tools/selfcheck_reads.py`，做**两遍 AST 扫描** ——
  第一遍找出本文件的**键转发器**（形如 `def f(cfg, key)` 且体内把 `key`
  传给 loader 取键函数的参数位置），第二遍扫调用点并把实参代入。
  同名转发器在多个文件声明**不同** `module` ⇒ 归入 `unresolved`（宁可不判也不猜）。
- 效果：5 个假红消失（当轮实测读取点 168 → 173 —— ⚠️ **这是当轮值，不是当前值**；
  该计数随代码变化，要引用一律实跑 `[7]`，**不得抄写**。本文档曾把它抄成 176，
  而当时真值已是 185 —— 这就是"两份真相"的实例）。

**③ `--selftest` 报 `[14] 没抓住` —— 但根因是变异写错了，不是判据空转。**

- 现象：`[14]` 的变异（把"明确要求只用模型值时不接受降级来源"的
  `return None` 改成 `continue`）跑下来判据没红。
- 排查：手工复现变异 ⇒ 锚点命中 **0 次**；而 `--selftest` 走的是"没抓住"分支
  ⇒ 两者矛盾。诊断脚本打印 `repr()` 时发现 `\n` 被 Git Bash 的 **MSYS 路径转换**
  吃成 `/n`（KAI 记过的 `MSYS_NO_PATHCONV` 陷阱），不影响结论。
- **真根因**：**变异本身写错了** —— 原代码 `return None`（立即拒绝）被改成
  `continue`，但循环里后续的 bid/ask 槽位通常是空的 ⇒ 最终**仍然 `return None`**
  ⇒ **行为与原代码完全等价** ⇒ 判据当然不会红。
- 修法：变异改为 `return comp, tick_type`（**真正接受**降级），并在变异表里
  留注释说明这个陷阱。
- **教训**：`变异必须真的改变行为` —— 否则"抓住了"和"没抓住"两个结论都不可信。
  ⚠️ **"变异无效"与"判据空转"必须分得清**：前者是测试代码的 bug，
  后者是被测判据的 bug，修的地方完全不同。

**④ `[13]` 首版"区段表（0 段）"空转。**

- 现象：`_minimal_frame()` 的 `zones` 留空，"区段表非空"判据在 **0 段**下
  也打印通过。
- 修法：夹具填 **3 段** `SessionZone`（gth / gap / rth），判据改为 `len(zones) >= 2`。
- **教训**：夹具的**填充度**决定判据是否空转。本项目已有两处同类
  （此处 + `web_e2e` 的"真实帧 `g=5` 可比格数 = 0"）。

### 16.7 待补

- **`tools/` 下 8 个独立检查器仍待建**（不在 `--check` 里，状态表见 `README.md §6`）：
  `check_matrix_codec` / `check_grid_contract` / `check_period_aggregation` /
  `check_session_grid` / `check_surface_payload` / `check_reconnect_gap` /
  `check_window_tolerance` / `check_ws_compression` / `ws_probe`。
  ⚠️ **`check_grid_contract.py` 尚未建 = 当前最大的门禁缺口**
  （"网格单元 = 已走满的桶"这条核心契约目前只由 `tmp/l5_smoke.py` 的一次性探针守着）。
- ⚠️ **配置注释里已引用其中 6 个**，本轮已把这些引用逐条标注"**待建**"
  （`serialization.json` ×3 处 / `subscription.json` ×1 / `transport.json` ×1）。
  在它们建出来之前，那些引用是**设计意图而非既成事实**。
- ⚠️ **`check_grid_contract.py` 不得断言"没有 `g == 1` 短路"** ——
  实测 `g=1` 时短路路径与聚合路径**数值恒等**（`floor(cols/1) = cols`），
  断言它会**把正确代码判违规**。详见 §15.2 与 `open_tasks.md` 的 #14 条。
- **`README.md` 已按 9 层新架构重写完成**（10 节），旧版（6 层结构 + 旧检查器名）
  仍刻意不恢复。

