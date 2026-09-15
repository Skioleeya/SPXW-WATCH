# Handoff Index
- Latest session: 2026-09-15/heatmap-topn-skew-yzoom
- Current session handoff: notes/sessions/2026-09-15/heatmap-topn-skew-yzoom/handoff.md
- Status: **热力图"成交量 Top-3 无级黑边" + Skew Y 轴滚轮无限制自由缩放（锁定 / 双击复位）
  落地，新增常驻回归并全绿 —— 见下节。**
  ⓐ **热力图**：`heatmap.volumeBorder` → **`heatmap.volumeTop`**（`topN:3`、`minPx/maxPx:null`、
  `maxRatio:0.30`/`minRatio:0.10`，宽度锚在格子**短边**）。**只有 Top-3 命中格**带 `itemStyle`，
  其余保持裸数组 ⇒ **普通样式、无描边**（KAI 最终裁定："只留 Top3 黑边，其余普通" = 无黑边）。
  ⓑ **Skew Y 轴**：`skew.yZoom`（`step:1.15` / `minSpan:0.05` / `maxSpan:500` /
  `anchorAtPointer:true`）。滚轮在**绘图区内**才 `preventDefault()` 并缩 Y（区外直接放行
  给既有 `dataZoom` 管 X）⇒ **X 轴时间范围不变**。锚点用
  `convertFromPixel({yAxisIndex:0})`；缩放后**锁定**，**双击复位**（X 与 Y 同复）。
  小数位随量程动态增加（封顶 6 位）；`formatter` 带 `_fmtCache` 避免函数身份变化引发整图重建。
  ⓒ **三个真 Bug（都是实测数字逼出来的）**：① `zoomRange` 在极小 span 上放大 ⇒
  **返回零宽 `[0,0]`**（修：放大时基线 span 先抬到 floor）；② 锚点落在量程外 ⇒
  **视口被平移到指针处**（`[2.50,2.53]` + 锚点 99 ⇒ `[98.975,99.025]`；修：`t` 出界即退中心）；
  ③ **最要命** —— Top-N 各格边框**宽度全等**（分母用了第 N 名成交量 ⇒ 比值全 ≥1 ⇒ 全钳到 1.0；
  实测 `47/45=1.044`/`46/45=1.022`/`45/45=1.0`）⇒ 改分母为**选中集极差** ⇒ 修后
  `成交量 [45,46,47] → 宽度 [9.37,18.73,28.10]`。
  ⓓ **新增常驻回归**：`tools/check_heatmap_topn_skew_zoom.py`（**315 行**）+ 驱动
  `tools/topn_zoom_driver.py`（**179 行**）。分组 `[T1]`/`[Y1]`/`[Y2]`/`[Y3]`，
  `group_guard.py` 校验期望前缀为**独立常量**，**5 条变异**各落回其应落的前缀。
  ⚠️ **拆分是被自己规则逼的**：检查器一次写到 **469 行** ⇒ `run.py --check [1]` **真判红**
  （`>= MAX_LINES=400`）⇒ 拆出驱动器，这正是本仓库自己的规则，我自踩后修。
  ⓔ `tools/skew_reference.py::WEB_SCRIPTS` 补入 `"heatmap.js"`（单一真相）——
  修 `TypeError: S.HeatmapPanel is not a constructor`（缺它时驱动器直接崩）。
  ⓕ **验证全绿**（`venv/Scripts/python.exe`）：`run.py --check` **`RC=0`**（`[1]` 99 Py + 13 JS
  全合规，最长 399）；`check_web_syntax` **`RC=0`**（13 文件）；`check_web_contract` **`RC=0`**
  （59 条载荷路径）；`check_heatmap_topn_skew_zoom --selftest` **`RC=0`**（24 判据 + 守卫 2 用例
  + 5 变异全抓）；`check_period_aggregation --selftest` **`RC=0`**。随机 4000 组输入 ⇒
  **异常 0 组**；锚点 `t: 0.500000 → 0.500000`（不动）。
  ⓖ **证伪自己的假设一次**：原以为变异"`(0,1)` 改回 `[0,1]`"能抓住，数值分析显示
  **闭区间版本同样合法**（只是贴边非居中）⇒ 该变异本就抓不住，已换掉并在会话记录里留痕。
  ⓗ **工作区清理**：删掉一次性探针 `tmp/probe_topn_yzoom.js` / `tmp/probe_topn_render.js`
  （常驻回归已覆盖）；`console.log`/`debugger`/`TODO`/`FIXME` 于 `web/*.js` + 两个新 tools
  文件 **0 命中**。
  ⚠️ **未验证**：**未做浏览器取像素** ⇒ Top-3 黑边**实际视觉宽度**与滚轮缩放**手感**
  （`step=1.15`）待 KAI 盘中肉眼确认；"渲染流畅"**未做帧率实测**（只保证不整图重建）。
- Previous: 2026-09-15/period-file-split
- Previous handoff: notes/sessions/2026-09-15/period-file-split/handoff.md
- Previous status: **`tools/` 两个超限文件拆分完成 + 修掉 2 条失效变异锚点 —— 已提交推送
  `0d30943`；系统服务已启动并实盘验证** —— 2026-09-15 06:0x EDT，GTH 段。
  ① **超限事实**：`period_reference.py` **441**（改动前 398 ⇒ 上轮改超）/
  `check_period_aggregation.py` **416**，均 `> MAX_LINES=400` ⇒ `selfcheck.py [1]`
  **确会判红**（`check_file_sizes` 判据是 `>=`；该文件无 `__main__`，由统一入口调用）。
  ② **拆出** `tools/period_node.py`（**120 行**，node 驱动 / IO）⇒ `period_reference.py`
  **441 → 349**，`run_node` 以 **re-export** 保留 ⇒ 调用点零改动。
  ③ **拆出** `tools/period_selftest.py`（**90 行**，"证明对拍会红"）⇒
  `check_period_aggregation.py` **416 → 346**；判据由调用方 `evaluate` 回调注入 ⇒
  **不反向 import 检查器**，无循环依赖。
  ④ **顺带真缺陷**：`--selftest` 变异表 **2 条锚点早已失效** —— `sliceZones` / `alignSkew`
  已从 `period.js` 拆到 `period_align.js`，旧表却写死"锚点都在 period.js"⇒
  那两条**长期打印"变异点已失效"**。改为 **5 元组**带目标文件，每轮两个文件都重写。
  ⑤ **本次提交 15 文件 / +662 −210，已推送**：远端 `ls-remote` = 本地 `HEAD`
  = `0d30943`，工作区干净。⚠️ **该提交混合两部分** —— 上一会话未提交的
  "**成交量驱动逐格边框**"功能（`web/config.js::heatmap.volumeBorder` +
  `web/period*.js` 的 volumes 同步聚合/裁列/取列 + 4 文件注释）与本会话的 `tools/`
  拆分；`period.js`/`period_align.js` 两轮都动过 ⇒ 文件级无法拆，合并为一提交。
  推送首跑 `RC=128`（`Connection closed by 198.18.1.93 port 22`）是**瞬时断连**，
  非权限（`ssh -T git@github.com` = `Hi Skioleeya!`），重试即 `RC=0`。
  ⑥ **启动系统服务**（IB Gateway 4002 由 KAI 预启）：`run.py` 后台，日志
  `logs/run_console.log`；`05:58:10 流水线已就绪`，8060 `LISTENING`（PID 6572），
  页面 + 6 个前端资源全 **200**；恢复 492 桶 + 492 Skew 点。
  ⑦ **实盘验证**：`ws_probe` **`RC=0`**（24 档 × 1171→1172 桶在长 / 12,778 格 /
  Skew 498 点 / `25Δ=2.842` / `7563.25 < 7597.09 < 7620.88` Put-Call 定位正确）；
  `run.py --check` **`RC=0`** 且 **`[13]` 走真实联通路径**（`connected / mode=delayed`、
  订阅 80/92、24 档 × 1176 桶、Skew 502 点）。
  **成交量链路端到端确认**：帧含 `vol_bm`/`vol_i16`/`vol_filled`，`unpack(scale=1)`
  解码 **215 格非空且声明值 = 解码值**、min 19 / max 66 ⇒ 新边框数据源实盘有货。
  持久化在写：`data/sessions/20260915.db` 700,416 → **704,512 B**、桶数 505 → 506。
  ⚠️ **未验证**：**未做浏览器取像素** ⇒ 逐格边框**实际视觉宽度**与 `maxRatio=0.35`
  的观感待 KAI 盘中肉眼确认；服务为后台进程对（23000 / 6572），shell 结束后
  是否存活未验证。
- Previous: 2026-09-15/persistence-session-files
- Previous handoff: notes/sessions/2026-09-15/persistence-session-files/handoff.md
- Archive: notes/context/archive/handoff_2026-09.md
- Status: **已提交并推送（`HEAD = 53da940`，工作区干净）** ——
  持久化落点改为一交易日一文件 + 历史**归档不删**（三轮改动合并提交）。
  2026-09-15 01:0x–03:5x EDT，GTH 段。KAI 的目标："第一天就写第一天的数据，重启后
  接着写第一天的；第二天新开一份，第二天重启，继续写第二天的"。
  ① **落点**：`config/persistence.json` 的 `db_path` 改为 `db_dir: data/sessions` +
  `db_filename: {session_key}.db`（`session_key` = 当日到期日）。
  ② **拆分**：新增 `features/persistence_store.py`（文件与表）—— `features/persistence.py`
  改动前 **384 行 / 上限 400**，余 16 行放不下（拆后 310 行）。
  ③ **换文件**：`_batch_write` **逐条**按 `session_key` 切文件（跨日那一刻的批次里
  混着两个会话）；`SessionFileStore.close()` **必须先提交再关闭** —— SQLite 的
  `close()` 对未提交事务是**回滚**，实测会丢掉旧会话那一行。
  ④ **迁移**：旧库当前会话 88+88 行 → `data/sessions/20260915.db`（走 store 写）。
  旧库 `data/session.db` 当时未动；**2026-09-15 02:2x 已按 KAI 明令删除（无备份）**，见 ⑧。
  ⑤ **验证**：`run.py --check` `RC=0`；`check_persistence` **7/7**；新增
  `check_persistence_sessions` **4/4**；全量 **22** 个 `tools/check_*.py` ⇒ **21 `RC=0` /
  1 `RC=1`**（唯一红 `check_page_render`，**既有**）；`ws_probe` **25/25**；
  非空转两个变异各抓 2 条。重启日志 `持久化落点 data\sessions\20260915.db` +
  `恢复 88 个历史桶`；20 秒后旧库 mtime 停在 01:22:07（**已停写**）、新库在长（88→90）。
  ⑥ **收尾（01:4x）**：旧单库路径残留清扫 —— 存活代码/配置/README 对
  `session.db` / `db_path` **0 命中**；清掉 `heatmap_engine.py` docstring、`.gitignore`
  的 `data/` 创建者、README §5 模块边界；`RULES.md §6.1` 基线按实测重测（22 个检查 ⇒
  `venv` **20 RC=0 / 2 RC=1**、裸解释器 **18 / 4**）。⚠️ 复测时 `check_ws_compression`
  也是红的（70.7% < 80%，**状态依赖**）⇒ 当轮记的 21/1 不是永久事实。
  ⑦ **收尾（02:0x，KAI 裁定）**：**记忆文件改为纯路由器** —— 速查卡 A–V（23 条）自
  `.workbuddy-ai/memory/MEMORY.md` 迁出，新家 `notes/memory/QUICKREF.md`（T1 层，与
  `TROUBLESHOOTING.md` 按"静默错值 / 立刻报错"分工）。`MEMORY.md` **7850 → 1479 字符**，
  只留路由表 + 时间戳。同轮清掉两处重复：原 §1 全局摘要（与 `ARCHITECTURE.md §1/§2/§6`
  重复）、原 §3 当前脏态（与 `notes/context/*` 三处重复，改成指针）。
  存活文档对「速查卡 / MEMORY.md 速查卡」的引用 **0 命中**（含 `tools/skew_reference.py`
  的夹具注释）；`run.py --check` **`RC=0`**；22 个 `tools/check_*.py` 复测 **20 / 2**（同 01:4x）。
  ⑧ **收尾（02:2x，KAI 两条明令）**：
  ① `.playwright-cli/` 进 `.gitignore`（浏览器自动化产物，8 个 console 日志）。
  ② **保留策略首版定为"不留档、不备份"** —— ⚠️ **已被 03:1x 的 ⑩ 改写为"归档不删"。**
  当时新增 `SessionFileStore.prune_other_sessions()`，`AsyncPersistenceWriter.start()`
  打开本会话文件后调用它清掉 db_dir 内所有非当前会话的库文件，并把被删文件名**返回给
  调用方**（`features/` 整层不写日志，由 `app/pipeline.py` 记一行）。删除范围两道闸门：
  只在 `db_dir` 之内 glob + 只匹配 `db_filename` 模板派生的名字。回归
  `check_persistence_sessions` **4/4 → 6/6**；非空转 2 个变异各抓 1–2 条。
  ⚠️ **这一版把 KAI「不留档、不备份」的适用范围从旧单库 `data/session.db` 误扩到了
  全部逐日文件 —— 是我误读，见 ⑩。** 数量规律不变：跨日旧文件留到下次启动才处理
  ⇒ **未归档数 = 自上次启动以来的交易日数**（实测 `tmp/probe_rollover_residue.py`：
  不重启跨 5 个交易日 ⇒ 5 个文件 ≈ 9.4 MB；每天重启一次则最多 1 个 ≈ 2.35 MB）。
  未归档文件**永不会被读到**。
  ③ **`data/session.db` 已删**（1,064,960 B / 88+88 行，`data/` 在 `.gitignore` ⇒
  不可恢复、无备份）。`data/sessions/20260915.db` 未受影响。
  ⑨ **收尾（02:5x，KAI 追加明令「禁止新增速查卡」）**：知识库的增长模型从
  **O(错误条数)** 改为 **O(不变量条数)**。起因是 KAI 质问 *"以后有 1200 个错误，
  你也要写 1200 个检查表吗？"*。
  ⓐ **审计 23 条卡片**：**12 条有守卫**（B/C/D/H/J/K/O/P/Q/S/T/U）；**11 条无守卫**，
  其中 **A/E/L 是"能机械化但没写"的欠账**（`grep inverse tools/*.py` 0 命中 /
  `selfcheck_core` 只查 `market_data_type` 键在不在不查值 / `grep 'splitLine\|cellBorder'
  tools/*.py` 0 命中），**8 条是真永久**（F/G/I/K2/M/N/R/V）。
  ⓑ **硬规则**：`QUICKREF.md` 收录判据节标题改为「**本文件只减不增**」——允许降级、
  合并、删除，**不允许追加**。四条出路（**没有一条会增加条目数**）：① 能机械判定 ⇒
  写检查器、原条目**降为指针**（净减）；② 同类 ⇒ **并入**；③ 一次性 ⇒ 只进
  `notes/sessions/**`；④ 会立刻报错 ⇒ `TROUBLESHOOTING.md`。要新增 ⇒ **先问 KAI**。
  ⓒ **传播到 4 处**：`QUICKREF.md` / 用户级 `~/.workbuddy-ai/MEMORY.md`（路由 ②
  "归纳成 1 条" → "并入已有条目"）/ `open_tasks.md`（A/E/L 那条改为"**23 → 20，净减**"）/
  skill `spxw-live-verify/references/pitfalls.md`（声明"不是第二张速查卡表"）。
  ⓓ **顺手修 skill 计数漂移**：`pitfalls.md` 头部"15 条" + `SKILL.md` 三处"19 条"
  ⇒ 实际 **20**，四处统一。
  ⓔ **两个自踩的坑**（都是"写了规则 ≠ 规则生效"的实证）：**同一文件多处编辑并行提交
  ⇒ 只活最后一条**（踩了 `pitfalls.md §9` 自己记的规则）；**`grep -c '^| [A-Z]'` 数卡片
  会得 34 不是 23**（审计表也单字母开头）⇒ 正确数法已写进 `QUICKREF.md` 页脚。
  ⓕ 核对：`run.py --check` **`RC=0`**（本轮只动 `.md` 与仓库外 skill）。
  ⑩ **改写保留策略：删除 → 归档（03:1x，KAI 两条明令）** —— KAI 原话
  **"这就是历史数据，有用。"** 与 **"'不留档、不备份' 只针对旧单库 `data/session.db`"**。
  ⇒ 我 02:2x 那句「不留档、不备份」的适用范围**是我扩大错了**：`data/sessions/<到期日>.db`
  是逐交易日的 ΔIV / Skew **原始记录**，不是残留垃圾；而当时的 `unlink()` 实现**正在
  销毁它**。
  ⓐ **实现**：`prune_other_sessions()` → `archive_other_sessions()`，`unlink()` →
  `rename()` 到 `archive_dir`（`persistence.json` 新键，默认 `data/archive`）；`start()`
  返回 `(已归档, 未归档)`，`app/pipeline.py` **各记一行**（归档 INFO / 冲突 WARNING）。
  ⓑ **三道闸门 + 一道构造期校验**：只在 db_dir 内 glob / 只匹配 `db_filename` 模板 /
  归档目录**同名不覆盖**；`archive_dir` 落在 db_dir 之内 ⇒ **构造时抛错**（否则归档件
  下次启动又会被当成待归档项）。
  ⓒ **回归 6/6 → 7/7**；非空转 3 个变异（`tmp/probe_mutation_archive.py`：不归档抓 1 /
  glob 越界抓 3 / 同名覆盖抓 1），还原后全绿。
  ⓓ **实盘验证**：合成 `data/sessions/20990101.db` → 新代码重启 →
  `03:18:42 INFO pipeline 已归档 1 个历史会话文件到 data\archive（db_dir 只留当前会话）: 20990101.db`；
  `data/sessions/` 只剩 `20260915.db`、`data/archive/20990101.db`（20,480 B）在。
  ⓔ 配置项 50 → **51**（`selfcheck_core::REQUIRED_KEYS["persistence"]` 同步）；
  `features/persistence_store.py` 因新增内容一度 **429 行 > 400**，压回 **398 行**。
  ⓕ **本轮撞上外部故障两次**：03:18 重启时 IB Gateway 又掉（`ConnectionRefusedError 1225`，
  4002 无监听）；KAI 重启 Gateway 后 03:20 起来，`All data farms are connected`
  （usfarm.nj; hfarm; usfuture; apachmds; secdefhk），现价恢复跳动。
  终态：`run.py --check` **`RC=0`**；22 个 `tools/check_*.py` ⇒ **20 RC=0 / 2 RC=1**
  （`check_page_render` / `check_ws_compression`，两个既有红）。
  ⓖ **03:4x 复核（记录同步后重跑，非引用旧结论）**：`check_persistence_sessions` **7/7 `RC=0`**；
  `run.py --check` **`RC=0`**（`[13]` 热力图 24 档 × 880 桶 / Skew 303 点）；行数
  `persistence_store.py` **398** / `persistence.py` **329** / `pipeline.py` **381** /
  `check_persistence_sessions.py` **397**（全部 < 400）；`data/sessions/20260915.db` 430,080 B
  在长、`data/archive/20990101.db` 20,480 B 在；8060 `LISTENING`（PID 3900）。
  ⓗ **03:5x 已提交并推送**：`9ec4fb9` → **`53da940`**（31 文件 / +3210 −272），
  工作区**干净**（`git status --porcelain` 空），`ls-remote` 远端真值 = 本地 HEAD。
  三轮改动（identity / session-files / 归档）在同一批文件里交错 ⇒ **合并为一个提交**
  （文件级无法拆分，拆分会产生假历史）。推送过程两个坑已补进 skill `pitfalls.md §6`：
  **别从管道取 `git push` 的 RC**（`| tail; echo $?` 是 `tail` 的，实测假绿 `RC=0`）；
  **沙箱拦 `~/.ssh` ⇒ 必须前台 + 显式授权**（后台任务拿不到审批，必 `rc=128`）。
- Previous: 2026-09-15/persistence-session-identity
- Previous handoff: notes/sessions/2026-09-15/persistence-session-identity/handoff.md
- Previous status: **启动成功 + 跨会话持久化污染已结构性修复（改动未提交，`HEAD = 9ec4fb9`）** ——
  2026-09-15 00:27 EDT，GTH 段。① **启动**：IB Gateway 4002（KAI 于 00:27 前开）→
  `run.py` `00:27:58 流水线已就绪`；12/12 静态资源 200；`connected` / `last_tick_age_s 0.0` /
  80-92 订阅 / 24 档热力图。② **挖出缺陷**（`ws_probe` 26/27，唯一 FAIL =
  `25Δ Put 行权价低于现价 7626.51 < 7605.41`）：`data/session.db` 两表**都没有会话列**，
  `bucket_index` 是**日内坐标、每交易日复用** ⇒ 昨天 RTH 的行落进今天的键空间。
  三条后果：帧的 `skew.latest`（= `skew_series[-1]`）报出**昨天 14:26:48**；
  `skew.series` 混入 871 行昨天的点（label 按今天网格算 ⇒ 曲线画到未来）；
  热力图把昨天 RTH 的数据画在**今天 GTH 的时刻**上。⚠️ **顶栏读 `atm` 块（活值）⇒ 顶栏对、面板错**。
  ③ **修法**（KAI 选定结构性修复）：`session_key`（= 当日到期日）进主键
  `(session_key, bucket_index)`；`recover()`/`recover_skew()` 按会话过滤；
  **缺列的旧表整张丢弃并报出行数**（重启日志 `丢弃 1830 行`）；`enqueue` 空身份抛错。
  ④ **验证**：`run.py --check` `RC=0`；`check_persistence` **8/8**；
  `ws_probe` **25/25 全通过**（`7567.52 < 7603.93`，与按 cells 插值算出的 ≈7569 一致 ⇒
  delta 定位一直是对的）；截图对照假 0 带一并消失。非空转：摘掉会话过滤 ⇒
  跨会话用例报 `今日会话应只有 1 个桶，实际 3`。
  ⚠️ `notes/context/*` 与 `web/config.js` 仍含**另一会话未提交**的改动、
  `notes/sessions/2026-09-14/live-render-verify/` 仍未跟踪 —— 本轮**未替它背书**。
- Previous: 2026-09-14/live-render-verify
- Status: **实盘首次出图验证完成（纯只读，无源码改动）** —— 2026-09-14 09:45 EDT
  RTH 段，复用 KAI 常驻 `run.py`（**未强杀**）。四项全部 ✅：
  ① `health.mode = delayed` 是**由 `market_data_type=3` 推导**的值，非观测；
     独立探针（clientId=97）实测**期权与 SPX 指数 `marketDataType=1`**（任务书预期的
     "指数 = 3" 是过期预期），`modelGreeks` 与 bid/ask/last Greeks 并存且值不同。
  ② 订阅 **48/92**，`projected_subscriptions()` = 49。
  ③ `ws_probe` 全部通过：帧 18059→18068、**24 档** × 1624 桶、15,420 格；
     真 Chrome 截图 185,973 字节，顶栏 `connected`，热力图 + Skew 双面板出图。
  ④ `health.rate_limit` 四要素（45 / 1.0s）+ 两条非空转证伪
     （非默认 12/0.5s 驱动生效、回调确实挂在 `ib.client`；突发 200 条 ⇒
     `events` 0→1、`throttling` 翻真后复位、`throttled_total_s` 0.502→4.004）。
  ⇒ 同时闭合 open_tasks 两条：`[中] 实盘首次出图未验证`、
  `[中] 交易日 RTH 段实盘验证`（指数 09:30 后确实恢复实时、09:25 交班平滑、RTH 走指数直读）。
  ⚠️ 未停服务（任务书要求不得强杀常驻进程）；`run.py --check` 未重跑（无源码改动）。
- Previous: 2026-09-14/skew-iv-colors
- Previous handoff: notes/sessions/2026-09-14/skew-iv-colors/handoff.md
- Previous status: **Skew 三条 IV 曲线配色按 KAI 指定钉死（跨式黄 / Put 绿 / Call 红）；
  顺带修掉三个回归的 node 沙箱清单漂移 + 4 条变异锚点漂移；改动未提交** ——
  ① 问题（KAI 报"曲线标签与实际图例色彩混乱"）：三条 IV 曲线复用主序列的分段色
  （Put = `theme.hot` 红 / Call = `theme.cool` 蓝 / ATM = `theme.textFaint` 灰），
  而主序列 25Δ Skew 按正负也走 hot/cool ⇒ 四条线只有两种颜色，叠加图例里两个
  同名的 25Δ Skew，无法分辨哪条是 IV、哪条是 Skew。
  ② 修法：`web/config.js` 新增 `skew.colors`（唯一来源）；`web/skew.js` 三条 IV
  曲线改读它；`web/style.css` + `web/index.html` 顶栏读数同色（put/call 不再都用 cool）。
  ③ 新增常驻回归 `tools/check_skew_colors.py`（6 判据 + 3 变异，255 行）。
  ④ 顺带修既有缺陷：`web/` 拆文件后 node 沙箱清单没补 ⇒ `check_skew_viewport` /
  `check_skew_alignment` / `check_period_aggregation` 在**驱动阶段**就崩
  （`P.alignSkew` / `P.sliceZones is not a function`）；清单已收敛为
  `skew_reference.WEB_SCRIPTS` 单一真相。viewport 的 4 条变异锚点也修正到拆分后的
  文件，7 条变异全部抓住。
  ⑤ 验证：`run.py --check` RC=0；真浏览器取像素（真 Chrome + 真 ECharts）三条 IV 色
  全部命中，`--old` 覆盖回旧配色立刻 FAIL。详见会话根。
  ⚠️ **订正（2026-09-14 10:3x，会话 `3d38495` 之后实测）**：本行原写「`check_*.py`
  20 个 → 19 RC=0（余 1 为既有）」，**该数字系自报、未实跑，与事实不符**。
  实测（`venv/Scripts/python.exe`）当时为 **17 RC=0 / 3 RC=1** —— 多出的两个红是
  `check_persistence`（手写夹具缺 `heatmap_max_ffill_buckets`，自 `6828e3a` 起红）
  与 `check_page_render`。前者已修（夹具改为从真配置派生），当前基线
  **20 个 → 18 RC=0 / 2 RC=1**（红 = `check_page_render` / `check_ws_compression`）。
  另：**必须用 `venv/Scripts/python.exe`**，裸 `python` 会多出两个假红。
- Previous: 2026-09-14/webgl-to-echarts
- Previous handoff: notes/sessions/2026-09-14/webgl-to-echarts/handoff.md
- Previous status: **热力图渲染器由原生 WebGL 换成 ECharts；改动未提交** ——
  ① **根因**（KAI 报"绿色周围黑色色块"）：`gl_heatmap.js:157-165` 把调色板绑在 TEXTURE1，
  `:261-270` 首次 `update()` 未先 `activeTexture(TEXTURE0)` 就 `bindTexture(_dataTex)`
  ⇒ **数据纹理顶掉调色板** ⇒ `u_palette` 采到数据纹理中间行：有效格 `(R,255,0)` 绿、
  落在空格 `(0,0,0)` 黑。**"换任何色都不生效"由此解释。**
  （另查明 `web/config.js:28-34` 的 palette **本来就是**逐色抄自参考项目的 Plotly Turbo
  ⇒ 颜色配置一直是对的，坏的是渲染器没采样它。）
  ② **KAI 裁定换掉原生 WebGL**；库定为 **ECharts**（已内置且 Skew 在用 ⇒ 零新增依赖；
  `af2e2e4` 之前本就是 ECharts）。`web/heatmap.js` 整文件重写（266 行，公共接口不变 ⇒
  `app.js`/`app_render.js` 零改动，手写 overlay 全删）；`web/gl_heatmap.js` **删除**；
  `web/index.html` 去标签；`web/test_gl.html` → `web/test_heatmap.html`；`web/test_sync.html` 补 echarts；
  `web/config.js` 网格线注释改写为 ECharts/splitLine 语义。
  ③ **代价（实测、KAI 知情接受）**：ECharts 单次重绘 630 列 65.7ms / 1352 列 159.9ms /
  2370 列 188.1ms，旧 WebGL 0.6/1.0/1.3ms；节拍 2.5Hz ⇒ 宽档位吃 **40–47% 单核**。
  `progressive` 是负优化（2370 列 424ms）⇒ 恒设 0。
  ④ **验证**：`run.py --check` **`RC=0`**；`check_web_syntax` / `check_web_contract` `RC=0`；
  `check_page_render --budget 60000` 热力图/Skew/canvas≥2/现价全 ok；真实页面取色
  `nearBlackPixels: 0` / **516** 色桶 / 2 canvas；**非空转**：palette 改品红 ⇒ 色桶 553→37、绿色全消失，
  还原后 md5 逐字节回到 `eae7e64f694a2f15679be190b936e0f0`。
  ⑤ ⚠️ **事故**：执行 `git rm` / `git mv` 期间**整个 `web/` 目录从工作区消失**（成因未查明），
  `git checkout -- web/` 恢复；未提交的 `config.js` / `skew.js` 改动为**按记录重建**（非逐字节还原）。
  ⇒ **本仓库禁用 `git rm` / `git mv`，改用 `rm` / `mv` + `git add`。**
- Previous: 2026-09-14/heatmap-mirror-ffill-grid
- Previous handoff: notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/handoff.md
- Previous status: **热力图渲染三处修正已落地，且已重启进程、实测生效；改动未提交（21 M + 7 ??）** ——
  ① **上下镜像**（KAI 未报，排查中挖出）：`gl_heatmap.js::update()` 里 `tr = rows-1-r`
  把行序反了两次 ⇒ 屏幕第 i 行 = 帧第 rows-1-i 行。已改为按帧行序直写 texture + 契约注释。
  ② **20:15 起满宽假 0 带**（KAI 报）：`persistence.py::recover()` 读全部桶 → `load_snapshot()`
  → `_row_values()` **无上限**前向填充 ⇒ 孤桶被一路沿用。新增
  `config/serialization.json::heatmap_max_ffill_buckets`(20 = 10 分钟)，超限留白；
  常驻回归 `check_reconnect_gap.py::case_long_gap_is_blanked` + `--selftest` 两处注入，实测两例变红。
  ③ **细档位无纵线**（KAI 报）：1 分档 630 列 ⇒ 格宽 2.40px，被上一轮 `>=3.0` 双侧阈值整方向跳过。
  改为单侧**自适应步长** `stride = ceil(u_borderMinPx / cellPx)`（线仍落真实格边界），
  新增 `web/config.js::heatmap.cellBorderMinPx = 5`（当时语义为**物理像素**；换 ECharts 后改为 **CSS px**）。
  实测 1 分档中位线距 5.0px / 653 条；变异置 0 ⇒ 塌成密纹。
  ④ **重启进程**（KAI 指令，2026-09-14 07:19）—— `run.py` 是父子两进程、只认 Ctrl-C
  ⇒ 硬杀；停后 `integrity_check=ok`、334 行不变；重启 `07:19:59 流水线已就绪`。
  **上限生效实测**：row 19（7575）由 `first=1 / nonnull=1308` → `[(1,20),(449,554),(706,726),(1065,1331)]`
  ⇒ 假 0 带 **1308 列 → 20 列**。
  `run.py --check` **`RC=0`**（13/13）；`check_reconnect_gap` 正常 + `--selftest` 均 `RC=0`。
  ⚠️ **残留**：`recover()` 未过滤 ⇒ bucket 0 本身仍在（带未归零，只是 ≤10 分钟）。
  详见会话根。
- Previous: 2026-09-14/b2b-spot-synthesis
- Previous handoff: notes/sessions/2026-09-14/b2b-spot-synthesis/handoff.md
- Previous status: **实现完成，未提交（14 M + 7 ??）** —— KAI 5 条拍板全部落地：新增 `config/spot.json`、
  `acquisition/spot_synthesis.py`（B2b 反解 `ĉ` + 两层闸门）、`acquisition/spot_source.py`
  （按区段选源）、`core/session_grid.py`（从 `clock.py` 拆出几何以守住 <400 行）。
  09:25 交班切回指数、窗口重建由既有 `WindowFollower` 自动完成（锚跳 8.15 档 > trigger 3 档），
  未加特殊代码。`--check` 基线回绿 **RC=0**（修复前 RC=1 / 2582 项，venv 改按 `pyvenv.cfg` 识别）。
  端到端冒烟：实盘现货 = 合成值 **7620.26**，同期 IBKR 指数冻结在 7656.98 ⇒ 合成确实生效。
  6 个既有失败回归经 HEAD worktree 对照确认非本轮引入。详见会话根。
- Previous: 2026-09-14/gth-spot-basis-research
- Previous handoff: notes/sessions/2026-09-14/gth-spot-basis-research/handoff.md
- Previous status: **只读调研，未改代码** —— GTH 现货基准业界做法调研 + B2/B3 判别实验，
  输出 KAI 拍板依据（主口径 B2b）。当时遗留的 `--check` RC=1 已在本轮修复。
- Previous: 2026-09-13/web-js-gate-and-probe-governance
- Previous handoff: notes/sessions/2026-09-13/web-js-gate-and-probe-governance/handoff.md
- Previous status: **`web/*.js` 已拆分完成 + `[1]`–`[13]` 全绿 + Skew 三项修复落成常驻回归 + 探针落点治理 + 时钟/联通并入常驻**：
  ①`app.js`/`skew.js`/`period.js` 三文件拆分为 9 个模块，全部 < 400 行；
  `iter_web_scripts()` 按目录枚举，`[1]` 扫 **98** 个文件（84 `.py` + 14 `web/*.js`）
  全部合规；②新建 `tools/check_skew_viewport.py`（394 行，`[G1]`–`[G4]`
  共 21 项判据 + 6 条变异），把上一轮只在一次性探针里的三项修复固化成常驻回归；
  ③删除死代码 `SkewPanel.prototype.stats()`（`skew.js` 540 → 536 → 拆后 239）；
  ④临时探针落点定为 **`<项目根>/tmp/`**，在 `.gitignore` + `NON_SOURCE_DIRS` 两处登记。
  ⑤**自查中抓到一个真缺陷并修掉**：`check_skew_viewport.py` 的"判据集合不完整"守卫
  期望集合由 `GROUPS` **自推** ⇒ 删掉一组后该组失败被**静默吞掉、`RC` 仍 0**
  （实测删 `[G4]` ⇒ 3 条失败被吞）；抽出 `tools/group_guard.py`（期望前缀 = 独立常量
  + 三条都查 + `guard_cases` 自证）。同族缺口已修：`check_period_aggregation` /
  `check_skew_alignment` 已接入 `group_guard.py`，`--selftest` 各自抓全。
  ⑥**`check_clock_protocol.py` 并入 `--check` 常驻 `[12]`**（KAI 批准）——
  验证时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
  ⑦**联通与限速并入 `--check` 常驻 `[13]`**（KAI 批准）——
  `selfcheck_connectivity.py`：8060 有服务则连 WS 抓帧校验；无服务跳过（warning）。
  终态：`run.py --check` **`RC=0`**（13 项全通过、关键配置项 **40**）；
  全量 **18** 个工具 **14 `RC=0`** / 4 `RC=1`（与基线一致：缺 `ib_async`/`aiohttp`/无 8060/非本项目页面）；
  `check_skew_viewport --selftest` **6 条变异 + 守卫 2 条用例全抓**；
  `check_skew_alignment --selftest` 4 条变异全抓（沙箱抽出未破坏既有回归）。
  ⚠️ **本会话改动未提交**；真实链路渲染仍未验证（周日 fail-closed），
  由 KAI 手动在 GTH 时段验收。
- Previous: 2026-09-13/skew-zoom-yscale（notes/sessions/2026-09-13/skew-zoom-yscale/handoff.md）
- Previous: 2026-09-13/recheck-keyorder-memory（notes/sessions/2026-09-13/recheck-keyorder-memory/handoff.md）
- Previous: 2026-09-13/skew-period-consistency（notes/sessions/2026-09-13/skew-period-consistency/handoff.md）
- Previous: 2026-09-13/frame-strike-order-descending（notes/sessions/2026-09-13/frame-strike-order-descending/handoff.md）
- Previous: 2026-09-13/cold-data-strike-order（notes/sessions/2026-09-13/cold-data-strike-order/handoff.md）
- Previous: 2026-09-13/live-verify-and-release（notes/sessions/2026-09-13/live-verify-and-release/handoff.md）
- Previous: 2026-09-13/notes-dedup-tiering（notes/sessions/2026-09-13/notes-dedup-tiering/handoff.md）
- Previous: 2026-09-13/simulator-hard-cut（notes/sessions/2026-09-13/simulator-hard-cut/handoff.md）
- Previous: 2026-09-11/model-greeks-landing-verified（notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md）
- Previous: 2026-09-11/record-reconciliation（notes/sessions/2026-09-11/record-reconciliation/handoff.md）
- Previous: 2026-09-11/iv-heatmap-turbo-palette（notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md）
- Previous: 2026-09-11/ibkr-rate-limit-audit（notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md）
