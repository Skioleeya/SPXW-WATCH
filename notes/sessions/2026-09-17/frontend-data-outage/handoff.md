TASK-ID: frontend-data-outage
DATE: 2026-09-17
TIER: T1
STATUS: 诊断 complete → 后端修复已实施并验证（前端部分未做）
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
STARTUP-PROOF: `run.py --check` 16/16；修复前基线（诊断阶段）为 `/health` + 帧内 `health` 快照；修复后基线为 `tmp/probe_zombie_ws.py`（见文末「修复验证」）。

# Handoff — 前端数据中断（诊断）

## 一句话

**后端与行情源都是好的，断在「后端 → 浏览器」这一跳**：后端里那条 WS 连接的**发送协程
早就退出了，但客户端从没被注销** ⇒ 客户端成僵尸，**100% 丢帧**；而前端只会在
`onclose` 时重连，socket 一直没关 ⇒ **永远不自愈**。

## 现象（KAI 报「前端数据中断」）

页面停在旧数据上，顶栏显示 `数据中断 Ns`；后端日志一切正常（每分钟一行、`WARN` 计数恒 0）。

## 排查结论：逐段定性

| 环节 | 判据 | 结论 |
|---|---|---|
| IBKR → 后端 | 帧里的 `health`（**不是** `/health`） | ✅ 正常：`connection=connected`、`last_tick_age_s=0.1`、`ticks_received=7218420`、`subscribed=80/92`、`store_cells=92` |
| 后端产帧 | 日志每分钟一行 + `/health.frames` | ✅ 正常：帧号单调涨、现价在动（7632→7635）、订阅 80/92 |
| **后端 → WS 投递** | 6 秒间隔采 `/health` | ❌ **断在这里**：`frames +14` / `total_sent +0` / `total_dropped +14` |
| WS → 前端接收 | 同上 | ❌ 一帧都没到浏览器 |
| 前端数据处理 + 状态更新 | 新开页面 A/B | ✅ 正常：`帧#63122 · 丢 0 · 缺口 0`，热力图与 Skew 全出图 |

**决定性 A/B**：同一后端、同一份前端代码，**新开一个页面完全正常**
（`connected · delayed`、现价 7635.2、丢 0 缺口 0）。
⇒ 前端代码本身没坏，坏的是**那个标签页持有的旧连接**。
⇒ 立即恢复手段：**刷新页面**（未代 KAI 执行）。

## 证据

```
# 6 秒间隔采两次 /health
T0     frames 62897  total_sent 57479  total_dropped 20131
       per [{sent: 5044, dropped: 20131, age_s: 14596.9}]
T+6s   frames 62911  total_sent 57479  total_dropped 20145
       per [{sent: 5044, dropped: 20145, age_s: 14604.9}]
⇒ 每帧都被丢、一帧都没发；per_client.sent 冻结在 5044
```

`5044` 帧 × 400ms ≈ **33.6 分钟** ⇒ 该连接只正常工作了半小时就死了。
`age_s ≈ 14948`（4h09m）⇒ 已僵尸 3 小时 35 分。
TCP 仍是 `ESTABLISHED`（`127.0.0.1:52119 → :8060`），所以**从外部看连接是"好的"**。

## 根因（两处，缺一不可）

### ① 后端：连接的生命周期锚在错的协程上

`transport/ws_broadcaster.py`

- `_sender()`（L190–212）：`await wait_for(send_str, timeout=send_timeout_s=1.0)`，
  任何异常被 `except Exception: pass` **就地吞掉** ⇒ 协程**静默退出**，**一条日志都不留**
  （这正是本项目 `WARN` 计数恒 0 的成因之一）。
- `handle()`（L131–141）：注销**只**发生在 `finally`，而 `handle()` 停在
  `async for message in ws:`（L132）—— **前端从不发上行消息** ⇒ 这个循环永不结束
  ⇒ `finally` 永不执行 ⇒ **客户端永不注销**。
- 结果：僵尸客户端留在 `self._clients` 里，队列（`client_queue_size: 1`）没人消费
  ⇒ `_offer()` 每帧走 QueueFull 分支 ⇒ `dropped += 1` **每帧一次、永远**。
- `heartbeat_interval_s: 20.0` **救不了**：心跳的 PING/PONG 由浏览器**网络栈**应答，
  与 JS 是否在消费无关 ⇒ 只能证明"TCP/WS 层活着"，证不了"应用在消费"。
  实测该僵尸存活 4 小时、心跳从未把它关掉。

**判据**：`_sender` 只有两个出口 —— `break`（`ws.closed`）与异常。
若走 `break`，说明 ws 已关，`handle()` 的 `async for` 会随之结束并注销；
**而它没有被注销 ⇒ 只能是异常出口**（`send_timeout_s` 超时）。

### ② 前端：看门狗只报不改

`web/app.js`

- `watchdog()`（L160–171，`setInterval(…, 1000)`）算出 `age` 后**只改状态文字**
  （`数据中断 Ns` / `数据陈旧 Ns`），**不触发任何重连**。
- `web/ws_client.js` 的重连入口**只有两个**：`ws.onclose`（L103–110）与
  `new WebSocket()` 构造抛错（L76）。**没有**"沉默超时"重连，**没有**
  `visibilitychange` / `onLine` 兜底。
- ⇒ socket 一直 OPEN、`onclose` 永不触发 ⇒ **页面永远卡在中断状态，只能人工刷新**。

## 触发条件（未完全复现，如实标注）

触发是**一次 >1 秒的发送背压**：浏览器 JS 主线程被占住（重渲染 / GC / 标签页被节流）
⇒ Chrome 停止读 socket ⇒ 接收窗口打满 ⇒ 服务端 `send_str` 超过 `send_timeout_s=1.0`
⇒ 发送协程死。
**具体是什么占住了 JS，本会话无法重建**（浏览器侧没有埋点，日志里也没有对应记录）。
可确证的只有：`payload_bytes = 354737`（约 347 KB/帧，比旧记录的 ~150 KB 翻了倍，
因为热力图改成画 40 档）、`client_queue_size: 1`、`send_timeout_s: 1.0` —— 余量很薄。

⚠️ 本会话**没有**把 33 条 `Task exception was never retrieved` 当成 `_sender` 的死因：
那批堆栈指向 aiohttp 自己的 `WebSocketWriter._send_compressed_frame_async_locked`，
是客户端断线时的库噪声。`_sender` 的死**是静默的、无堆栈**。

## 修复建议（原提 A–E；其中 **A 被实测证伪后改方案**、B 已实施，C/D/E 未实施）

**A. 后端（根治，最小改动）**：让发送协程退出时**自己关连接**，
使 `handle()` 的 `async for` 结束、`finally` 生效：

```python
# _sender() 末尾补 finally
finally:
    if not client.ws.closed:
        try:
            await asyncio.wait_for(client.ws.close(), timeout=1.0)
        except Exception:
            pass
```

更彻底的做法是把连接寿命与发送协程绑定（`handle()` 用
`asyncio.wait({reader, client.task}, return_when=FIRST_COMPLETED)`），
因为**前端不发上行消息时，发送协程是唯一能发现"对端已死"的协程**。

**B. 后端（可观测，防再犯）**：`_sender` 的 `except Exception: pass` 改为
**计数 + 记一条 WARN**；`stats()` 增加 `sender_alive` / `last_sent_at`，
让 `/health` 能直接看出僵尸。

**C. 前端（纵深防御）**：`watchdog()` 在 `age > staleErrorMs` 时**执行**重连
（`SwatchSocket` 增加 `forceReconnect()`：关掉旧 ws，交给既有 `onclose` 走退避重连），
而不是只写文字。可选加强：利用后端既有行为 ——
`handle()` 收到任何 TEXT 会立刻回一帧（L136–139）⇒ 前端定期发 `"ping"`，
收不到回帧就重连，比"沉默超时"更快更准。

**D. 门禁**：新增一条检查器 —— `/health` 的 `per_client.sent` **必须在涨**；
冻结即为红。这正是本项目"静默错值"类缺陷该有的守卫。

**E. 运维**：`max_clients: 16`，僵尸不清会逐个占满（当前只 1 个，KAI 每次刷新
会清掉旧的）。修复 A 之后此项自然消失。

## OPEN-RISKS

- **触发点未重建**（哪段 JS 占住了主线程），只能定性为"一次 >1s 背压"。
- **僵尸当前仍在**（`clients: 1`、`sent` 冻结在 5044、`dropped` 持续增长）——
  **后端进程还在跑旧代码**，本会话未代 KAI 重启（重启才生效）。
- 帧体积已涨到 ~347 KB/帧（热力图 40 档的副作用），
  与 `client_queue_size: 1` + `send_timeout_s: 1.0` 的组合余量变薄 —— 值得单独评估。
- 前端 ②（只报不改）、门禁 D、运维 E **均未实施**；前端不修则"后端放弃连接"仍要靠
  `onclose` 才自愈（而 `onclose` 需要连接真的断得掉，见下"关不掉"一节）。

---

# 修复（已实施，2026-09-17 05:0x EDT）

KAI 拍板"先修后端"。改动**只在一个文件**：`transport/ws_broadcaster.py`（256 → 333 行）。

## 为什么原方案 A 走不通（实测，不是推理）

原方案是"发送协程退出时 `ws.close()`，把 `handle()` 的读循环顶醒"。探针实测**做不到**：

```
对端不读 ⇒ 发送缓冲满 ⇒ ws.close() 卡在内部 drain
        ⇒ 即使超时后 aiohttp 去关底层 transport，transport.close() 也要等缓冲冲出去
⇒ 读循环永远不醒。实测三者同时成立：
   ws.closed=True · transport.is_closing()=True · ws._waiting=True
   sender done=True cancelled=False      ← 客户端一直留在注册表里
```

**结论：把"注销"的成立条件绑在"TCP 还写得动"上，等于没有不变量。**

（顺带排掉一个假线索：探针里 `_sender` 任务一度显示 `cancelled=True`，
调用栈落在 `asyncio/timeouts.py:130 _on_timeout → self._task.cancel()` ——
那是 `wait_for` 自己的超时机制，不是别的代码在取消它。）

## 实际做法：注销由"发送协程结束"直接触发

`handle()` 不再就地 `async for`，而是把读循环拆成 `_reader()` 协程，与发送协程**赛跑**：

```python
client.task = asyncio.create_task(self._sender(client))
client.reader = asyncio.create_task(self._reader(client))
try:
    await asyncio.wait({client.task, client.reader},
                       return_when=asyncio.FIRST_COMPLETED)
finally:
    await self._unregister(client)
```

配套三处：

- `_unregister()`：**先 `_clients.discard()`，再清理**（注册表才是 `max_clients` 名额
  与丢帧统计的依据，清理慢不能继续占名额）；两个协程一律 cancel + await（顺手取走异常，
  免 "never retrieved" 噪音）；`ws.close()` 带 `wait_for(timeout=send_timeout_s)` 兜底
  （关不掉也无妨，客户端已不在注册表里）。
- `_sender()`：`except Exception: pass` → **`send_failures += 1` + 一条 WARN**
  （僵尸之所以能藏 4 小时，就是因为这里一条日志都不留）。
- `stats()`：`per_client` 增 `sender_alive`（**派生**自 task，不另存字段，免得漂移）、
  `last_sent_age_s`、`send_failures`；`ClientStats` 增 `last_sent_at`。

## 修复验证（非空转 A/B）

探针：`tmp/probe_zombie_ws.py` —— 真实 aiohttp 服务 + 真实 TCP；
阶段 1 用"只握手、此后不读"的裸 socket（`SO_RCVBUF=4096`）制造写不动的客户端，
阶段 2 用正常客户端做**主路径回归**（防止修僵尸把好客户端弄坏）。

| 代码 | 阶段 1（僵尸） | 阶段 2（正常） | WARN | RC |
|---|---|---|---|---|
| 旧（`git stash` 摘掉修复） | **FAIL** —— 15s 观察窗内一直留在注册表（`sender done=True cancelled=False`、`ws._waiting=True`） | PASS（收 3 帧、关闭后立即注销） | **0 条** | 1 |
| 新 | **PASS —— 1.5s 被注销，注册表清空** | PASS（`sent 1→10`、`dropped 0`、关闭后 0.0s 注销） | 1 条 | 0 |

同一份探针、两种代码给出不同结果 ⇒ 不是空转。
静态门禁：`run.py --check` **16/16**（改动前后各跑一次，均 16/16）。

## 未做 / 待办

- ⚠️ **后端未重启 ⇒ 修复尚未生效**，线上仍跑旧代码（僵尸仍在）。
- 前端 ②（看门狗只报不改）、门禁 D（`per_client.sent` 必须在涨）、运维 E 未做。
- 探针留在 `tmp/`（按既有约定不建常驻检查器）⇒ **无回归保护**。
- 未在真实浏览器 + 真实背压下复测（探针用的是裸 socket，比浏览器更极端）。

