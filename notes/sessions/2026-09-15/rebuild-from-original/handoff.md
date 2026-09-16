# Handoff — rebuild-from-original

```text
TASK-ID: rebuild-from-original
DATE: 2026-09-15
TIER: T2
STATUS: in-progress（L0–L8 九层 + `web/` 前端全部落盘并实测；`tools/` 门禁重建中）
CHANGE-ID: N/A:本项目无 OpenSpec change 流程
```

## 一句话

`spxw_swatch` 源码被清空，改为**基于原版 `live-volatility-surface` 重写**。
已完成 **L0–L8 九层**落盘 + **`web/` 前端**移植。`models/` 整层移植的保真度用差分
对拍证明（**零差异**）；L2/L3/L5/L6/L8 各有离线冒烟 + 变异反证（**非空转**）；
`web/` 用**跨语言端到端对拍**（Python 编码 → node 解码/聚合 → 逐值比）钉住，
4 个变异全部被抓到。`tools/` 门禁重建中（已完成 `check_web_contract.py`）。

## 触发与拍板

KAI 原话：*「我把 spxw_swatch 的源码清空了，请基于原版
E:\US.market\SPXW SWATCH\live-volatility-surface，重新在 spxw_swatch 文件夹下写项目」*

两轮 `AskUserQuestion` 拍板：

1. **「原版为底座 + 重建雷达」** —— 取原版的 IBKR 接入语义与 `models/` 曲面层当底座，
   在它上面重建 SPXW SWATCH 的实时 ΔIV 热力图 + 25Δ Skew；**不**取原版
   `live_surface.py` 的 `ibapi` + 线程回调，也**不**取 `dash_surface.py` 的 8006 行单体。
2. **「沿用旧项目的分层纪律」** —— <400 行 / 单一职能 / 禁止硬编码 / 配置零耦合 /
   严格分层单向依赖 / fail-closed / 非空转验证。
3. acquisition 层用 **`ib_async`**（不用 `ibapi`）；numpy/pandas/scipy **只限 `models/` 层**。

## 现场事实（必须先知道）

```text
HEAD            = bedbf11（main），工作区被清空：236 D / 23 M / 5 ??
被清掉的        源码（acquisition/ app/ contracts/ core/ features/ models/
                serialization/ state/ tools/ transport/ web/ run.py requirements.txt）
                以及 notes/ 全部 131 个文件
保留下来的      .git（完好）、.workbuddy-ai/、.playwright-cli/
```

**已恢复 `notes/`**：`git checkout HEAD -- notes/`（131 文件 / 2.3 MB）。
理由是 notes 是知识库不是源码。恢复后做了三件防"两份真相"的处理：

- 旧 `notes/memory/ARCHITECTURE.md` → 归档为 `notes/context/archive/ARCHITECTURE_pre_rewrite.md`；
- 新架构文档写入 `notes/memory/ARCHITECTURE.md`（描述重写后的系统）；
- `QUICKREF.md` / `RULES.md` / `TROUBLESHOOTING.md` 三个 T1 文件**加了复核横幅**：
  内容是从 `bedbf11` 恢复的旧实现记录，纪律与教训继续有效，但路径/检查器名可能已变，
  重写推进到对应层时逐条复核并标 `[已复核 2026-09-15]`。

> ⚠️ **今天早些时候 `grid-rebuild` 会话的 notes 未提交，随清空永久丢失**
> （`notes/sessions/2026-09-15/grid-rebuild/`、`notes/context/*` 的当时版本）。
> 那轮的两个核心结论已被重新写进 `notes/memory/ARCHITECTURE.md §8`（网格单元 =
> 已走满的桶）与 §7（帧契约），所以**结论没丢，只有过程记录丢了**。

## 本轮 CHANGED-PATHS

```text
 A config/surface.json                    12 号配置文件：active_model / r / q + 曲面清洗标定全部可调常量
 M config/transport.json                  补 bucket_seconds_s（推送节拍源，对齐世界时间桶边界）

 A contracts/enums.py                     含新增 SurfaceModelName（parse() fail-fast）
 A contracts/tick.py                      OptionRef/ChainSlice/OptionTick/QuoteTick/SpotTick/FutureTick/…
 A contracts/feature.py                   含新增 SurfaceResidual / SurfaceSummary；**删掉死字段 quote_quality**
 A contracts/frame.py                     SessionZone/SessionBlock/HealthBlock/Frame（Frame 加 surface）
 A contracts/ports.py                     含新增 SurfaceInputPort（5 属性）/ SurfaceModelPort
 A contracts/__init__.py

 A core/session_grid.py  core/clock.py  core/ring_buffer.py  core/errors.py  core/logging_setup.py  core/__init__.py
                                          （core/errors.py 含新增 SurfaceModelError / SurfaceFitError）

 A models/surface_params.py               本层唯一读 config/surface.json 的地方：→ 4 个 frozen dataclass
 A models/base_surface_model.py           逐字移植
 A models/raw_surface_model.py            444 → 200 行（清洗流水线拆去 raw_cleaning）
 A models/raw_cleaning.py                 274 行（原 _build_surface + _max_iv_age）
 A models/svi_math.py                     378 → 364 行（bounds 搬去配置，本文件变纯函数模块）
 A models/svi_fit.py                      209 行（原 svi_surface_model 的标定半边）
 A models/svi_reporting.py                266 行（原 svi_surface_model 的报告半边，SVIReportingMixin）
 A models/svi_surface_model.py            710 → 331 行（本体）
 A models/ssvi_math.py                    246 行（原 ssvi_surface_model 的数学/标定半边）
 A models/ssvi_surface_model.py           485 → 302 行（本体）
 A models/market_params.py                重写：读 config，**删掉静默兜底与死键 contract_multiplier**
 A models/surface_adapter.py              重写：SurfaceModelPort 实现（原 Dash shim 整体删除）
 M models/__init__.py                     出口改为 SurfaceModelAdapter

 A notes/memory/ARCHITECTURE.md           重写后的架构（12 节，含 §11 移植保真度证据）
 A notes/context/archive/ARCHITECTURE_pre_rewrite.md
 M notes/memory/{QUICKREF,RULES,TROUBLESHOOTING}.md   仅加复核横幅
 A notes/sessions/2026-09-15/rebuild-from-original/{handoff.md,artifacts/*}
 A tmp/port_probe.py                      差分对拍探针（一次性，冻结时钟）

 ── 第二批：L2/L3（2026-09-15 13:0x–13:2x）────────────────────────────────
 A acquisition/__init__.py                26 行；**刻意空壳**（理由见文件 docstring）
 A acquisition/chain_resolver.py          218    A acquisition/contract_factory.py  142
 A acquisition/feed_errors.py              88    A acquisition/feed_reconcile.py    159
 A acquisition/feed_service.py            391    A acquisition/ibkr_gateway.py      399
 A acquisition/rate_limit_watch.py        136    A acquisition/spot_source.py       154
 A acquisition/spot_synthesis.py          195    A acquisition/spot_tap.py           50
 A acquisition/subscription_manager.py    335    A acquisition/tick_router.py       299
 A state/__init__.py                       19    A state/market_state.py            138
 A state/tick_store.py                    238
 A tmp/l2l3_smoke.py                      37 判据的功能冒烟（一次性，含变异开关）

 ── 第三批：L5（2026-09-15 14:0x–15:0x）──────────────────────────────────
 M config/surface.json                    +2 键（min_expiries=1 / min_strikes=8）；顶部注释改
                                          「除 min_expiries 外数值与原版逐字一致」
 M config/features.json                   +1 键 surface_refit_interval_s=30.0（SVI 618ms vs 400ms 节拍）
 M models/surface_params.py               CleaningParams +4 字段（min_points_to_plot/min_expiries/
                                          min_strikes/require_bid_ask_for_filter）
 M models/raw_cleaning.py                 两处写死门槛（2 / 8）改为读 CleaningParams
 M contracts/ports.py                     SurfaceInputPort 五个 docstring 按消费方代码重写（真契约缺陷）
 A features/surface_engine.py             273 行；L3↔L4 唯一接缝（SurfaceSnapshot + 限流）
 A features/atm_reader.py                 116 行；从 feature_engine 拆出（撞门禁）
 A features/heatmap_snapshot.py            90 行；从 heatmap_engine 拆出（撞门禁）
 M features/heatmap_engine.py             396→389 行；**核心契约**：只含已走满的桶（§8）
 M features/skew_engine.py                series(moment) 加 last_done 过滤（155→164 行）
 M features/feature_engine.py             364→334 行；接线 SurfaceEngine（surface_model/is_delayed 必填）
 A features/{strike_window,delta_locator,glitch_filter,impulse_engine,persistence,
              persistence_store}.py       整目录移植，只改层号引用
 M features/__init__.py                   出口 +SurfaceEngine / +SurfaceSnapshot
 A tmp/port_features_layer_refs.py        层号改写脚本（未命中即报错）
 A tmp/probe_surface_gate.py              曲面门槛配置对照（同一代码只翻 min_expiries）
 A tmp/l5_smoke.py                        32 判据冒烟（夹具=带种子随机游走）
 A tmp/mutate_grid_contract.py            非空转反证（inspect 只替换 build 一个方法）
 A tmp/diag_color_lock.py                 诊断探针（必须分两个进程跑）

 ── 第四批：L6/L7/L8（2026-09-15 15:0x–16:0x）────────────────────────────
 A serialization/{__init__,numeric,bitmap_codec,cell_encoder,heatmap_matrix,
                  skew_series,frame_encoder,payload_builder}.py
                                          整目录移植；层号 31 处（通用脚本改写）
 A serialization/surface_encoder.py        新建；曲面摘要编码 + residuals 等间隔抽样上限
 M contracts/frame.py                      **Frame 加 `skew` 字段**（实时点，与已过滤的
                                          `skew_series` 是两回事）；summary() 加 surface
 M serialization/frame_encoder.py          +SurfaceSerializer；`skew.latest` 改取 `frame.skew`
                                          （旧写法 `skew_series[-1]` 在新语义下滞后一个桶）
 M serialization/payload_builder.py        build() 补搬 `skew` / `surface`（旧版漏传 ⇒ 静默 null）
 M config/serialization.json               +`surface_residuals_limit: 200`；`_comment` 的 L4→L6
 A transport/{__init__,http_static,push_loop,server,ws_broadcaster}.py
                                          整目录移植；层号 14 处 + 措辞 1 处
 A app/{__init__,pipeline}.py              整目录移植；层号 16 处
 A app/persistence_boot.py                 新建（81 行）；从 pipeline 拆出启动期持久化接回
 M app/pipeline.py                         381 → 364 行；接 SurfaceModelAdapter + is_delayed
 A run.py                                  63 行，无层号改动（`--check` 指向待建的 tools.selfcheck）
 A tmp/port_layer_refs.py                  通用层号改写脚本（占位符双阶段 + 防重复跑标记）
 A tmp/.ported_dirs.json                   已处理目录标记（脚本不幂等，靠它兜底）
 A tmp/l6_smoke.py                         39 判据 + 两个变异开关
 A tmp/l8_smoke.py                         30 判据 + 变异开关
 M core/errors.py                          模块头 L0 → L1（层号改写的漏网之鱼）
```

### 第五批（`web/` 前端 + `tools/` 起步）

```text
 A web/                                     18 文件整目录复制（旧项目 HEAD，逐字节一致）
                                            —— `git status --short web/` 为空即证据
 A tmp/web_e2e.py                           跨语言端到端对拍（375 → 重写）
                                            真实帧 + 稠密合成帧；4 个变异开关；报比较格数
 M .gitignore                               按 HEAD 恢复（被清空 ⇒ tmp/venv/data 不再被忽略）
 A tools/__init__.py                        tools/ 不属于任何运行时层（不被任何层 import）
 M tools/check_web_contract.py              前端契约回归（DOM id / CFG 路径 / 载荷字段）
                                            自动发现 web/*.js；`--offline` / `--selftest`
 M tools/selfcheck_core.py                  自检基础设施；LAYER_OF 改 9 层；**砍掉 REQUIRED_KEYS**
 M tools/selfcheck_structure.py             [1] 长度（+余量<5 警告）[2] 分层（+层表覆盖核对）
                                            [2b] 反向越界（任何层不得 import tools/）
 M tools/selfcheck_duty.py                  [9] 单一职能（新增"纯数据载体"豁免）
                                            [9b] 依赖白名单（只有 models/ 可用数值库）
 M tools/selfcheck.py                       编排器；未移植项逐条打 [N/A]；`--selftest` 变异反证
```

> `tools/` 里的 37 个文件仍是 ` D`（旧检查器尚未移植）。
> `tools/selfcheck_config.py` / `selfcheck_slots.py` / `selfcheck_hardcode.py` /
> `check_clock_protocol.py` / `check_tick_router.py` / `selfcheck_connectivity.py`
> 在 `HEAD` 里完好，**移植优先于重写**。

**`web/` 的改动性质：零改动**。`git status --short web/` 输出为空 ⇒ 工作区 `web/`
与 `HEAD`（`bedbf11`）**逐字节一致**。这不是偷懒，是**保真度证据**：前端没有一行
是我"顺手改"的，本轮 KAI 报的两个缺陷（整点触发 / 颜色锁定）在 `HEAD` 里已经修完
（`bedbf11 fix(web): 周期只出已走满的组 + 论证「桶分组 ≡ 挂钟整点分分组」`）。

> ⚠️ 但也意味着：**前端一行都没被我验证过"改对了"**，只验证了"与 HEAD 一致"。
> 所以本轮补的是**跨语言对拍**（证据 Q）—— 证明这份 HEAD 版前端在当前后端编码下
> 确实解得对、聚合得对，而不是"它以前是对的"。

**L2/L3 的改动性质：整目录 `cp` + 只改「层号引用」** —— 逐行 diff 归类后确认
**零内容改动**（见证据 F）。共 57 条：55 条层号表 + 2 条代码注释里的层号
（`feed_service.py:343-344`）。同批把 `模拟模式` / `模拟器` 全部改为 `离线夹具`
（本项目纯实盘，没有模拟分支，旧措辞会让人以为存在一条模拟路径）。

**已删除的游离文件**：`model_config.json`（原版根文件被一并复制，无消费方）。

## 关键决策与理由

### 1. `models/` 层去硬编码 —— 有意偏离原版

原版把曲面模型的**全部可调常量**写死在 `models/*.py` 模块顶：清洗阈值 13 个、
SVI 标定 12 个、SSVI 6 个、两个 RNG seed。旧项目的
`tools/selfcheck_hardcode.py` 规则是：模块级字面量常量要么来自配置，要么逐条进
`EXEMPT_CONSTANTS`，而**"调大调小会改变行为"的值不许进例外表**。

⇒ 全部搬进 `config/surface.json`（33 个键），由 `models/surface_params.py`
翻译成 4 个 frozen dataclass（`CleaningParams` / `SviFitParams` / `SsviFitParams` /
`PricingParams`）。**数值逐字一致。**

刻意**没有**搬走的两处，并写了理由：SSVI 的蝶式套利约束 `η·(1+|ρ|) ≤ 4` 与搜索区间
`[(-0.999,0.999),(1e-4,3.999)]` —— 前者是 Gatheral & Jacquier (2014) 的定理常数，
后者由 `|ρ|<1` 与该式在 `ρ→0` 时的上界推出。改这两个数等于改 SSVI 的定义，不是调参。

### 2. RNG 必须"延迟初始化 + 复用同一个对象"

原版 `_RNG = np.random.default_rng(seed=42)` 在**导入时**建流。seed 搬进配置后不能在
导入时建（配置读会变成导入副作用），改成首次调用时建、之后复用。
**必须复用同一个生成器对象** —— 若每次 fit 都按同一 seed 重建流，连续两次 fit 会拿到
**完全相同**的随机起点，多起点搜索悄悄退化成固定起点。这是个不报错、只让拟合变差的改动。
实测：同进程内连续两次 fit 的 avg RMSE 分别是 0.001645 / 0.001018 ⇒ 流确实在推进。

### 3. `surface_adapter.py` 整体重写（原版那个已删除）

原版是 Dash 过渡期 shim，三处违规：读 CWD 下的 `model_config.json`、模块导入时
`_model = create_active_model()`、未知模型名 print 一句就退回 SVI。
新版是 `SurfaceModelPort` 实现，职责是**把 pandas 输出翻译成 L0 类型**
（`SurfaceSummary` / `SurfaceResidual`），让 L5 拿到的东西里没有任何 pandas 对象可用 ——
这是把 numpy/pandas 关在 L4 的机械手段，不是约定。

### 4. 删掉两个死物

- `SurfaceResidual.quote_quality`：原版 docstring 说 "welcome" 但 `clean_df` 从来没有
  这个列，恒为空字符串。凭空留一个字段会让下游以为"我们有质量信息"。
- `market_params` 返回的 `contract_multiplier`：`grep` 全库无消费方；契约乘数的唯一
  来源是 `config/app.json::option_multiplier`，在这里再放一份就是第二份真相。

## 实测证据（全部可复现）

命令一律用 `venv/Scripts/python.exe`（Python 3.13.14；numpy 2.5.3 / pandas 3.0.5 /
scipy 1.18.1 / ib_async 2.1.0 / aiohttp 3.14.3 / tzdata ok）。

### A. 移植保真度：差分对拍 **零差异**

```bash
# 金标准（原版）
venv/Scripts/python.exe tmp/port_probe.py \
  --root "E:/US.market/SPXW SWATCH/live-volatility-surface" --out tmp/golden_orig.json
# 待测（移植版）
venv/Scripts/python.exe tmp/port_probe.py \
  --root "E:/US.market/SPXW SWATCH/spxw_swatch" --out tmp/golden_port.json
# 逐字段比对 models 段
```

结果：**总差异条目 0**（3 个模型 × `stats / diagnostics / surface / clean_df /
residuals / iv()` 六个输出面）。

两套实现的控制台输出一字不差：

```text
[SVI]  fitted 4/4 expiries | avg RMSE=0.001645
[SSVI] fitted 4 expiries | ρ=-0.357 η=2.483 | RMSE=1.4695 vol pts
```

**非空转反证**：把 `config/surface.json::svi_n_multistart` 5 → 1 重跑 ⇒
**差异 210 条**，avg RMSE 0.001645 → 0.005517。⇒ 对拍确实在比东西。
（配置已还原，复跑确认 `models` 段仍逐字节一致。）

> 探针**必须冻结时钟**（`time.time` + `pd.Timestamp.now`）：否则 `raw_cleaning` 的
> tick 年龄与 `year_fraction_from_expiry` 的 TTE 随"跑的那一天"变，金标准隔天失效。
> 探针另用固定到期日，不依赖 `date.today()`。

### B. AST 级符号保真

```text
原版 69 个函数 / 新版 69 个函数；缺失 6 个全部是"搬进 SVIReportingMixin"；
函数体逐字一致 62 / 有差异 1 —— 唯一差异是 RawSurfaceModel.fit 里
self._build_surface(app) → build_clean_surface(app)（拆分的接缝）。
Mixin 抽出的 5 个方法（fit_summary / expiry_diagnostics / residuals /
diagnostics / _expiry_fit_status）方法体逐字一致。
```

### C. 协议符合性与封装

```text
isinstance(SurfaceModelAdapter(), SurfaceModelPort)  → True
isinstance(mock_app, SurfaceInputPort)               → True
三个模型 summary() 出口字段类型                       → 只有 str/int/float/bool/None + tuple，无 pandas/numpy
```

### D. fail-fast **7/7 全部生效**（无一静默兜底）

```text
删掉 risk_free_rate       → ConfigError: 缺少必需配置项 config/surface.json 的 'risk_free_rate'
删掉 svi_max_iter         → ConfigError: 缺少必需配置项 ...
删掉 ssvi_min_expiries    → ConfigError: 缺少必需配置项 ...
删掉 active_model         → ConfigError: 缺少必需配置项 ...
SurfaceModelName.parse('Nope') → ValueError: 未知曲面模型 'Nope'，可选：RawSurface, SVI, SSVI
svi_bounds 只给 2 组       → ConfigError: ...::svi_bounds 必须有 5 组，收到 2 组
下界 > 上界                → ConfigError: ...::svi_random_start_ranges[0] 下界 1.0 大于上界 -1.0
```

### E. 行数门禁

`models/` + `contracts/` + `core/` + `config/` 全部 < 400 行（判据 `>=` 即超）。
最大：`models/svi_math.py` 364。

### F. L2/L3 移植：逐行 diff 归类 ⇒ **零内容改动**

```bash
for d in acquisition state; do for f in _ref_spxw_head/$d/*.py; do
  diff "$f" "spxw_swatch/$d/$b"; done; done
```

全部差异都是下面三类之一，**没有一条是逻辑改动**：

```text
① 层号：L1→L2 / L2→L3 / L3→L5 / L4→L6 / L5→L7 / L6→L8（含"仅有的两个"→"直接的两个"）
② 措辞：模拟模式 / 模拟器 → 离线夹具（本项目无模拟分支，旧措辞会误导）
③ 依赖行：`依赖：L0。` → `依赖：L0（config / contracts）与 L1（core）。`
```

### G. L2/L3 功能冒烟 **PASS 37 / FAIL 0**

```bash
venv/Scripts/python.exe tmp/l2l3_smoke.py    # RC=0
```

夹具：`FakeClock` / `FakeContract` / `FakeGreeks` / `FakeTicker` / `CollectSink`。
覆盖三块：① `TickStore`（收 tick / `option_buffer` / `latest_option` / `quote` /
`spot` / `refs` / `refs_with_history` / `cell_count` / `counts` / `status_events` /
`prune` / `snapshot_meta` / `prune_interval_s`）；② `MarketState`
（`session_block` / `zones` 首尾相接 / `health` / `spot_with_fallback` /
`is_data_healthy` / `stale_threshold_s`）；③ `TickRouter` 三条拒绝路径
（IV 超 `max_iv` / 低于 `min_iv` / 无 computation）+ DTO 字段透传 + `model_greeks` 标记。

**非空转反证**：`config/features.json::max_iv` 3.0 → 0.05 重跑 ⇒

```text
FAIL  handle_tickers 返回接受数 = 2  → n=0
FAIL  sink 收到 2 个 OptionTick     → 0
FAIL  router.rejected = 3           → 5
FAIL  拒绝的 IV 确实越界（0.01 < 0.183 <= 0.05）
变异后 REAL_RC=1
=== 已还原，复跑 ===  L2/L3 冒烟：PASS 37 / FAIL 0   REAL_RC=0
```

### H. `ib_async` 依赖边界（逐个模块独立导入，实测）

```text
总模块 = 14（acquisition 12 + state 2）
拉起 ib_async = 3  → acquisition.contract_factory / acquisition.feed_service /
                      acquisition.ibkr_gateway
离线安全     = 11 → 其余全部
```

`feed_service` 是**传递性**拉起（它在模块级 import 了 `contract_factory` 与
`ibkr_gateway`）。⇒ `acquisition/__init__.py` 刻意保持**空壳**，否则
`import acquisition` 一句就会把 `ib_async` 拉进内存，`run.py --check` 与 `tools/`
下的离线回归（只跑 `state` + `features` + `serialization` + `transport`）无法脱依赖。

### I. 行数门禁（含 L2/L3 全库复扫）

```text
检查文件数 = 48（排除 venv / tmp / notes / .git / .workbuddy-ai / .playwright-cli）
超限(>=400) = 0
最接近上限的 5 个: 399 acquisition/ibkr_gateway.py  391 acquisition/feed_service.py
                   364 models/svi_math.py  335 acquisition/subscription_manager.py
                   331 models/svi_surface_model.py
```

### J. 曲面门槛：配置对照（同一份代码，只翻一个键）

```bash
venv/Scripts/python.exe tmp/probe_surface_gate.py    # PASS 7/7
```

```text
Q1  本项目配置  min_expiries=1  → surface_ok=True   SVI fitted=1/1   model_iv 48/48
Q2  原版口径    min_expiries=2  → surface_ok=False  SVI fitted=0/1   model_iv  0/48
```

⇒ 原版"≥2 个到期日"的硬门槛在**单到期日**下会让 SVI 永不拟合，
**且不抛异常**（`surface_ok=False` 静默）。KAI 拍板**「只订阅 0 DTE」**
⇒ 门槛搬进 `config/surface.json`，按单到期日落地。
fail-fast 实测：删键 ⇒ `ConfigError: 缺少必需配置项 config/surface.json 的 'min_expiries'`。

> ⚠️ 差分对拍要**重跑**：`models/raw_cleaning.py` 改过代码（写死值 → 读配置），
> 上一轮的"零差异"结论作废。重跑后：**8813 个可比字段，唯一差异是 `root` 路径本身**
> ⇒ 原版金标准逐字节可复现。

### K. L5 功能冒烟 **PASS 32 / FAIL 0** + 变异反证

```bash
venv/Scripts/python.exe tmp/l5_smoke.py              # PASS 32 / FAIL 0   RC=0
venv/Scripts/python.exe tmp/mutate_grid_contract.py  # PASS 25 / FAIL 7   RC=1
```

覆盖六段：① 网格列数与标签（`cols == bucket_index`，末列 = `bucket_label(current-1)`）；
② 桶内改 IV 后两帧矩阵逐格相同（**KAI 报的"颜色锁定"缺陷**）；
③ Skew 序列只含已走满的桶（`latest()` 仍实时）；
④ 曲面首轮拟合 / 间隔内复用 / 超间隔重拟合；
⑤ 会话翻篇 `reset()` 生效（旧桶不混入）；
⑥ 帧内自洽（`quality_ok + flagged == len(cells)`）。

**变异反证**（`inspect.getsource` 只替换 `HeatmapEngine.build`，不动磁盘源码）：

```text
last_done = current - 1                       →  last_done = current
...bucket_labels()[:current])                 →  ...[: current + 1])
```

```text
失败判据 0 → 7 条，其中「颜色锁定」那条变红：
  PASS  两帧确实落在同一个桶（前提成立）        → 1782 / 1782
  PASS  ⚠️ 自检：桶内那一跳确实被毛刺过滤器放行  → 4/25 档
  FAIL  ⚠️ 矩阵逐格完全相同（颜色锁定）         → 差异格数 = 21
  FAIL  volumes 也逐格相同
```

⇒ **非空转成立**。还原后复跑 `PASS 32 / FAIL 0`。

### L. 行数门禁（含 L5 全库复扫）

```text
检查文件数 = 61（排除 venv / .venv / .git / __pycache__ / data / logs / notes / tmp）
超限(>=400) = 0
余量 <5 行（建议 Task #15 列为警告）:
  399 acquisition/ibkr_gateway.py      398 features/persistence_store.py
```

⚠️ `feature_engine.py` 拆前 **407 行**、`heatmap_engine.py` 拆前 **432 行** ——
**两者都是真违规**，靠拆出 `atm_reader.py`（116 行）/ `heatmap_snapshot.py`（90 行）解决。

### M. L6/L7/L8 的来源与层号改写

```text
原版 live-volatility-surface/ 没有 serialization / transport / app
⇒ 来源 = 旧项目 HEAD（_ref_spxw_head，bedbf11）

通用脚本 tmp/port_layer_refs.py（映射对所有层都一样）：
  serialization/  31 处
  transport/      14 处 + 措辞 1 处（模拟模式 → 离线夹具）
  app/            16 处
逐行 diff：**零逻辑改动**（全是层号 / 措辞）。
```

⚠️ **脚本不幂等**：新层号 `L2`/`L3`/`L5`/`L6` 都落在被匹配的 `[0-6]` 里
⇒ 对已改过的目录再跑会把它们再串一遍，**而且语法照样合法、能 import**。
兜底两条：占位符双阶段替换 + `tmp/.ported_dirs.json` 标记（重复跑被拒）。

### N. L6 补的三处**静默缺口**（本轮最重要的一组修复）

旧版 `PayloadBuilder.build()` 是逐字段搬运，而新 `Frame` 多了字段 ⇒ 漏传**不报错**，
只让字段恒为 `None`（前端表现为"这功能一直没有数据"）：

```text
① bundle.surface 没搬        ⇒ 帧里 surface 恒为 null（残差图永远空白）
② Frame 缺 skew 字段         ⇒ 实时点无处可放，build() 也没搬 bundle.skew
③ skew.latest 取 skew_series[-1]
   —— 旧项目里序列含正在走的桶，[-1] 恰好是实时点；
      新语义（§8）给序列加了 last_done 过滤 ⇒ [-1] 变成"上一个桶"，
      顶栏读数最多滞后一整个桶（30 s）
```

修法：`Frame` 加 `skew` 字段（并在 docstring 里写明与 `skew_series` 的区别）+
编码器取 `frame.skew` + `build()` 补搬两个字段。
`build()` 里加了一行注释说明**为什么不用 `dataclasses.replace` 这类自动搬运**。

### O. L6/L8 冒烟与变异反证

```text
tmp/l6_smoke.py   PASS 39 / FAIL 0
  --mutate=surface  ⇒ FAIL 7（surface=bundle.surface → None）
  --mutate=latest   ⇒ FAIL 2（frame.skew → skew_series[-1]）
tmp/l8_smoke.py   PASS 30 / FAIL 0（真跑 Pipeline()，验装配接缝；**不调用 start()**）
  --mutate=session_key ⇒ FAIL 2（不再取 clock.expiry_str()）
```

回归复跑（本轮收尾）：

```text
l2l3_smoke  PASS 37 / FAIL 0    l5_smoke  PASS 32 / FAIL 0
l6_smoke    PASS 39 / FAIL 0    l8_smoke  PASS 30 / FAIL 0
全库 import：71 个模块，OK 71，FAIL 0
行数门禁：79 文件，超限 0
```

### P. 全库层号一致性核对

```text
① 模块头 'L{n} — ' vs 所属目录：71 文件，不符 1（core/errors.py 写 L0 ⇒ 已修为 L1）
   models/ 13 个文件无中文模块头（原版英文 docstring 逐字移植，刻意保留）
② 带模块名的层号引用（'L2（rate_limit_watch）'）：错配 0
③ 依赖行层号：错配 0
```

**不把"模块头"做成机械门禁**：它只是文档，而 `models/` 为保真刻意保留英文
docstring ⇒ 门禁一上就得开 13 条例外，正是"清单越守越长"的起点。
真正该机械守的是**跨层 import 的方向**（Task #15 的 `selfcheck_structure.py`）。

### Q. 跨语言端到端对拍（`tmp/web_e2e.py`）**PASS 34 / FAIL 0** + 4 个变异全被抓到

```text
甲 真实帧 seq=1  热力图 24x1776   编码 bm16  scale=1000.0  cols=1776  filled=120
乙 稠密帧 4x24  filled=91  scale=1000

① A. 解码（真实帧）
  PASS  行数/列数一致  → 24x1776
  PASS  None 位置完全一致（位图掩码没错位）  → 错位 0 格，比较 120 格
  PASS  数值逐格一致（容差 = 量化步长）  → 最大误差 0.00048991，比较 120 格
①' A. 解码（稠密帧）
  PASS  None 位置一致  → 错位 0 格，比较 91 格
  PASS  数值逐格一致（3 位小数 ⇒ 量化无损）  → 最大误差 0，比较 91 格
  PASS  实际比较格数 = filled  → 91 vs filled=91（证明这条不是空转）
② B. volumes（走 vol_bm/vol_i16 另一条路径）
  PASS  真实帧逐格一致  → 比较 124 格 ；PASS  稠密帧逐格一致  → 比较 93 格
③ C. g == 1 恒等（ARCHITECTURE §8 的修正结论）
  PASS  g=1 列数/bucket_seconds/bucket_index 均不变
  PASS  数值恒等 ⇒ 短路合法  → 比较 120 格，最大误差 0
④ D/E/F. g > 1（稠密帧）
  PASS  g=2 列数=12（丢 0）· None 位置一致 · 求和一致（比较 43 格）· volumes 另一条语义（48 格）
  PASS  g=3 列数=8 （丢 0）· 同上（27 / 32 格）
  PASS  g=5 列数=4 （丢 4）· 同上（13 / 16 格）
⑤ 真实帧聚合：只断言结构
  g=2 可比格数 48 ； g=3 可比格数 24 ； **g=5 可比格数 0**
```

**⑤ 的最后一行是本轮第二个"假绿"的现场证据**：真实帧按**绝对桶号**索引，夹具只喂了
最后 7 个桶 ⇒ 1776 列里只有尾部约 5 列有值。`g=5` 时唯一的满组恰好横跨一个 null
⇒ 整组 null ⇒ **一格都没得比**，而"最大误差 0"照旧 PASS。**判据恒真，不是通过。**

变异反证（`--mutate=`，锚点命中次数都恰好 1；改的是 `web/` 的**临时副本**，工作区零污染）：

```text
codec_scale     /scale → *scale       ⇒ PASS 29 / FAIL 5   ✅ 抓到
codec_bitmask   位序 MSB→LSB          ⇒ PASS 25 / FAIL 9   ✅ 抓到
period_null     None 语义 → 跳过求和  ⇒ PASS 31 / FAIL 3   ✅ 抓到
volumes_agg     求和 → 取最大         ⇒ PASS 31 / FAIL 3   ✅ 抓到
```

⚠️ 变异模式下**退出码语义反转**：红了才返回 0（证明判据不是空转），全绿返回 1。
⚠️ **锚点漂移走独立退出码 3**，不能复用 `_report()` —— 变异模式下它会把"有 FAIL"
判成通过，把锚点漂移误判成变异成功。

### R. 四个离线冒烟复跑（确认本轮改动未破回归）

```text
l2l3_smoke     L2/L3 冒烟：PASS 37 / FAIL 0    RC=0
l5_smoke       L5 冒烟：   PASS 32 / FAIL 0    RC=0
l6_smoke       L6 冒烟：   PASS 39 / FAIL 0    RC=0
l8_smoke       L8 冒烟：   PASS 30 / FAIL 0    RC=0
                                          ── 合计 138 条判据全绿
```

### S. `tools/check_web_contract.py`：离线两项 + 变异自检

```text
$ venv/Scripts/python.exe tools/check_web_contract.py --offline
[1] DOM id：JS 引用 20 个，HTML 定义 27 个（扫描 13 个 JS）
  [ok] JS 引用的 id 全部存在
[2] CFG 路径：JS 引用 42 条
  [ok] CFG 引用的配置键全部存在
[3] 载荷字段：N/A：--offline，未连服务
结果: 全部通过                                    RC=0

$ venv/Scripts/python.exe tools/check_web_contract.py --selftest
  [ok] DOM id 对照 → 已抓住
  [ok] CFG 路径对照 → 已抓住                        RC=0
```

**两处对旧版的改进**：

1. **自动发现 `web/*.js`**（旧版写死 `("app.js",)` / 6 个文件名）。新 `web/` 有 13 个
   JS，DOM 访问点分布在 `app.js` + `app_render.js` 两个文件、`CFG.*` 分布在 10 个文件
   ⇒ 写死清单就是"哪些文件被检查过"有两处真相，新增文件**静默不受检查**。
2. **`--selftest` 注入假引用**（往 `web/` 的**副本**里塞 `el("__selftest_missing_id__")`
   与 `CFG.__selftest.missing.key`），证明两项对照不是空转。
   ⚠️ 必须改副本：改工作区会污染真实代码，且中途抛异常就留下脏文件。

### T. `tools/` 重建起步：`run.py --check` 从**坏入口**修到 RC=0（覆盖 5/16）

**修前**（本轮实测）：

```text
$ venv/Scripts/python.exe run.py --check
  File "run.py", line 51, in main
    from tools.selfcheck import run_selfcheck
ModuleNotFoundError: No module named 'tools.selfcheck'          RC=1
```

**修后**：

```text
[1] 文件长度（上限 400 行，严格小于）
  [ok] 85 个 Python + 13 个前端脚本全部合规，最长 acquisition/ibkr_gateway.py = 399 行
  [warn] acquisition/ibkr_gateway.py = 399 行，距上限只剩 1 行
  [warn] features/persistence_store.py = 398 行，距上限只剩 2 行
[2] 依赖方向（只允许 L0–L8 单向）
  [ok] 未发现反向依赖，10 个包按 L0–L8 分层，树里 11 个包全部已登记
[2b] 反向越界（运行时层不得 import tools/）
  [ok] 没有任何运行时层 import tools/
[9] 单一职能（模块不得承载多个职能）
  [ok] 非契约/工具模块的顶层公开类均不超过 2 个（豁免: contracts, tools）
  [ok] 所有 __init__.py 都只做导出，未承载实现
[9b] 依赖白名单（只有 models/ 可用 numpy / pandas / scipy）
  [ok] models/ 之外的模块均未 import numpy / pandas / scipy（豁免: tools）
⚠️ 覆盖不完整：本次只跑了 5/16 项检查
  [N/A] [3]…[8]、[10]…[14] 逐条列出（见 §16）
结果: 已实现的 5 项全部通过（覆盖 5/16）                     RC=0
```

**为什么把"覆盖 5/16"印在结果里**：`--check` 的职责是回答"现在能不能发"。
少跑 11 项却报"全部通过"，就是本项目头号禁忌（静默错值）的**门禁版**。
所以未移植项逐条打 `[N/A]`，覆盖率写进结果行 —— **不许静默跳过**。

**三处对旧版的改进（都不是抄来的）**：

1. **砍掉手工 `REQUIRED_KEYS`**（旧版 11 模块 × 若干键的"必须存在的键"清单）。
   本项目 `config/loader.py` 已 fail-fast（缺键即抛 `ConfigError`、不含业务默认值），
   而"声明的键必须被读、读的键必须被声明"由 `check_config_ownership` **双向推导**。
   机制覆盖了那张清单的全部职能，且**新增配置键时不需要回来改工具**。
2. **补 `[2b]` 反向越界**：旧版只有"下层不得 import 上层"（`EXEMPT_PACKAGES` 让
   `tools/` 豁免），**没有反向那条** —— 于是产品代码 `import tools` 无人拦。
   那是"产品行为依赖测试代码"，必须成对存在。
3. **补 `[2]` 的层表覆盖核对**（本轮发现的**静默漏洞**）：旧版对不在 `LAYER_OF`
   里的包直接 `continue` ⇒ 新增一个包（例如 `forecasting/`）时，该包的跨层 import
   **一行都不检查**，而输出照旧是"未发现反向依赖"。现在树里出现未登记的顶层包
   直接 FAIL。实测输出 `树里 11 个包全部已登记`。

### U. `tools/selfcheck.py --selftest`：**5/5 全部被抓到**（含对照运行）

```text
$ venv/Scripts/python.exe tools/selfcheck.py --selftest
  [ok] 对照（未变异副本）→ RC=0
  [ok] [1] 文件长度   → 已抓住  (注入 contracts/enums.py，RC=1)
  [ok] [2] 依赖方向   → 已抓住  (注入 acquisition/feed_errors.py，RC=1)
  [ok] [2b] 反向越界  → 已抓住  (注入 features/glitch_filter.py，RC=1)
  [ok] [9] 单一职能   → 已抓住  (注入 state/market_state.py，RC=1)
  [ok] [9b] 依赖白名单 → 已抓住  (注入 features/glitch_filter.py，RC=1)
变异自检: 5/5 项被抓到                                          RC=0
```

**做法**：把源码目录复制到临时工程 → 注入缺陷 → 用 `sys.executable` 在副本里
跑 `tools/selfcheck.py` 子进程 → 看退出码。

⚠️ **必须先跑一次未变异的对照**：若副本本身跑不出 RC=0，后面所有"变红"都
**不可归因**（可能只是副本坏了）。这一步最容易省，也最不该省。
⚠️ **每条变异用独立副本**：共用一份的话，一条变异会污染下一条的归因。

### V. 修掉 `[9]` 的一个**假阳性**：`models/surface_params.py`

首次跑 `--check` 就报红：

```text
[FAIL] models/surface_params.py 定义了 4 个顶层公开类:
       CleaningParams, SviFitParams, SsviFitParams, PricingParams
```

**逐条查证后判定：这是检查器的假阳性，不是代码违规。**
该文件的 docstring 写着"**一个文件 = 一张参数表**"，4 个 frozen dataclass 是同一张
参数表的四段（清洗 / SVI / SSVI / 定价），是**一个**职能；`CleaningParams.max_iv_age()`
只是两个字段的二选一（`return self.delayed_max_iv_age_s if is_delayed else self.live_max_iv_age_s`）。

**修的是判据，不是阈值**（调大 `MAX_PUBLIC_CLASSES` 会让真正多职能的 4 类文件放行）：

```python
# 新增第二类豁免：纯数据载体
#   @dataclass 且类体里只有字段声明与「纯派生读取器」
#   纯派生读取器 = 方法体只有一条 return，且返回表达式里**没有任何 ast.Call**
_IMPURE_NODES = (ast.Call, ast.Assign, ast.AugAssign, ..., ast.ListComp, ...)
```

判据是**结构性**的：没有调用就没有副作用 / I/O，方法只能是字段的投影。
所以"多加第 5 张参数表"不会让它悄悄放行一个真正有行为的第二职能
（那种方法必然含调用 / 赋值 / 控制流，判据立刻失效）。

⚠️ 只要求"单条 `return`"**不够** —— `return open("f").read()` 也是单条 return
却能做 I/O。这正是"判据要能报出它拦不住什么"的一个具体例子。

### W. 恢复 `.gitignore`（被清空 ⇒ 一个真隐患）

`git status` 显示 `.gitignore` 是 ` D`（被清空的那批文件之一），而 `tmp/`、
`venv/`、`data/` 都还在 ⇒ **三者不再被忽略**，一次 `git add -A` 就会把
`venv/`（2312 个文件）与 `data/`（.db 库）全部纳入。

这不是可选项：`selfcheck_core.py::NON_SOURCE_DIRS` 的注释明写
**"本条与 `.gitignore` 的 `tmp/` 是一对，缺一条就会让探针被误报"**。
按 `HEAD` 恢复（目录未变，内容仍正确），只删掉指向已删除 README 的引用。
恢复后实测 `git check-ignore -v venv tmp` 均命中；`git status` 从 131 项降到 127 项。

⚠️ **`README.md` 刻意未恢复** —— 旧版描述的是 6 层结构与旧检查器名，
恢复它等于制造"两份真相"（`ARCHITECTURE.md §3` 才是现行真相）。**待重写。**

## 本轮踩到的坑（都可复现，写给下一个会话）

### 1. 「只改 docstring」也能撞穿 400 行门禁

`ibkr_gateway.py` 原版 **398 行**，我在层号改写时扩了 5 行 docstring ⇒ **400 行**，
判据 `>= 400` 即超 ⇒ **真·门禁违规**（不是"接近上限"）。
发现方式：`venv/Scripts/python.exe` 全库 `rglob('*.py')` 数行数（48 个文件）。
**教训**：移植时"只改注释"这个念头本身是危险的 —— 注释也算行。
⇒ 门禁必须在**每次落盘后**跑一次，不能等到收尾。

### 2. `Edit` 插入 docstring 时把原句**切成两截**

`contract_factory.py` 原本是一句完整的话：

```text
其余 L1 模块通过鸭子类型与本模块交互，从而在离线模拟
模式下完全不触碰 ``ib_async``。
```

我把 ⚠️ 提示块插在"离线夹具"之后 ⇒ 变成：

```text
...从而在离线夹具
⚠️ 「直接 import 的只有两个」...
离线回归要用 L2 时，只 import 那 9 个安全模块。
模式下完全不触碰 ``ib_async``。      ← 悬空半句
```

**语法没错、能 import、检查器也抓不到** —— 这是文档层的"静默错值"。
根因不是手滑，是**同一条事实被抄进了 3 个模块的 docstring**（`__init__` /
`contract_factory` / `ibkr_gateway`），抄的时候必然要往句子里塞。
⇒ 修法是**收敛归属**：层内全局事实只写在 `acquisition/__init__.py`，
两个直接 import 的模块只留一行指针。**净减 6 行 + 消灭 2 处重复真相。**

### 3. 层号改写要按**含义**改，不是按字符串替换

`L1 → L2` 这类替换里，`L0、L1（rate_limit_watch）` 这种"依赖行"必须改成
`L0、L1（core）、L2（rate_limit_watch）` —— 因为 `rate_limit_watch` 自己就是 L2。
纯 `sed` 会把 `L1（rate_limit_watch）` 改成 `L2（rate_limit_watch）` 之外，
还会把 `L1（core）` 也误伤。**逐条看上下文**，55 条 + 2 条注释一共 57 条。

### 4. ⚠️ 判据"全绿"其实是空转 —— 本轮最深的一个坑

第一次跑变异反证时，「颜色锁定」那条判据**不变红**。查下去发现根因不在代码，
在**测试前提不成立**：

`GlitchFilter._off_baseline` 用 `4 × MAD` 判 GLITCH，而 **GLITCH 不写进时间桶**。
原夹具历史是**线性缓升**（每桶 +0.0005）⇒ `MAD ≈ 0.001` ⇒ 门槛 `0.004`
⇒ 测试用的"桶内抬 0.05"那一跳**被判 GLITCH 拦下** ⇒ `HeatmapEngine.observe()`
**根本没写进桶** ⇒ `latest_option()` 拿到的还是旧 tick ⇒ 两帧**必然**相同
⇒ 这条判据**恒真**，无论被测代码对不对。

**两条修法**：

1. 夹具改成**带种子的随机游走**（σ = 0.004 ⇒ `MAD ≈ 0.0027` ⇒ 门槛 ≈ 0.011）；
   **夹具必须按被测过滤器的量纲设计，不是按"看着合理"设计。**
2. B 段加**自检判据**：「桶内那一跳确实被毛刺过滤器放行、写进了桶（否则本段空转）」
   ⇒ 实测 `4/25 档`。**任何"两帧应该相同"的判据，都要先证明"这一帧真的变了"。**

### 5. 变异脚本的锚点必须唯一，且必须报出命中次数

`'last_done = current - 1'` 在源码里命中 **3 次**（docstring 两处 + 代码一处）；
改用 `inspect.getsource(HeatmapEngine.build)` 后仍命中 **2 次**（build 的 docstring 里也有）。
⇒ 锚点必须带上下文 `"\n    last_done = current - 1\n"`，且脚本要
**报出"锚点命中 N 次"，N != 1 即报错退出** —— 挑第一个就改，很可能只是在改注释，
回归当然不变红，于是"非空转"结论是假的。

### 6. 变异注入别重新 `exec` 整个模块

重新 exec `features/heatmap_engine.py` 会撞导入环：exec 到
`from features.heatmap_snapshot import ...` 时会拉起 `features/__init__.py`
→ `feature_engine` → `from features.heatmap_engine import HeatmapEngine`，
而被注入的模块还**没执行完**（类还没定义）⇒ `ImportError`。
**修法**：用 `inspect.getsource` 只替换 `build` 一个方法、再重绑回类上。

⚠️ 连带教训：诊断脚本**同进程里删 `sys.modules` 再重导入是骗自己** ——
`FeatureEngine` 的类全局仍指着旧类，变异静默失效（未变异与变异两段输出完全一样）。
⇒ 分**两个进程**跑（`--mutate` 开关）。

### 7. ⚠️ **并行 Edit 同一个文件会静默丢改动**（不报错）

本轮在 `handoff.md` 上**并行**发了两个 Edit（STATUS 行 + 「一句话」段）。
两个都返回 `Successfully edited`，但事后复核发现 **STATUS 那次改动消失了** ——
后一个 Edit 读到的是**改之前**的文件快照，写回时把前一个覆盖掉了。

**与之前那个 `EBUSY` 是同一类问题的两种表现**：那次是并发写被文件锁挡住（报错），
这次是读-改-写竞态（**不报错**）。后者更危险。

⇒ **纪律**：同一文件的多处编辑**必须串行**（一次一个 Edit，等返回再发下一个）。
**并且改完要复核** —— 本轮就是靠"改完 grep 一遍自己写进去的独特短语"才发现的。
（这类"写成功但没生效"的静默失败，正是本项目最忌讳的一类。）

### 8. 变异脚本的锚点要按 `textwrap.dedent` **之后**的缩进写

`inspect.getsource(SomeClass.method)` 拿到的方法源码首行是 4 空格缩进，
`textwrap.dedent` 会把公共缩进削掉 ⇒ **方法体从 8 空格变 4、参数行从 12 变 8**。
我按原始缩进（12 空格）写的锚点，命中 **0 次**。

⇒ 这次没造成假结论，因为脚本**报出了命中次数并退出非 0**（这是 L5 那轮加的纪律）。
**锚点匹配必须报数、必须要求恰好 1 次。**

### 9. f-string 里别拼跨行嵌套引号

L6 冒烟里写了：
```python
f"最大差 {max((abs(r['residual'] - (r['raw_iv'] - r['model_iv'])) "
f"for r in ...), default=0):.2e}"
```
⇒ `SyntaxError: f-string: expecting '}'`。**跨行拼接的 f-string 不能在表达式里
再嵌同类引号**。改成先算成普通变量（`worst = max(diffs) if diffs else 0.0`）
再放进 f-string —— 顺带也更可读。

### 10. ⚠️ 判据"两侧一致"但**可比格数为 0** —— 第二种空转（比第 4 条更隐蔽）

第 4 条那类空转是"两组函数写好了却没接进汇总"。这一条更隐蔽：**判据确实在跑、
确实在比，只是没东西可比**。

`tmp/web_e2e.py` 原先用真实帧测聚合，`g=5` 那条一直 PASS，我一开始以为没问题。
直到跑 `--mutate=codec_scale`（把 `/scale` 改成 `*scale`，数值应整体错 10^6 倍）
发现 **`g=5` 那条仍然 PASS** —— 一个把数值改错 10^6 倍的变异它都抓不到。

根因：热力图矩阵按**绝对桶号**索引（`cols() == bucket_index`），夹具只喂了最后 7 个桶
⇒ 1776 列里只有尾部约 5 列有值，早段全 null。`g=5` 时唯一的满组恰好横跨一个 null
⇒ 整组 null ⇒ `cmp` 里"两侧都是 None 就跳过" ⇒ **比较格数 = 0**，`max(0)` 恒为 0。

**修法两层**：
1. 比较函数返回**实际比较格数**，并单列一条判据 `实际比较格数 > 0`；
2. 聚合语义改用**稠密合成帧**（24 列全填、故意留几个 None），仍走真实编码器。

**教训**：凡"逐值一致"类判据，**必须同时报出比较了多少个值**。
"0 个值一致"与"100 个值一致"在日志上长得一模一样。

### 11. 变异模式下"锚点漂移"不能复用正常模式的报告函数

`--mutate=` 模式下 `_report()` 的语义是**反转**的（红了返回 0）。于是锚点漂移
（命中 0 次 ⇒ 判据变红 ⇒ `_report()` 返回 0）会被误判成"变异成功"。
⇒ 锚点漂移走**独立退出码 3**，与"变异成功(0) / 变异未被抓到(1) / 参数错(2)"区分开。

### 12. node 驱动里前端用到的每个全局都得显式挂上，否则被 try/catch 静默吞掉

`matrix_codec.js:29` 用 `global.atob(b64)`。driver 里我写的是
`const window = { console: console }`，漏了 `atob` ⇒ `b64ToBytes` 抛
`ReferenceError`，被 `decode()` 内部的 `try/catch` **吞掉**，静默返回未解码的 block。
表面症状是"数值全 None"，看起来像后端编码错了。

⇒ 两条纪律：① 垫片对象要按前端实际用到的全局补全；② **必须把 node 的 stderr
打出来**（前端的 `fail()` 走 `console.error`，那是唯一线索），并加一条
"解码确实产出了 values"的判据 —— 否则会去查错方向。

### 13. ⚠️ 检查器自己的**静默漏洞**：未登记的包被 `continue` 跳过

`check_layering` 原写法：

```python
owner = parts[0]
if owner in EXEMPT_PACKAGES or owner not in LAYER_OF:
    continue          # ← 新增一个包就整包跳过，且不报错
```

于是新增 `forecasting/` 之类的包时，**该包的跨层 import 一行都不检查**，
而输出照旧打印"未发现反向依赖"。这与"探针全绿但是坏的"是同一个病，
只不过病在门禁自己身上。

**修法**：先核对**层表覆盖** —— 树里出现的每个顶层包都必须在 `LAYER_OF` 里，
否则 FAIL。实测输出 `树里 11 个包全部已登记`。

**通用教训**：凡是"查表 + 表里没有就跳过"的检查，都要配一条
**"表是否覆盖了全集"** 的断言。否则表漏一项 = 该维度永久静默失守。

### 14. 判据"方法体只有一条 `return`"**不等于**"没有副作用"

写"纯数据载体"豁免时，第一版判据是"类体里只有字段声明（一个 `def` 都没有）"，
结果把 `CleaningParams.max_iv_age()`（两个字段的二选一）判成"有行为的第二职能"。

第二版放宽成"单条 `return`"—— 但这**也不够**：`return open("f").read()`
同样是单条 `return`，却能做 I/O。

**第三版（采用）**：单条 `return` **且返回表达式里不得出现任何 `ast.Call`**。
没有调用 ⇒ 没有副作用 / 没有 I/O ⇒ 只能是字段的投影。

**教训**：判据放宽时，要问"它现在拦不住什么"，并把答案写进 docstring ——
否则下一个会话只会看到"这条豁免挺宽松"，然后把真正违规的东西塞进来。

### 15. ⚠️ 被清空的文件里，`.gitignore` 是**功能性**的，不是文档

`git status` 里 `.gitignore` 只是一个 ` D`，很容易和 `README.md` 一起当成"文档，
以后再补"。但它与 `selfcheck_core.py::NON_SOURCE_DIRS` 的 `tmp` 条目是
**成对的机制**：少任何一条，探针里的 `.py` 都会被 `[1][2][9][10]` 误报。
更直接的是：没有它，一次 `git add -A` 会把 `venv/`（2312 个文件）与 `data/` 的
`.db` 全部纳入。

**判据**：清空重写后，先跑一次 `git status --untracked-files=normal`，
看**未跟踪项里有没有本不该出现的目录**。有 ⇒ 对应的忽略规则没恢复。

## 已知风险 / 未做

1. **pandas 3.0.5 是大版本跳跃**。对拍用的是**同一个 venv**，所以证明的是"移植没引入
   差异"，**没有**证明"pandas 3 没改变原版行为"。后者要靠原版自己的 `test_models.py`
   （1589 行，已复制到 `tmp/test_models.py`）。**未跑** —— 其中
   `surface_adapter` / `dashboard_config` 相关用例针对的是已删除的旧 API，会预期失败。
2. `SurfaceSummary.residuals` 目前带**全部**清洗后的点（L5 实测 **50 个/模型**，
   单到期日 48 点 + 2）。L6 组装载荷时必须有上限（每 400ms 推一次，几十个点 ×
   每点若干字段仍会压过位图编码的热力图本身）。上限属于"上线格式"的决策，
   等 L6 落地时连同配置键一起加 —— **现在加就是死配置键**。
3. `models/forecasting/`（ewma / garch / har_rv / snapshot_history）已一并移植，
   但本项目**尚未确定是否需要**（原版是 RV 信号引擎用的）。未接线。
4. `tools/` **部分重建** —— 旧检查器 43 个随清空消失（现仍 ` D`），本轮建了 6 个
   （`__init__` / `check_web_contract` / `selfcheck_core` / `selfcheck_structure` /
   `selfcheck_duty` / `selfcheck`），`run.py --check` 已从坏入口修到 RC=0 但
   **只覆盖 5/16 项**（未移植项逐条打 `[N/A]`，不静默跳过）。
   `notes/memory/RULES.md §1` 的"机械校验映射"表需要按新结构重写。
   ⚠️ **优先从 `HEAD` 移植**（`selfcheck_config` / `selfcheck_slots` /
   `selfcheck_hardcode` / `check_clock_protocol` / `check_tick_router` /
   `selfcheck_connectivity` / `check_matrix_codec` / `check_period_aggregation`
   + `period_reference` / `period_node` / `group_guard` / `period_selftest`），
   它们是踩过坑的产物。**层号口径不同**（旧 `serialization` = L4，新 = L6），
   移植时逐个核对。
4b. ⚠️ **`README.md` 仍未恢复，且刻意不恢复** —— 旧版描述 6 层结构与旧检查器名，
   恢复即制造"两份真相"（现行真相在 `notes/memory/ARCHITECTURE.md`）。**需重写。**
5. `_ref_spxw_head` worktree（`HEAD = bedbf11` 只读参照）仍在
   `E:/US.market/SPXW SWATCH/_ref_spxw_head`，用完再清。
6. **L2/L3 只做了"离线冒烟"，没有任何在线验证** —— `IbkrFeed` 连真实 Gateway、
   `SubscriptionManager` 的 300 退避、`SpotSourceSelector` 的区段切换、
   `WindowFollower` 的窗口重建，**全部未跑**。原因：本轮没有启动服务，
   且 L5–L8 还没落盘，跑起来也出不了帧。**在线验证排在 L8 完成之后。**
7. **L2/L3 的层号引用只核了 docstring 与注释，没有核"跨层调用"** ——
   例如 `feed_service` 是否真的没 import 任何 L3+ 的东西。这条要等
   `tools/selfcheck_structure.py`（Task #15）落地才能机械守住。
8. `acquisition/ibkr_gateway.py` = **399 行**，距门禁只剩 1 行余量。
   下一个会话只要在它里面加两行（哪怕只是注释）就会违规。
   ⇒ 建议 Task #15 的门禁把"余量 < 5 行"的文件也列出来当**警告**。

## 下一步

**Task #15（`tools/` 门禁 + `run.py --check` + 非空转验证）** —— in-progress。
已完成 `tools/__init__.py` + `tools/check_web_contract.py`（见证据 S）。

**入口约束（全部基于本轮实测）**：

1. ✅ **`g == 1` 恒等短路是合法的**（`ARCHITECTURE §8` **已修正**）。
   本条原写作"聚合不得有 `g == 1` 恒等短路"，**那是错的** —— 经逐值核对：
   `g=1` 时短路路径与聚合路径**数值恒等**（`floor(cols/1) = cols`，元字段换算同样
   恒等），已由 `tmp/web_e2e.py` 的 C 段实测（120 格全等，误差 0）。
   原禁令描述的是**修复前状态**（后端含未定稿桶），真正保证末列定稿的是**后端**。
   ⚠️ **`tools/check_grid_contract.py` 不得断言"没有 `g==1` 短路"** —— 会把正确代码判违规。
2. ⚠️ **`web/matrix_codec.js` 与 `serialization/heatmap_matrix.py` 是成对契约**：
   `enc` / `scale` / `bm` / `i16` / `filled` / `vol_bm` / `vol_i16`。
   改一侧必须改另一侧。`vol_bm`/`vol_i16` 是**可选字段**（`matrix.volumes`
   非空时才发）—— 契约检查器不得当必填。
3. ⚠️ **帧里新增了 `surface` 段**，且 **`skew.latest` 的语义变了**（现在取
   **实时点** `frame.skew`，不再是序列末项）。前端若要显示曲面残差 / 顶栏读数，
   按 `ARCHITECTURE §7` 接。
4. **不要给"前端不消费的字段"补消费**：`serialization/` 的 82 个键里有 16 个是
   **前端从不解码的诊断元数据**（`health.rate_limit.*` / `ticks_dropped` /
   `cells.quality` / `skew.series.put25_strike` …），那是**设计**不是缺口。
   唯一一处真掉地是 `volumes`（旧项目已修好）。
   ⚠️ 反向检查（"后端发的字段前端是否都读"）**不可固化成常驻门禁** —— 会满屏误报。
5. `web/*.js` **只进 `--check` 的 `[1]`（行数门禁）**，不进 AST 类检查。
6. ⚠️ 旧项目已知的两个前端坑（保留在 `open_tasks` 的"历史 Active"段）：
   热力图换 ECharts 后宽档位占 40–47% 单核（KAI 已知情并接受）；
   Top-3 高亮在细档位下是亚像素（**待 KAI 定视觉规格**，未自行改配置）。
7. ⚠️ **旧项目 `tools/` 的 43 个文件在 `HEAD` 里完好**（工作区已删，46 个 D）。
   重建**优先移植旧版**而不是重写：旧版是踩过坑的产物（`group_guard.py` 守
   "删掉一组判据不算通过"、`period_selftest.py` 注入缺陷自证），比新写更可靠。
   ⚠️ 但**层号口径不同**：旧项目 `serialization` = L4、`contracts` = L0；
   新项目 `serialization` = L6。移植时逐个核对，别机械替换。
8. ⚠️ **聚合的数值判据在稀疏夹具上会空转**（本轮实测）：真实帧按**绝对桶号**索引，
   夹具只喂最后几个桶 ⇒ 早段全 null ⇒ `g=5` 时**可比格数 = 0**，"最大误差 0"恒真。
   对拍必须**报出实际比较格数**，并用稠密合成帧（经真实编码器）测聚合语义。

**在线验证排在 `tools/` 之后**（见已知风险 6）—— L8 已落盘，可以启动了。

NOTES-PATHS: `notes/sessions/2026-09-15/rebuild-from-original/{handoff.md,artifacts/}`、
`notes/memory/ARCHITECTURE.md`、`notes/context/{handoff,project_state,open_tasks}.md`、
`.workbuddy-ai/memory/{2026-09-15.md,MEMORY.md}`
