TASK-ID: zombie-trigger-rebuild
DATE: 2026-09-18
TIER: T2
STATUS: complete
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
STARTUP-PROOF: 见 `startup.md`（树基线 `70cba0c` + 工作区干净；`:8060`/`:4001`/`:4002` 全 closed、无 `ibgateway`；`date` 与外部 HTTP `Date` 头一致 ⇒ 休市，不起服务）。
**行为基线不引用旧记录，由探针现场给出**：`old` 臂运行时从
`git show 748cd56^:transport/ws_broadcaster.py` 现取僵尸修复**之前**那一版，
sha256 = `46976ac4ca5fbdb0…`。

# Handoff — 重建「浏览器侧触发僵尸」的条件

## 一句话

**触发条件重建成功，而且它比原先设想的窄**：把页面主线程卡住 **~12s 以上**才够
（实测要吸收 **≈2.24 MB** 才建立背压）；卡 15s 时后端发送协程死掉、而 socket
随后恢复正常 ⇒ **僵尸长期存在**，正是 2026-09-17 事故的形状。
前端修复**第一次**在真僵尸上验证：不修 ⇒ 页面永远停在「数据中断 Ns」；修了 ⇒
45s 换连接、帧回来。新后端则**根本不会形成僵尸**（注销与协程结束同一拍）。

## 触发条件（重建出来的，可复现）

```
真 headless Chrome → 真页面 → 真后端代码（自带 8063）
CDP Runtime.evaluate: while (Date.now() - t0 < N) {}     ← 卡住渲染器主线程
```

* 卡住期间浏览器**有界缓冲**先吞掉 ~28 帧（82,021 B/帧压缩后 ≈ **2.24 MB**，约 11s）；
* 缓冲填满 ⇒ 后端 `send_str` 卡在 `_drain()` ⇒ `send_timeout_s = 1.0` 到点
  ⇒ `_sender` 退出；
* 卡住结束、socket 恢复 ⇒ 对端能读能写，但**发送协程已经没了** ⇒
  队列（容量 1）有人丢、没人收 ⇒ **0 帧送达、每帧进 `dropped`**，而状态栏写着
  「已连接」—— 与生产事故逐条同形。

## 判据：非空转 A/B（同一份探针，只翻一个变量）

探针 `tmp/probe_zombie_browser.py`。四个臂**全部在最终字节上重跑**，**均 RC=0**：

| # | 后端 | 前端 | 卡住 | 心跳 | 结果 | 项数 |
|---|---|---|---|---|---|---|
| 1 | `old` | `off` | 15s | 20s | 僵尸 **≥80s**；`forces=0`；页面停在「数据中断 79s」，**永不恢复** | **8/8** |
| 2 | `old` | `on` | 15s | 20s | 僵尸活到 **45s** ⇒ 前端 `forceReconnect` 清掉 ⇒ 帧恢复 | **8/8** |
| 3 | `head` | `on` | 15s | 20s | **僵尸根本没形成**（`clients` 归零于 t=13.0s）；页面 ~8s 自愈，`forces=0` | **8/8** |
| 4 | `old` | `on` | 20s | **86400s**（对照） | 僵尸 **50s**，只有前端能清掉 | **8/8** |

**臂 1 ↔ 臂 2 就是前端修复的非空转证明**：同一份前端代码、只翻
`render.reconnectOnStale` 一个开关 ⇒ 判定相反（`forces=0` 卡死在「数据中断 79s」
vs `forces=1` 45s 后帧恢复）。**摘掉修复必须能报错** —— 臂 1 就是那个"摘掉"。

臂 2 的页面侧事件（探针从页面内取的，不是从后端推的）：

```
76420 | error          | 连接已强制重建：数据中断 46s
76421 | state:connecting | ws://127.0.0.1:8063/ws
76423 | ws.close        | 1000/
76424 | state:open      | ws://127.0.0.1:8063/ws
```

臂 3 的后端侧 WARN（新代码唯一的"我放弃了这条连接"出口）：

```
WARNING transport.ws: 客户端 127.0.0.1 发送失败（TimeoutError: ），
                      已发 32 帧 / 丢 1 帧，放弃该连接
```

**僵尸形态判据（两臂通用）**：`clients == 1` ∧ `sender_done == [True]`
∧ `sent` 冻结 ∧ `dropped` 单调涨。臂 1 实测 `sent` 冻结在 32、`dropped` 从 27
涨到 224（观测 80s），全程 0 帧送达。

## 本轮最重要的发现：心跳是「半张网」，僵尸的寿命差两个数量级

`old on 20 400 on` **首次运行**时，僵尸在 **~29s** 被 aiohttp 清掉
（时间点 = 连接建立 + 心跳 20s + pong 期限 10s），页面靠 `onclose` 自己重连
（`forces=0`）—— **看起来像是"不用修也能好"**。查代码坐实了路径：

`_send_heartbeat` → `loop.call_at(now + _pong_heartbeat, _pong_not_received)`
→ `_handle_ping_pong_exception` → `reader.feed_data(WSMessage(WSMsgType.ERROR, …))`
→ 旧代码 `async for` 里的 `if message.type is WSMsgType.ERROR: break`
→ `finally: _unregister`。

**但同一配置重跑没复现**（僵尸活到 45s、由前端清掉），而把心跳窗口拉到 86400s
（臂 4）则僵尸必然活到前端动手 ⇒ 它是**竞态**（PING 能不能在 pong 期限前写出去、
PONG 能不能在期限内回来），**不能当兜底**。已写进
`transport/ws_broadcaster.py` 的模块 docstring（**只加文档，无行为改动**）。

## CHANGED-PATHS

- `transport/ws_broadcaster.py`（333 → **352 行**，**纯文档**）：模块 docstring 新增一节
  「心跳**不是**僵尸的安全网」，含代码路径、单次观测、未复现、86400s 对照。
  **无任何行为改动**（`git diff` = 20 insertions / 1 deletion，全在 docstring 内）。
- `tmp/probe_zombie_browser.py`（**新建**，519 行，gitignored）：自带后端
  （产品自己的 `WsBroadcaster` + `StaticHandler`）+ 真帧样本 + 真 Chrome + CDP 卡主线程
  + 页面侧事件记录。`old` 版后端运行时从 git 取，打印 sha256。
- **未改**任何 `web/*.js`、任何配置、`features/`、`serialization/`。

## VALIDATION-SUMMARY

- `tmp/probe_zombie_browser.py` 四臂（`old off 15` / `old on 15` / `head on 15` / `old on 20 hb=off`）→ **4×8/8，RC 全 0**
- `run.py --check` → **16/16 全部通过，RC=0**
- `py_compile transport/ws_broadcaster.py tmp/probe_zombie_browser.py` → ok
- 真后端 / IB Gateway 侧：**N/A:开工时 `:8060`/`:4002` 全 closed 且休市，按纪律不起服务**

## COMMAND-EVIDENCE

```
# 四臂（每臂约 2 分钟；`old` = git show 748cd56^:transport/ws_broadcaster.py）
venv/Scripts/python.exe -u tmp/probe_zombie_browser.py old  off 15 400 on   → 8/8  RC=0
venv/Scripts/python.exe -u tmp/probe_zombie_browser.py old  on  15 400 on   → 8/8  RC=0
venv/Scripts/python.exe -u tmp/probe_zombie_browser.py head on  15 400 on   → 8/8  RC=0
venv/Scripts/python.exe -u tmp/probe_zombie_browser.py old  on  20 400 off  → 8/8  RC=0

# 背压建立所需的量（臂 1，卡住期间）
sent 4 → 32（+28 帧 ≈ 2243 KB）· 最长冻结 11.0s · sender_done 于 t=12.5s 变 True

# 僵尸形态（臂 1 末拍）
clients=1 sender_done=[True] sent=32 dropped=224 | page text='数据中断 79s' forces=0

# 门禁
venv/Scripts/python.exe run.py --check → 结果: 16/16 项全部通过  RC=0
```

## NOTES-PATHS

- `notes/sessions/2026-09-18/zombie-trigger-rebuild/{startup,project_state,handoff}.md`
- `notes/context/{handoff,open_tasks,project_state}.md`（同步）
- `.workbuddy-ai/memory/2026-09-18.md`

## Closed in session

- **[低] 触发点未重建**（`open_tasks.md` 的 `frontend-data-outage` 块）—— **关闭**。
  触发手法 = 卡住渲染器主线程 ≥12s（实测 15s 稳）；`old`/`head` 两版行为相反，
  四臂 RC 全 0。生产事故的形状（僵尸长期存在 + 状态栏写「已连接」）已按需重建。
- 前端修复**首次在真僵尸上验证**（此前只在"假后端 + 只停推流"上验证过）。

## OPEN-RISKS

- **仍未在 KAI 的真实浏览器 + 真实盘中背压下验证**。触发条件现在能按需重建，
  但重建用 headless Chrome；**KAI 那个标签页当时被什么卡住仍然未知**
  （浏览器侧无埋点这件事没有改变）。
- **卡住时长的边界没扫过**：只测了 15s（够）与 20s（够但会被心跳抢清）。多少秒
  开始"短到不足以杀死发送协程"、多少秒开始"长到必然被心跳清掉"，**未测**。
- **心跳那条约 29s 的清理路径只有单次观测**（同配置重跑未复现）⇒ 归因成立但是竞态；
  docstring 已按"竞态、不可依赖"措辞写明，**没有**把它写成稳定行为。
- **探针留 `tmp/`，无回归保护**（按 KAI 明令不建常驻检查器）⇒ 日后改
  `ws_broadcaster.py` 的注销逻辑不会被自动跑到。
- **KAI 侧仍有两件事要做**（沿用上一轮）：① 重启后端让 `748cd56` + 本轮 docstring 生效；
  ② 刷新页面（旧标签页仍连着旧连接）。
