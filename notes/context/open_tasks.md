# Open Tasks

Archive: notes/context/archive/open_tasks_2026-09.md

## Active

- [ ] **[中] ΔIV 公式缺一个"端到端逐格对拍"的检查器**（2026-09-15 04:5x 审计，
  探针已写在 `tmp/verify_delta_iv.py`，**未落成常驻回归**）。

  **审计结论（全部实测，无一处是"看代码觉得对"）**：

  | 环节 | 结论 | 证据 |
  |---|---|---|
  | `ImpulseEngine` ΔIV(N) = `(IV_now − IV_{now−N}) × 100` | ✅ 正确 | 同一个合约的 buffer 内做差，`OptionRef` 带方向 ⇒ 结构上不可能串边 |
  | `HeatmapEngine` ΔIV = `(value − previous) × 100` | ✅ 正确 | 端到端逐格对拍 **1272/1272 格一致** |
  | 热力图按**行权价**分键（不带方向）是否引入 Put/Call 混淆 | ✅ 不引入 | 实测两侧 model IV **逐位相同**（4 档 × 8 采样 = 32 次比对，`|ΔIV|` 全 0.0000；两侧 conId 不同，确属两张合约） |
  | `SkewEngine` | ✅ 正确 | `put_samples`/`call_samples` 按 `cell.right` 分开；`skew = (put25.iv − call25.iv) × 100` |
  | `_atm_iv` / `_straddle` | ✅ 正确 | 是回 `store.latest_option()` 取**另一侧**，不是从单侧的 `cells` 里凑 |
  | `use_model_greeks=true` 这个**前置条件** | ✅ **已有守卫且非空转** | `tools/selfcheck_config.py::_check_model_greeks_prerequisite`（`--check` 的 `[6]`）：正常态 `[ok]`+`RC=0`；**变异为 false ⇒ `[FAIL]` + `RC=1`**，还原后两次输出完全一致（54 ok / 0 fail / 0 warn） |

  **缺口**：以上第 2 行那条"逐格对拍"目前**只在 `tmp/` 里、是一次性的**。现有
  `tools/check_matrix_codec.py` 只做 **pack/unpack 往返**（编解码自洽），
  `check_persistence.py` 只管键序 —— **没有任何常驻检查器断言"帧里那个数 = 库原始
  IV 差分 × 100"**。少乘/多乘 100、行序反了、单位换成百分数，三者都会让图**照常
  渲染**（典型的静默错值）。

  - [ ] 把 `tmp/verify_delta_iv.py` 提为 `tools/check_heatmap_delta.py`
    （形态参考已有的 `tools/period_reference.py` / `skew_reference.py` 的"参考实现
    对拍"族），并登记进 `--check` 矩阵与 `NON_SOURCE_DIRS`。
    ⚠️ 它需要**在线的 8060 + 当日库**，属"需服务"类检查 ⇒ 盘中才能跑，
    盘前/盘后应记 `N/A`，不要判成回归破坏。

- [ ] **[高] 空图真根因已定性：IBKR `modelGreeks` **间歇缺失**，不是"GTH 结构性"**
  （2026-09-15 04:3x 查清，KAI 提供两条网关日志后收口）。

  **证伪**：当天 `data/sessions/20260915.db` 的空洞史显示 **GTH 段内 IV 连续跑了好几小时**
  （bucket 527–806 = 00:38:59→02:46、852–927 = 03:21→03:58:56，GTH = bucket 0..1579）。
  每个空洞都对齐一次连通性/重启事件（807–851 ↔ `1100` 丢失 → `1102` 恢复；
  928–994 ↔ 服务重启 + 网关重启），**没有一次对齐 GTH 边界**。
  ⇒ 我 04:1x 写进 skill 的"GTH 段热力图必然为空是结构性的"**是错的，已改写**
  （`spxw-live-verify/references/pitfalls.md` §5b，同条目重写、未新增清单项）。

  **量化指纹（可直接复现，比看热力图强）**：`health.ticks_dropped` = `router.rejected`
  （`acquisition/feed_service.py:120`）。`use_model_greeks = true` ⇒
  `tick_router._pick_computation` 只收 tick 13 ⇒ 模型缺失窗口留下巨大拒绝计数：
  ```text
  失效窗口 04:12→04:32（20 min）：received 80,207  dropped 317,621
  恢复后   04:36:40→04:37:00（20 s）：received +127  dropped **+0**
  ```
  ⇒ **判据**：抓两帧间隔 10–20 s 比增量。`dropped` 增量为 0 ⇒ 模型正常；
  若此时仍空图，才该怀疑项目自己。**实测 04:32:55 自愈**（`atm_iv 17.22`、
  `heatmap.filled 8543`），未做任何代码改动。

  **网关那条日志不是客户端的锅**（已排除）：`Client 71 Output exceeded limit
  (was: 100010), removed first half` —— 同窗口内 ① 帧计数**精确 149–150 帧/分钟**
  （= 400ms 间隔，事件循环有大量空闲）② `现价` 每分钟都在变（期货 tick 走同一条
  socket、同一个 `pendingTickersEvent`）③ `ticks_received` 持续增长 ⇒ 客户端在读在排空。
  读侧结构也支持：`ib_async` 读路径纯事件驱动（`Connection.data_received` →
  `Client._onSocketHasData` 同步解完缓冲区内**全部**消息 → `tcpDataProcessed` 发
  `pendingTickersEvent`），**没有会被卡住的读循环**。`netstat` 亦确认 4002 只有
  **一条**连接（PID 8504），无僵尸进程占 `clientId`。

  **待 KAI 定（二选一）**：
  - [ ] 前端是否加提示。⚠️ 提示**不能写"夜盘无 IV"**（已证伪）—— 必须是**数据驱动**的
    "model IV 不可用"（判据：`ticks_received` 在涨 + `store_cells == 0` +
    `ticks_dropped` 在涨）。现状：帧里已有这三个数，但前端未据此给原因。
  - [ ] 是否把 `ticks_dropped` 的**增量**纳入健康判据（当前它只被 `feed_service` 计数，
    没有任何检查器/日志在盯它；317,621 这个量级此前无人看见）。

- [ ] **[中] 三条卡片是"欠账"：能机械守、但没写检查器**（2026-09-15 02:5x 审计；
  判据见 `notes/memory/QUICKREF.md` 的"收录判据"节：**每条卡片必须能报出"谁守着它"
  或"为什么守不住"**）。这三条两样都报不出 ⇒ 不是永久卡片，是欠账：

  | 卡 | 现状（实测） | 该补的断言 |
  |---|---|---|
  | A | `grep inverse tools/*.py` **0 命中** | 帧行序降序 ↔ `web/heatmap.js::yAxis.inverse = true` 必须**成对**（静态可判） |
  | E | `selfcheck_core` 只查 `market_data_type` **键在不在、不查值** | `config/ibkr.json::market_data_type` **必须 = 3**（写 1 会 fail-closed 退出，但没人拦） |
  | L | `grep 'splitLine\|cellBorder' tools/*.py` **0 命中** | `cellBorderMinPx` 单位是 **CSS px** + 网格线走轴 `splitLine` 抽样 |

  ⚠️ 目标不是"再加三张卡"，而是**把这三条降级**：细节归检查器 docstring，
  卡片只留一行指针。⚠️ **本文件所在清单「只减不增」**（KAI 2026-09-15 明令
  **"禁止新增速查卡"**，判据写在 `notes/memory/QUICKREF.md` 的"收录判据"节）
  ⇒ 这三条补完是 **23 → 20 条，净减**，不是"持平"。

- ~~**[中] 持久化落点：单库 → 一交易日一文件**~~ —— **已完成**（2026-09-15，
  会话 `notes/sessions/2026-09-15/persistence-session-files/`）。
  KAI 目标原话："第一天就写第一天的数据，重启后接着写第一天的；第二天新开一份，
  第二天重启，继续写第二天的"。落地：`config/persistence.json` 的 `db_path` 改为
  `db_dir: data/sessions` + `db_filename: {session_key}.db`；新增
  `features/persistence_store.py` 承载"文件与表"，`features/persistence.py` 只留队列
  与调度（384 → 310 行，改动前余 16 行放不下）。旧库当前会话 88+88 行已迁移。
  回归 `check_persistence` 7/7 + 新增 `check_persistence_sessions` 4/4；
  `run.py --check` `RC=0`；`ws_probe` 25/25；非空转两个变异各抓 2 条。
  ⚠️ 两个坑已写进 README §5 与 `project_state.md`：
  ① `_batch_write` 必须**逐条**按会话切文件（跨日批次里混着两个会话）；
  ② `SessionFileStore.close()` **必须先提交再关闭** —— SQLite 的 `close()` 对未提交
  事务是**回滚**，实测丢掉旧会话那一行。

- ~~**[中] 旧会话文件的保留策略未定 —— 当前只增不删**~~ —— **已定并落地：归档不删**
  （2026-09-15 02:2x 首版 → **03:1x 按 KAI 明令改为"归档"**，会话
  `notes/sessions/2026-09-15/persistence-session-files/`）。

  **KAI 2026-09-15 03:0x 两条明令**：
  ① 原话 **"这就是历史数据，有用。"** ⇒ `data/sessions/<到期日>.db` **不是"残留垃圾"，
  是逐交易日的 ΔIV / Skew 原始记录**（回看、对拍、做数据集的唯一来源）。
  ② 原话 **"'不留档、不备份' 只针对旧单库 `data/session.db`"** ⇒ 我在 02:2x 把这句话
  的适用范围**从旧单库扩大到了全部逐日文件**，是**误读**（已按此更正，见下）。

  实现（**移动，不删除**）：`SessionFileStore.archive_other_sessions(keep_key)` 把 db_dir
  内所有非当前会话的库文件 `rename()` 到 `archive_dir`（`persistence.json::archive_dir`，
  默认 `data/archive`）；`AsyncPersistenceWriter.start()` 在打开本会话文件后调用它，并把
  `(已归档, 未归档)` **两组**返回给调用方（`features/` 整层不写日志，由 `app/pipeline.py`
  **各记一行** —— 动数据不允许静默，"没归档成功"更不允许）。
  **三道闸门 + 一道构造期校验**：① 只在 `db_dir` 之内 glob；② 只匹配 `db_filename`
  模板派生的名字；③ 归档目录**同名不覆盖**（跳过并上报，源文件留 db_dir 下次再试）；
  ④ `archive_dir` 落在 `db_dir` 之内 ⇒ **构造时抛错**。
  回归 `check_persistence_sessions` **6/6 → 7/7**；非空转 3 个变异（摘掉归档 / glob 越界
  到上一级 / 同名无条件覆盖）各抓 1–3 条，还原后全绿。
  ⚠️ **未做**：跨日那一刻产生的旧文件留到**下次启动**才归档（`features/` 无日志可记）
  ⇒ **未归档数 = 自上次启动以来的交易日数**（实测 `tmp/probe_rollover_residue.py`：
  不重启跨 5 个交易日 ⇒ 5 个文件 ≈ 9.4 MB；每天重启一次则最多 1 个文件 ≈ 2.35 MB）。
  未归档文件**永不会被读到**，只是还没归位。
  ✅ **实盘验证**（2026-09-15 03:18:42）：合成 `data/sessions/20990101.db` → 用新代码
  重启 → 日志 `已归档 1 个历史会话文件到 data\archive（db_dir 只留当前会话）: 20990101.db`；
  `data/sessions/` 只剩 `20260915.db`，`data/archive/20990101.db`（20,480 B）在。

- ~~**[低] `data/session.db` 是否删除 —— 待 KAI 定**~~ —— **已删除**
  （2026-09-15 02:2x，**KAI 明令：禁止备份，必须删**）。
  删除前实况：1,064,960 B，`heatmap_buckets` / `skew_points` 各 88 行，
  mtime 停在 01:22:07（已停写）。删除后 `data/` 只剩 `sessions/`，
  `data/sessions/20260915.db` 未受影响（当刻 290,816 B 且在长）。
  `data/` 在 `.gitignore` 里 ⇒ **不可恢复、无备份**（按明令执行）。
  引用同步：`notes/context/handoff.md` 两处"留作迁移前存档"、
  `tmp/migrate_session_files.py` 与 `tmp/repro_holes.py` 的横幅均已改口。

- ~~**[低] `notes/memory/ARCHITECTURE.md §4` 目录约定系统性过期**~~ —— **已完成**
  （2026-09-15 01:5x，会话 `notes/sessions/2026-09-15/persistence-session-files/`）。
  按目录枚举重写 §4（列**全部实际模块**）；同批更正 §2 的 Python 版本
  （3.13.12 → **3.13.14**，项目 `venv/`）、§5 的 `10 个 JSON` → **11** /
  `关键配置项 40` → **50**、§6 四处类名（`SkewSeries`/`ImpulseTracker`/`FrameBuilder`/
  `WSBroadcaster`）与 `TickStore (SQLite)` → **内存环 `RingBuffer`**、§7 的
  "`run.py` 只剩 `--check`" → **不带参数即启动服务**。改后 `run.py --check` 仍 `RC=0`。

- ~~**[低] `tmp/` 残留探针清理**~~ —— **已完成（改为加"已失效"横幅，未删）**
  （2026-09-15 01:5x，同上会话）。实测校准横幅措辞：`tmp/repro_holes.py`
  **rc=0、静默打印冻结值**（危险的一类）、`tmp/probe_mutation_cross_session.py`
  **rc=1 `AttributeError`**（响的一类，首炸点是已消失的 `_fetch_session_rows`）。
  不删的理由：`tmp/` 是 gitignore 的一次性脚本区，且 `tmp/migrate_session_files.py`
  仍是本轮迁移的证据。

- ~~**[中] 假 0 带残留：bucket 0 本身仍被恢复**~~ —— **已关闭**（2026-09-15，
  会话 `notes/sessions/2026-09-15/persistence-session-identity/`）。
  本条登记的根因（`features/persistence.py::recover()` 读 `heatmap_buckets` **全部行**、
  无任何过滤）**就是**修复对象：`bucket_index` 是**日内坐标、每个交易日复用**，
  而表里**没有会话身份** ⇒ 跨会话的行落进同一键空间。
  修法：`session_key`（= 当日到期日）进主键 `(session_key, bucket_index)`，
  `recover()` / `recover_skew()` 按会话过滤；**缺列的旧表整张丢弃并报出行数**
  （实测 `丢弃 1830 行`）。重启后**假 0 带一并消失**（截图对照：
  `tmp/startup_panel_20260915_0030.png` → `tmp/fixed_panel_0041.png`）。
  回归 `tools/check_persistence.py` 8/8（含跨会话隔离 / 旧表迁移 / 空身份拒绝），
  非空转：摘掉会话过滤 ⇒ 跨会话用例报 `今日会话应只有 1 个桶，实际 3`。
  ⚠️ **本轮只关了上面这一条**：同一根因还有三种更严重的表现（帧的 `skew.latest`
  取 `skew_series[-1]` ⇒ 报出**昨天**的点；`skew.series` 混入昨天的点、label 用今天的
  网格算 ⇒ 曲线画到未来；热力图把昨天 RTH 的数据画在今天 GTH 的时刻上）——
  它们由同一次修复一并消除，但**之前从未登记**，故记在这里而非当作"旧残留"。
  ⚠️ "`recover()` 只取最后一段连续桶"这条**仍未被选**（KAI 2026-09-14 未选，
  2026-09-15 仍未选）：会话身份修好后它**不再是错值来源**（别的交易日的行读不进来），
  只剩"同一会话内孤桶被前向填充沿用 ≤ `heatmap_max_ffill_buckets`(20) 桶"这个形状，
  由 `check_reconnect_gap.py::case_long_gap_is_blanked` 守着。

- ~~**[中] 细档位纵线（自适应步长）未做高 dpi 实测**~~ —— **已作废**（2026-09-14）。
  热力图渲染器换回 ECharts 后，网格线改走轴 `splitLine`，`cellBorderMinPx` 的单位随之
  由**物理像素**变为 **CSS px**（ECharts 的坐标单位），"高 dpi 下 stride 翻倍"的问题**不再存在**。
  新语义见 `notes/memory/QUICKREF.md` 卡 L。

- [ ] **[高] 热力图换 ECharts 后宽档位持续占用 40–47% 单核**（2026-09-14，**KAI 已知情并接受**）——
  实测（headless + SwiftShader，1400×520、24 行）：ECharts 单次重绘 630 列 65.7ms /
  1352 列 159.9ms / 2370 列 188.1ms；同环境旧 WebGL 0.6 / 1.0 / 1.3 ms。
  节拍 `web/ws_client.js:137` = 200ms、后端推送 400ms ⇒ **2.5Hz**。
  可选缓解（**均未实施，需 KAI 指令**）：热力图重绘节流到 ~1Hz（与推送解耦，占用 → ~19%）、
  或给 `maxColumns` 降档。注意 `progressive` 是负优化（2370 列 424ms > 不开 188ms）。

- [ ] **[高] 本仓库禁用 `git rm` / `git mv`**（2026-09-14 事故）——
  执行 `git rm -f web/gl_heatmap.js && git mv web/test_gl.html ...` 期间**整个 `web/` 目录
  从工作区消失**（`git status` = ` D web/*.js` ×17 + `D  web/gl_heatmap.js`），`git mv` 报
  `fatal: bad source`；**无任何命令显式删除目录，成因未查明**。靠 `git checkout -- web/` 恢复，
  但未提交的 `web/config.js` / `web/skew.js` 改动丢失、只能按记录重建（非逐字节还原）。
  ⇒ 一律改用 `rm` / `mv` + `git add`。证据见
  `notes/sessions/2026-09-14/webgl-to-echarts/handoff.md::事故`。

- [ ] **[中] 图例两项同名 `25Δ Skew` —— 待 KAI 定名**（2026-09-14）——
  `web/skew_helpers.js::displayName()` 把 `25Δ Skew·负` 也显示成 `25Δ Skew`（正负分段渲染的设计），
  图例上因此出现两条同名项（一暖一冷）。**改名属产品决策，未获指令不动。**
  注意：已修的是**颜色**（`itemStyle.color`），**不是**命名 —— 别把两件事混为一件。

- [ ] **[低] `check_page_render` 默认 budget 下必失败 —— 根因已定位**（2026-09-14）——
  该检查用 `--virtual-time-budget=14000` + `--dump-dom`（`tools/check_page_render.py:91-110`）。
  **虚拟时间跑在真实 WebSocket 帧之前** ⇒ 抓到的 DOM 是"还没收到第一帧"的状态：
  `meta 为空` ×2、`0 个 canvas`、`现价 --`。`--budget 60000` 即恢复
  （热力图 22 档 × 741 桶、Skew、canvas≥2、现价 7603.7 全 ok）。
  另有**断言本身过期**一条："有且仅有一个周期处于选中态" —— 会话按钮（`app_sessions.js`）
  与周期按钮各有一个 `on` ⇒ 恒为 2 个。**仅记录，未改**。

- ~~**[高] `现货 7591.70` 来源未定位**~~ —— **已关闭**（2026-09-14）。KAI 更正：7591.70 是上一轮
  被驳回算法自己算出来的产物，**不是** IBKR 给的值。探针实测（`tmp/probe_spot_basis.py`）：
  IBKR 在 GTH 给的 SPX 指数 = **7656.98 = 周五官方收盘，恒定**。
  ⇒ "IBKR 给的是冻结的 RTH 收盘价"这个说法是对的。残余风险转为下一条（新鲜度判不出）。

- [ ] **[低] `marketDataType` 判不出指数新鲜度 —— 危害已消除，机制缺口保留**（2026-09-14 实测）——
  GTH 期间 SPX 指数恒定 7656.98（周五收盘），但 `marketDataType = 1`（报"实时"）。
  ⇒ `ibkr.max_underlying_age_s = 10.0`（`acquisition/feed_reconcile.py::_spot_stale`）
  **结构上拦不住这类值**。
  **危害已由 B2b 结构性消除**：`SpotSourceSelector` 在合成区段**直接丢弃**指数 tick，
  冻结值不再进入下游 ⇒ 原先"比真实现货高 40.4–42.0 点 ≈ 8.1–8.4 档"不再发生。
  机制缺口仍在（判新鲜只能看"值有没有变过"，`marketDataType` 无此语义），
  但当前**无已知受影响路径** ⇒ 降为低。**未获指令不改闸门判据。**

- ~~**[中] 交易日 RTH 段实盘验证（B2b 落地的最后一块）**~~ —— **已闭合**（2026-09-14 09:45 EDT，
  会话 `notes/sessions/2026-09-14/live-render-verify/`）。三项全部实测通过：
  ① 指数在 09:30 后确实恢复实时 —— 冻结值 7656.98（09:27 日志）→ 09:30 `现价 7611.44`，
     独立探针实测 `last=7611.27 ≠ close=7656.98`；
  ② 09:25 交班平滑 —— 帧内 messages 依次出现
     `现货源切换：区段 rth → 指数直读` → `现价恢复更新，窗口跟随继续` →
     `窗口跟随现价重建 ±12 档 (+22 / -22, 共 48)`，窗口按既有 `WindowFollower` 自动重建；
  ③ RTH 段走**指数直读**而非合成（同上第 1 条 message）。

- ~~**[中] `check_period_aggregation.py` 既有失败 —— 根因已定位**~~ —— **已关闭**
  （2026-09-15 复扫，会话 `notes/sessions/2026-09-15/persistence-session-identity/`）。
  本条列的 6 个"既有失败"（`check_period_aggregation` / `check_page_render` /
  `check_skew_alignment` / `check_skew_viewport` / `check_web_contract` /
  `check_ws_compression`）**现只剩 1 个**：2026-09-15 用 `venv/Scripts/python.exe`
  全量复扫 **21 个 `tools/check_*.py` ⇒ 20 `RC=0` / 1 `RC=1`**，唯一红 =
  **`check_page_render`**（其两处成因见下条，**本轮未动**）。
  ⚠️ **判据必须用 venv 解释器**：裸 `python` 缺 `ib_async`/`aiohttp`，
  `check_web_contract` 等会在 import 阶段崩成假红。
  🆕 本轮另修一个**不在本清单里**的假红：`check_session_grid.py` 的"交易日推导"
  用例隐含"锚点必须是周一"，只在周一通过、其余六天报 4 条红（详见会话记录
  `handoff.md::第二个缺陷`）。**⇒ 这张清单本身漏了它，说明"按清单清点"不可靠。**

- ~~**[中] B2b 实现待启动**~~ —— **已完成**（2026-09-14，会话
  `notes/sessions/2026-09-14/b2b-spot-synthesis/`）。5 条拍板全部落地：
  ① `config/spot.json` 独立文件；② 09:25 交班下线 GTH 锚定、切回指数（窗口重建由既有
  `WindowFollower` 自动完成，锚跳 8.15 档 > trigger 3 档，**未加特殊代码**）；
  ③ `ĉ` 两层闸门（`max_abs_carry` fail-closed + `max_carry_jump` 拒收该桶、基准跟上）；
  ④ 不做 09:30 单点对拍；⑤ `--check` 按 `pyvenv.cfg` 识别 venv。
  新回归 `check_spot_synthesis` 16/16 + `check_spot_source` 11/11，非空转 5/5 变异被抓。

- ~~**[中] `run.py --check` 基线已漂移：RC=1，2582 项误报**~~ —— **已修**（2026-09-14）——
  根因：`.venv/` 与 `venv/` 未登记 `NON_SOURCE_DIRS`，`ROOT.rglob("*.py")` 收了 site-packages。
  修法按 KAI 拍板：`iter_py_files()` 新增 `_in_virtualenv()`，**按 `pyvenv.cfg` 识别**
  （与目录名解耦，不再补两条目录名）。
  非空转验证：`mv .venv/pyvenv.cfg .venv/pyvenv.cfg.off` → `RC=1 / 1291 项`；
  恢复后复跑 → `RC=0`。终态 `RC=0`（90 个 Python + 14 个前端脚本全部合规）。

- ~~**[中] 残留进程 PID 15612 占用 8060**~~ —— **已中断**（2026-09-14 KAI 指令）。
  `MSYS_NO_PATHCONV=1 taskkill /F /PID 15612` → SUCCESS，`netstat :8060` 已无监听。
  教训保留：它跑的是已撤回构建（日志字段 `公允` 在 HEAD 代码中不存在），
  **实盘验证前必须先确认 8060 上没有别的进程**。

- ~~**[中] 实盘首次出图未验证**~~ —— **已闭合**（2026-09-14 09:45 EDT RTH 段，
  会话 `notes/sessions/2026-09-14/live-render-verify/`）。四项逐条取证：
  - ✅ `health.mode = delayed`（推导值，非观测）；**期权与 SPX 指数实测 `marketDataType=1`**
    （任务书预期的"指数 = 3"是过期预期，实测为准）；`modelGreeks` 与 bid/ask/last Greeks
    并存且值不同
  - ✅ **48 条订阅**（±12 档 × Put/Call），`projected_subscriptions()` = 49
  - ✅ 热力图出图：`ws_probe` 全部通过（帧 18059→18068、**24 档**、1624 桶、15,420 格）；
    真 Chrome 截图 185,973 字节，顶栏 `connected`，热力图 + Skew 双面板出图
  - ✅ `health.rate_limit` 四要素（45 / 1.0s）+ 两条非空转证伪
    （非默认 12/0.5s 生效 + 突发 200 条 ⇒ `events` 0→1、`throttling` 翻真后复位）
  - 2026-09-13 遗留的 ⚠️「SPX 现价 7591.70」仍**作废**（那是被驳回算法的产物，非 IBKR 值）。

- ~~**[中] 4 个需服务的检查 — 1/4 已跑通**~~ —— **已关闭**（2026-09-15 盘中，
  会话 `notes/sessions/2026-09-15/persistence-session-identity/`）。
  服务在跑（GTH 段，`connected` / `last_tick_age_s 0.0` / 80-92 订阅）时全量复扫：
  - ✅ `ws_probe` —— **25/25 全部通过**（修复前 26/27；唯一 FAIL 是跨会话持久化污染，
    已修）。24 档 × 532 桶、Skew 5 点。
  - ✅ `check_web_contract` —— **`RC=0`**（**用 venv 解释器走它自己的入口**，
    不再是"离线等价物"）。此前它红是**裸 `python` 缺 `aiohttp`**，不是产品问题。
  - ✅ `check_ws_compression` —— **`RC=0`**（压缩比阈值不再漂红）。
  - ❌ `check_page_render` —— 仍 `RC=1`，**既有缺陷、本轮未动**：
    ① 断言「有且仅有一个周期处于选中态」把页面上**所有** `<button>` 收成一个列表，
    而页面有**两组**独立按钮（会话 `全时段/GTH/RTH` + 周期 `30秒/1分/…`）各有一个 `on`
    ⇒ `len(chosen) == 1` **恒不成立**；② 虚拟时间窗口随首帧体积漂移
    （`--budget 14000` 无 canvas / `20000` 报数据陈旧 / `120000` 报数据中断）。
    要修得先改断言语义、再换掉虚拟时间方案，**不是调个数**。

- [ ] **[低] `check_web_contract.py` 顶层 `import aiohttp`** 使第 1、2 段
  （纯静态对照）也无法在无 aiohttp 的环境运行。是否把 import 挪进函数内
  **待 KAI 定** —— 改动小，但属"重构现有工具"，未获指令不擅自动。

- [ ] **[低] `~/.workbuddy-ai/tmp/` 历史探针 —— 清单已列，待 KAI 拍"全迁 / 部分迁 / 只登记不动"**
  （2026-09-15，会话 `notes/sessions/2026-09-15/persistence-session-identity/`）——
  新约定落点已是 `<项目根>/tmp/`，但历史文件仍在用户级目录（被所有项目共用）。
  KAI 2026-09-13 拍板：**下一个会话做**，且"开始前先列清单"。
  🆕 **清单已出**：`notes/sessions/2026-09-15/persistence-session-identity/artifacts/user-tmp-probes.md`
  —— 共 **72** 项（13 目录 / 35 个带 `import` 的脚本 / 24 个非脚本产物），
  其中 **38 项**与 SPXW 相关（判据：文件名或内容含 `spxw`/`8060`/`4002`）。
  本轮**未移动、未删除任何文件**（动用户目录需 KAI 明令）。
  ⚠️ 清单的 `proj` 列是**关键词判定，未逐一人工确认归属** —— 拍板前若要更准，
  可按 mtime 分段人工过一遍。

- ~~**[中] 热力图格子边框（"网格线"）在 WebGL 重写时丢失**~~ —— **已修**（2026-09-14）——
  根因：旧版 ECharts `heatmap.js` 有 `itemStyle: { borderWidth: 1, borderColor: CFG.theme.grid }`
  （每格 1px 边框），`af2e2e4` WebGL 重写时删掉且未在新引擎实现；
  `gl_heatmap.js` 的 shader 只画填充 + volume 高亮白边 ⇒ `theme.grid` 成**死配置**。
  修法：在 fragment shader 里补逐格边框（1 物理像素，**两个方向独立判断**，
  某方向格子 < 3 物理像素时不画 —— 否则 `bw = 1/cellPx ≥ 0.5` 会让判定区间覆盖整格，
  热力图糊成一片深灰）。`config.js` 新增 `heatmap.cellBorderMix`（0.55），
  边框色复用 `theme.grid`（死配置复活）。
  实测：1 分档（~570 列）横向网格线可见；5 分档（115 列）完整双向网格。
  非空转：`cellBorderMix=0` → 网格**完全消失**（截图 `mut-mix0.png`），改回后恢复。
  注意：坐标轴 `splitLine` 旧版就是 `show: false`，**不是**这个问题。
  ⚠️ **本条的"某方向 < 3 物理像素即整方向不画"已被 2026-09-14 后一会话推翻** ——
  1 分档 630 列时格宽 2.40px，纵线因此整条消失（KAI 报"长条状"）。
  现改为**单侧自适应步长**（见下条）。

- ~~**[高] 热力图上下镜像（屏幕行序 = 帧行序的反向）**~~ —— **已修**（2026-09-14）——
  根因：`web/gl_heatmap.js::update()` 写 `var tr = rows - 1 - r;`（注释称 "inverse Y"），
  而 shader 的天然映射是"屏幕顶 = texture 行 0"、HTML overlay 的标签/现货线也从索引 0 起
  ⇒ 行序被**反了两次**，整张图上下镜像（满宽的行跑到屏幕顶部）。
  修法：去掉 `tr`，按帧行序直写 texture（`var i = (r * cols + c) * 4`）+ 契约注释
  "帧行序 ≡ texture 行序，**不要再反转**"。
  非空转：改回 `rows-1-r` 重截 ⇒ 满宽行跑回顶部（`tmp/mut_mirror.png`）；
  复原后逐行对上帧（`706/706`、`450/449`、`2/1`）。

- ~~**[高] 20:15 起满宽"假 0 带"（系统非 20:15 启动，前端首列却落在 20:15）**~~ —— **已修**（2026-09-14）——
  根因链：`features/persistence.py::recover()` 读 `heatmap_buckets` **全部行**
  → `app/pipeline.py:175-177` → `HeatmapEngine.load_snapshot()` → `_row_values()` 的
  `carried` **无上限前向填充** ⇒ 一个孤立旧桶被一路沿用，拉出满宽 `ΔIV=0` 的亮黄绿带，
  与真"IV 没变"无法区分。
  修法：新增 `config/serialization.json::heatmap_max_ffill_buckets`(20 = 30s×20 = 10 分钟，
  取 `heatmap_feed_gap_s`(300s) 的 2×)；`HeatmapEngine` 加 `_max_ffill` slot，
  `_row_values()` 用 `last_seen` 记账，跨度超限输出 `None`（留白）。
  回归 `tools/check_reconnect_gap.py::case_long_gap_is_blanked`（阈值从 config 读，不写死）；
  `--selftest` 扩为两处注入（吞 `break_now` + 上限推到无穷）⇒ 实测两例变红。
  ⚠️ ~~**需重启进程才生效**~~ —— **已重启并实测生效**（见下条）；**残留**见 Active 段第一条。

- ~~**[高] PID 896 需重启，前向填充上限才生效**~~ —— **已完成**（2026-09-14 KAI 指令）——
  `run.py` 只认 Ctrl-C（`Pipeline.stop()` 打印 `已停止`），**无 HTTP / 文件 / 信号停机入口**
  ⇒ 沙箱内只能硬杀。实测 `venv/Scripts/python.exe run.py` 是**父子两进程**
  （venv 存根 ~8MB 父 + 真实解释器 ~100MB 子，同秒创建）。
  `taskkill /T /PID 8908` 报 `8908 not found`，但 `tasklist` 复核两个都已消失；
  日志**无 `已停止` 行** ⇒ 属硬杀。
  硬杀安全性核过三条：`journal_mode=delete`（不损坏）· `_batch_write()` 每批 commit
  （最多丢一个未提交批次）· `recover()` 会把已提交桶捞回；停后 `integrity_check` = `ok`、334 行不变。
  重启：`07:19:49` 启动 → 恢复 **335** 个历史桶 → `07:19:59 流水线已就绪`。
  **生效判据**（活帧逐行非空列分段）：row 19（strike 7575）由 `first=1 / nonnull=1308`
  变为 `[(1,20),(449,554),(706,726),(1065,1331)]` ⇒ 假 0 带 **1308 列 → 20 列**（= 上限）。
  对照 row 2（7660）无 `(1,20)` 段 ⇒ 修的是**带**，真实数据未动。
  流程已沉淀进 `spxw-live-verify`（SKILL.md §5 + `references/pitfalls.md` 第 11 条）。

- ~~**[中] 细档位（30秒/1分）没有纵线，看着是长条状**~~ —— **已修**（2026-09-14）——  根因：默认周期 1 分 ⇒ 630 列 ⇒ 格宽 2.40px，被上一轮 `>= 3.0` 的**双侧**阈值判为"太窄"，
  纵线整方向跳过；5 分档（126 列 / 12px）本来就有完整网格 ⇒ **档位相关**，非损坏。
  修法：换成**单侧自适应步长** `stride = ceil(u_borderMinPx / cellPx)`，线仍落在**真实格边界**
  （只取子集），`stride = 1` 退化为旧行为；新增 uniform `u_borderMinPx` +
  `web/config.js::heatmap.cellBorderMinPx = 5`（**物理像素**），`web/heatmap.js` 透传。
  实测 1 分档：**653 条纵线、间距中位 5.0 px**（`tmp/grid_final.png`）。
  非空转：`cellBorderMinPx = 0` ⇒ `stride = 1` ⇒ 纵线塌成密纹、四条扫描线仅检出 0–9 条、无周期。
  单位坑见 `notes/memory/QUICKREF.md` 卡 L；高 dpi 实测仍是待办。

- ~~**[中] Skew 图例色与曲线色系统性不符**~~ —— **已修**（2026-09-14）——
  根因：5 条 series 只设 `lineStyle.color`，而 ECharts 的 legend 图标**不读**它，
  退化为默认调色板按索引分配。
  修法：给 5 条 series 补 `itemStyle.color`（与 `lineStyle.color` 同值），
  并在 `skew.js` 注释里写明"两处必须一起改"的理由，防止后人当冗余删掉。
  实测：`itemStyle` 与 `lineStyle` **5/5 一致**；图例色块由 `蓝紫/绿/黄/红/浅蓝`
  变为 `红/蓝/灰/红/蓝`，与曲线对应。
  非空转：把 `series[0].itemStyle` 改回调色板色 `#5470c6` → 图例第 1 项立刻变回蓝紫。
  ⚠️ **附带问题仍未处理**：图例有两项同名 `25Δ Skew`
  （`skew_helpers.js::displayName()` 把 `25Δ Skew·负` 也显示成 `25Δ Skew`）——
  这是正负分段渲染的设计，改名属产品决策，**待 KAI 定**。

- ~~**[低] 本机缺 `ib_async` 与 `aiohttp`**~~ —— **已解决**（2026-09-13 KAI 启动 Gateway 后安装）。
  `check_reconnect_flow` / `check_web_contract` / `ws_probe` 现在都能跑。

- ~~**[中] 网格粗细「受成交量无级调节」未实现**~~ —— **已实现**（2026-09-15 05:3x，KAI 拍板方案）。

  **丢失与发现**（2026-09-15 04:5x）：该特性原在旧 `web/gl_heatmap.js` 的 fragment shader
  （`float vol = s.b/255.0; float border = vol*0.35;`），`6828e3a`（WebGL→ECharts 重写）
  删掉该文件时一并消失。此后数据链"三跳掉在最后一跳"：后端在发（`heatmap_engine.py::_row_volumes`
  → `heatmap_matrix.py` 打包 `vol_bm`/`vol_i16`）、前端在解（`matrix_codec.js` → `block.volumes`）、
  **但没有任何渲染器消费**（`heatmap.js` 全文零引用 `volumes`）。
  ⚠️ 本条与上方「格子边框在 WebGL 重写时丢失（已修）」是**两件事**：那条修的是**固定 1px 网格线**，
  并在描述里把 shader 的 volume 白边当成"要替换的旧实现"抹掉 —— 丢失点就在这里。

  **KAI 定的方案**（2026-09-15 05:1x）：① 数据源唯一 = **30 秒桶**的 tick 计数，更粗周期在组内聚合；
  ② 视觉 = **统一黑色边框**，成交量越大越粗（不做白边、不做圆点）。

  **实现**：
  - `web/config.js` 新增 `heatmap.volumeBorder{enabled,color,maxRatio:0.35,minPx}`
  - `web/heatmap.js::buildOption` 读 `block.volumes` → 逐格 `itemStyle.borderWidth`，
    `volMax` 取**本视口内**最大值，宽度锚在格子**短边**（锚长边时窄行上下边框会吃穿）
  - **补齐三条变换链路的 volumes 传递**（此前三处都丢，只有 `app_render.js::applyViewport` 保留了）：
    `period_align.js::sliceZones`（复用同一 `picked`）、`period.js::aggregate`（组内求和）、
    `period.js::clipTail`（同一个 `drop`）
  - 注释去重：`contracts/feature.py` 原写"tick 数多 = **圆点大**"、`matrix_codec.js` 写"不画圆点"、
    shader 画白边 —— 三种说法已统一为"黑色边框越粗"

  **实测（`tmp/vol_border_probe/`，Playwright + Chrome 153，像素级）**：
  受控设计 = 同一列内 volume 随行递增（vol 0→10）、**水平位置固定** ⇒ 排除位置伪影；`values` 全 0。

  | 模式 | 带宽（vol 0→2→…→10） | 极差 | 判定 | RC |
  |---|---|---|---|---|
  | `on`（生产配置） | 1.00 → 2.81 → 5.13 → 7.38 → 9.56 → 11.81 px | **11.00 px** | PASS | 0 |
  | `off`（只关 `volumeBorder.enabled`） | 恒定 1.00 px | 0.00 px | FAIL | 1 |

  **非空转**：两份跑的是**同一份 `web/heatmap.js`**，唯一差异是一个开关 ⇒ 相反判定。
  另有**真帧端到端**（`real.html`）：用后端 `HeatmapSerializer` 铸帧 → `SWATCH_MATRIX.decode`
  → 渲染，断言 `volumes` 逐值一致、`values` 往返误差 < 1e-6 ⇒ 全过。

  **回归已补**（这是本条的重点：此前"没有任何回归守着"）：
  `tools/check_period_aggregation.py` + `tools/period_reference.py` 新增 13 条 volumes 逐值对拍
  （aggregate 7 档 × / clipTail / sliceZones 4 组）。**变异验证**：从 `period.js` 删掉 2 处传递
  ⇒ `aggregate(g2…g200)` 与 `clipTail` 全转 FAIL；从 `period_align.js` 删 1 处 ⇒ `sliceZones(gth/rth/gth+rth)`
  全转 FAIL；还原后复绿。`g1` 与 `keep=none` 变异后仍 ok 属正确（走恒等分支，原样返回整块）。

  **性能代价（实测，画布 1400×520 / 24 行 / 27% 填充）**：

  | 列数 | off | on | 增量 |
  |---|---|---|---|
  | 630（默认 1 分档） | 57.4 ms | 88.0 ms | +53% |
  | 1352 | 86.1 ms | 140.7 ms | +63% |
  | 2370（30 秒档全时段） | 135.9 ms | 273.5 ms | **+101%** |

  节拍 = 后端推送 400 ms ⇒ 最坏 273.5 ms 仍**在预算内**（占用 68%，此前 34%）。
  ⚠️ 若日后把推送提到 2 Hz 以上，这里会先撞线。

  **契约清单为何没加 volume 字段**：`vol_bm`/`vol_i16` 是**可选字段**（后端只在 `matrix.volumes`
  非空时才发），而 `check_web_contract.py` 的语义是"键缺失算失败" ⇒ 加进去会让合法帧误报。
  已在 `PAYLOAD_PATHS` 处写明理由，并指向上面那两个守它的检查器。

  **同类排查（2026-09-15 05:0x 顺带做完，已封口）**：`tmp/audit_dead_payload.py`
  把 `serialization/` 的 82 个键名逐个在 `web/` 里按词边界搜 ⇒ 17 个零命中。
  逐个定性后 **16 个是"前端从不解码的诊断元数据"，属设计**：
  - `health.rate_limit.*` / `health.sub_limit_backoff` —— skill `spxw-live-verify/references/live-link.md`
    第 53-58 行明写这是**抓帧排查读数**（`f["health"]["rate_limit"]`），前端本就不显示
  - `health.ticks_received` / `ticks_dropped`、`session.date` / `is_open`
  - `cells.quality` / `delta_iv` / `primary_impulse` —— 前端不画 cells 表格
  - `skew.series.put25_strike` / `call25_strike` / `atm_delta` / `quality` —— 前端只画曲线

  **判据（唯一可靠）**：看**前端是否为它写过代码** ——
  写了却不用 = 掉地；从没写 = 不需要。按这条判据，**`volumes` 是唯一一处**：
  `matrix_codec.js:101-126` 专门解码它、`app_render.js:27` 在 viewport 缩放时专门
  切片搬运它 —— 数据流一路维护到最后，却没有任何渲染器接。
  ⇒ **本项是同类缺陷里的孤例，不是普遍现象。**
  ⚠️ 反向检查（"后端发的字段前端是否都读"）**不可**固化成常驻门禁 ——
  上面 16 个合法的不读会让它满屏误报（同 `frontend.md` 文末"不要把前端探针
  固化成常驻回归"的理由）。该排查是**一次性取证**，脚本留 `tmp/`。

  **遗留**：`splitLine` 抽样网格**保留**（细档位 30 秒档格宽约 0.44 px，逐格边框等比缩到
  亚像素必然不可见，去掉它等于回归掉 2026-09-14 修的"密集区看不见网格"）。两套线颜色都在
  深色端，粗档位下逐格边框在上层盖住 splitLine，不冲突。**待盘中肉眼确认**实际观感。

  **同类排查（2026-09-15 05:0x 顺带做完，已封口）**：`tmp/audit_dead_payload.py`
  把 `serialization/` 的 82 个键名逐个在 `web/` 里按词边界搜 ⇒ 17 个零命中。
  逐个定性后 **16 个是"前端从不解码的诊断元数据"，属设计**：
  - `health.rate_limit.*` / `health.sub_limit_backoff` —— skill `spxw-live-verify/references/live-link.md`
    第 53-58 行明写这是**抓帧排查读数**（`f["health"]["rate_limit"]`），前端本就不显示
  - `health.ticks_received` / `ticks_dropped`、`session.date` / `is_open`
  - `cells.quality` / `delta_iv` / `primary_impulse` —— 前端不画 cells 表格
  - `skew.series.put25_strike` / `call25_strike` / `atm_delta` / `quality` —— 前端只画曲线

  **判据（唯一可靠）**：看**前端是否为它写过代码** ——
  写了却不用 = 掉地；从没写 = 不需要。按这条判据，**`volumes` 是唯一一处**：
  `matrix_codec.js:101-126` 专门解码它、`app_render.js:27` 在 viewport 缩放时专门
  切片搬运它 —— 数据流一路维护到最后，却没有任何渲染器接。
  ⇒ **本项是同类缺陷里的孤例，不是普遍现象。**
  ⚠️ 反向检查（"后端发的字段前端是否都读"）**不可**固化成常驻门禁 ——
  上面 16 个合法的不读会让它满屏误报（同 `frontend.md` 文末"不要把前端探针
  固化成常驻回归"的理由）。该排查是**一次性取证**，脚本留 `tmp/`。

## Stale / Needs Verification

- [ ] **`check_reconnect_gap.py` 的假冲量场景未在真实断线下复现** ——
      "断线 >900s 时两道毛刺闸门因样本被裁双双失效"仍是静态分析结论。
      （`reset_feature_state_on_reconnect=false` 是**刻意默认值**，不是缺陷。）
- [ ] **`ibkr.max_underlying_age_s` 与重连清状态的真实断线场景未确认** ——
      2026-09-11 接线时只在单元/生命周期层面验证过，需 TWS / IB Gateway 实测。
- [ ] **`tools/fixtures.py::SyntheticSurface` 是简化曲面** —— 只保证确定性，
      不保证与真实 IV 曲面同形。依赖它的 `check_side_flip` 只验结构性事实，
      但**后续若有人拿它做数值断言会得到与实盘不符的结论**。
- [ ] **ib_async 合并 tickType 13/83** —— `TickRouter.source_tick_type` 恒为 13
      （名义值），属性层无法区分实时模型与延迟模型 greeks。
- [ ] **`git fetch` 在本环境不落地 remote-tracking ref（根因未定位）** ——
      `git fetch` 退出 0、输出 `[new branch] main -> origin/main`、并写了
      `.git/logs/refs/remotes/origin/main`，但 `refs/remotes/origin/main` **不存在**；
      手动建好后**下次 fetch 又被删**。全环境**无任何 prune 配置**；
      对照仓库 `live-volatility-surface` 正常。**不影响提交/推送**
      （`git ls-remote` 已核实远端 = 本地 HEAD），只让 `git status -sb` 显示 `[gone]`。
      需 KAI 在自己终端复现一次才能判定是否为工具沙箱侧现象。

## 已决策（KAI）—— 不要再当待办重提

- **RTH 收盘 = `16:00`，不是 Cboe 官方页写的 `4:15 PM`**（2026-09-13 KAI 明确）——
  理由：**KAI 只在正股的 RTH 时间（09:30–16:00）交易**，网格按自己的交易时段切。
  与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**，不要再提。
- **不设任何验收自动任务**（2026-09-13 KAI 明确）—— 由 KAI **手动在 GTH 时段验证**。
  此前记录的"定时任务不见了"**是预期行为**（KAI 有意不让它存在），
  不是工具缺陷，不要再当 bug 排查、也不要再重建。
- **限速桶读数不上前端**（数据已到帧 `health.rate_limit`，`web/` 刻意不动）。
- **IV 热力图 ΔIV ≈ 0 不退回中性色** —— 维持 `Turbo` **顺序**色阶
  （0 = 亮黄绿 `#a4fc3b`）。理由：忠实参考项目截图 + 原指令就是"只改色调"。
- **冷数据键序也统一为降序**（2026-09-13 复核时 KAI 选定）—— 与帧 `strikes` 同向。
  `dump_bucket()` 改 `sorted(..., reverse=True)`，回归
  `check_persistence.py::_case_key_order_descending`。
- **`web/*.js` 已拆分完成**（2026-09-13）—— `app.js` / `skew.js` / `period.js` 三文件
  拆分为 9 个模块，全部 < 400 行；`--check` `[1]` 全绿 `RC=0`。
  `.js` 只进 `[1]`，不进 AST 类检查（`[2][9][10]`）。
- **同族守卫缺口已修**（2026-09-13）—— `check_period_aggregation.py` 与
  `check_skew_alignment.py` 已接入 `tools/group_guard.py`，`--selftest` 各自抓全
  守卫 2 条用例 + 全部变异。`group_guard.py::prefixes` 契约 = `tuple[str, ...]`
  （不要传 `str`）。
- **`~/.workbuddy-ai/tmp/` 40 个历史探针推迟到下一个会话**（2026-09-13 KAI 拍板）—— 动
  用户目录需明令。已登记 `Active` 段，待下一会话开清单。
- **临时探针落点 = `<项目根>/tmp/`**（2026-09-13 KAI 拍板）—— 不再写用户级
  `~/.workbuddy-ai/tmp/`（那个被所有项目共用、已串味）。配套：**必须在
  `.gitignore` 与 `NON_SOURCE_DIRS` 两处登记**；探针用完即弃，判据要落成常驻回归。
- **`check_web_contract.py` 的 `import aiohttp` 不内移**（2026-09-13 复核时 KAI
  未选）—— 保持顶层 import 原样，静态两段仍靠桩模块离线补跑。
- **`notes/` 与 `.workbuddy-ai/memory/` 的分工**（2026-09-13）：
  `notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`），
  `memory/` 为根路由器（只留指针与跨项目约定）。**同一事实只写一处。**
- **色板缺机械回归 = 不做**（2026-09-13 KAI 明确）—— 前端是空壳，色彩映射由后端值驱动；
  色值变更的责任在后端，不需要前端做机械回归。从 Active 剔除。
- **`check_clock_protocol.py` 已并入 `--check` 常驻**（2026-09-13 KAI 批准）——
  作为 `[12]` 检查项，验证三个时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
- **联通与限速已并入 `--check` 常驻**（2026-09-13 KAI 批准）—— 作为 `[13]` 检查项，
  `selfcheck_connectivity.py`：若 8060 有服务则连 WS 抓帧校验结构；无服务时跳过（warning，
  非交易日预期），不视为失败。
