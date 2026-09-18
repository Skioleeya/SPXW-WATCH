# Handoff Index

- **提交状态**：`ab853d3`（五轮交互改动合并提交，19 文件 / +2151 −346）→
  `21293a1`（`docs(notes)`）→ `748cd56`（`fix(transport)` 后端僵尸修复）
  → **本轮** `fix(web)` 前端自愈 + `docs(notes)`。
  ⚠️ **HEAD 以 `git log` 为准，本文件不写死**（写死就会被下一条记录提交立刻变成假记录）。
  ⚠️ **提交 ≠ KAI 逐轮验收** —— 各轮证据仍在各自的 `handoff.md`。

## 最新：2026-09-18 / zombie-trigger-rebuild（完成，**触发条件已重建**）

- **会话交接**：`notes/sessions/2026-09-18/zombie-trigger-rebuild/handoff.md`
  （"为什么这么造"在 `project_state.md`；开工基线在 `startup.md`）
- **一句话**：把页面主线程**故意卡住 ≥13s**，后端的发送协程就会超时死掉、而 socket
  随后恢复正常 ⇒ **真僵尸造出来了**，形状与 2026-09-17 生产事故逐条同形。
- **触发条件（可复现）**：真 headless Chrome + 真页面 + 真后端代码（自带 `:8063`），
  CDP `Runtime.evaluate: while (Date.now() - t0 < N) {}`。卡住期间浏览器有界缓冲先吞
  **28 帧 ≈ 2.24 MB**（三次独立运行完全一致 ⇒ 是缓冲**容量**，推送 400ms 下 ≈11.5s 填满），
  填满后 `send_str` 卡在 `_drain()` ⇒ `send_timeout_s = 1.0` 到点 ⇒ `_sender` 退出
  （实测 t≈12.5s）；卡住结束、socket 恢复也**救不回来**（发送协程已经没了）⇒
  队列（容量 1）有人丢没人收 ⇒ **0 帧送达**。
- ⚠️ **边界已扫（8/10/12/13/14/15s）—— 判据不是"卡多久"，而是"冻结起点 + `send_timeout_s`
  是否落在卡住窗内"**：8s/10s 冻结 0.0s（缓冲还没满）；**12s 冻结 0.5s < 1.0s ⇒
  后端挺住、无僵尸**；**13s 冻结 9.0s ⇒ 协程死、僵尸 ≥80s**；14s/15s 冻结 10.5s/11.0s。
  ⇒ 可用下限 ≈ 11.5s + 1.0s；**稳的做法是卡 15s**（留 3.5s 余量）。
- ⚠️ **推送速率对照（可证伪预测，命中）⇒ 容量按字节算**：`old off 9 200` 冻结于
  **t=5.5s**、吞 **+26 帧 ≈ 2083 KB**（400ms 那档是 t=11.5s / 2243 KB）⇒
  填满时间比值 **2.09 ≈ 400/200**、字节几乎不变；`old off 15 800` **未填满、协程未退出、
  造不出僵尸**（填满要 ≈23s）⇒ 下限随推送速率走。⚠️ 200ms 那档被 `maxFps: 5` 混淆，
  只用于证明"容量按字节算"，不用于定边界。
- ⚠️ **指标语义已写清（我读错过一次）**：`sent` 在协程死后永不再动 ⇒ 探针那个
  「最长冻结」是"冻结起点 → 采样窗结束"，**不是"被堵了这么久"**；真实量是
  冻结起点（≈11.5s）与协程退出（= 冻结起点 + `send_timeout_s`，实测间隔 1.0~1.5s）。
  探针已单独打印这两值，且 `best < 3` 时不再报"冻结起点"。
- **非空转 A/B（同一探针只翻一个变量；四臂全在最终字节上重跑，均 RC=0，各 8/8）**：

  | # | 后端 | 前端 | 卡住 | 心跳 | 结果 |
  |---|---|---|---|---|---|
  | 1 | `old` | `off` | 15s | 20s | 僵尸 **≥80s**；`forces=0`；停在「数据中断 79s」，**永不恢复** |
  | 2 | `old` | `on` | 15s | 20s | 僵尸活到 **45s** ⇒ 前端 `forceReconnect` 清掉 ⇒ 帧恢复 |
  | 3 | `head` | `on` | 15s | 20s | **僵尸根本没形成**（`clients` 归零于 t=13.0s）；页面 ~8s 自愈，`forces=0` |
  | 4 | `old` | `on` | 20s | **86400s**（对照） | 僵尸 **50s**，只有前端能清掉 |

  **臂 1 ↔ 臂 2 就是前端修复的非空转证明**（`reconnectOnStale` 一个开关 ⇒ 判定相反）。
  **臂 1 的僵尸形态**：`sent` 冻结 32、`dropped` 27 → 224（观测 80s）、`clients=1`
  且 `sender_done=[True]`。**臂 3 的新后端自愈比看门狗快一个数量级**（13s vs 45s）。
- ⚠️ **本轮最重要的发现：心跳是「半张网」，不是兜底。** `old on 20` **首次**跑时僵尸在
  **~29s** 被 aiohttp 清掉（= 连接建立 + 心跳 20s + pong 期限 10s，代码路径
  `_send_heartbeat` → `_pong_not_received` → `feed_data(WSMsgType.ERROR)` →
  旧代码 `async for` 的 `break`），**但同一配置重跑没复现**（僵尸活到 45s），
  心跳拉长到 86400s 则僵尸必然活到前端动手 ⇒ **竞态，不能依赖**。
  已写进 `transport/ws_broadcaster.py` 模块 docstring（**只加文档，无行为改动**）。
- **改了什么**：`transport/ws_broadcaster.py`（333 → **352 行**，**纯文档**：
  新增「心跳**不是**僵尸的安全网」一节，`git diff` = 20 insertions / 1 deletion，全在
  docstring 内）；`tmp/probe_zombie_browser.py`（新建 519 → **566 行**，gitignored；
  +47 行全是补扫时改的**字符串/注释/一行诊断输出**，判据逻辑与阈值一字未动）。
  **未改**任何 `web/*.js`、任何配置、`features/`、`serialization/`。
- **验证**：四臂 **4×8/8 RC=0**；补扫 `old off {8,10,12,13,14,15} 400` ⇒
  **8/10/12s 无僵尸（RC=1，属预期）、13/14/15s 僵尸形成（8/8 RC=0）**；
  推送速率对照 `old off 9 200`（8/8 RC=0）与 `old off 15 800`（RC=1）；
  最终字节上复跑 `old off 15 400`（8/8 RC=0）、`12 400`（RC=1）、`15 800`（RC=1）；
  `run.py --check` **16/16 RC=0**；`py_compile` ok。
  真后端侧 **N/A:开工时 `:8060`/`:4002` 全 closed 且休市，按纪律不起服务**。
- ⚠️ **仍未在 KAI 真实浏览器 + 盘中背压下验证**；**帧尺寸方向未测**（容量 2.24 MB
  只在 400ms/200ms 两档、同一帧尺寸下一致）；~29s 心跳清理路径只有单次观测；
  探针留 `tmp/` **无回归保护**。
- ⚠️ **KAI 侧仍有两件事**：① 重启后端让 `748cd56` + 本轮 docstring 生效；
  ② 刷新页面（旧标签页仍连着旧连接）。

## 上一会话：2026-09-17 / frontend-stale-reconnect（完成，**缺陷②前端自愈**）

- **会话交接**：`notes/sessions/2026-09-17/frontend-stale-reconnect/handoff.md`
  （"为什么这么改"在 `project_state.md`）
- **一句话**：页面以前只会把状态文字写成「数据中断 Ns」，socket 一直开着、
  `onclose` 永不触发 ⇒ **永不自愈，只能人工刷新**；现在超过 `staleErrorMs`（45s）
  没有成功渲染过的帧、且连接自称还是 `open`，就**主动把这条连接换掉**。
- **改了什么**：`web/app.js`（217 → 243 行）`watchdog()` 改判据 + `state.conn` 记连接自称态；
  `web/ws_client.js`（178 → 213 行）新增 `forceReconnect()` + `stats.forces`；
  `web/config.js`（327 → 334 行）新增 `render.reconnectOnStale`（默认 `true`）。
- ⚠️ **两个关键设计点**：① `forceReconnect()` **先摘掉四个回调再 `close()`** ——
  否则"等 `onclose`"与"已开的新连接"并存 ⇒ 每 45s 泄漏一条连接；
  ② 计时基准加兜底 `lastFrameAt || connectedAt` —— 老代码在"连上了却一帧都没有"时
  **整段跳过**（本项目最怕的静默形状）。
- **验证（非空转）**：`tmp/probe_stale_reconnect.py` 真 headless Chrome + 产品自己的
  `WsBroadcaster`/`StaticHandler`（只停推流、不断连接 = 事故原形），同一份代码只翻
  `reconnectOnStale` ⇒ **A 臂**（旧行为）`forces=0`、恢复推流后帧**在原来那条连接上**
  就回来了（证明连接本来还能用，页面只是不知道要重连）；**B 臂** `forces=1`、
  服务端连接数 1→2、恢复后帧到达 ⇒ **6/6 PASS RC=0**。
  `tmp/probe_live_page.py 100` 对**真后端**采样 100s ⇒ **6/6 PASS RC=0**
  （169 帧单调涨 · `forces` 恒 0 · 从未误报「数据中断」）。
  `run.py --check` **16/16** · `node --check` 3/3。
- ⚠️ **未在 KAI 真实浏览器 + 盘中背压下验证**；最坏自愈延迟 = 45s；
  触发条件（JS 主线程被占住）仍未重建。
- ⚠️ **后端侧修复（`748cd56`）仍未生效** —— 需重启后端，KAI 决定自己重启。
- **补记（14:1x）**：复核时发现上一轮**我自己引入**的缺陷 —— 两个不同故障
  （传输 / 渲染）塞进了同一个信号，且计时基准用 `||` 让新连接继承老时间戳。
  **实测后果比预想重**：注入"帧在来但页面不画"后，旧写法 50s 内 `forces=5`
  （**≈每秒一条连接的重连风暴**），新写法 `forces=0` + 报出「渲染停滞 Ns」。
  改成两个活体信号（`rxAge` 传输 / `drawAge` 渲染）分开驱动；
  **非空转 A/B：旧 RC=1 7/9 / 新 RC=0 9/9**。`web/app.js` 243 → **265 行**。
  顺带**证伪**"解码抛错会冻结时间戳"（`matrix_codec.decode()` 无 throw 路径）。

## 上一会话：2026-09-17 / frontend-data-outage（诊断完成 → 后端①已修）

- **会话交接**：`notes/sessions/2026-09-17/frontend-data-outage/handoff.md`
- **一句话**：前端"数据中断"**两处根因** —— ① 后端 WS 客户端变僵尸
  （`_sender` 死掉但没人注销 ⇒ 连接留着、100% 丢帧、零日志，实测挂了 4h11m）；
  ② 前端看门狗只报不改（见上一节）。
- ⚠️ **原修复设想被实测证伪**：想用 `ws.close()` 顶醒读循环 —— 对端不读时
  `close()` 卡在 drain、`transport.close()` 也冲不出缓冲 ⇒ 读循环永不醒
  （`ws.closed=True` / `transport.is_closing()=True` / `ws._waiting=True` 三者同时成立）。
  **改成**：`handle()` 用 `asyncio.wait({sender, reader}, FIRST_COMPLETED)` 赛跑，
  谁先结束都立刻注销。

## 上一会话：2026-09-17 / commit-and-push（完成，**已提交 `21293a1`**）

- **会话交接**：`notes/sessions/2026-09-17/commit-and-push/handoff.md`
- **一句话**：把叠在同一工作区的**五轮改动**提交并推送远端（`ab853d3` 代码 +
  `21293a1` 记录），工作区转干净；**顺带查出并修掉**一个本地引用存储缺陷 ——
  远端跟踪引用 `origin/main` 被陈旧 `packed-refs` 钉在 `6828e3a`，
  导致 `git status` 长期谎报 `[ahead 23]`（`ls-remote` 与 `HEAD` 明明一致）。
- **修复手段**：`git pack-refs --all`（标准命令，非手工改 `.git`）。
- ⚠️ **根因未定论且会复现**：git 建不了 `.git/refs/` 下的二级子目录（排除权限与 junction）；
  **本环境每次 push/fetch 都会让跟踪引用陈旧**，`pack-refs` 只是把当前值改对，不是根治。

## 更早：2026-09-17 / heatmap-auto-roll（完成，**已提交 `ab853d3`**）

- **会话交接**：`notes/sessions/2026-09-17/heatmap-auto-roll/handoff.md`
- **一句话**：热力图缩出横轴窗口后，窗口右缘**自动跟着最新列走**（不再越看越旧）；
  往历史里拖 ⇒ 停滚；面板头「回到最新」按钮把右缘拉回最新列并恢复跟随，
  **保住当前缩放跨度**（与「复位」分工：复位 = 丢掉缩放回全宽）。
- **KAI 要的三个量**：**触发**三条同时成立（`heatmap.xRoll.enabled` ∧ 有窗口 ∧
  处于跟随态；**全宽不需要滚**）· **方向**只有时间正方向（永不自动往回走）·
  **速度**数据驱动不插值（每帧把右缘移到 `cols-1-lagCols`，即"前进量 = 该帧新增列数"，
  `lagCols` 是唯一调节量，默认 0）。**不设定时速度** —— 那是插值动画，
  一次 `setOption` p50 27.4ms，插到 60fps 做不到。
- **新增 `web/heatmap_roll.js`(159)**；改 `heatmap.js` / `app_render.js` / `app.js` /
  `config.js` / `index.html` / `style.css`。
- ⚠️ **最关键的设计点**：**「跟随」态必须显式存一个布尔位，不能现算** ——
  列一追加，任何窗口的右缘都不再贴最新列 ⇒ "用户往回拖了 5 列"与"过了 5 列"无法区分。
- ⚠️ **三个真教训**：① `enabled=false` 时按钮会亮着却点了没用（静默无操作）⇒
  新增 `snap()`，**用户指令不受自动化开关管**；② **自动滚动改变了"拖动方向"的含义**
  —— 跟随态下右缘就在最新列，**向左拖被 `clampCols` 原地夹住**（正确行为，不是缺陷），
  要翻历史得**向右拖** ⇒ 三个老 pan 探针据此改向；③ **契约检查器 id 覆盖有缺口（已补）**：
  `_ID_CALL` 原只认 `el/setText/setClass` ⇒ `bindButton("…")` 与 `ViewChips.*("…")`
  的 id 不在覆盖内（打错字就静默失效），已补两分支（引用 20 → 27）并把 `--selftest`
  扩成三条取法各注入一个假 id。
- **验证**：`run.py --check` **16/16**；契约离线**与**在线 + `--selftest` 全通过；
  **非空转**：同一份代码只翻一处配置 ⇒ prod `44/0` · noroll `39/0`（均 RC=0），
  关键判定相反（窗口前进 Δto=Δcols=1 vs 原地不动 dTo=0）。
  回归：feedback `49/0` · pan_drag on/off 均 PASS · pan_guards / pan_reset PASS ·
  skew_drag `26/0`。
- ⚠️ **残留**：**`web/heatmap.js` 397 行（上限 400，只剩 3 行）** —— 下次动它几乎
  必然要先拆分（缝：左键拖拽手势整块下沉 `heatmap_pan.js`）；`web/style.css` 395 行
  同样贴上限。`lagCols > 0` 只有单元断言覆盖。探针在 `tmp/` **无回归保护**。
- ⚠️ **本会话未提交任何东西**；**该会话结束时**工作区**五轮改动叠在一起**（本轮 +
  `interaction-feedback-5fix` + `skew-drag-interaction` + `heatmap-pan-drag` +
  `skew-dual-axis-zoom`）。

## 上一会话：2026-09-17 / interaction-feedback-5fix（完成，**已提交 `ab853d3`**）

- **会话交接**：`notes/sessions/2026-09-17/interaction-feedback-5fix/handoff.md`
- **一句话**：把 KAI 从交互诊断"大白话版"里点名的 **2 / 4 / 5 / 6 / 7** 五项补上 ——
  全宽横拖弹瞬时徽标、Skew 锁定侧纵轴变色 + 锁定徽标、两图复位按钮 + `Esc`/`R`、
  Skew 四手势区游标语义 + 轴区高亮框、热力图十字线 + 命中格描边 + 提示框跨重建存活。
- **对照**：2→A2 · 4→B2 · 5→C1/C4 · 6→C2/D1 · 7→D2/D3。
- **新增 3 个前端文件**：`web/heatmap_hover.js`(185) · `web/skew_regions.js`(155)
  · `web/view_chips.js`(85)；另改 9 个 `web/` 文件。**只改交互层**，后端未动。
- ⚠️ **本轮确立的通用不变量（最重要）**：**凡必须在帧间持续存在的反馈，都不能建在
  ECharts 内部状态上** —— 每 ≤400ms 一次 `setOption(opt, true)`（notMerge）实测摧毁
  悬停（指针静止也在 **+450ms** 消失）、原生 `axisPointer`（三种挂法 × 5 变体
  **一次都没画出来**）、自带 `moveOnMouseMove` 拖拽（8 段只有**前 3 段**生效）
  ⇒ 常驻反馈一律走 **DOM 覆盖层**；重建后按**像素**补
  `dispatchAction({type:"showTip", x, y})`（**不能用 dataIndex**，列每帧在追加）。
- **验证**：`run.py --check` **16/16**（**最终字节上重跑**）；`check_web_contract`
  离线**与**在线均通过；**非空转**：同一份代码只翻一处配置 ⇒ prod `49/0`（RC=0）·
  nofb `43/0` · nohover `41/0` · nohint `48/0`（**断言数故意不同** ⇒ 判定相反）。
- ⚠️ **差点把假绿当非空转证据**：探针模式原本只读环境变量，按位置参数传会
  **静默退回 prod** ⇒ 已加守卫（未知模式抛错，实测 `nofbb` 会抛）。
- ⚠️ **残留**：**A1 热力图纵轴仍不可交互**（诊断里最大的功能缺口，本轮**没做**）；
  触摸未接；三个探针在 `tmp/` **无回归保护**（按 KAI 明令不建常驻检查器）；
  `web/style.css` 与 `web/skew_zoom.js` 都到 **394 行**（上限 400）。
- ⚠️ **本会话未提交任何东西**；**该会话结束时**工作区**四轮改动叠在一起**
  （本轮 + `skew-drag-interaction` + `heatmap-pan-drag` + `skew-dual-axis-zoom`）。

## 上一会话：2026-09-17 / skew-drag-interaction（完成，**已提交 `ab853d3`**）

- **会话交接**：`notes/sessions/2026-09-17/skew-drag-interaction/handoff.md`
- **一句话**：Skew 图删滚轮，改为四种按住拖动（轴区缩放 / 网格平移 / 底部轴区缩时间窗），
  双击复位三条轴。

- **会话交接**：`notes/sessions/2026-09-17/skew-drag-interaction/handoff.md`
- **一句话**：Skew 图**删掉滚轮缩放**，改为四种按住拖动 —— 左 / 右 Y 轴区上下拖 =
  **只缩那一侧**纵轴；底部 X 轴区左右拖 = 缩 / 放时间窗；网格内按住拖 = 自由平移
  （纵向两条轴一起移、横向挪时间窗）；双击复位三条轴。
- **互不冲突怎么保证**：手势归属在**按下那一刻**按位置定死（纯函数
  `SKEW.regionOf()`，四区互不重叠、有探针断言）；`skew.zoom.enabled` 与
  `skew.pan.enabled` **两个开关彼此独立** —— 这就是"互不冲突"的机械判据。
- **改动**：`web/skew_zoom.js` **重写（399 行）**；纯函数与配置访问器下沉
  `skew_helpers.js`（226 → 348）；`skew_option.js` 新增 `buildDataZoom()`（自带手势全关）；
  `skew.js` 290 → 310（`_yRange(view)` 收可见窗口、新增 `_view()` / `resetZoom()`）；
  `config.js` 252 → 270；`index.html` 提示改写；`app_render.js` 增报时间窗；
  `app_periods.js` / `app_sessions.js` 切周期 / 换时段时显式复位。
- **验证**：`run.py --check` **16/16**；`check_web_contract` 离线 + 在线全通过；
  **非空转**：同一份代码只翻一个开关 ⇒ prod `PASS 26/0`、`nozoom` `24/0`、`nopan` `25/0`
  （均 `RC=0`）。三次都先断言"开关真的翻到位了"，否则"零变化"可能是配置没替换上。
- ⚠️ **本轮修掉两条自己引入的缺陷**：① `skew.js::_count` 被赋成窗口列数 ⇒ `_cols`
  **逐帧自我折叠**（实测 654 列折成 4 列）；② `view()` 越界一律复位太破坏性 ⇒ 改先夹后复位。
- ⚠️ **已证伪假设**："`_cols` 帧间抖动"是**错误归因**，那个 555 就是缺陷 ① 的产物
  （基线采样 20s / 50ms 只看到 `638 → 639`）。注释已改正。
- ⚠️ **残留**：探针留 `tmp/` 无回归保护；**`skew_zoom.js` 399 行，距上限只剩 1 行**；
  未做像素级复核、未用真实物理鼠标验证、触屏未接。
- 📄 **同会话另产出**：`notes/analysis/2026-09-17-main-chart-interaction-audit.md`
  （主流主图交互逻辑分析 + 本项目两主图交互缺陷诊断；**新建 `notes/analysis/` 目录，归属未定**）。
- ⚠️ **本会话未提交任何东西**；**该会话结束时**工作区**三轮改动叠在一起**
  （本轮 + `heatmap-pan-drag` + `skew-dual-axis-zoom`）。

## 更早：2026-09-17 / heatmap-pan-drag（完成，**已提交 `ab853d3`**）

- **会话交接**：`notes/sessions/2026-09-17/heatmap-pan-drag/handoff.md`
- **一句话**：热力图**左键在网格内按住左右拖拽 = 平移横轴窗口**；与既有滚轮缩放
  共用同一个窗口状态 `_xWin`，双击仍复位。新增配置 `heatmap.xZoom.panOnDrag`
  与 `panThrottleMs: 100`；`web/heatmap.js` 250 → 342 行。
- **为什么不是一行开关**：ECharts 自带的 `moveOnMouseMove` 平移**实测不可用** ——
  它把"正在拖"存在自己的 `RoamController` 里，而本面板每 400ms `notMerge` 重建
  整份 option ⇒ 控制器连同状态一起重建。实测 8 段拖拽只有前 3 段生效，
  停点正好落在一次 `setOption` 上。⇒ 改由面板自己做（绑 `chart.getZr()`，
  与 `skew_zoom.js` 同一套判据）。
- **验证**：`run.py --check` **16/16 `RC=0`**；`check_web_contract` 离线 + 在线
  均 `RC=0`；`tmp/_dom_check.js` **PASS 15 / FAIL 0**；
  **非空转**：同一份代码只翻 `panOnDrag` 一个开关 ⇒ 生产 8 段位移 /
  关掉 **零位移**（两次都 `RC=0`）；边界 8/8、拖拽中途复位 6/6。
- ⚠️ **残留**：三个探针留 `tmp/` **无回归保护**；未做像素级复核、未用真实物理鼠标
  验证、触屏未接；全宽时拖拽是空操作（设计如此，面板头已加提示）。
- ⚠️ **本会话未提交任何东西**；**该会话结束时**工作区仍含**上一会话**（`skew-dual-axis-zoom`）
  的未提交改动与未跟踪目录，本轮未替它背书。

## 更早：2026-09-17 / skew-dual-axis-zoom（完成，**已提交 `ab853d3`**）

- **会话交接**：`notes/sessions/2026-09-17/skew-dual-axis-zoom/handoff.md`
- **一句话**：Skew 图左轴 25Δ Skew 与右轴 IV **同一格滚轮一起缩**，X 轴时间范围不动；
  双击复位两者。
- **顺带查实（重要）**：2026-09-15 那版"绑在容器上"的纵轴滚轮缩放**从未执行过** ——
  zrender 在容器内部另建 viewport root 并 `stopPropagation()`，
  实测计数 `zr=1 / 容器=0 / document=0`。旧检查器只调纯函数
  （`grep -rn "wheel" tools/*.py` **0 命中**）⇒ 死绑定一路全绿。
- **改动**：新增 `web/skew_zoom.js`（347 行，交互与锁定态的唯一出口）；
  `skew.js` 378→321；`skew_helpers.js` 新增纯函数 `zoomWindow()`、
  `zoomRange()` 的上下限改显式参数、**删掉 `FALLBACK_YCFG`**（配置的第二份真相）；
  `skew_option.js` 的 `dataZoom.zoomOnMouseWheel` `true`→**`false`**（一个手势一个主人）；
  `config.js::skew.yZoom` → `skew.zoom`（+`minCols`）；面板头加一行手势提示；
  读数同时报两条轴的锁定区间。
- **状态**：`run.py --check` **16/16 RC=0**；`node --check web/*.js` 全过；
  真机探针 `tmp/_probe_skew_yzoom.js` **PASS 19 / FAIL 0**（真机 + 真帧）；
  非空转 **4 处变异全部 `RC=1`**、4/4 逐字节还原。
- ⚠️ **残留**：两条轴共用一组 `minSpan/maxSpan` ⇒ 下限会先后触底（左轴先夹住）；
  探针留在 `tmp/` **无回归保护**；**未做浏览器取像素**、**未在盘中 RTH 复验**。

## 上一会话：2026-09-17 / heatmap-two-window（完成，**已提交 `130acdc` 并推送远端**）

- **会话交接**：`notes/sessions/2026-09-17/heatmap-two-window/handoff.md`
- **一句话**：热力图纵轴改为「**画 40 档 / 露 24 档**」—— 三个半径
  （订阅 20 / 绘制 20 / 可视 12），三条不变量由 `[6]` 守（变异 1 → 3 条）。
- **提交**：`130acdc feat(web): 热力图纵轴「画 40 档 / 露 24 档」—— 三个半径 + 三条不变量`
  （26 文件 / +1207 −319）。推送后 **`git ls-remote origin refs/heads/main` ==
  `git rev-parse HEAD`**、工作区 **0 项脏**。
- **状态**：`run.py --check` **16/16 RC=0**；`--selftest` **18/18**；
  **真机联调已补做**（IB Gateway PID 1232 + 后端 PID 7784）：
  DOM 渲染 `tmp/_dom_check.js` **PASS 15 / FAIL 0**（40 行 / `yAxis 8..31` /
  像素复核恰好 24 行在网格内 / Top-N 描边全在可视区 / 读数「可见 24/40 档」）、
  `tools/check_web_contract.py` **在线 RC=0**、窗口扫描 FAIL 0、
  渲染 `setOption` p50 27.4ms / max 44.6ms（远低于 400ms 推送间隔）。
- **两条已定性的"看着像缺陷其实不是"**：① 「每帧发 40 行」是**上限**
  （实测现价 7612/7614 ⇒ 40、7618 ⇒ 39，随现价漂移）；② 已退订的档仍在
  `TickStore.refs()` 里，但冻住的行只可能落在**可视区之外**（实测 39 行 0 行落后）。
- **本会话根只有 2 个文件**（无 `startup.md`）：改动前未采基线，
  按 skill 规则不补写，`handoff.md` 里记 `STARTUP-PROOF: N/A:<原因>`。

> 以下为**上一会话**的原索引文字（保留原样，未 retro-fit）。
> 其中"绘制 24 行"等读数描述的是**本次改动之前**的形状。

## 更早：2026-09-16 / runtime-monitors（完成）

- **会话交接**：`notes/sessions/2026-09-16/runtime-monitors/handoff.md`
- **一句话**：KAI 要四件验证 —— ① 写独立前后端监听脚本；② 新网格出列后数值不再变；
  ③ 每周期按 ET 挂钟推进出列；④ 各周期 ΔIV 独立互不干扰；写完再启动整个系统。
  ⇒ 新增**两只只读探针**：`tmp/monitor_backend.py`（读 WS 原始帧）、
  `tmp/monitor_frontend.js`（Playwright 读**页面上真正渲染出来的矩阵**）。
- **四项结论全部成立**：
  - ② 后端 7133 格指纹 / **0 改写**；前端显示 3385 格 + 基线 6796 格 / **0 改写**
  - ③ 后端 3 列 + 前端 2 列新列，**全部**落在挂钟整 30s / 60s
  - ④ 后端组和可加性 24 行 0 违反；前端跨档位对拍 144 列 / 3405 格全部吻合
- **证据**：`run.py --check` **16/16 RC=0**；两只探针重启前后各跑一轮，**四次全 PASS**。
- **非空转验证（摘掉修复要能报 FAIL）**：后端解码器改坏 ⇒
  `RC=1`「逐格指纹 0 个 … ✗ 帧 #17775 的矩阵解不开 —— **逐格判据在这帧上是空转的**」
  （没把"什么都没看"报成 PASS）；前端指纹键改回行号 ⇒ `RC=1`「改写 67870 处」。
- **本轮挖出的三个"假绿"陷阱**（都是探针自己的 bug，产品代码无缺陷）：
  ① 帧里**没有** `values` 字段（线上是 `bm16` 位图+int16）⇒ 直接读它永远空、
     "0 改写"看着像通过；② 指纹键**不能用行号**（±12 档窗口随现价平移，
     行号集体换身份 ⇒ 实测 50827 条假改写）；③ 列身份**不能用轴标签或行长**
     （`view.labels` 是裁尾切片；行长与 `view.cols` 会差一 ⇒ 稳键是"距右端偏移"）。
- **一处真契约边界（非缺陷）**：`heatmap.cols` 与 `session.bucket_index` 偶发差 1
  （529 帧里 1 次，桶内秒 29.998、方向恒为矩阵落后、次帧即恢复）
  —— 成因是两处独立读钟跨了 30s 边界。**判据：允许差 1 且落后；差 >1 或超前一律 FAIL。**
- **已按要求重启后端**：旧 PID 1228 → 新 PID 20636，`08:59:41 流水线已就绪`，
  恢复 278 个历史桶；前端列数 **767（未归零）** ⇒ 历史跨重启保全。
- ⚠️ **两个变异未激活**（诚实标注）：后端 T3 恒真 / 前端 T4 不标记 ——
  本轮观测期内确实不存在真违例，变异体没被执行到 ⇒ **未验证，不冒充通过**。
- ⚠️ **两只探针停在 `tmp/`**（按 KAI 明令不建常驻检查器）⇒ **无回归保护**。
- **清理**：22 个 `tmp/_*` 一次性脚手架已删（`_diag_*` / `_repro_*` / `_probe_*` / `_mutant_*`）。
- ⚠️ **本轮未提交任何东西**；工作区仍是大面积未提交的重写中间态（`HEAD = bedbf11`）。

---
## 最新：2026-09-15 / gate-tools-rewrite（完成）

- **会话交接**：`notes/sessions/2026-09-15/gate-tools-rewrite/handoff.md`
- **一句话**：KAI 明令「**必须重写，禁止移植失败品**」+「**README.md 必须重写**」
  ⇒ `#15 tools/` 门禁从**覆盖 5/16 重写到 16/16**（按 9 层新架构，未从 `HEAD` 移植一行），
  `README.md` 按 9 层架构重写（10 节），并完成全量复扫取证。
- **证据**：`run.py --check` **16/16 RC=0** · `selfcheck.py --selftest` **16/16 全抓 RC=0** ·
  四个冒烟 + web 对拍 **172 条判据全绿**（`l2l3` 37 / `l5` 32 / `l6` 39 / `l8` 30 / `web_e2e` 34）·
  `check_web_contract --offline --selftest` RC=0。
- **顺带抓到的真缺陷**：① `config/transport.json::bucket_seconds_s` 是**真死键 + 描述
  不存在机制的注释**（上一轮移植时凭空补的，旧项目 `HEAD` 里根本没有）⇒ 删键；
  ② `[7]` 的**键转发器覆盖盲区**（`_param_pairs(cfg, key, ...)` 把键名当参数转发 ⇒
  5 个活键被误报死键）⇒ 新建 `selfcheck_reads.py` 两遍 AST 扫描（当轮假红消失；
  ⚠️ 读取点计数随代码变化，**不抄写**，要引用实跑 `[7]`）；
  ③ 配置注释里 **6 处引用不存在的检查器** ⇒ 逐条标注"**待建**"。
- **下一步**：`tools/` 下 **8 个独立检查器仍待建**（`check_matrix_codec` /
  `check_grid_contract` / `check_period_aggregation` / `check_session_grid` /
  `check_surface_payload` / `check_reconnect_gap` / `check_window_tolerance` /
  `check_ws_compression` / `ws_probe`）。⚠️ **`check_grid_contract.py` 尚未建 =
  当前最大的门禁缺口**。状态表见 `README.md §6`。
- ⚠️ **KAI 明示待定、本会话未做**：① 在线验证；② 曲面残差无方向字段。
- ⚠️ **工作区脏态大**（`git status --short` = **133 项**，含 43 个 `D`）—— **未提交**。

---

## 上一轮：2026-09-15 / rebuild-from-original（L0–L8 + web/ 重写）

- **会话交接**：`notes/sessions/2026-09-15/rebuild-from-original/handoff.md`
- **一句话**：源码被清空，改为**基于原版 `live-volatility-surface` 重写**。
  完成 **L0–L8 全部九层 + `web/` 前端**落盘（#8–#14），`#15 tools/` 起步到 5/16。
- **`notes/` 已从 `HEAD = bedbf11` 恢复**（131 文件 / 2.3 MB）。

---

## 历史索引（重写前）

- Latest session: 2026-09-15/period-wallclock-semantics
- Current session handoff: notes/sessions/2026-09-15/period-wallclock-semantics/handoff.md
- Status: **周期分组的「桶 vs 挂钟时间」议题结案 —— 两者数值等价，"按挂钟整点分对齐"
  已经成立，本会话未改任何业务逻辑（只在 `web/period.js` 加一节论证注释）。**
  ⓐ **裁定来源**：KAI 原话"必须基于时间，时间是系统最重要的，21:00 21:03 21:06……
  时间周期才是第一，桶无效，必须删除这个错误逻辑"。查证后结论是**无需删任何逻辑**。
  ⓑ **两级依据（均可复现）**：① 网格起点 `20:15:00` = **72900 秒**，而
  `72900 % {30,60,180,300,900}` **全为 0** ⇒ 第 c 组的起点恒落在挂钟整点
  （20:15 / 20:18 / … / 21:00 / 21:03）；② `core/session_grid.py::_make_zone`
  （71-76 行）**强校验**区段边界落在桶边界上（不满足直接抛错），`parse_hm` 又只接受
  `HH:MM` ⇒ "整分钟 ∪ 桶宽整除"必然成立。故 `floor(cols/g)` ≡
  `floor((t−20:15)/period秒)` —— **改成按时间分组是恒等变换，不会动一个像素**。
  ⓒ **两条作废的方案**：KAI 先选"后端算周期值"、"档位告诉后端"，**两者均已作废** ——
  不是 KAI 选错，而是**提方案时我们还不知道边界已经对齐**；事实澄清后方案失去对象。
  **将来不得照着去实现那个双向通道 / 后端预计算。**
  ⓓ **一条被 KAI 裁定"不用"的真缺陷**（备将来）：空档桶 1580–1589 被切进两组 ——
  组 263 = 桶 1578–1583（09:24–09:27，混算 GTH 尾 + 空档）、组 264 = 桶 1584–1589
  （09:27–09:30，整组在空档内 ⇒ **该列永远无颜色**）。修法是"每会话从自己起点起算分组"，
  **已明确否决，勿自作主张**。
  ⓔ **上一会话遗留缺口已闭环（方法学）**：所谓"旧语义漂移复现不出来"是**采样位置问题** ——
  旧语义（`ceil`）的漂移触发条件是 **`cols % g == 1`**（末组恰 1 桶 = 刚跨周期那一帧），
  而非"末组不满"。按 3s 抽间隔帧而帧间隔 400ms ⇒ 必然跳过边界帧。实测 60 帧连续采样
  （`seq 18200 bi=1461 cols=1462 → 旧末 −0.223`；`seq 18201 bi=1462 cols=1463 → 旧末 −0.223`）
  显示 `1462 = 6×243+4`，末组已有 4 个桶且**早已走满** ⇒ 此刻两语义同值、本就不漂移。
  ⓕ **验证全绿**（`venv/Scripts/python.exe`）：`check_period_aggregation --selftest`
  **`RC=0`**（24 判据 + 守卫 2 + **6 变异全抓**，含"未走满的末组也出列"抓 24 项、
  "标签序列未同步"抓 5 项）；`run.py --check` **`RC=0`**（`[13]` 真实联通：24 档 × 1489 桶、
  Skew 815 点）；`tools/check_*.py` 矩阵 **21 绿 / 2 红**，两红经 `git stash -u`
  **证明为既存**（`check_page_render` 周期选中态、`check_ws_compression` 71.2%）；
  `web/period.js` **391 行**（< 400）。
  ⓖ **清理**：删 `tmp/` 12 个一次性探针 + `frames_seq.jsonl`(4.7MB) + `edge_cross*.log`。
  ⚠️ **风险**：`period.js` 余量仅 **9 行**，再加内容必须拆分；
  两个既存红灯未修，**引用"21/2"时必须带既存性证据**；未做浏览器取像素。
- Previous: 2026-09-15/heatmap-topn-skew-yzoom
- Previous handoff: notes/sessions/2026-09-15/heatmap-topn-skew-yzoom/handoff.md
- Previous status: **热力图"成交量 Top-3 无级黑边" + Skew Y 轴滚轮无限制自由缩放
  落地，新增常驻回归并全绿。**
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
