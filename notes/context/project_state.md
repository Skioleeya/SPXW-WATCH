# Project State

ACTIVE_SESSION: 2026-09-18/zombie-trigger-rebuild
LAST_UPDATED: 2026-09-18 03:4x EDT —— **僵尸的触发条件已重建**（此前唯一缺的那块证据）。
后端修复 `748cd56` / 前端自愈 `87fa904`+`70cba0c` 均未改动；本轮**只加文档**。
⚠️ **HEAD 以 `git log` 为准，本文件不写死**（写死就会被下一条记录提交立刻变成假记录）。
⚠️ **时间基准**：环境注入的时钟比本机 `date` 慢 8h；本文件及 `notes/sessions/` 里
2026-09-17 早先标注的 `04:xx`–`06:xx` **实际是本机 `13:xx`–`14:xx`**。

## 本轮 —— 重建「浏览器侧触发僵尸」的条件（`zombie-trigger-rebuild`）

会话：`notes/sessions/2026-09-18/zombie-trigger-rebuild/{startup,handoff,project_state}.md`

**结论：触发条件造得出来，而且它比原先设想的窄。** 把页面主线程**故意卡住 ≥13s**，
后端 `_sender` 就会超时死掉（实测 t≈12.5s）；卡住结束、socket 恢复正常也**救不回来**
（发送协程已经没了）⇒ 队列（容量 1）有人丢、没人收 ⇒ **0 帧送达、每帧进 `dropped`**，
状态栏却写着「已连接」—— 与 2026-09-17 生产事故逐条同形。

**触发手法（可复现）**：真 headless Chrome + 真页面 + 真后端代码（产品自己的
`WsBroadcaster`/`StaticHandler`，端口 8063），CDP `Runtime.evaluate` 执行
`while (Date.now() - t0 < N) {}`。卡住期间浏览器**有界缓冲**先吞掉 **28 帧**
（82,021 B/帧压缩后 ≈ **2.24 MB** —— 13/14/15s 三次独立运行完全一致 ⇒ 是缓冲**容量**，
推送 400ms 下 ≈11.5s 填满），填满后 `send_str` 卡在 `_drain()` ⇒
`send_timeout_s = 1.0` 到点 ⇒ `_sender` 退出。

⚠️ **边界已扫（8/10/12/13/14/15s）：判据不是"卡多久"，而是"冻结时长是否越过
`send_timeout_s`"** —— 8s/10s 冻结 0.0s（缓冲没满）；**12s 冻结 0.5s < 1.0s ⇒ 后端挺住、
无僵尸**；**13s 冻结 9.0s ⇒ 协程死、僵尸 ≥80s**；14s/15s 冻结 10.5s/11.0s。
⇒ 可用下限 ≈ 11.5s + 1.0s；**稳的做法是卡 15s**（留 3.5s 余量）。
⚠️ 我一开始把 12s 的 `+49~50 帧` 读成"吞了 4 MB 都没堵" —— **是错的**，它堵了 0.5s，
只是**堵得不够久**；探针里那句「卡主线程不是可行的触发手法」属**过度断言**，已改。

**非空转 A/B（同一份探针只翻一个变量；四臂全部在最终字节上重跑，均 RC=0、各 8/8）**：

| # | 后端 | 前端 | 卡住 | 心跳 | 结果 |
|---|---|---|---|---|---|
| 1 | `old` | `off` | 15s | 20s | 僵尸 **≥80s**；`forces=0`；停在「数据中断 79s」，**永不恢复** |
| 2 | `old` | `on` | 15s | 20s | 僵尸活到 **45s** ⇒ 前端 `forceReconnect` 清掉 ⇒ 帧恢复 |
| 3 | `head` | `on` | 15s | 20s | **僵尸根本没形成**（`clients` 归零于 t=13.0s）；页面 ~8s 自愈，`forces=0` |
| 4 | `old` | `on` | 20s | **86400s**（对照） | 僵尸 **50s**，只有前端能清掉 |

- **臂 1 ↔ 臂 2 = 前端修复的非空转证明**：只翻 `render.reconnectOnStale` 一个开关
  ⇒ 判定相反（卡死在「数据中断 79s」vs 45s 后帧恢复）。
- **臂 1 的僵尸形态**：`clients=1` ∧ `sender_done=[True]` ∧ `sent` 冻结 32 ∧
  `dropped` 27→224（观测 80s）。**臂 3 的新后端自愈比看门狗快一个数量级**（13s vs 45s）。

⚠️ **本轮最重要的发现：心跳是「半张网」，不是兜底。** `old on 20` **首次**跑时僵尸在
**~29s** 被 aiohttp 清掉（时间点 = 连接建立 + 心跳 20s + pong 期限 10s，代码路径
`_send_heartbeat` → `_pong_not_received` → `_handle_ping_pong_exception` →
`feed_data(WSMsgType.ERROR)` → 旧代码 `async for` 里的 `break` → `finally: _unregister`），
**但同一配置重跑没复现**（僵尸活到 45s、由前端清掉），心跳拉长到 86400s 则僵尸**必然**
活到前端动手 ⇒ 它是**竞态**（PING 能否在 pong 期限前写出去、PONG 能否期限内回来），
**不能当兜底**。2026-09-17 事故里 PING/PONG 一路正常、僵尸活了 4h11m，也印证这点。

**改了什么**：`transport/ws_broadcaster.py`（333 → **352 行**，**纯文档**：模块 docstring
新增「心跳**不是**僵尸的安全网」一节；`git diff` = 20 insertions / 1 deletion，全在
docstring 内，**无任何行为改动**）；`tmp/probe_zombie_browser.py`（新建 519 → **539 行**，
gitignored；+20 行是补扫边界时改的两处**字符串/注释**，判据逻辑与阈值一字未动）。
**未改**任何 `web/*.js`、任何配置、`features/`、`serialization/`。

**验证**：四臂 **4×8/8 RC=0**；补扫 `old off {8,10,12,13,14,15}` ⇒ **8/10/12s 无僵尸
（RC=1，属预期）、13/14/15s 僵尸形成（8/8 RC=0）**；最终字节上复跑 12s（RC=1）与
15s（8/8 RC=0）；`run.py --check` **16/16 RC=0**；`py_compile` ok。
真后端 / IB Gateway 侧：**N/A:开工时 `:8060`/`:4002` 全 closed 且休市，按纪律不起服务**。

⚠️ **残留**：**仍未在 KAI 真实浏览器 + 盘中背压下验证**（重建用 headless Chrome，
KAI 那个标签页当时被什么卡住**仍然未知**）；**"堵住后为何还要 9~11s 才松开"未查**
（像是积压 2.24 MB 的排空耗时，**未做实验区分**）；2.24 MB 容量只在一种推送节奏 +
一种帧尺寸下测过；**~29s 心跳清理路径只有单次观测**（归因成立但是竞态）；
探针留 `tmp/` ⇒ **无回归保护**。
⚠️ **KAI 侧仍有两件事**：① 重启后端让 `748cd56` + 本轮 docstring 生效；
② 刷新页面（旧标签页仍连着旧连接）。

---

## 上一轮 —— 前端「数据中断」自愈（`frontend-stale-reconnect`）

会话：`notes/sessions/2026-09-17/frontend-stale-reconnect/{handoff,project_state}.md`

页面以前只会把状态文字写成「数据中断 Ns」，socket 一直开着、`onclose` 永不触发
⇒ **永不自愈，只能人工刷新**。现在超过 `staleErrorMs`（45s）没有成功渲染过的帧、
且连接**自称**还是 `open`，就主动把这条连接换掉。

- `web/app.js`（217 → 243 行）：`state.conn` 记连接自称态；`watchdog()` 改判据
  （自称 `open` + 超时 ⇒ 换连接）；计时基准加兜底 `lastFrameAt || connectedAt`。
- `web/ws_client.js`（178 → 213 行）：新增 `forceReconnect(reason)`；`stats.forces` 计数。
- `web/config.js`（327 → 334 行）：新增 `render.reconnectOnStale`（默认 `true`）。

⚠️ **两个关键设计点**：
① `forceReconnect()` **先摘掉四个回调再 `close()`** —— 否则"等 `onclose`"会与
"已开的新连接"并存 ⇒ **每 45s 泄漏一条连接**（且 `_ws` 只指向后一条）。
② 计时基准必须有兜底 —— 老代码 `if (!state.lastFrameAt) return;` 让
**"连上了却一帧都没有"整段跳过**（本项目最怕的静默形状）。
③ **看门狗只动手、不说话**（文字归 `onState`）—— 否则下一秒就被写回
「数据中断 Ns」，用户永远看不到"它其实试过重连"。

**验证（非空转）**：`tmp/probe_stale_reconnect.py`（真 headless Chrome + 产品自己的
`WsBroadcaster`/`StaticHandler`/`config/transport.json`，只停推流**不断连接** = 事故原形），
同一份代码只翻 `reconnectOnStale`：
- **A 臂**（`false` ＝ 修复前）`forces=0`、恢复推流后帧**在原来那条连接上**就回来了
  —— 证明那条连接本来还能用，页面只是永远不知道该重连（本轮最有力证据）。
- **B 臂**（`true`）`forces=1`、`connectedAt` 变、**服务端连接数 1→2**、恢复后帧到达。
- ⇒ **6/6 PASS，RC=0**（1m44s）。
`tmp/probe_live_page.py 100` 对**真后端**采样 100s（>2 个 `staleErrorMs` 窗口）
⇒ **6/6 PASS，RC=0**（1m51s）：帧 19→169 单调涨 · `forces` 恒 0 · `conn` 恒 `open` ·
从未误报「数据中断」⇒ 排掉本轮特有坏法"每 45s 自己换一次连接"。
`run.py --check` **16/16** · `node --check` 3/3。

⚠️ **残留**：未在 KAI 真实浏览器 + 盘中背压下验证（触发条件"JS 主线程被占住"仍未重建）；
最坏自愈延迟 = 45s（画面旧 45 秒，用户可感知）；未覆盖"后端进程整个挂掉"的形状
（那种情况 socket 会关、走既有 `onclose` 退避）；门禁 D（`/health` 的
`per_client.sent` 必须在涨）**仍未做**；三个探针留 `tmp/` ⇒ **无回归保护**。

### 补记（14:1x EDT）—— 看门狗拆成两个活体信号

复核时发现上一轮**我自己引入**的缺陷：把两个不同的故障塞进了同一个信号
（`state.lastFrameAt` 既代表"传输活着"、又代表"页面画出来了"），
且计时基准用 `||` ⇒ 换上的新连接**继承上一条连接的老时间戳**，一开就被判超时。

- **实测后果比预想重**：注入"帧在来但页面不画"（只 `delete window.renderHeader`，
  后端不动）后，旧写法 **50s 内 `forces=5`**（≈每秒一条连接的**重连风暴**，永不停），
  新写法 `forces=0` 且报出「渲染停滞 Ns」。
- **修法**：`rxAge`（传输 = `socket.stats.lastFrameAt`，在 `_accept` 里、任何解析前打点）
  与 `drawAge`（渲染 = `state.lastFrameAt`，在 `decodeFrame` 之后打点）**分开**，
  基准都用 `max(最后一帧, 连接建立时刻)`；`rxAge` 超时 ⇒ 换连接，
  `drawAge` 超时且传输正常 ⇒ **只报、不动**。
- ⚠️ **踩坑**：`!rxAt` 守卫一度写成 `isFinite(rxAge)`（**恒真 ⇒ 真回归**），
  已改回 —— 守卫要判"有没有基准"，不是判"算出来是不是数"。
- **顺带证伪**："`decodeFrame` 抛异常冻结时间戳"**不可达** ——
  `web/matrix_codec.js::decode()` 所有错误路径都是 `fail()` + 原样返回，**无 throw**。
- `web/app.js` 243 → **265 行**。非空转 A/B：**旧 RC=1 7/9 / 新 RC=0 9/9**；
  最终字节上三个探针 **9/9 · 6/6 · 6/6（RC 全 0）**、`run.py --check` 16/16。

---

## 上一轮 —— 提交推送 + 引用存储修复（`commit-and-push`）

会话：`notes/sessions/2026-09-17/commit-and-push/handoff.md`

五轮交互改动合并提交并推送（`ab853d3` 代码 19 文件 / +2151 −346 + `21293a1` 记录），
工作区转干净。**顺带修掉一个引用存储缺陷**：远端跟踪引用 `origin/main` 被一份缺
`# pack-refs with:` 头、mtime 2026-09-14 的 66 字节 `.git/packed-refs` 钉在 `6828e3a`
⇒ `git status` 长期谎报 `[ahead 23]`（而 `ls-remote` 与本地 `HEAD` 明明一致）。
**用标准命令 `git pack-refs --all` 修复**（**非**手工改 `.git` 文件）；
⚠️ **根因未定论且会复现** —— 只查到"git 建不了 `.git/refs/` 下的二级子目录、
非权限/重解析点"，**本环境每次 push/fetch 都会让跟踪引用陈旧**，`pack-refs` 只是
把当前值改对、不是根治。**未在沙箱外复跑**。
⚠️ **`git commit` 的 auto maintenance 在本环境会挂住** ⇒ 临时绕法
`rm -f .git/objects/maintenance.lock` + `-c gc.auto=0 -c maintenance.auto=false`。

---

## 更早 —— 五轮交互改动（合并提交 `ab853d3`）

⚠️ **该提交混合五个会话**：`heatmap-auto-roll` / `interaction-feedback-5fix` /
`skew-drag-interaction` / `heatmap-pan-drag` / `skew-dual-axis-zoom` ——
`web/index.html` 与 `web/config.js` 被五轮共同改动（新脚本标签、新配置块），
`web/heatmap*.js` 被三轮动过、`web/skew*.js` 被两轮动过 ⇒ **文件级无法拆**，
沿用 `0d30943` / `53da940` 先例**合并为一提交**；19 文件 / **+2151 −346**
（含 5 个新增 `web/*.js`）。`notes/` 单独一个 `docs(notes)` 提交。
⚠️ 提交前 KAI 未逐轮验收，**本提交不等于 KAI 对五轮改动背书** ——
各轮证据仍在各自的 `notes/sessions/2026-09-17/<task-id>/handoff.md`。

热力图缩出横轴窗口后，窗口右缘**自动跟着最新列走**；往历史里拖 ⇒ 停滚；
面板头「回到最新」按钮把右缘拉回最新列并恢复跟随、**保住当前缩放跨度**
（与「复位」分工：复位 = 丢掉缩放回全宽）。
**触发**三条同时成立（`heatmap.xRoll.enabled` ∧ 有窗口 ∧ 处于跟随态；全宽不需要滚）·
**方向**只有时间正方向 · **速度**数据驱动不插值（每帧把右缘移到 `cols-1-lagCols`，
即"前进量 = 该帧新增列数"；`lagCols` 是唯一调节量，默认 0）。
新增 `web/heatmap_roll.js`(159)。

⚠️ **最关键的设计点**：**「跟随」态必须显式存一个布尔位，不能现算** —— 列一追加，
任何窗口的右缘都不再贴最新列 ⇒ "用户往回拖了 5 列"与"过了 5 列"无法区分。

⚠️ **三个真教训**：① `enabled=false` 时按钮会亮着却点了没用（静默无操作）⇒ 新增
`snap()`，**用户指令不受自动化开关管**；② **自动滚动改变了"拖动方向"的含义** ——
跟随态下右缘就在最新列，**向左拖会被 `clampCols` 原地夹住**（正确的边界行为，
不是缺陷），要翻历史得**向右拖** ⇒ 三个老 pan 探针据此改向；
③ **契约检查器 id 覆盖有缺口（已补）**：`_ID_CALL` 原只认 `el/setText/setClass`
⇒ `bindButton("…")` 与 `ViewChips.*("…")` 的 id 不在覆盖内，已补两分支
（引用 20 → 27）并把 `--selftest` 扩成三条取法各注入一个假 id。

**验证**：`run.py --check` **16/16**；契约离线**与**在线 + `--selftest` 全通过；
**非空转**：同一份代码只翻一处配置 ⇒ prod `44/0` · noroll `39/0`（均 RC=0），
关键判定相反。回归：feedback `49/0` · pan_drag on/off 均 PASS · pan_guards /
pan_reset PASS · skew_drag `26/0`。

**残留**：**`web/heatmap.js` 397 行（上限 400，只剩 3 行）** —— 下次动它几乎必然要
先拆分（缝：左键拖拽手势整块下沉 `heatmap_pan.js`）；`web/style.css` 395 行同样贴上限；
`lagCols > 0` 只有单元断言覆盖；探针在 `tmp/` **无回归保护**。

---

## 上一轮 —— 五项交互缺陷修复（`interaction-feedback-5fix`，已提交 `ab853d3`）

工作区脏项 = **该会话 3 个新增 `web/` 文件 + 9 个修改的 `web/` 文件 + 3 个 `tmp/` 探针 + `notes/`**，
外加**三个上一会话**（`skew-drag-interaction` 的 `web/skew*.js`、`heatmap-pan-drag` 的
`web/heatmap*.js`、`skew-dual-axis-zoom`）的未提交改动 ——
**四轮改动叠在同一工作区**，该会话未替它们背书、也未一并提交。

KAI 从交互诊断"大白话版"点名 **2 / 4 / 5 / 6 / 7** 五项，已全部修完：
2→A2 全宽横拖弹瞬时徽标（**语义不变**，全宽仍不生成窗口）· 4→B2 锁定侧纵轴变警示色
`#ffb020` + 锁定徽标 · 5→C1/C4 两图复位按钮 + `Esc`/`R` · 6→C2/D1 Skew 四区游标语义
+ 轴区高亮框 · 7→D2/D3 热力图十字线 + 命中格描边 + 提示框跨重建存活。
新增 `web/heatmap_hover.js`(185) · `web/skew_regions.js`(155) · `web/view_chips.js`(85)。
配置新增 `heatmap.hover` / `heatmap.xZoom.hintPx` / `skew.pan.hintPx` / `skew.feedback`
/ `ui.flashMs` / `ui.resetKeys`（**缺键即抛错**，不静默兜底）。

⚠️ **本轮确立的通用不变量（最重要）**：**凡必须在帧间持续存在的反馈，都不能建在
ECharts 内部状态上** —— 每 ≤400ms 一次 `setOption(opt, true)`（notMerge）实测摧毁
悬停（指针静止也在 **+450ms** 消失）、原生 `axisPointer`（三种挂法 × 5 变体
**一次都没画出来**）、自带 `moveOnMouseMove` 拖拽（8 段只有**前 3 段**生效）
⇒ 常驻反馈一律走 **DOM 覆盖层**（与重建无关，也不吃 `setOption` 的 p50 = 27ms 预算）；
重建后按**像素**补 `dispatchAction({type:"showTip", x, y})`（**不能用 dataIndex**，列每帧在追加）。

⚠️ **差点把假绿当非空转证据**：探针模式原本只读环境变量，按位置参数传会**静默退回 prod**
⇒ 三次"单开关翻转"跑的是同一份代码。**已加守卫**（未知模式抛错，实测 `nofbb` 会 `exit 1`）。

**验证**：`run.py --check` **16/16**（**最终字节上重跑**）；`check_web_contract` 离线 + 在线全通过；
**非空转**：同一份 `web/*.js` 只翻一处配置 ⇒ prod `49/0`（RC=0）· nofb `43/0` ·
nohover `41/0` · nohint `48/0`，**断言数故意不同** ⇒ 判定相反。

**残留**：**A1 热力图纵轴仍不可交互**（诊断里最大的功能缺口，本轮**没做**）；
触摸未接；两图不联动（KAI 的明确取舍）；三个探针在 `tmp/` **无回归保护**；
`web/style.css` 与 `web/skew_zoom.js` 都到 **394** 行（上限 400）。

---

## 上一轮 —— Skew 图交互改版（`skew-drag-interaction`，已提交 `ab853d3`）

工作区脏项 = **该会话 6 个 `web/` 文件 + 3 个 `tmp/` 探针 + `notes/`**，
外加**两个上一会话**（`heatmap-pan-drag` 的 `web/heatmap*.js`、
`skew-dual-axis-zoom` 的 `web/skew*.js`）的未提交改动 ——
三轮改动**叠在同一工作区**，该会话未替它们背书、也未一并提交。

Skew 图**删掉滚轮缩放**，改为四种按住拖动：左 / 右 Y 轴区上下拖 = **只缩那一侧**纵轴；
底部 X 轴区左右拖 = 缩 / 放时间窗；网格内按住拖 = 自由平移（纵向两条轴一起移、
横向挪时间窗）；双击复位三条轴。方向统一为「**往轴的正方向拖 = 放大**」，
锚点固定为**按下那一刻**的位置。归属在**按下那一刻**按位置定死
（纯函数 `SKEW.regionOf()`，四区互不重叠）。
配置：`skew.zoom` 删滚轮语义、加 `stepPx 40` / `minCols 8`；新增
`skew.drag.throttleMs 100` 与 `skew.pan.enabled`。
`web/skew_zoom.js` **重写 → 399 行**；`skew_helpers.js` 226 → 348；
`skew_option.js` 156；`skew.js` 290 → 310；`config.js` 252 → 270。

⚠️ **`web/skew_zoom.js` 399 行，距 400 上限只剩 1 行** —— 下次动它几乎必然要先拆
（可拆的缝：手势状态机 / 视图状态导出）。

⚠️ **本轮修掉两条自己引入的缺陷**：
① `skew.js::_count` 被赋成**窗口列数**（应为总列数）⇒ `_applyZoom()` 拿它去 `setCols()`
⇒ `_cols` **逐帧自我折叠**（拖一次窗口 → 下一帧 `_cols` = 窗口宽 → 再拖更小），
**实测 654 列被折成 4 列**；已修，探针补两条断言守着
（窗口宽度 ≥ `minCols`、宽度逐级收窄不反弹）。
② `view()` 越界一律复位太破坏性 ⇒ 改**先夹、后复位**，两条路都 `console.warn`。

⚠️ **已证伪假设（不要再写回注释）**："`_cols` 会帧间抖动（638 → 555 → 638），
来源是 Skew 序列对齐后比热力图列数短" —— 这是**错误归因**，那个 555 就是缺陷 ① 的产物。
基线采样（不做手势、20s / 50ms 读 `_zoom._cols`）只看到 `638 → 639`（单调 +1，无抖动）。

**验证**：`run.py --check` **16/16**；`check_web_contract` 离线 + 在线全通过；
**非空转**：同一份代码只翻一个开关 ⇒ prod `PASS 26 / FAIL 0`、
`SWATCH_MODE=nozoom` `24/0`、`SWATCH_MODE=nopan` `25/0`（均 `RC=0`）。
三次都先断言"开关真的翻到位了"（读 `SWATCH_CONFIG` 实际值）——
否则"零变化"可能是配置替换的正则没匹配上，**探针自己变成空转**。

⚠️ **残留**：① 探针留 `tmp/` **无回归保护**（按 KAI 明令不建常驻检查器）；
② 未做像素级 / 肉眼复核，`throttleMs: 100` 的**手感未看**；
③ 未用真实物理鼠标验证（都是 Playwright 合成事件）；④ 触屏 / 触控板未接；
⑤ 全宽时横向拖不动（设计如此，与热力图一致，但**无任何视觉反馈** —— 见下）；
⑥ `skew.zoom.minSpan/maxSpan` 两条轴共用一组，极端缩放下会先触底，**属设计取舍待 KAI 定**。

📄 **同会话另产出**：`notes/analysis/2026-09-17-main-chart-interaction-audit.md`
（主流金融前端主图交互逻辑分析 + 本项目两主图交互缺陷诊断 A1–F2）。
**新建 `notes/analysis/` 目录，归属未定待 KAI 裁**（按"答不出类别的不进永久库"纪律，
未进 `notes/memory/` 知识库）。

详见 `notes/sessions/2026-09-17/skew-drag-interaction/{handoff,project_state}.md`。

> 以下为**上一会话**的原状态文字（保留原样，未 retro-fit）。

---

ACTIVE_SESSION_prev: 2026-09-17/heatmap-pan-drag
LAST_UPDATED: 2026-09-17 06:0x —— **热力图横轴「左键按住拖拽 = 平移」落地（未提交）**。
`HEAD` = `390ac6e`（与 `origin/main` 一致；功能提交仍是 `130acdc`）。
工作区脏项 = **本会话 4 个 `web/` 文件 + 3 个 `tmp/` 探针 + `notes/`**，
外加**上一会话**（`skew-dual-axis-zoom`）未提交的 `web/skew*.js` 与未跟踪目录 ——
本会话**未替它背书、也未一并提交**。

热力图面板新增手势：**左键在网格内按住左右拖动 = 平移横轴窗口**，与既有滚轮缩放
**共用同一个窗口状态** `_xWin`（列下标 `{from,to}`），双击仍复位回全宽。
配置新增 `heatmap.xZoom.panOnDrag`（开）与 `panThrottleMs: 100`（重绘节流）；
`web/heatmap.js` **250 → 342 行**。

⚠️ **为什么不是打开 ECharts 自带开关**（实测，`tmp/_diag_pan_drag.js`）：
`dataZoom.inside.moveOnMouseMove` 把"正在拖"存在自己的 `RoamController._dragging` 里，
而本面板每 400ms `notMerge` 重建整份 option ⇒ 控制器连同状态一起重建。
实测 8 段拖拽只有**前 3 段**生效，停点正好落在一次 `setOption` 上（反方向拖只剩 1 段）。
⇒ 改为面板自己做：绑 `chart.getZr()`（不是容器 —— 容器收不到 zrender 事件，
上一会话已钉死），只认左键，网格内才算，换算用"内容跟指针走"（1px = `span/gridW` 列）。

**验证**：`run.py --check` **16/16 `RC=0`**；`check_web_contract` 离线 + 在线均 `RC=0`；
真机渲染 `tmp/_dom_check.js` **PASS 15 / FAIL 0**；
**非空转**：同一份代码只翻 `panOnDrag` 一个开关 ⇒ 生产 8 段位移 / 关掉 **零位移**；
边界 `tmp/_probe_pan_guards.js` **8/8**（全宽不动 / 右键不动 / 网格外不动 /
左键网格内动 / 双击复位 / 0 报错）；拖拽中途复位 `tmp/_probe_pan_reset.js` **6/6**。

⚠️ **残留**：① 三个探针留 `tmp/` **无回归保护**（按 KAI 明令不建常驻检查器）；
② **未做像素级复核**（判据读 `dataZoom` 百分比与 `_xWin`，不是屏幕观感），
`panThrottleMs: 100` 的**手感未看**；③ **未用真实物理鼠标验证**（都是 Playwright
合成事件）；④ 触屏 / 触控板未接；⑤ **全宽（未缩放）时拖拽是空操作**（设计如此，
面板头已加提示）。

详见 `notes/sessions/2026-09-17/heatmap-pan-drag/{handoff,project_state}.md`。

> 以下为**上一会话**的原状态文字（保留原样，未 retro-fit）。

---

ACTIVE_SESSION_prev: 2026-09-17/skew-dual-axis-zoom
LAST_UPDATED_prev: 2026-09-17 04:3x —— **Skew 图双纵轴缩放落地（未提交，工作区 7 项脏）**。
`HEAD` 当时是 `130acdc`（其后另有一个 docs 提交 `390ac6e`）。

左轴 25Δ Skew 与右轴 IV **同一格滚轮一起缩**（各自按同一倍率绕同一屏幕锚点），
X 轴时间范围**一动不动**；指针在网格外则只缩 X；双击一次性复位两者。
触发 / 步长 / 上下限全在 `web/config.js::skew.zoom`（`step 1.15` /
`minSpan 0.05` / `maxSpan 500` / `minCols 8` / `anchorAtPointer`）。
交互与锁定态的唯一出口 = **新增的 `web/skew_zoom.js`**。

⚠️ **顺带查实一条老缺陷**：2026-09-15 那版"绑在图表容器上"的纵轴滚轮缩放
**从未执行过** —— zrender 在容器内部另建 viewport root 并 `stopPropagation()`，
实测 `zr.on("mousewheel")` = 1 而容器 = 0、document = 0。旧检查器只调纯函数
（`grep -rn "wheel" tools/*.py` 0 命中）⇒ 死绑定一路全绿。

**验证**：`run.py --check` **16/16 RC=0**；`node --check web/*.js` 全过；
真机探针 `tmp/_probe_skew_yzoom.js` **PASS 19 / FAIL 0**；
非空转 **4 处变异全部 RC=1**（绑回容器 / 只缩左轴 / 打开 dataZoom 滚轮 / 锚点改中心），
4/4 逐字节还原。行数：`skew.js` 321 / `skew_zoom.js` 347 / `skew_helpers.js` 230。

⚠️ **残留**：① 两条轴共用一组上下限 ⇒ 左轴（自然量程小）先夹到 `minSpan`，
极端缩放下"同步"名不副实；② 探针留 `tmp/` **无回归保护**（按 KAI 明令不建常驻检查器）；
③ **未做浏览器取像素**；④ **未在盘中 RTH 复验**（本轮 GTH，曲线基本平）。

详见 `notes/sessions/2026-09-17/skew-dual-axis-zoom/{handoff,project_state,startup}.md`。

> 以下为**上一会话**的原状态文字（保留原样，未 retro-fit）。

---

ACTIVE_SESSION_prev: 2026-09-17/heatmap-two-window
LAST_UPDATED_prev: 2026-09-17 04:0x —— **热力图纵轴「画 40 档 / 露 24 档」已落盘、已推送、
工作区干净**（`HEAD = 130acdc`，与 `origin/main` 一致，`git ls-remote` 已核）。

纵轴现在是**三个半径**：订阅 20（`subscription.json::num_strikes_each_side`）/
绘制 20（`features.json::heatmap_draw_rows_each_side` ⇒ 稳态 40 行）/
可视 12（`features.json::heatmap_visible_rows_each_side` ⇒ 屏幕 24 行）。
可视半径**随帧下发**，前端从帧上读。三条不变量（绘制 ≤ 订阅 / 可视 ≤ 绘制 /
订阅 − 可视 ≥ 重建触发）由 `run.py --check [6]` 守，3 条变异。

**真机联调已补做（03:09–04:00，IB Gateway PID 1232 + 后端 PID 7784）**：
DOM 渲染 `tmp/_dom_check.js` **PASS 15 / FAIL 0**（40 行 / `yAxis 8..31` /
像素复核恰好 24 行在网格内 / Top-N 描边全在可视区 / 读数「可见 24/40 档」）；
在线契约检查 RC=0；窗口扫描 FAIL 0；`run.py --check` 16/16。

⚠️ **两条已定性的"看着像缺陷其实不是"**：
① **「每帧发 40 行」是上限不是保证** —— 实测现价 7612/7614 ⇒ 40 行、7618 ⇒ 39 行
（随现价漂移 ±1，会来回变），冷启动约 1 分钟 33 行；可视 24 行不受影响
（`S − V ≥ T` 保证）。已修 `README.md §4` 与 `features.json` 注释。
② **已退订的档仍留在 `TickStore.refs()`**（`prune()` 不删键），但冻住的行只可能出现在
绘制窗口最外侧（距现价 ≥18 档），比可视区（±12）外扩 6 行以上 ⇒ 用户看不到；
实测 39 行 **0 行落后**。守卫仍是 `S − V ≥ T`。

详见 `notes/sessions/2026-09-17/heatmap-two-window/{handoff,project_state}.md`。

> 以下为**上一会话**的原状态文字（保留原样，未 retro-fit）。
> 其中的「24 行」「绘制 24 档」等读数描述的是**本次改动之前**的形状。

---

ACTIVE_SESSION_PREV: 2026-09-16/runtime-monitors
LAST_UPDATED_prev: 2026-09-16 09:0x —— **两只只读探针落地，四项要求全部验证成立；
后端已按要求重启生效。**

探针：`tmp/monitor_backend.py`（读 WS 原始帧判 T2/T3/T4）、
`tmp/monitor_frontend.js`（Playwright 读**页面真实渲染的矩阵**判 T1–T4）。
**后端全绿 ≠ 前端不抖** —— 帧到屏幕要过 5 道变换，故两者不可互替。

**实测**（重启前后各一轮，四次全 PASS）：门禁 `16/16 RC=0`；
出列即定稿 —— 后端 7133 格指纹 / 0 改写，前端显示 3385 + 基线 6796 格 / 0 改写；
挂钟推进 —— 后端 3 列 + 前端 2 列新列**全部**落在整 30s / 60s；
周期独立 —— 后端组和可加性 24 行 0 违反，前端跨档位对拍 144 列 / 3405 格吻合。

**非空转**：后端解码器改坏 ⇒ RC=1 且明确报「**逐格判据在这帧上是空转的**」
（没把"什么都没看"报成 PASS）；前端指纹键改回行号 ⇒ RC=1「改写 67870 处」。

**重启**：旧 PID 1228 → 新 PID 20636，`08:59:41 流水线已就绪`，恢复 278 个历史桶；
前端列数 **767（未归零）** ⇒ 历史跨重启保全。

⚠️ **两个变异未激活**：后端 T3 恒真 / 前端 T4 不标记 —— 观测期内无真违例，
变异体没被执行到 ⇒ **未验证，不冒充通过**。
⚠️ **探针停在 `tmp/`**（按 KAI 明令不建常驻检查器）⇒ **无回归保护**。
⚠️ **曲面残差前端仍未消费**（`web/` 读不到 `surface` 段）—— 另一件未开始的任务。
⚠️ **本轮未提交**；工作区仍是大面积未提交的重写中间态（`HEAD = bedbf11`）。

ACTIVE_SESSION_PREV: 2026-09-16/surface-residual-right
LAST_UPDATED_PREV: 2026-09-16 05:xx —— **曲面残差方向字段落地（KAI 选方案 B）**。
`SurfaceResidual` 新增 `right` 字段，`SurfaceInputPort.id_map` 改**三元组**
`(expiry, strike, right)` 把方向透传到帧。**原版数值口径全部未变**
（`pivot_table` 仍对同档两侧取 mean；残差仍报单侧 IV 与它的差）。

**实测**：门禁 **16/16 RC=0**；`l2l3` 37/0 · `l5` 32/0 · `l6` **41/0**（新增 2 条）·
`l8` 30/0 · `web_e2e` 34/0 · **新建** `tmp/verify_residual_right.py` **15/0**
（夹具喂 Put IV ≠ Call IV ⇒ 同档两条残差最小差 **1.0 波动率点**，
`model_iv` 两侧仍 **25/25 完全一致** ⇒ 拟合确实未受影响）。
**非空转**：`id_map` 改回二元组 ⇒ 4 条 FAIL；编码器删 `"right"` ⇒ 1 条 FAIL；
两者还原后**逐字节**回原状。

⚠️ **前端尚未消费**（`web/` 完全不读 `surface` 段）—— 残差图是另一件未开始的任务。

ACTIVE_SESSION_PREV: 2026-09-15/gate-tools-rewrite
LAST_UPDATED_PREV: 2026-09-15 14:4x —— **`#15 tools/` 门禁重写完成（覆盖 5/16 → 16/16）+
`README.md` 按 9 层架构重写。** KAI 明令「**必须重写，禁止移植失败品**」——
旧项目 `tools/` 的 43 个文件虽在 `HEAD` 里完好，但**层号口径不同**
（旧 `serialization` = **L4**、新 = **L6**），机械移植会让 `[2]` 的层号判据整体错位
且**不报错**（门禁自己静默失效）⇒ 16 项全部按新架构重写，未从 `HEAD` 移植一行。

**实测结论（可复现，全部用 `venv/Scripts/python.exe`）**：
`run.py --check` **16/16 RC=0** · `selfcheck.py --selftest` **16/16 全抓 RC=0**（2m06s）·
四个冒烟 + web 对拍 **172 条判据全绿**（`l2l3` 37 / `l5` 32 / `l6` 39 / `l8` 30 /
`web_e2e` 34）· `check_web_contract --offline --selftest` RC=0。

**本轮抓到的真缺陷**：① `config/transport.json::bucket_seconds_s` 是**真死键 +
描述不存在机制的注释**（上一轮移植时凭空补的，旧项目 `HEAD` 里根本没有）⇒ 删键；
② `[7]` 的**键转发器覆盖盲区**（`_param_pairs(cfg, key, ...)` 把键名当参数转发 ⇒
5 个活键被误报死键）⇒ 新建 `selfcheck_reads.py` 两遍 AST 扫描（当轮假红消失；
⚠️ 读取点计数随代码变化，**不抄写**，要引用实跑 `[7]`）；
③ 配置注释里 **6 处引用不存在的检查器** ⇒ 逐条标注"**待建**"。

**待做**：`tools/` 下 **8 个独立检查器仍待建**（`check_matrix_codec` /
`check_grid_contract` / `check_period_aggregation` / `check_session_grid` /
`check_surface_payload` / `check_reconnect_gap` / `check_window_tolerance` /
`check_ws_compression` / `ws_probe`）。⚠️ **`check_grid_contract.py` 尚未建 =
当前最大的门禁缺口**。状态表见 `README.md §6`。
⚠️ **KAI 明示待定、本轮未做**：在线验证；曲面残差无方向字段。
⚠️ **工作区脏态大**（`git status --short` = **133 项**，含 43 个 `D`）—— **未提交**。

见 `notes/sessions/2026-09-15/gate-tools-rewrite/handoff.md`（上一轮 `#8–#14` 见
`notes/sessions/2026-09-15/rebuild-from-original/handoff.md`）。
新架构：`notes/memory/ARCHITECTURE.md`（§16 已重写为 16/16）。
**`notes/` 已从 `HEAD = bedbf11` 恢复**；旧 `ARCHITECTURE.md` 归档为
`notes/context/archive/ARCHITECTURE_pre_rewrite.md`；`QUICKREF/RULES/TROUBLESHOOTING`
仍带"待按新实现复核"横幅。
ARCHIVE: notes/context/archive/project_state_2026-09.md

⚠️ **2026-09-15 白纸重写 —— 以下正文是重写前的记录。**
`spxw_swatch` 源码已被清空，基于 `live-volatility-surface`（原版）重写。
本文件正文（旧实现的状态/待办/交接）**保留作历史**：其中的纪律与教训继续有效，
但文件路径、检查器名、模块名可能已变。**重写进度以本文件顶部的新块为准。**


<!-- ↓↓↓ 以下为 2026-09-14 webgl-to-echarts 会话的历史快照，不 retro-fit ↓↓↓ -->

**本会话（webgl-to-echarts，2026-09-14）**：热力图渲染器换栈。
① **根因**（KAI 报"绿色周围黑色色块"）：`web/gl_heatmap.js:157-165` 把调色板绑在 TEXTURE1；
`:261-270` 首次 `update()` **未先 `activeTexture(TEXTURE0)`** 就 `bindTexture(_dataTex)`
⇒ 数据纹理顶掉调色板，此后 `pal` 再未被绑回 ⇒ `texture2D(u_palette, vec2(t,0.5))` 采到的是
**数据纹理中间行**：有效格 `(R,255,0)` 绿、落在空格 `(0,0,0)` 黑 —— 一个根因同时解释绿与黑，
也解释"换色不改渲染"。**这不是 WebGL 的 bug，是我方绑定顺序写错。**
② 另查明 `web/config.js:28-34` 的 `palette` **本来就是**逐色抄自参考项目
`live-volatility-surface` 的 Plotly `Turbo` ⇒ **颜色配置一直是对的**，坏的是渲染器没采样它。
③ **KAI 裁定换掉原生 WebGL**；库定为 **ECharts**（已内置且 Skew 在用 ⇒ 零新增依赖；
`af2e2e4` 之前的热力图本就是 ECharts；Plotly 要新增 ~3.5MB 且同为逐格绘制，不占优）。
`web/heatmap.js` 整文件重写（266 行，公共接口不变 ⇒ `app.js`/`app_render.js` 零改动，
手写 overlay 全删）；`web/gl_heatmap.js` **删除**（283 行）；`web/index.html` 去 script 标签；
`web/test_gl.html` → `web/test_heatmap.html`；`web/test_sync.html` 补 echarts；
`web/config.js` 网格线注释改写为 ECharts/splitLine 语义。
④ **关键映射（避免被当成自创）**：参考项目用 Plotly `xgap=1/ygap=1` 做格子间隙，ECharts 无等价项
⇒ 改用轴 `splitLine` + `interval = stride-1` 抽样画线；`cellBorderMix` → 线的 **opacity**
（`opacity m` 叠在数据色上 ≡ 旧 shader 的 `mix(color,border,m)`，数学等价 ⇒ 两个键都非死配置）。
`yAxis.inverse: true` 保证帧行序（降序行权价）第 0 行落在屏幕最上方。
⑤ **代价（实测、KAI 知情接受）**：ECharts 单次重绘 630 列 65.7ms / 1352 列 159.9ms /
2370 列 188.1ms，旧 WebGL 0.6/1.0/1.3ms；节拍 2.5Hz ⇒ 宽档位吃 **40–47% 单核**。
原始画布 `fillRect` 地板 9.5/21.3/40.5ms ⇒ 额外开销在 JS 侧逐格处理，**换 GPU 降不下来**。
`progressive` 是负优化（2370 列 424ms > 不开 188ms）⇒ 恒设 0。
⑥ **验证**：`run.py --check` `RC=0`；`check_web_syntax` / `check_web_contract` `RC=0`；
`check_page_render --budget 60000` 全 ok；真实页面取色 `nearBlackPixels: 0` / 516 色桶 / 2 canvas；
截图 `tmp/after_echarts_final.png`。**非空转**：palette 15 色改 `#ff00ff` ⇒ 色桶 553→37、绿色全消失，
还原后 md5 逐字节回到 `eae7e64f694a2f15679be190b936e0f0`。
⑦ ⚠️ **事故**：执行 `git rm -f web/gl_heatmap.js && git mv ...` 期间**整个 `web/` 目录从工作区消失**
（`git status` = ` D web/*.js` ×17 + `D  web/gl_heatmap.js`），`git mv` 报 `fatal: bad source`；
**无任何命令显式删除目录，成因未查明**。`git checkout -- web/` 从索引恢复，但未提交的
`web/config.js` / `web/skew.js` 改动丢失、只能**按记录重建**（`skew.js` 以 `grep -c itemStyle`=8、
`itemStyle`/`lineStyle` 5/5 同值收口；`config.js` 重建版比原版长 142 字节，**非逐字节还原，不作宣称**）。
⇒ **纪律：本仓库禁用 `git rm` / `git mv`，改用 `rm` / `mv` + `git add`。**
完整记录见 `notes/sessions/2026-09-14/webgl-to-echarts/`。

CURRENT_STATE: **spxw_swatch 纯实盘已落地，`ib_async`/`aiohttp` 已装，Gateway 链路验证通过；
`[1]`–`[13]` 全绿；Skew 面板无限制缩放 + 视口自适应；`web/*.js` 全部 < 400 行**。
模拟盘（`simulator/` + `config/simulator.json`）已物理删除，无特性开关、无兼容分支、无回退路径。
**交易日网格 = GTH 20:15→次日 09:25 + 空档 09:25–09:30 + RTH 09:30→16:00**，跨午夜，
71100s ÷ 30s = **2370 桶**；会话真相只有一处（`config/app.json::sessions`），
区段表随帧下发到 `session.zones`。
**Skew 纵轴量程 = 当前可见列内极值 ∪ {0} + 留白**（`web/skew.js::axisRange`）——
`skew.scale_policy` / `skew_scale_window_seconds` 已**全链路删除、无兼容分支**；
修掉"缩放到早盘段 ⇒ 整屏空白且不报错"的静默失效（改前 21/21 点越界 → 改后 0/21）。
同一轮另收三项：**图例补全**（两条 skew 曲线改用不同 series name + `legend.formatter`
同名显示 ⇒ 图例上两条 `25Δ Skew`，一暖一冷）、**刻度精度收进
`web/config.js::skew.axisDecimals`**（原硬编码 `toFixed(1)`）、**meta 读数随视口收窄**
（`_readout()` 按可见列算 + `setViewportHook` 让缩放立刻重写 meta）。
浏览器稽核 **26 项全绿**；4 条变异逐条摘掉修复**全部被抓**。

**本会话（heatmap-mirror-ffill-grid，2026-09-14）**：热力图渲染三处修正。
① **上下镜像**（KAI 未报，排查中挖出）—— `web/gl_heatmap.js::update()` 写
   `var tr = rows - 1 - r;`（注释称 "inverse Y"），而 shader 的天然映射是"屏幕顶 = texture 行 0"、
   HTML overlay 的标签/现货线也从索引 0 起 ⇒ **行序被反了两次**，整张图上下镜像。
   修法：去掉 `tr`，按帧行序直写 texture + 契约注释"帧行序 ≡ texture 行序，**不要再反转**"。
② **20:15 起满宽"假 0 带"**（KAI 报）—— `features/persistence.py::recover()` 读
   `heatmap_buckets` **全部行** → `load_snapshot()` → `_row_values()` 的 `carried`
   **无上限前向填充** ⇒ 孤桶被一路沿用，拉出满宽 `ΔIV=0` 的亮黄绿带，与真"IV 没变"无法区分。
   修法：新增 `config/serialization.json::heatmap_max_ffill_buckets`(20 = 10 分钟，
   取 `heatmap_feed_gap_s`(300s) 的 2×)，`HeatmapEngine` 加 `_max_ffill` slot，
   `_row_values()` 用 `last_seen` 记账、超限输出 `None`。
③ **细档位无纵线**（KAI 报，看着是长条）—— 1 分档 630 列 ⇒ 格宽 2.40px，
   被上一轮 `>= 3.0` 的**双侧**阈值判为"太窄"、纵线整方向跳过。
   修法：单侧**自适应步长** `stride = ceil(u_borderMinPx / cellPx)`（线仍落**真实格边界**，
   `stride=1` 退化为旧行为），新增 `web/config.js::heatmap.cellBorderMinPx = 5`（**物理像素**）。
两处非空转：镜像改回 `rows-1-r` ⇒ 满宽行跑回顶部（`tmp/mut_mirror.png`）；
纵线置 `minPx=0` ⇒ 塌成密纹、扫描线仅检出 0–9 条。
`check_reconnect_gap.py` 新增 `case_long_gap_is_blanked`（阈值从 config 读），
`--selftest` 扩为两处注入 ⇒ 实测两例变红。1 分档实测 **653 条纵线 / 中位线距 5.0 px**。
**重启（KAI 指令，07:19）**：`run.py` 是**父子两进程**（venv 存根 ~8MB 父 + 真实解释器 ~100MB 子），
只认 Ctrl-C（`Pipeline.stop()` 打印 `已停止`），**无 HTTP / 文件 / 信号停机入口** ⇒ 硬杀。
硬杀安全（SQLite `journal_mode=delete` + `_batch_write()` 每批 commit ⇒ 最多丢一批；
`recover()` 会把已提交桶捞回），停后 `integrity_check=ok`、334 行不变。
重启 `07:19:49` → 恢复 **335** 个历史桶 → `07:19:59 流水线已就绪`。
**上限生效实测**（活帧逐行非空列分段）：row 19（7575）由 `first=1 / nonnull=1308`
变为 `[(1,20),(449,554),(706,726),(1065,1331)]` ⇒ 假 0 带 **1308 列 → 20 列**（= 上限）；
对照 row 2（7660）无 `(1,20)` 段 ⇒ 修的是**带**，真实数据未动。
流程已沉淀进 `spxw-live-verify`（SKILL.md §5 + `references/pitfalls.md` 第 11 条）。
**残留**：`recover()` 未过滤 ⇒ bucket 0 本身仍在，带**未归零**（≤10 分钟）。
完整记录见 `notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/`。

**上一会话（frontend-render-fix-and-skill-split，2026-09-14）**：修掉 KAI 报的两个前端渲染缺陷。
① **热力图"网格线"消失** —— 真正的"网格线"是旧 ECharts 版每格的
   `itemStyle: { borderWidth: 1, borderColor: CFG.theme.grid }`，`af2e2e4` 的 WebGL 重写把它删掉
   且未在新引擎实现 ⇒ `theme.grid` 成**死配置**（`grep -rn "theme\.grid" web/` 零引用）。
   修法：fragment shader 补逐格边框（新增 `u_cellBorder`/`u_resolution`/`u_borderMix` +
   `setCellBorder()`），`config.js` 新增 `heatmap.cellBorderMix: 0.55`，边框色复用 `theme.grid`。
   ⚠️ **两个方向必须独立判断**：某方向格子 < 3 物理像素时不画 —— 否则
   `bw = 1/cellPx ≥ 0.5` 会让 `localX<bw || localX>1-bw` 覆盖整格、热力图糊成一片深灰。
   ⚠️ **该"< 3 物理像素即整方向不画"已被本会话推翻**（1 分档 2.40px ⇒ 纵线全消失），
   现为自适应步长。
   坐标轴 `splitLine` 旧版就是 `show: false`，**不是**这个问题。
② **Skew 图例色与曲线色系统性不符** —— ECharts legend 图标取 `series.itemStyle.color`
   （否则按 series 索引取默认调色板），**不读 `lineStyle.color`**；而 5 条 series 当时只设了后者。
   实测图例 `#5470c6/#91cc75/#fac858/#ee6666/#73c0de` vs 曲线
   `#ff5a5a/#4ea8ff/#5d6874/#ff5a5a/#4ea8ff` ⇒ **5 项中 3 项不符**。
   修法：5 条 series 补 `itemStyle.color` 同值 + 在 `skew.js` 钉成契约注释
   （同值**看似冗余**，后人极易当重复配置删掉 —— 那正是本次缺陷的成因）。
两处均做**非空转验证 2/2 被抓**（`cellBorderMix=0` → 网格完全消失；`itemStyle` 还原 → 图例第 1 项变回蓝紫），
4 个 `web/` 文件事后逐字节还原。另把 `spxw-live-verify` skill 从 703 行拆为 **209 行 + 6 份 `references/`**。
完整记录见 `notes/sessions/2026-09-14/frontend-render-fix-and-skill-split/`。

**上一会话（b2b-spot-synthesis，2026-09-14）**：GTH 段现货基准落地 —— KAI 5 条拍板全部实现。
① 新增 `config/spot.json`（独立文件，已登记 `selfcheck_core::REQUIRED_KEYS`）；
② `acquisition/spot_synthesis.py`：`ĉ = (ln F2 − ln F1)/(T2 − T1)`、`S = F1·e^(−ĉ·T1)`，
   两层闸门（`max_abs_carry` fail-closed / `max_carry_jump` 拒收该桶、**基准照常跟上**防死锁）；
③ `acquisition/spot_source.py`：按区段选源 —— 合成区段**丢弃**指数 tick，`rth` 直读指数；
④ `core/session_grid.py`：从 `clock.py` 拆出网格几何纯函数（`clock.py` 414 → ~340 行）；
⑤ `--check` 的 venv 识别改按 `pyvenv.cfg`（与目录名解耦）。
**09:25 交班窗口重建无需额外代码** —— 锚跳 8.15 档 > `recenter_trigger_strikes` 3 档，
既有 `WindowFollower` 自动重建。
期货合约月与到期日**全部来自 IBKR**（`ContractDetails.realExpirationDate`），代码零推算。
新回归 `check_spot_synthesis` **16/16** + `check_spot_source` **11/11**，非空转 **5/5 变异被抓**。
端到端冒烟（GTH 正在交易）：`帧 137 | 客户端 1 | 分片 48 | 现价 7620.26 | 订阅 48/92`
—— **现价 = 合成值**，同期 IBKR 指数冻结在 **7656.98**。
⚠️ **改动未提交**（全树 **18 M + 7 ??**，基线 `HEAD=92a516c`），待 KAI 决定。

`run.py --check` **`RC=0`**：**90 个 Python + 14 个前端脚本全部合规**（最长 398 行）。
全量 **19** 个 `check_*.py`（实测 `ls tools/check_*.py | wc -l`）：**13 `RC=0` / 6 `RC=1`** ——
6 个失败经 `git worktree add -f tmp/head_tree HEAD` 对照，**HEAD 上同样 `RC=1` ⇒ 既有，非本轮引入**；
其中 `check_period_aggregation` 根因已定位（node 驱动未加载拆分后的 `web/period_align.js`）。

本会话完整记录见 `notes/sessions/2026-09-14/frontend-render-fix-and-skill-split/`；
上一会话（B2b 现货合成落地）见 `notes/sessions/2026-09-14/b2b-spot-synthesis/`；
更早（GTH 现货基准调研 + B2/B3 判别实验）见
`notes/sessions/2026-09-14/gth-spot-basis-research/`；
更早见 `notes/sessions/2026-09-13/web-js-gate-and-probe-governance/`。

## 仍然有效（跨会话结论，未受本轮影响）

- **冷数据键序 = 降序**（2026-09-13 统一）：`dump_bucket()` 输出前
  `sorted(..., reverse=True)`，由 `tools/check_persistence.py::_case_key_order_descending`
  守着（含非空转证伪）。**与对外帧的 `strikes` 同向**（高行权价在前）。
  ⚠️ `data/` 已于 2026-09-13 清空（KAI 指令，不备份）：无历史桶，下次启动
  `recover()` 冷启动。上述"降序"是**代码行为**，不是现存数据。
- **热力图纵轴：帧 `strikes` 与屏幕自上而下统一为降序**（高行权价在前/在上）——
  由**两处成对**保证，**缺一即上下翻转**：
  ① `HeatmapEngine.build()` 的 `sorted(..., reverse=True)`（帧行 0 = 最高行权价）；
  ② `web/gl_heatmap.js::update()` **按帧行序直写 texture**（屏幕顶 = texture 行 0）。
  标签与现货线走 HTML overlay（`web/heatmap.js:156`/`:209`，`y = g.y+(i+0.5)/rows*g.h`，索引 0 在最上）。
  ⚠️ **`web/heatmap.js` 已无任何 ECharts yAxis**（`yAxis.inverse` 的旧说法已作废）——
  2026-09-14 前 `update()` 里那句 `tr = rows-1-r` 把行序**反了两次**，即本会话修掉的镜像缺陷。
  判据写成等式（"帧第 r 行写在 texture 第 r 行"），**不要写成"要反转"这类方向性描述**。
- **端口 `4002`**（IB Gateway 模拟盘）；TWS 实盘 7496 / 模拟 7497；Gateway 实盘 4001。
- **`ibkr.json::market_data_type` 必须写 3** —— 写 1 时指数无权限 → Error **354**、
  一个 tick 都不推 → `_await_spot` 20s 超时 → `SpotUnavailableError` 退出（fail-closed）。
  ⚠️ `health.mode` **派生自本键**，不能用来判断某合约是否实时 —— 看
  `ticker.marketDataType`。行情权限**按合约分档**：SPXW 期权 `1`（实时）、
  SPX 指数 `3`（延迟）。
- **106 模型 Greeks 已证实** —— `generic_tick_list: "106"` 推 `tickOptionComputation`，
  四档 greeks 并存且值不同。⚠️ `ib_async` 把 tickType 13/83 合并到同一属性，
  属性层无法区分，`TickRouter.source_tick_type` 恒为 13（**名义值**）。
- **限速桶在 `ib_async` 库层**（45 msg/s = 官方 50 的 90%），项目**只观测不重建**；
  `health.rate_limit`（库层消息速率）与 `health.sub_limit_backoff`（Error 300
  行数退避）是**两个东西**，别混。
- **热力图配色 = Plotly `Turbo` 15 色顺序色阶**；基线桶宽 30s，聚合在前端
  （`web/period.js`）。
- ⚠️ **前端脚本语法无门禁的盲区已封**（2026-09-13）：由
  `tools/check_web_syntax.py`（**按目录枚举**，新增文件自动纳入）覆盖全部 `web/*.js`。
- ⚠️ **ECharts 版本 = 5.5.1，zrender = 5.6.0**（`web/vendor/echarts.min.js` 里
  `t.version="5.5.1"` / `t.dependencies={zrender:"5.6.0"}`）。**别把两者搞混。**
- **线格式**：`enc`/`scale`/`bm`/`i16`/`filled`；位序/字节序/遍历顺序只以
  `serialization/bitmap_codec.py` 的 docstring 为准。permessage-deflate 已显式化
  （`transport.json::ws_compression`）。
- ⚠️ **JS 里 `""` 是 falsy** —— 判"字段在不在"必须用 `=== undefined`。
- ⚠️ **`tools/` 的自检豁免范围（实测，勿假设）**：豁免 [2] 分层 / [9] 单一职能 /
  [10] 硬编码；**不豁免 [1] 行数与 [8] `__slots__`**。
- **记录体系**：`notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`，
  三件套上限），`memory/` 为根路由器；**同一事实只写一处**。

## 多会话网格的口径（2026-09-13，本轮定稿）

- **网格几何**：会话时长 + 会话之间的空档，**必须能被桶宽整除**，否则
  `SessionClock` 构造即抛错（fail-fast，不静默补一截）。判据由
  `tools/check_session_grid.py` 从 `config` 推出来，**不写死 20:15 / 09:25 / 2370**。
- **区段起点桶必须留白**：跨过 09:25–09:30 空档的第一笔 IV 若与空档前最后一笔做差，
  整段空档的变化被压进一个 30 秒桶，画出一堵**与真冲量无法区分的假墙**
  （与断线恢复是同一类假信号）。落点在 `features/heatmap_engine.py`。
- **环形缓冲容量必须覆盖整个网格**：`heatmap_max_buckets` / `skew_series_max_points`
  780 → **2370**。否则最早的桶被静默裁掉，图上表现为"左端凭空少一截"。
  由 `check_session_grid.py` 核对。
- **`maxColumns` 400 → 2370**（`web/config.js`）：**在一个交易日之内这个截断永不生效**，
  这是刻意的 —— 横轴是时间轴，从尾部截掉历史段在图上看不出来（没有滚动条也没有
  提示），GTH 开盘那段会静默消失。密度交给周期选择器。由
  `check_period_aggregation.py` 的跨文件不变量核对。
- **时段切列 = 切掉，不是涂白**：`web/period.js::sliceZones` 把空档的列整段移除
  （填 `null` 只是不画颜色，那几列照样占宽度 = 告诉人"这里本该有数据"）。
  **顺序是契约**：先切列再并组，否则一个组会横跨空档。
- **切列映射只有一份**：`sliceZones` 产出 `index`（基线桶号 → 切后列号，-1 = 已切掉），
  **热力图与 Skew 共用**；`alignSkew` 先查表再整除平移。
  ⚠️ 本会话修的就是它没消费这份映射 —— 切掉 10 列空档后 RTH 段每点左移 10 列，
  两块图横轴指向不同时刻，**不报任何错**。
- **`index` 为 null 是契约的另一条入口**（序列里的桶号已是切后位置），不是兜底分支：
  由 `check_period_aggregation.py` [6] 组的"时段映射路径 ≡ 预映射路径"钉住。

NEXT:
0. ~~**[高] 重启 PID 896**~~ —— **已完成**（2026-09-14 07:19，KAI 指令）。
   重启后实测上限生效：假 0 带 **1308 列 → 20 列**。
   **残留**：`recover()` 未过滤 ⇒ bucket 0 本身仍在（带未归零，只是 ≤10 分钟）。
   彻底消除需在 `recover()` 只取最后一段连续桶 —— KAI 上一轮**未选**，见
   `notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/project_state.md`。
   ⚠️ 另注意：**改后端参数（`features/` / `config/*.json`）不重启就不生效，
   而 `run.py --check` 照样全绿**（它不读活进程）。前端 `web/` 静态 + `no-store` ⇒ 刷新即生效。
1. **[中] RTH 段（09:30–16:00）实盘验证**（**只能盘中做**）—— B2b 落地的最后一块。
   GTH 段已冒烟通过（合成值 7620.26 出图、48 订阅、帧流正常）。
   待验：① 09:30 后 SPX 指数是否**真恢复实时**（而非继续冻结）；② 09:25 交班切源是否平滑、
   窗口是否按既有机制重建；③ RTH 段确实走指数而非合成。
   前端仍需肉眼确认：热力图纵轴高行权价在上、两块图横轴按同一周期对齐、
   GTH / RTH / 全时段三按钮切换正常、**GTH 时段的列确实画出来了**。
   ✅ **由 KAI 手动在盘中验证 —— 不设任何自动任务**（2026-09-13 KAI 明确）。
2. **[中] 6 个既有失败回归待修**（2026-09-14 登记）—— `check_page_render` /
   `check_skew_alignment` / `check_skew_viewport` / `check_web_contract` /
   `check_ws_compression` / `check_period_aggregation`，均已 `HEAD` worktree 对照确认
   **非本轮引入**。其中 `check_period_aggregation` 根因已定位（node 驱动未加载
   拆分后的 `web/period_align.js`），修法明确，但属"重构现有工具"，**未获指令不擅自动**。
   其中 4 个需服务的检查**只能盘中跑**（`check_web_contract` / `check_page_render` /
   `check_ws_compression` / `ws_probe`）；`check_web_contract` 三段已用**离线等价物**补验
   （桩模块跑第 1、2 段；真实流水线造帧跑第 3 段，61/61 路径命中），
   **但走的不是它自己的入口**。⚠️ 判据是 `/health` 的 `frames > 0`，不是 HTTP 200。
3. ~~**`web/*.js` 拆分方案待 KAI 拍板**~~ —— **已完成拆分**（2026-09-13 本会话）。
   `app.js` → `app.js` + `app_sessions.js` + `app_periods.js` + `app_render.js`；
   `skew.js` → `skew.js` + `skew_helpers.js` + `skew_option.js`；
   `period.js` → `period.js` + `period_align.js`。
   全部 14 个前端脚本 ≤ 400 行；`--check` `[1]` 全绿 `RC=0`。
4. ~~**`check_period_aggregation` / `check_skew_alignment` 缺分组完整性守卫**~~ ——
   **2026-09-13 第二轮一并修**：两文件已接入 `tools/group_guard.py`，
   `--selftest` 各自抓全守卫 2 条 + 全部变异（period: 5 条 / alignment: 4 条）。
5. **[低] `~/.workbuddy-ai/tmp/` 40 个历史探针未迁移**（KAI 第二轮拍板本轮不做，
   下一会话代办）—— 动用户目录需明令。开始前先列清单（按 mtime / 大小 / 是否含
   `import`），让 KAI 一眼能拍"全迁 / 部分迁 / 只登记不动"。

低优先（记录但不阻塞）：
- ~~**色板缺机械回归**~~ —— **已剔除**（前端空壳，色彩映射由后端驱动）
- ~~**`check_clock_protocol.py` 是否并入 `--check` 常驻**~~ —— **已完成**（`[12]`）
- ~~**联通与限速无常驻回归**~~ —— **已完成**（`[13]`，`selfcheck_connectivity.py`）
- **换账户 / 换机器后确认实时数据权限**；**本机缺 `ib_async` 与 `aiohttp`**
  ⇒ `check_reconnect_flow` 与 `check_web_contract` 在本环境跑不了。
- **`check_web_contract.py` 顶层 `import aiohttp`** 使它的第 1、2 段（DOM id、
  CFG 路径，均为纯静态对照）也无法在无 aiohttp 的环境运行。2026-09-13 复核时
  KAI **未选**内移，保持原样。
- **`web/*.js` 已纳入 `[1]` 且拆分完成**（2026-09-13）—— `[1]` 现扫 **104** 个文件
  （**90 `.py` + 14 `web/*.js`**，2026-09-14 更新：新增 6 个 `.py`），全部合规。
  最长文件 `tools/check_period_aggregation.py` = 398 行。`--check` **`RC=0`**。
- **[约束] 临时探针一律写 `<项目根>/tmp/`**（2026-09-13 KAI 定）——
  旧约定"写在工程目录之外（`…/.workbuddy-ai/tmp/`）"**路径含糊且理由错误**
  （只有用户级那个真实存在、被所有项目共用）。必须在 `.gitignore` +
  `NON_SOURCE_DIRS` **两处**登记：缺前者探针入库，缺后者被 `[1][2][9][10]` 误报。

**已决策不再重提（KAI）**：限速桶读数**不上前端**；**IV 热力图 ΔIV ≈ 0 不退回中性色**
（维持 Turbo 顺序色阶）；**纵轴高行权价在上**（帧与屏幕同向降序）；
**冷数据键序也统一为降序**（2026-09-13）；`notes/` 为记录落点、`memory/` 为根路由器。
**RTH 收盘 = `16:00`**（2026-09-13 KAI 明确：他只在正股 RTH 09:30–16:00 交易，
与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**，不要再提）；
**不设任何验收自动任务**（由 KAI 手动在 GTH 时段验证；"定时任务不见了"是
**预期行为**，不要再当 bug 排查或重建）；
**`web/*.js` 已拆分完成**（2026-09-13）—— `app.js` / `skew.js` / `period.js` 三文件
拆分为 9 个模块（含原文件重写），全部 < 400 行。`--check` `[1]` 全绿 `RC=0`。
`.js` 只进 `[1]`，不进 AST 类检查（`[2][9][10]`）。
**临时探针落点 = `<项目根>/tmp/`**（2026-09-13 KAI 拍板，不再写用户级
`~/.workbuddy-ai/tmp/`；必须在 `.gitignore` + `NON_SOURCE_DIRS` 两处登记，
探针用完即弃、判据要落成常驻回归）。
- **`check_clock_protocol.py` 已并入 `--check` 常驻 `[12]`**（2026-09-13 KAI 批准）——
  验证时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
- **联通与限速已并入 `--check` 常驻 `[13]`**（2026-09-13 KAI 批准）——
  `selfcheck_connectivity.py`：8060 有服务则连 WS 抓帧校验；无服务跳过（warning，
  非交易日预期），不视为失败。

**记录教训（累积，五条同族）**：
1. 2026-09-13 复核 —— **"记录里写了"不等于"系统里有"**：把"已设一次性验收定时任务"
   写进了 `open_tasks.md` 与 `project_state.md`，但系统里查无此任务。
2. 2026-09-13 本会话 —— **"检查里写了"不等于"检查里跑了"**：
   `check_period_aggregation` 的 [5][6] 两组对照函数存在、`GROUPS` 有标题、
   README 说"七组对照"，但 `evaluate()` 没串进去，**一次都没执行**，
   而报告照样打印"全部通过"。
3. 更早 —— `check_page_render` 拿到 Chrome 自己的错误页也算"画出来了"（假通过）。
4. 2026-09-13 本会话（**误判，已修正**）—— **"系统里没有"不等于"系统坏了"**：
   上一轮"已设"的验收定时任务查不到，我直接定性为工具缺陷并**重建了两次**；
   KAI 澄清那是他**有意为之**（手动在 GTH 验收，不要自动任务），创建的已删除。
   ⇒ 下"这是缺陷"的结论之前，先问一次"**是不是有人故意这么设的**"。
5. 2026-09-13 本会话 —— **"守卫的期望集合不能从被守卫的对象自推"**：
   `check_skew_viewport.py` 的完整性守卫用 `known = [p for _, ps in GROUPS …]`
   推出期望前缀 ⇒ **删掉 `[G4]` 那一组，期望集合跟着变小、守卫失明**，而该组判据
   **连报告都进不去** ⇒ 3 条失败被静默吞掉、`RC` 仍 0（探针留档见本会话 `artifacts/`）。
   ⇒ 期望值必须来自**独立常量**，且"分组表是否恰好覆盖它"要**单独查**。

⇒ 凡"已设 / 已开 / 已生效 / 有 N 组对照 / 全绿"这类状态，判据都是**去系统里读一次 /
数一遍实际执行了几个**，不是读记录、不是读代码里有没有这个函数；
而"读到的东西与记录不符"时，**先排除"这是有意为之"**再定性为缺陷。
