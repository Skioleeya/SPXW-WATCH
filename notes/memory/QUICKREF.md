# 静默错值型速查卡（A–V）

> ⚠️ **2026-09-15 白纸重写 —— 本文件尚未按新实现复核。**
> `spxw_swatch` 源码已被清空，正在基于 `live-volatility-surface`（原版）重写
> （见 `notes/sessions/2026-09-15/rebuild-from-original/`）。本文件是从 `HEAD = bedbf11`
> 恢复的**旧实现记录**：其中的**工程纪律、根因分析、教训**继续有效，
> 但提到的**文件路径 / 检查器名 / 模块名可能已变**。重写推进到对应层时逐条复核，
> 复核过的条目请在行尾标 `[已复核 2026-09-15]`。
> 新旧架构对照：新 → `notes/memory/ARCHITECTURE.md`；旧 → `notes/context/archive/ARCHITECTURE_pre_rewrite.md`。

> 本文件 = T1 层。**收录标准：错了不报错、只出错值**——所以必须靠"判据"当场识破，不能等报错。
> 错了**会立刻报错**的陷阱 → `notes/memory/TROUBLESHOOTING.md`；
> 工程约束的机械校验映射 → `RULES.md §1`；基线验证命令与已知红 → `RULES.md §6.1`。
> 本表原挂在 `.workbuddy-ai/memory/MEMORY.md` 的 §1 附表下，2026-09-15 迁出
> （记忆文件改为**纯路由器**，不再承载内容）。旧记录里的"MEMORY.md 速查卡 X"即指本文件。
> 引用方式：本目录内写 `卡 X`；跨目录写 `notes/memory/QUICKREF.md` 卡 X。
> 与 `RULES.md §2`（关键接口约定，同属"静默错值型"）有部分重叠：§2 讲**接口该怎么写**，
> 本表讲**坏了长什么样、拿什么判**。

## 收录判据：**本文件只减不增**（2026-09-15 KAI 定）

> **⛔ 禁止新增速查卡**（KAI 2026-09-15 原话）。本文件**只减不增** —— 允许降级、合并、删除，
> **不允许追加**。新发现一律走下面四条出路，**都不写进本文件**：

| 分诊 | 去处 | 本文件 |
|---|---|---|
| ① 能机械判定（**首选**） | **写检查器**（`tools/check_*.py` / `selfcheck [N]`） | 对应卡片**降为一行指针** |
| ② 与已有卡片同类 | **并入那条卡片**（补一句判据即可） | 条目数不变 |
| ③ 一次性实例 | 只进 `notes/sessions/**` 会话记录 | 不动 |
| ④ 错了会**立刻报错** | `notes/memory/TROUBLESHOOTING.md` | 不动 |

⇒ 每条卡片必须能报出**"谁守着它"**（检查器 id）或**"为什么守不住"**（外部条件 / KAI 已裁定 / 只能靠人看）。
两样都报不出，就是 ③，删。

⚠️ 确实需要一条新卡片时（既不能机械化、又不属于任何已有条目）：**先问 KAI，不要自行追加**。

**审计（2026-09-15，23 条）**：**12 条已有守卫** —— B/C/D/H/J/K/O/P/Q/S/T/U
（卡片内容与检查器 docstring 重复 ⇒ 第二份真相，应收敛成指针）；
**11 条无守卫**：

| 卡 | 为什么守不住 |
|---|---|
| A | ⚠️ **能守但没写** —— `grep inverse tools/*.py` **0 命中** |
| E | ⚠️ **能守但没写** —— `selfcheck_core` 只查 `market_data_type` **键在不在、不查值**（"必须写 3"没人拦）；静默那半是 `health.mode` 推导 |
| L | ⚠️ **能守但没写** —— `grep 'splitLine\|cellBorder' tools/*.py` **0 命中** |
| F | KAI 裁定：**不给 `web/` 加语义门禁**（加了就是第二份真相） |
| G | 外部条件：IBKR 报 `=1` 而值冻结，**结构上拦不住** |
| I | 量级诊断（8 档），没有单一断言可写 |
| K2 | 诊断分类法（四类互斥），**不该**有守卫 |
| M | KAI 知情接受的性能代价，**非回归** |
| N | 沙箱环境行为（git 引用不落盘） |
| R | 观测面：日志里就是没有，只能改看页面 |
| V | 工作流规则（改落点后扫残留引用） |

⇒ **A / E / L 是"欠账"不是"永久卡片"**：补上检查器后它们降为指针。
⇒ **真正的永久卡片 ≈ 8 条**（F/G/I/K2/M/N/R/V），**且只减不增**。
新错误只有四条出路 —— 写检查器（首选）/ 并入已有卡片 / 只进会话记录 / 归 `TROUBLESHOOTING.md`
—— **没有一条会增加本文件的条目数**。

---

| # | 规则 | 判据 |
|---|---|---|
| A | **热力图纵轴 = 高行权价在上** | 帧行序是**降序行权价**（`strikes[0]` 最高）。ECharts 靠 `web/heatmap.js::buildOption` 的 **`yAxis.inverse: true`** 让索引 0 落在屏幕最上方。**去掉 inverse ⇒ 整体上下镜像**，但轴标签与现货线（`markLine`，同一 category 轴）会**一起翻** ⇒ 只看标签看不出来。判据：现货线须落在 `ro-spot` 对应档位上。⚠️ 旧 `gl_heatmap.js` / `u_*` WebGL 概念**已随引擎删除，全部失效**。 |
| B | **Skew 与热力图共用列网格** | `period.js::alignSkew` 消费 `renderHeatmap` 的 `view`；标签相同**不可**作判据，时间域才是。 |
| C | **Skew 曲线 series name 必须不同** | `NAME_POS`/`NAME_NEG`；真同名被图例去重只剩暖色。靠 `legend.formatter` 抹成同名显示。 |
| D | **JS 判空字段用 `=== undefined`** | `bm`/`i16` 空矩阵 = `""`（falsy），真值判断会把合法全空矩阵误判成"无编码"。 |
| E | **`market_data_type` 必须写 3；`health.mode` 是推导值** | 3 = 择优；写 1 = 只接受实时，任一无权限即 Error 354 → fail-closed 退出。⚠️ `health.mode` **由本键推导**（写 3 恒显示 `delayed`），**不是观测值** ⇒ 判单合约权限只能看 `ticker.marketDataType`（须直接取 `ib.client`，`IB` 不转发）。2026-09-14 RTH 实测：期权与 SPX 指数**均为 1（实时）**。 |
| F | **前端是空壳** | 不给 `web/` 加语义门禁；后端报多少渲染多少。"网格自适应""行序"是 L3 不变量，前端复制 = 第二份真相。 |
| G | **`marketDataType=1` 不代表价格新鲜** | GTH 期间 SPX 指数恒定 7656.98（周五收盘），IBKR 仍报 `=1`。⇒ `ibkr.max_underlying_age_s` 按"多久没更新"判，**结构上拦不住这类值**。判新鲜只能看"值有没有变过"。 |
| H | **GTH 现货基准 = ES 推算，不用外部 r/q** | 指数在 GTH 不被计算（Cboe Rule 9.20）。四路径：B1 冻结 RTH 基差（**换月静默错值**）/ B2a 外部 `(r−q)`（**实测差 26.6bp**）/ **B2b 前后月期货反解 carry** / B3 同到期日平价。**KAI 2026-09-14 定：主口径 = B2b（已落地）；B3 降为可选校验；B2a/B1 弃用。** 合成只在 `gth` 段（20:15→09:25）生效，`rth` 段直接读指数。 |
| I | **陈旧 ≠ 恒定；指数冻结危害 = 8 档** | GTH 指数恒定 = 周五收盘，比 ES 推算现货高 **40.4–42.0 点 ≈ 8.1–8.4 档**。ES 是**远期**、SPX 是**现货**（量纲差一整个 carry，Dec-2026 约 65–67 点）⇒ 任何"ES 与 SPX 做差"的代码必须写明比的是哪个。 |
| J | **现货源按区段切换，开关 = `config/spot.json::synthesised_zones`** | 现写 `["gth"]`。合成区段里**丢弃**指数 tick（冻结值不能当锚），由 `SpotSourceSelector._sync_zone()` 决定走合成还是直读。**误把 `"rth"` 加进去 = 用合成值覆盖权威指数，不报任何错，只偏 40 点量级。** 两层闸门语义不同、不可合并：`max_abs_carry`(0.15) 越界 ⇒ fail-closed；`max_carry_jump`(0.005) 越界 ⇒ **拒收该桶但基准照常跟上**（写反 = 闸门焊死、通道静默死锁）。 |
| K | **前向填充上限 ⇒ 每段尾部一条「假 0 带」** | 孤桶被 `_row_values()` 一路沿用成 ΔIV=0，与首次真观测做差 = 假冲量。**已修**：`serialization.json::heatmap_max_ffill_buckets`(20)，超限留白；回归 `check_reconnect_gap.py`。**残留**：带宽**正好 = 20 桶**（上限指纹）；彻底消掉需只取末段连续桶 —— **KAI 两次未选**。跨会话那一半已由卡 T 修掉。 |
| K2 | **热力图空洞主要是数据侧缺失，不是渲染 bug** | 实测四类互斥：整列（该段无 IV 观测）/ 行首（该档进窗口晚）/ 行内（真没成交或 `heatmap_engine.py:141` 滤非 TRUSTWORTHY）/ 区段起点。`persistence.json::dropped_count` 从未被日志打印。**行首成因见卡 P。** |
| L | **网格线 = `splitLine` 抽样；`cellBorderMinPx` 单位是 CSS px** | Plotly 的 `xgap/ygap` 在 ECharts 无等价项 ⇒ 用轴 `splitLine` + `interval = stride-1`，`stride = ceil(cellBorderMinPx / cellPx)`，`cellPx` 由 `getBoundingClientRect()` 减 `PAD{66,84,10,28}` 算出。`cellBorderMix` → 线的 **opacity**（两键均非死配置）。**别改回逐格 `itemStyle.borderWidth`**：2370 列 = 5.7 万个矩形各描一次边，性能灾难。 |
| M | **换 ECharts 的代价：宽档位持续吃 40–47% 单核**（KAI 2026-09-14 知情裁定，非回归） | 单次重绘 630/1352/2370 列 = 65.7/159.9/188.1ms（旧 WebGL 仅 0.6–1.3ms），节拍 **2.5Hz**；`fillRect` 地板仅 9.5–40.5ms ⇒ 开销在 **JS 侧逐格处理，换 GPU 降不下来**。**`progressive` 是负优化**（424ms > 188ms）⇒ 恒设 `0`。 |
| N | **沙箱内 git 引用写入「报成功但没写」** | `git fetch` / `git update-ref` 返回 **RC=0** 并打印 `[new branch] main -> origin/main`，但 `.git/refs/remotes/origin/` 下的引用**根本不落盘** ⇒ `git status` 永久报 `upstream is gone`。**判据：任何 git 结论以 `git ls-remote origin main`（远端真值）为准。** 要建本地跟踪引用，直接写 `.git/packed-refs` —— 被拦的是 git 的原子 rename。 |
| O | **Skew 三条 IV 曲线配色（KAI 2026-09-14 指定）** | 跨式黄 `#ffb020` / Put25 绿 `#2fd07a` / Call25 红 `#ff5a5a`；唯一来源 `web/config.js::skew.colors`。**不得复用 `theme.hot`/`theme.cool`** —— 那是主序列 25Δ Skew 的正负分段色，复用会让图上出现"两红两蓝"且图例同名。注意 Call25 红与 `theme.hot` **同值**（KAI 指定，非遗漏），靠线型区分。守回归 `tools/check_skew_colors.py`（6 判据 + 3 变异）。 |
| P | **热力图纵轴有【三个】半径；容差要按【可视】半径算**（2026-09-17 重写） | ① `subscription.json::num_strikes_each_side`(20) = **订阅**（容量 `4×S+1 ≤ 92`）② `features.json::heatmap_draw_rows_each_side`(20) = **绘制**，每帧下发 2×draw = **40 行** ③ `features.json::heatmap_visible_rows_each_side`(12) = **可视**，屏幕只显示 2×V = **24 行**。三条不变量：`draw ≤ S`（画了也拿不到数据）、`V ≤ draw`（可视超绘制 ⇒ 露出**空白行**）、**`S − V ≥ T`**（T = `recenter_trigger_strikes`=3，由"两次重建间中心最多滞后 T 档"**推出**、非拟合）。⚠️ **判据里的被减数是 V，不是 draw** —— 按 draw 算会**假红**（20−20=0<3），而绘制窗口比订阅宽出来的那几档永远落在可视区之外、用户看不到，退订/复订只是白跑请求。容差破了的后果：现价一往返就退订**看得见**的档（`cancel_stale_before_add`），而 `_prune()` **只按时间裁剪、从不按行权价裁剪** ⇒ 行权价轴上留一条时间空洞。守住：`[6]`（静态，3 条变异）。⚠️ **行为回归缺失**：`tools/check_window_tolerance.py` 在白纸重写中已删、尚未重建 ⇒ 这条**只有静态门禁**。**上限 8 档 = 40 点；趋势日需选项 B。** |
| Q | **测试夹具的靶档不得锚在阶梯端点** | `strike_grid(...)[3]` 的行权价 = `现价 − (each_side−3)×步长`，随**订阅**半径漂移 ⇒ 落到显示窗口外 ⇒ 假红且看着像产品坏了。应当用锚在现价上、按**可视**半径设界的取档函数。⚠️ **2026-09-17 查实：`tools.fixtures.py` 里既没有 `strike_grid` 也没有 `display_window_strike`**（白纸重写后只剩 `FakeClock` / `make_session_clock` / `make_option_ticker` / `make_index_ticker` / `RecordingSink` 等）⇒ 这条纪律仍成立，但**当前没有可用的工具函数**，写新夹具得自己按现价锚定。见 RULES.md §6.6。 |
| R | **应用层告警不进日志文件**（只查日志会误判"没发生告警"） | `feed_service.py:378::_note()` **不写 logging**：只进 `self._messages`(32 条环) + `StatusEvent` → `tick_store.py:110` 的 128 条内存环；帧只带最近 6 条**字符串**（`FeedStatus.messages`）⇒ **页面能看到，日志看不到**。实测 `logs/spxw_swatch.log` **WARN 恒为 0**，ERROR 全来自 `ib_async.wrapper`。⇒ 判告警看页面状态区，别只查日志。10197 **不在** `feed_errors.py::_IGNORED_CODES` 内。 |
| S | **`use_model_greeks=true` 是热力图正确性的前提，不是性能选项** | 每档只留**一条**序列（键**不带方向**）⇒ 现价穿越某档时该行取边 Put↔Call 翻转，只有**两侧 IV 相等**才无跳变。IBKR 的 model IV **一个行权价只给一个 ⇒ Put == Call（实测差 0.000）**；bid 差 ~0.16、**last 差 5.5~6.3 波动率点**（色标仅 ±0.5）⇒ 关掉它，**每次穿越都打出一个假 ΔIV 跳变**（Put/Call 边界一根竖直亮条）。判据：见孤立竖直条先查该键。逐档表见 `TROUBLESHOOTING.md §10`。 |
| T | **持久化表必须带会话身份**（2026-09-15 已修） | 主键 = **`(session_key, bucket_index)`**，`session_key` = **当日到期日**。`bucket_index` 是**日内坐标、每交易日复用** ⇒ 无会话列时昨天 index 448..2183 落进今天的键空间。**症状三连**：帧 `skew.latest`（= `skew_series[-1]`）报**昨天**的点 / Skew 曲线画到**未来** / 热力图把昨天 RTH 画在**今天 GTH 的时刻**上。⚠️ **顶栏读 `atm` 块（每轮现算）⇒ 顶栏对、面板错**。`enqueue` 空身份**抛错**；缺列旧表**整张丢弃并报行数**（实测 1830）。 |
| U | **持久化 = 一交易日一文件**（2026-09-15 落地） | 落点 `data/sessions/<到期日>.db`（`persistence.json::db_dir` + `db_filename`）。同日内重启**续写同一文件**；跨日（`_sync_session()` 改 `_session_key`）**换新文件**。行内 `session_key` 列保留作第二道（文件被改名 ⇒ 查询取不到 ⇒ **留白**而非画错）。⚠️ 两个静默坑：① `_batch_write` 必须**逐条**按会话切文件（跨日批次混着两个会话）；② `SessionFileStore.close()` **必须先提交再关闭** —— `close()` 对未提交事务是**回滚**，批尾那次 commit 已落在新连接上 ⇒ 旧文件刚写的一批静默丢。保留策略（2026-09-15 定，**归档不删**）：`start()` 打开本会话文件后调 `archive_other_sessions()`，把 db_dir 内非当前会话的库文件**移动**到 `archive_dir`（`persistence.json`，默认 `data/archive`），返回 `(已归档, 未归档)` 两组。**三道闸门 + 一道构造期校验**：① 只在 db_dir 内 glob；② 只匹配 `db_filename` 模板派生的名字（`{session_key}`→`*`）；③ 归档目录**同名不覆盖**（跳过并上报，源文件留在 db_dir 下次再试）；④ `archive_dir` 落在 db_dir 之内 ⇒ **构造时抛错**（否则归档件下次启动又会被当成待归档项）。搬了哪几个 / 没搬成哪几个由 `app/pipeline.py` **各记一行**（`features/` 整层不写日志，动数据不允许静默）。⚠️ **历史是数据不是垃圾**：02:2x 曾实现为 `unlink()` 删除 —— 那是把 KAI「不留档、不备份」的适用范围**从旧单库 `data/session.db` 误扩到全部逐日文件**，同日 03:0x 改回，**别再"简化"回去**。⚠️ **跨日那一刻的旧文件留到下次启动才归档** ⇒ **未归档数 = 自上次启动以来的交易日数**（实测：不重启跨 5 个交易日 ⇒ 5 个文件 ≈ 9.4 MB；每天重启一次则最多 1 个 ≈ 2.35 MB）；未归档文件**永不会被读到**，只是还没归位。 |
| V | **改落点/模块名后必须全项目扫残留引用**（2026-09-15 收尾） | 判据 = **存活代码/配置/README 对旧标识 0 命中**；必扫：代码 docstring、`.gitignore` 归属注释、设计文档里的模块归属（README §5 / RULES §6.1 / ARCHITECTURE §4）。⚠️ **`notes/sessions/**` 是"当时为真"的证据，一律不 retro-fit**。改"唯一归属"型文档前先跑实测（枚举 / 自检读数），别把猜测写进去。 |

---

*条目数：**卡表**（下面那张三列表）A–V 共 **22** 个字母编号 + 补卡 **K2** = **23 条**
（旧 MEMORY.md 页脚记的"22 张"把字母数当行数用了）。*

*⚠️ **数法本身会骗人** —— 上面"无守卫审计表"也用单字母开头：*

```bash
grep -c '^| [A-Z]' notes/memory/QUICKREF.md                            # → 34  ❌ 错法
awk '/^\| # \| 规则 \| 判据 \|/{f=1} f' notes/memory/QUICKREF.md \
  | grep -cE '^\| [A-Z]'                                               # → 23  ✅ 锚卡片表头
grep -cE '^\| [A-Z][0-9]? \| \*\*' notes/memory/QUICKREF.md             # → 23  ✅ 两法须一致
```

*最后核对：2026-09-15 02:5x（含收录判据、守卫审计、条目数两法互校）。*
