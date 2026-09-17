TASK-ID: frontend-stale-reconnect
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
STARTUP-PROOF: 树基线 = `748cd56`（上一轮后端修复后的干净工作区；`run.py --check` 16/16）。
**行为基线不引用旧记录，由探针 A 臂现场给出**：同一份代码把 `render.reconnectOnStale`
翻成 `false` ⇒ 就是修复前的行为（实测见下）。真帧测试数据取自正在跑的后端
（`tmp/_capture_frame.py`，只读）。

# Handoff — 前端「数据中断」自愈（缺陷②）

## 一句话

页面以前只会把状态文字写成「数据中断 Ns」，socket 一直开着、`onclose` 永不触发
⇒ **永不自愈，只能人工刷新**。现在超过 `staleErrorMs`（45s）没有成功渲染过的帧、
且连接自称还是 `open`，就**主动把这条连接换掉**。

## CHANGED-PATHS

- `web/app.js`（217 → 243 行）：`state.conn` 记录连接自称的状态；`watchdog()` 改判据
  （自称 `open` + 超时 ⇒ 换连接；计时基准在"从未渲染过帧"时退回连接建立时刻）。
- `web/ws_client.js`（178 → 213 行）：新增 `forceReconnect(reason)`；`stats.forces` 计数。
- `web/config.js`（327 → 334 行）：新增 `render.reconnectOnStale`（默认 `true`）。
- **未改** `web/app_render.js`：它每帧把 `st-conn` 写成 `connected · delayed`，
  而看门狗只在"没有帧"时才轮到说话 —— 两者不冲突，见 `project_state.md`。

## 判据：非空转 A/B（同一份代码，只翻一个开关）

探针 `tmp/probe_stale_reconnect.py`：**真 Chrome（headless）+ 真后端代码**。
"数据中断"的造法 = **只停推流、不断连接**（正是 2026-09-17 那次事故的形状），
后端用的是产品自己的 `WsBroadcaster` + `StaticHandler` + `config/transport.json`
（只把端口改成 8062，不碰 KAI 正在跑的 8060）。

```
RC=0   6/6 项通过（两臂各跑一次，1m44s）

准备        PASS 首帧渲染 —— frames=3 conn=open staleErrorMs=45000（页面上报，探针不写死）

A 臂（reconnectOnStale=false ＝ 修复前行为）
  PASS 停推流后出现「数据中断」 —— 46s 后 text='数据中断 46s'
  PASS **没有**换连接（只报不改） —— forces=0
       connectedAt 1789667706911→1789667706911 · 服务端连接数 1→1
  PASS 恢复推流后帧回来（**同一条连接**） —— frames→8 forces=0

B 臂（reconnectOnStale=true ＝ 修复后）
  PASS 停推流后换掉连接 —— 45s 后 forces=1
       connectedAt 1789667706911→1789667800913 · 服务端连接数 1→2
       text='connected · delayed'（新连接**立刻补到一帧**：handle() 的既有行为）
  PASS 恢复推流后帧重新到达 —— frames→10 conn=open
```

**A 臂第 3 条是这次最有力的证据**：停推流 46 秒后恢复，帧**在原来那条连接上**就回来了
（`forces=0`）—— 说明那条连接**本来就还能用**，页面只是永远不知道该重连。

## COMMAND-EVIDENCE

```
node --check web/ws_client.js web/app.js web/config.js   → 3/3 ok
venv/Scripts/python.exe run.py --check                   → 16/16 项全部通过
tmp/_capture_frame.py tmp/frame_sample.json              → 411390 字符、seq=72175（真帧）
tmp/probe_stale_reconnect.py                             → RC=0，6/6
tmp/probe_live_page.py 100                               → RC=0，6/6（1m51s）
```

`VALIDATION-SUMMARY`（每次运行一行）：
- `probe_stale_reconnect.py`：**6/6 PASS**，RC=0（A 臂 3 条 + B 臂 2 条 + 准备 1 条）
- `probe_live_page.py 100`：**6/6 PASS**，RC=0，1m51s（帧 19→169 单调涨 · `forces` 恒 0）

## 真后端回归（不许自己乱重连）

`app.js::watchdog()` 改坏的具体形状是"**每 45 秒自己换一次连接**"，静态检查看不出来。
`tmp/probe_live_page.py` 直接打 KAI 在跑的 `http://127.0.0.1:8060/`，采样 100 秒
（> 2 个 `staleErrorMs` 窗口），判据：帧每拍都涨 · `forces==0` · `conn` 恒 `open` ·
文字从不出现「数据中断/数据陈旧」。只读，不重启后端。

结果（对 KAI 正在跑的后端，只读）：

```
RC=0   6/6 项通过（1m51s）

=== 等真后端出图 ===
=== 采样 100s（覆盖 >2 个 staleErrorMs 窗口）===
  t=   10s frames=19 conn=open forces=0 text='connected · delayed'
  t=   20s frames=35 conn=open forces=0 text='connected · delayed'
  t=   30s frames=51 conn=open forces=0 text='connected · delayed'
  t=   40s frames=68 conn=open forces=0 text='connected · delayed'
  t=   50s frames=85 conn=open forces=0 text='connected · delayed'
  t=   60s frames=102 conn=open forces=0 text='connected · delayed'
  t=   70s frames=119 conn=open forces=0 text='connected · delayed'
  t=   80s frames=136 conn=open forces=0 text='connected · delayed'
  t=   90s frames=152 conn=open forces=0 text='connected · delayed'
  t=  100s frames=169 conn=open forces=0 text='connected · delayed'
------------------------------------------------------------------------
  PASS  首帧渲染
  PASS  出厂默认 reconnectOnStale=true
  PASS  帧一直在流（每拍都涨）
  PASS  一次强制重连都没触发
  PASS  连接态恒为 open
  PASS  从未出现「数据中断/数据陈旧」
========================================================================
结果: 6/6 项通过
```

⇒ 新看门狗在**真行情、真后端、跨 2 个 `staleErrorMs` 窗口**下**没有误触发**：
169 帧 / 0 次强制重连 / 连接态恒 `open`。这就排掉了本次改动的特有坏法
（"每 45 秒自己换一次连接"）。

⚠️ 边界：这 100 秒里后端**一直是健康的**，所以它只证明"不会误触发"，
**不证明"该触发时真能触发"** —— 后者由上面的 A/B B 臂（假后端停推流）承担。
两者合起来才是完整证据。

## Closed in session

- **缺陷②（前端看门狗只报不改）已修并验证**（原记录在
  `notes/sessions/2026-09-17/frontend-data-outage/handoff.md` 与
  `notes/context/open_tasks.md`）。至此 2026-09-17 那次"前端数据中断"的**两处根因都修完**。

## OPEN-RISKS

- ⚠️ **未在 KAI 自己的浏览器 + 真实盘中背压下验证**：探针用的是无头 Chrome +
  本地假后端（虽然跑的是产品代码）。"JS 主线程被占住 ⇒ 接收窗口打满"那个**触发条件**
  仍未复现（与诊断阶段同一遗留）。
- ⚠️ **最坏自愈延迟 = `staleErrorMs` = 45s**：这 45 秒里画面是旧的、用户可感知。
  调小会与后端 20s 心跳（`heartbeat_interval_s`）贴太近，有误判风险。
- 未验证"后端进程整个挂掉"的形状（那种情况下 socket 会关、走既有 `onclose` 退避重连，
  本次**没有**覆盖）。
- 门禁 D（`/health` 的 `per_client.sent` 必须在涨）**仍未做**。
- 两个探针留 `tmp/`（按既有约定不建常驻检查器）⇒ **无回归保护**。
- 后端侧修复（上一轮 `748cd56`）**仍需重启才生效** —— KAI 决定自己重启。
