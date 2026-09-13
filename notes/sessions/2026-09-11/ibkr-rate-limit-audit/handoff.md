# Handoff — ibkr-rate-limit-audit

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: 第一轮 baseline=`run.py --check` **10/10 通过**（69 文件 / 最长
`acquisition/feed_service.py` 395 行 / 死键 0）；第一轮为**只读审计**，
**未修改任何生产代码**，故无"改动前/后"行为对比；IB Gateway 10.50 在
`127.0.0.1:4002` 实测可连（`serverVersion=178`）。
第二轮（限速桶显式化）baseline 同为 **10/10**（70 文件 / 最长
`feed_service.py` 395 行 / 死键 0）；改完并加上新检查 [11] 后为 **11/11**
（70 文件 / 最长 `feed_service.py` 396 行 / 死键 0）。

## 结论（直接回答 KAI 的提问）

**限速桶存在且实测生效，但它不是项目配置的，而是 `ib_async` 2.1.0 自带的
库级滑动窗口限速器（45 msg/s）。项目对它既未声明、未观测、也未校验。**

1. **桶的位置与阈值**：`ib_async/client.py:85-86`
   ```python
   MaxRequests = 45
   RequestsInterval = 1
   ```
   `Client.sendMsg`（同文件 `:323-352`）对**全部出站消息**做滑动窗口限速：
   窗口内超过 45 条即进 `_msgQ` 队列，用 `loop.call_at(times[0] + 1, ...)` 延迟重发。
   所有 `reqMktData` / `cancelMktData` / `reqContractDetails` 都走这条路。
   **45/s = 官方上限 50/s 的 90%**，是合理的保守值。

2. **项目侧没有自建桶**。全仓 `grep bucket|token|rate_limit|Semaphore` 的命中
   **全部是热力图的时间桶**（`bucket_seconds` / `bucket_index` 等业务概念），
   无一个是限速桶。项目自配的三样东西都是**固定间隔节流**，不是桶：
   - `min_request_interval_s=0.05` → 订阅/退订 20 req/s
   - `qualify_batch_size=40` + `qualify_batch_interval_s=0.3` → 批量确认分片
   - Error 300 指数退避（事后被动）

3. **订阅与退订实测流畅**：用项目自身 `SubscriptionManager` 走真实路径，
   72 条订阅 + 18 退 / 24 增的重建，**全流程 throttle 触发 0 次**，
   无 Error 100、无 Error 300。

4. **端口已于本会话修正并实测联通**：`config/ibkr.json` 原为 `7497`（TWS 模拟盘），
   实测 `ConnectionRefusedError`；已按 KAI 的模拟盘改为 **`4002`**，
   用 `run.py --live` + `ws_probe` 双路验证通过（见下方"处置"节）。

## 官方配额（查证结果）

| 项 | 数值 | 说明 |
|---|---|---|
| 通用消息速率上限 | **最大行情行数 / 2**；默认 100 行 → **50 msg/s** | 账户行数更高则速率上限也更高 |
| 超限错误码 | **100** "Max rate of messages per second has been exceeded" | |
| 违规后果 | **3 次违规终止 API 会话** | 恢复需重连 |
| 计入速率的请求 | `reqMktData` / `cancelMktData` / `reqContractDetails` / `reqHistoricalData` / `placeOrder` / `cancelOrder` | 主动请求 |
| **不计入** | 订阅后 TWS 推送的 tick | 不是程序发出的请求 |
| 同时订阅上限 | 行情行数（默认 **100**），超限 **Error 300** | 项目已按 92 自留余量 |
| 多客户端 | 连同一 TWS/Gateway 的客户端**累计共享**预算 | |
| 历史数据 pacing | 60 次/10min、同请求 15s 间隔等 | **本项目不涉及** |

来源：IBKR Campus TWS API 文档（经 `twsapi.kuaibian.net/pacing-limitations/`
镜像逐条转述）；`ib_async` 2.1.0 源码；第三方 `blive` 项目 KB-3
（其 §1 引官方 `order_limitations.html` 的"3 次违规断连"）。

## 实测证据（COMMAND-EVIDENCE）

环境：`IB Gateway 10.50`（模拟账户）@ `127.0.0.1:4002`，
`ib_async` 2.1.0，隔离 venv `C:/Users/Lenovo/.workbuddy-ai/binaries/python/envs/default`。

**A. 端口与桶阈值（`artifacts/rate_probe.py`）**

```
[port 7497] 连接失败: ConnectionRefusedError: [WinError 1225]   ← 项目配置值
[port 4002] 连接成功 serverVersion=178                          ← 实际监听值
[limiter] MaxRequests=45 RequestsInterval=1
[limiter] 库层速率上限 = 45 msg/s
[burst below] n= 30 wall=1.651s peak_msgQ=  0 throttle_start=0
[burst above] n= 90 wall=2.725s peak_msgQ= 45 throttle_start=1
```

- 30 条（< 45）：`peak_msgQ=0`、`throttle_start=0` → 桶未介入。
- 90 条（> 45）：`peak_msgQ=45`、`throttle_start=1` → **桶确实拦下 45 条排队**。
  这是桶生效的**可证伪证据**。

**B. 端到端订阅/退订（`artifacts/e2e_probe.py`）**

```
[connect] ok serverVersion=178 limiter=45/1
[underlying] conId=416904 SPX/IND
[chain] reqSecDefOptParams 返回 6 片
[slice] expiry=20260911 class=SPXW strikes=744 exchange=SMART
[window] 36 档  (7105.0, 7110.0)..(7275.0, 7280.0)
[subscribe] wall=7.017s total=66 add=66 failed=6 throttle=0
[recenter]  wall=3.529s drop=18 add=24 total=72 throttle=0
[errors] [200, 2104, 2119, 10090, 10167]
```

- 该探针**复用项目自身的** `IbkrGateway` / `ContractFactory` / `ChainResolver` /
  `SubscriptionManager`，**仅在内存里覆盖 `port=4002` 与 `client_id=98`**，
  不改任何配置文件。
- **throttle 触发 0 次** → 订阅与退订路径在真实链路上不触碰桶上限。
- `[errors]` 中 **无 100、无 300** → 未触发任何限流类错误。

**C. 源码证据**

- `ib_async/client.py:85-86` —— `MaxRequests = 45` / `RequestsInterval = 1`
- `ib_async/client.py:323-352` —— `sendMsg` 的滑动窗口 + `_msgQ` 积压 + `call_at` 重发
- `ib_async/ib.py:2124-2126` —— `qualifyContractsAsync` 用
  `asyncio.gather(*[self.reqContractDetailsAsync(c) for c in contracts])`
  **并发**发出全部请求 → `qualify_batch_size=40` 是**瞬时 burst**，不是流式
- `ib_async/ib.py:243+` —— `IB.events` 元组**不含** `throttleStart/End`，
  二者只挂在 `Client` 上
- `acquisition/ibkr_gateway.py:66-69` —— 读 `qualify_batch_size` / `qualify_batch_interval_s`
- `acquisition/subscription_manager.py:82` —— 读 `min_request_interval_s`
- `acquisition/subscription_manager.py:273 / 285` —— `await asyncio.sleep(self._min_interval)`
  位于**请求之后**，即无"请求前取令牌"，只是事后降速

**D. 基线自检**

- `python run.py --check` → `结果: 全部通过`（10/10；69 文件 / 最长 395 行 /
  158 处取键调用全部落在声明的配置文件里 / 未发现模块级硬编码常量，显式例外 7 条）
- 改 `port` 后**复跑一次**，仍 `结果: 全部通过`。

**E. 联通验证（端口改为 4002 之后）**

- `python run.py --live`（真实入口，读真实配置）→
  `09:28:04 启动 delayed` → `09:28:15 流水线已就绪`（**11 秒**）；
  `grep -oE "Error [0-9]+" | sort | uniq -c` → **72 Error 10090**，
  **无 100 / 300 / 200**
- `python tools/ws_probe.py`（服务运行中）→ 20 项中 **19 ok / 1 FAIL**；
  FAIL 项为 `矩阵含有效数值 0 格`，经查为盘前单桶冷启动的预期行为
  （`heatmap_engine.py::_row_values` docstring 已声明），非联通问题

## 处置：端口修正 + 联通验证（KAI 指派，已完成）

**改动**：`config/ibkr.json` 的 `port` `7497` → **`4002`**，并同步 `_comment`
（说明当前值指向 IB Gateway 模拟盘）。这是本会话**唯一的配置改动**，
未触碰任何 `.py`。

**联通验证 A —— 项目真实入口 `run.py --live`**（读真实配置，无任何覆盖）：

```
09:28:04 INFO pipeline 启动 delayed | 到期 20260911 | 会话 {... 'is_open': False ...}
09:28:04 INFO pipeline 界面地址 http://127.0.0.1:8060/ | 行情通道 ws://127.0.0.1:8060/ws
09:28:15 INFO pipeline 流水线已就绪
```

- 启动到就绪 **11 秒**；错误码统计 **只有 72 × Error 10090**，
  **无 Error 100、无 Error 300、无 Error 200**。
- `72` 恰好等于订阅条数（与下方 ws_probe 的 `72/92` 吻合）—— 即 72 条期权订阅
  每条一个"延迟数据可用"提示，源于 paper 账户无实时 OPRA 权限。
- 上一轮探针里的 Error 200 × 6 本次**未复现**，确认那是探针自造的合约范围问题。

**联通验证 B —— 端到端 `tools/ws_probe.py`**（服务运行中）：

```
已连接 ws://127.0.0.1:8060/ws，抓取 10 帧
[ok] 帧序号单调递增  69 → 77
[ok] 会话块含到期日  20260911
[ok] 健康块含连接状态  degraded / delayed
[ok] 订阅数未超 IBKR 上限 100  72/92
[ok] 热力图行数 > 0  36 档
[ok] 最新 Skew 有定义  25Δ = 10.339
[ok] 25Δ Put 行权价低于现价  7538.85 < 7592.3
[ok] 网格点明细非空  36 条
[FAIL] 矩阵含有效数值  0 格
末帧摘要: spot=7592.3 | 载荷 9,678 字节
```

**唯一 FAIL 项经查证为盘前冷启动的预期行为，不是缺陷**：热力图存的是
**ΔIV（差分）**，`features/heatmap_engine.py::_row_values` 的 docstring 明确写着
"只有第 0 桶时，差分天然全为空"。本次运行时刻 09:28、`is_open: False`（开盘前），
`bucket_index=0` 且仅 1 个时间桶，差分必然全空 —— 探针自身的
`[ok] 热力图列数随时间增长 1 → 1 桶` 也印证了只有 1 桶。
**开盘并累积 ≥2 个时间桶后该项才会通过**（`ws_probe` 在 sim 模式下快进时间，故能全绿）。

## 真实链接 + 前后端联调验证（KAI 指派，已完成）

时间：2026-09-11 09:53（**已开盘**，`is_open: True`，`bucket_index: 23`）

**服务**：`run.py --live` → `09:53:03 启动 delayed` → `09:53:17 流水线已就绪`（**14 秒**）。

**四项检查全过**：

| 检查 | 结果 | 关键读数 |
|---|---|---|
| `tools/ws_probe.py` | **全部通过** | 72/92 订阅、36 档 × 25 桶、**36 格有效数值**、25Δ=3.301、spot=7670.37、载荷 15,784 字节 |
| `tools/check_web_contract.py` | **全部通过** | DOM id 20 引用全存在；CFG 26 条全存在；载荷 43 条字段后端全在发 |
| `tools/check_page_render.py` | **全部通过** | 真 Chrome：热力图 36 档 × 25 桶 · **36 格** · 色标 ±0.50；Skew 2 点；2 canvas；现价 7671.1 |
| HTTP 静态资源 | **全部 200** | `/` `/app.js` `/heatmap.js` `/skew.js` `/ws_client.js` `/config.js` `/style.css` `/vendor/echarts.min.js` `/health` |

**页面实拍**（Chrome headless，存 `artifacts/panel_live_20260911.png`）：顶栏现价 7699.1、
ATM IV 15.70/16.83、25Δ Skew **+3.30**、状态 **connected · delayed**、72/92 订阅、错误 0；
左面板热力图 36 档 × 25 桶有内容；右面板 Skew 曲线 2 点；底部日志"行情服务已就绪"。

**踩到的坑（重要）**：服务启动后 **<1 分钟**跑 `ws_probe` 会报
`[FAIL] 矩阵含有效数值 0 格` —— **这不是缺陷**。热力图存的是 **ΔIV 差分**，
需要**至少两个时间桶都有值**才能算出差分；服务冷启动只写了当前桶
（本次是第 23 桶），要跨过下一个桶边界（约 1 分钟）才会有值。
**复跑即全过**：09:53:30 跑 → 0 格；09:54:5x 跑 → **36 格**。
同一次 `check_page_render`（跑得更晚）已报 36 格，两处证据互相印证。

顺带发现 `heatmap_engine.py::_row_values` 的 docstring **措辞不精确**：
写的是"只有**第 0 桶**时，差分天然全为空"，实际条件是
"**只有一个桶有值**时" —— 冷启动/重启时当前桶往往不是第 0 桶（本次是第 23 桶）。
**行为正确，仅注释与事实不符。**

## 处置：限速桶显式化 + 观测（KAI 指派，已完成）

KAI 原话：**"限速桶显式化（把 45 msg/s 从库隐式默认值变成配置项 + 观测
throttleStart/End）"**。

### 做了什么

1. **进配置** —— `config/ibkr.json` 新增
   `rate_limit_max_requests: 45` / `rate_limit_interval_s: 1.0`，
   并加 `_rate_limit_comment` 写明官方规则（行数÷2、Error 100、3 次断连）。
2. **显式写入** —— 新文件 `acquisition/rate_limit_watch.py::RateLimitWatch`，
   `apply()` 把配置写进 `ib.client.MaxRequests` / `RequestsInterval`
   （库的类属性默认值不再被依赖）。
3. **观测** —— `apply()` 同时挂 `ib.client.throttleStart` / `throttleEnd`
   （`IB.events` 不含这两个，`IB` 也不转发，**必须直接挂 client**）；
   `snapshot()` 产出 `RateLimitStatus`，经 `IbkrGateway.rate_limit` →
   `FeedStatus.rate_limit` → `HealthBlock.rate_limit` → 帧 JSON 的
   `health.rate_limit`。
4. **消歧命名** —— `SubscriptionManager` 的 `throttled` → `in_backoff`、
   `throttle_events` → `limit_events`、`note_throttled()` → `note_limit_hit()`；
   载荷里原 `health.throttled` 拆成 `health.rate_limit`（库层消息桶）与
   `health.sub_limit_backoff`（IBKR Error 300 退避）。
5. **机械校验** —— `tools/selfcheck_config.py` 新增检查 **[11]**，四条硬规则：
   容量 ≥ 1（0 是"关闭限速"的开关值）、窗口 > 0（0 会让窗口永不淘汰）、
   容量 ≤ 官方上限（100 ÷ 2 = 50）、容量 ≥ `qualify_batch_size`；
   外加一条节奏规则：桶速率 ≥ `1 / min_request_interval_s`。
   自检由 10 项变 **11 项**。
6. **顺手删掉一处重复真相** —— `contracts/tick.py::FeedStatus.with_message()`
   **零调用点**，且把 10 个字段名逐一重抄（每加字段要改两处，漏一处静默丢字段）。
   整段删除。

### 为什么不把桶建在项目侧

桶只**观测**，不在项目里重建第二个：库是唯一的限流者。两个桶互相不知情，
容量对不上时反而更容易撞上 Error 100（3 次即断连）。

### 为什么不把桶容量从订阅容量派生出来

项目硬约束第 5 条禁止配置文件之间互相引用，`ibkr.json` 不能去读
`subscription.json` 的行数。所以联动交给**检查器读两个文件**完成
（检查 [11] 用 `IBKR_SUBSCRIPTION_LIMIT / IBKR_MESSAGES_PER_LINE`），
配置本身保持零耦合。

### 关键实测

```
# 观测路径非空转验证（artifacts/falsify_rate_limit_watch.py.txt）
裸 IB() 的库默认值确实是 45 / 1s        MaxRequests=45 RequestsInterval=1
传 12/0.5 后 apply()                    MaxRequests=12 RequestsInterval=0.5   ← 配置真的驱动桶
真连 IBKR 突发 200 条：
  突发后  events=1  throttling=True   total_s=0.002
  排空后  events=1  throttling=False  total_s=4.004                          ← 事件真的接上了
  disconnect 后 throttling 归假

# 实盘冷启动全程（artifacts/live_rate_limit_probe.py.txt）
health 键 = connection, last_tick_age_s, messages, mode, rate_limit,
            store_cells, sub_limit_backoff, subscribed, subscription_cap,
            ticks_dropped, ticks_received
rate_limit = {"capacity":45,"interval_s":1.0,"events":0,
              "throttling":false,"throttled_total_s":0.0}
订阅 72/92 · connected · delayed
日志: INFO ibkr.rate_limit 出站限速桶显式设为 45 条 / 1s（不依赖 ib_async 的类属性默认值）
```

**结论：一次完整的实盘冷启动（40 条一批的 qualify + 72 条订阅）没有把桶填满，
`throttleStart` 一次都没跳 —— 45 条/s 对当前负载是宽的。**
（对照：审计轮的 90 条瞬时突发会跳 1 次。差别在于订阅路径被
`min_request_interval_s=0.05` 摊成了 20 条/s，而 qualify 是 40 条一批的瞬时并发。）

### 自检 [11] 的非空转验证

```
容量 60 超官方上限 50     → FAIL  rc=1
容量 0（会静默关掉限速）   → FAIL  rc=1（连带 2 条级联）
滑动窗口 0               → FAIL  rc=1
qualify 单批 50 超桶 45   → FAIL  rc=1
订阅节奏 200/s 超桶 45/s  → FAIL  rc=1
恢复后复跑                → 全部通过 rc=0；两个配置文件逐字节还原
```

### 未做（明确留白，KAI 已决策）

- **限速桶读数不上前端（KAI 决定：不上）。** 数据已到帧里（`health.rate_limit`），
  日志也有 `throttleStart` 的 WARN / `throttleEnd` 的 INFO，但**刻意不改 `web/`**。
- **`acquisition/feed_service.py` 不拆分（KAI 决定：不动）。** 当前 396/400（余 4 行）。
  → **仍然成立的约束**：下次往 `feed_service.py` 加任何字段/行之前，必须先解决
  行数上限（拆文件或压缩别处），不能硬加。
- **模拟模式不做桶** —— `SyntheticFeed.status()` 不传 `rate_limit`，取
  `RateLimitStatus()` 默认值（全 0），语义是"不适用"（sim 无 IBKR 连接）。

## 本地站点交付（KAI 指派：给出前端本地网站）

```bash
cd "E:/US.market/SPXW SWATCH/spxw_swatch"
NO_PROXY=127.0.0.1,localhost <VENV>/python.exe -u run.py --live
# 界面 http://127.0.0.1:8060/   行情通道 ws://127.0.0.1:8060/ws
```

启动实测（2026-09-11 10:27）：

```
10:27:36 INFO pipeline   启动 delayed | 到期 20260911 | is_open=True | bucket_index=57
10:27:36 INFO pipeline   界面地址 http://127.0.0.1:8060/ | 行情通道 ws://127.0.0.1:8060/ws
10:27:37 INFO ibkr.rate_limit  出站限速桶显式设为 45 条 / 1s（不依赖 ib_async 的类属性默认值）
```

页面验证（约 2 分钟后，热力图已跨过时间桶边界）：

```
ws_probe            → 全过；热力图 36 档 × 60 桶、25Δ=3.001、spot=7664.94、载荷 23,675 字节
check_page_render   → 全过；36 档 × 60 桶 · 72 格 · 色标 ±0.50；Skew 3 点 · 当前 +2.99 ·
                      ATM 14.93；connected · delayed；2 canvas；顶栏现价 7664.8
实拍                 → artifacts/panel_live_20260911_1029.png
```

⚠️ **截图时踩到的坑**：Chrome `--screenshot=` 给**相对路径**会失败并报
`Failed to write file ...: The system cannot find the path specified. (0x3)`，
而 **exit code 仍是 0** —— 不 `ls` 一下文件就误判成功。必须给绝对路径。

## 缺陷清单

1. **[已处置] 端口配置错误** —— `config/ibkr.json:4` `port: 7497` 是 TWS 模拟盘；
   IB Gateway 模拟盘在 **4002**（实盘 4001）。实测 7497 被拒。
   → **2026-09-11 已改为 `4002` 并实测联通（见上）。**
2. **[已处置] 桶容量是库的隐式默认值** —— 现为 `config/ibkr.json` 的
   `rate_limit_max_requests` / `rate_limit_interval_s`，由
   `RateLimitWatch.apply()` 显式写入实例属性；缺键时 `loader` 直接抛
   `ConfigError`。**已证伪**：传 12/0.5 后 `client.MaxRequests == 12`。
3. **[已处置] 桶状态零观测 + 命名误导** —— 已挂 `throttleStart` / `throttleEnd`，
   读数贯通到 `health.rate_limit`；`SubscriptionManager.throttled` 已改名
   `in_backoff`，载荷里拆成 `rate_limit`（桶）与 `sub_limit_backoff`（Error 300）。
   **已证伪**：突发 200 条 → `events=1`、排空后 `throttled_total_s=4.004s`。
4. **[已处置] `qualify_batch_size=40` 与 45/s 桶的隐式耦合** —— 自检 [11]
   强制 `qualify_batch_size ≤ 桶容量`（当前 40 ≤ 45，余量 5），耦合从
   "隐式"变成"机械校验"。启动序列前置消息的叠加仍未量化，但订阅路径已被
   `min_request_interval_s` 摊到 20 条/s，实测冷启动桶事件 0 次。
5. **[已处置] 官方"速率 = 行数/2"规则未落地** —— 自检 [11] 用
   `IBKR_SUBSCRIPTION_LIMIT(100) / IBKR_MESSAGES_PER_LINE(2)` 校验桶容量。
   桶容量与订阅容量仍分处两个配置文件（要求第 5 条禁止跨文件引用），
   联动由**检查器读两个文件**完成，不是配置派生。
6. **[未处置·低] `EXEMPT_CONSTANTS` 不完整** —— `feed_service.py::_IGNORED_CODES`
   是 `frozenset({...})`，`_literal_repr` 对 `ast.Call` 返回 `None` →
   **既扫不到也豁免不到**（漏检，非豁免）。
7. **[未处置·低] `_IGNORED_CODES` 缺 2119 / 10090** —— 实测二者均到达；
   第二轮实盘 10090 复现 72 次（paper 账户无实时 OPRA 权限）。
8. **[未处置·中] `iter_py_files()` 扫描范围过宽**（第一轮归档探针时实测踩到）——
   `tools/selfcheck_core.py:102-104` 用 `ROOT.rglob("*.py")`，会把 `notes/`、
   `.workbuddy-ai/` 等**非源码目录**下的 `.py` 一并纳入检查。第一轮把两条探针
   放进 `notes/.../artifacts/` 后，检查 [10] 立刻报 4 条 FAIL
   （`TODAY = '20260911'` / `HOST = '127.0.0.1'`），其中 2 条来自
   `.workbuddy-ai/tmp/` —— **连隐藏目录也在扫描范围内**。
   处置：探针改后缀为 `.py.txt`（证据仍可读、可复现），重跑 `--check` 恢复
   10/10。**第二轮改把临时探针写在工程目录之外**
   （`C:/Users/Lenovo/.workbuddy-ai/tmp/`），从根上绕开该缺口。
   该检查器缺口本身未修，仅登记。
9. **[未处置·低] `heatmap_engine.py::_row_values` docstring 措辞不精确** —— 写的是
   "只有**第 0 桶**时，差分天然全为空"，实际条件是"**只有一个桶有值**时"。
   冷启动/重启时当前桶往往不是第 0 桶（本次实测是第 23 桶），
   **行为正确，但注释会误导排查方向**（按字面理解会以为"只有盘前才有此现象"）。

原 **[待查] Error 200 × 6** 已查明：是探针自造的合约范围问题，
`run.py --live` 两次运行均未复现（错误码只有 72 × Error 10090）。

## 硬编码核实（对应项目硬约束第 3 条）

- `run.py --check` 检查 [10] **通过**：模块级无硬编码常量，7 条例外逐条登记理由。
- **但存在"隐式契约"缺口**：真正决定限速的 `45 msg/s` 既不在 `config/`，
  也不在豁免表里 —— 它是第三方库的默认值。项目的限速行为**实际由库版本决定**，
  升级 `ib_async` 可能静默改变速率上限。这与"禁止硬编码"的精神相悖
  （硬编码至少是显式的，隐式默认值连"可见"都做不到）。
- 覆盖边界诚实声明：检查 [10] 只覆盖**模块级字面量**，函数体内的魔法数字不在
  范围内；`frozenset({...})` 这类调用式构造也在覆盖之外。

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 本会话确立六个可复用的事实，均来自实测而非文档推断：
1. **限速桶在库层，不在项目层** —— 审计"项目有没有限速"时，必须先查
   `ib_async/client.py` 的 `MaxRequests`，否则会得出"项目没有限速"的错误结论。
2. **`IB.events` 不转发 `throttleStart/End`** —— 想观测桶必须直接拿
   `ib.client` 挂事件，这条路径在官方文档里没有，只能读源码。
3. **可证伪的桶验证法** —— 用"30 条 vs 90 条"的 `peak_msgQ` 对比来证明桶生效
   （`0` vs `45`），比"看有没有报错"强得多：不报错不等于桶在工作。
4. **`Client.MaxRequests` 是类属性，`reset()` 不清它** —— 写一次实例属性即可覆盖
   整条连接的生命周期；每次 `connect()` 都新建 `IB`/`Client`，所以不会重复挂事件。
5. **"配置驱动了桶"要单独证伪** —— 配置值和库默认值都是 45，直接断言
   `MaxRequests == 45` 是空转。必须传一个**非默认值**（本会话用 12/0.5）再断言，
   否则"配置生效"与"落回默认值"两种情形无法区分。
6. **观测路径本身也要证伪** —— `events=0` 有两种可能：桶真没满，或者事件压根没挂上。
   本会话用 200 条突发（`reqMarketDataType`，语义无害且不属于 IBKR 官方计速的
   六类请求，不消耗官方配额）把 `events` 顶到 1，才排除后者。
建议把第 3/5/6 条沉淀为常驻回归（当前仓库无任何覆盖限速的测试）。

NOTES-PATHS: 13 个文件（会话根 5 件 + 证据 6 件 + 上下文索引 3 件，上下文索引见下）
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/startup.md`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/project_state.md`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/open_tasks.md`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/meta.yaml`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/rate_probe.py.txt`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/e2e_probe.py.txt`
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/panel_live_20260911.png`
  （实盘页面实拍：顶栏 25Δ Skew +3.30 / connected · delayed，热力图 36 档 × 25 桶，Skew 曲线 2 点）
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/falsify_rate_limit_check.py.txt`
  （第二轮：自检 [11] 五条规则的非空转验证）
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/falsify_rate_limit_watch.py.txt`
  （第二轮：桶容量是否真由配置驱动 + throttleStart/End 是否真接上）
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/live_rate_limit_probe.py.txt`
  （第二轮：实盘冷启动全程读 `health.rate_limit`）
- `notes/sessions/2026-09-11/ibkr-rate-limit-audit/artifacts/panel_live_20260911_1029.png`
  （第三轮：限速桶显式化之后的页面实拍。现价 7663.2、ATM IV 14.90、25Δ Skew **+3.06**、
  **connected · delayed**、72/92 订阅、帧 845 · 丢弃 0；热力图 36 档 × 61 桶 · **188 格**、
  色标 ±0.50；Skew 曲线 4 点。两块面板均出图）
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

CHANGED-PATHS: 两轮合计 15 处

第一轮（2026-09-11，只读审计 + 端口处置）：
- `config/ibkr.json`（改）—— `port` `7497` → `4002`，`_comment` 同步
  （**当时唯一的配置改动；未触碰任何 `.py`**）
- `notes/`（新增 + 改）—— 新增会话目录
  `notes/sessions/2026-09-11/ibkr-rate-limit-audit/`（7 文件）；
  更新 `notes/context/` 3 个索引文件

第二轮（2026-09-11，KAI 指派"限速桶显式化"，**改了生产代码**）：
- `config/ibkr.json`（改）—— 新增 `rate_limit_max_requests: 45` /
  `rate_limit_interval_s: 1.0` / `_rate_limit_comment`
- `acquisition/rate_limit_watch.py`（**新增**）—— `RateLimitWatch`：
  `apply()` 显式写 `Client.MaxRequests` / `RequestsInterval` 并挂
  `throttleStart` / `throttleEnd`；`snapshot()` 产出 `RateLimitStatus`
- `acquisition/ibkr_gateway.py`（改）—— `connect()` 调 `apply()`；
  新增 `rate_limit` 属性；`disconnect()` 结算限速窗口
- `acquisition/subscription_manager.py`（改）—— 消歧改名
- `acquisition/feed_service.py`（改）—— `status()` 接 `rate_limit` /
  `sub_limit_backoff`（396 行，距 400 上限仅 4 行）
- `contracts/tick.py`（改）—— 新增 `RateLimitStatus`；`FeedStatus.throttled`
  拆成 `rate_limit` + `sub_limit_backoff`；**删除零调用点的
  `FeedStatus.with_message()`**（它把 10 个字段名重抄一遍，是重复真相）
- `contracts/frame.py` / `contracts/__init__.py`（改）
- `state/market_state.py` / `serialization/frame_encoder.py` /
  `simulator/synthetic_feed.py`（改）
- `tools/selfcheck_core.py`（改）—— `REQUIRED_KEYS["ibkr"]` 加 2 键
- `tools/selfcheck_config.py`（改）—— 新增检查 [11]
- `tools/selfcheck.py`（改）—— 注册 [11]，自检 10 项 → **11 项**

探针以 **`.py.txt`** 后缀归档 —— 因为 `iter_py_files()` 的 `rglob("*.py")`
会扫到 `notes/` 下的 `.py`（见缺陷 8），保留 `.py` 后缀会让 `--check` 变成
4 项不通过。本轮临时探针写在工程目录之外
（`C:/Users/Lenovo/.workbuddy-ai/tmp/`），验证完保留原文件备查。

VALIDATION-SUMMARY: `run.py --check` **11/11 通过**（第一轮 10/10；第二轮新增 [11] 后 11/11）。
第一轮归档探针后曾因缺陷 8 变为 4 项不通过，改后缀后恢复 10/10（实测记录在案）。

第一轮实质验证 **7 项**：
1. 桶阈值与突发行为（30 vs 90 条，`peak_msgQ` 0 vs 45）；
2. 端到端订阅/退订探针（72 条，throttle 触发 0 次，无 Error 100/300）；
3. `run.py --live` 真实入口联通（11 秒就绪，错误码仅 72 × Error 10090）；
4. `ws_probe` 端到端（72/92 订阅、spot=7592.3、25Δ=10.339）；
5. 开盘后 `ws_probe` 复跑（36 档 × 25 桶、**36 格有效数值**、25Δ=3.301）；
6. `check_web_contract` 前端契约（DOM id 20 / CFG 26 / 载荷字段 43 全对上）；
7. `check_page_render` 真浏览器渲染（热力图 36 格 · 2 canvas · 现价 7671.1）
   ＋ HTTP 静态资源 9 条全 200 ＋ 页面实拍截图。

第二轮实质验证 **9 项**：
1. **自检 [11] 非空转验证** —— 5 个扰动用例（容量 60 超官方上限 / 容量 0 /
   窗口 0 / qualify 单批 50 超桶 / 订阅节奏 200 条每秒）**全部 FAIL，rc=1**；
   恢复后复跑 rc=0，两个配置文件**逐字节还原**；
2. **桶容量是否真由配置驱动** —— 传 12/0.5 后 `client.MaxRequests == 12`
   （对照：裸 `IB()` 的库默认值确实是 45/1）；
3. **throttleStart/End 是否真接上** —— 真连 IBKR 突发 200 条 →
   `events=1`、`throttling=True`；排空 7s 后 `events=1`、`throttling=False`、
   `throttled_total_s=4.004`；`disconnect` 后 `throttling` 归假；
4. **实盘冷启动全程** —— `health.rate_limit = {capacity:45, interval_s:1.0,
   events:0, throttling:false, throttled_total_s:0.0}`，72/92 订阅、
   `connected · delayed`；服务端日志出现
   `INFO ibkr.rate_limit 出站限速桶显式设为 45 条 / 1s（不依赖 ib_async 的类属性默认值）`；
   **桶事件 0 次**；
5. **消歧改名已在载荷生效** —— 每帧都有 `health.rate_limit`、
   `health.sub_limit_backoff`，且 `health.throttled` **已消失**；
6. 本地回归 5 个：`check_clock_protocol` / `check_session_rollover` /
   `check_side_flip` / `check_tick_router` / `check_subscription_qualify` 全过；
7. `smoke_test.py` 全过（帧 25,855 字节，36 条 cells，无 NaN）；
8. 实盘服务下 `check_web_contract`（DOM 20 / CFG 26 / 载荷 43）全过；
9. 实盘服务下 `check_page_render`（热力图 36 档 × 47 桶 · 108 格 · 色标 ±0.50、
   Skew 4 点、2 canvas）＋ `ws_probe`（35 档 × 50 桶、**210 格有效数值**、
   25Δ=2.936、spot=7669.61、无 NaN）全过。

**未验证**：tick 回流后的 106 模型 Greeks 落地（paper 账户无实时 OPRA 权限，
只返回延迟数据）；限速桶读数未上前端（载荷与日志里有，`web/` 一个字段都没读）。

OPEN-RISKS: 3 条（原第 1–3 条已于第二轮处置，见"处置"节）
1. **[低] 联通与限速无常驻回归** —— 两轮的联通/限速验证全靠手工跑
   `run.py --live` + 三个探针，仓库 `tools/` 里没有覆盖实盘联通或限速的测试。
   第二轮的三个探针仍留在工程外的临时目录，**未**收进 `tools/`。
2. **[中] `acquisition/feed_service.py` 只剩 4 行余量（396/400）** ——
   下一次给它加字段就会撞硬上限，届时须先按"单一职能"拆文件。
3. **[中] 限速桶读数未上前端** —— 数据已经到帧里了，但 `web/` 没读；
   要上顶栏须同时改 `web/app.js` 与 `tools/check_web_contract.py::PAYLOAD_PATHS`。
   （原"Error 200 × 6"已查明为探针自造的合约范围问题，两轮 `--live` 均未复现。）

FAST-FAIL-CHECK: 通过 —— 桶容量缺键时 `loader` 直接抛 `ConfigError`，不回落默认值；
   配置自相矛盾（桶容量 < qualify 批量、桶容量 < 订阅节奏）由自检 [11] 直接 FAIL，
   而不是运行时静默变慢。
NO-COMPAT-BRANCH: 通过 —— 未引入任何兼容分支。旧字段名 `throttled` 是**直接改名**，
   没有留"新旧双写"或 `if 旧名 in payload` 之类的过渡分支。
NO-ROLLBACK-PATH: 通过 —— 未新增任何回滚路径。
NO-PATCH-BANDAGE: 通过 —— 第一轮：端口不匹配是**配置错误**，修法是**改配置**
   （`port: 7497` → `4002`），不是在代码里加 fallback 端口探测。第二轮：桶容量
   是**配置缺失**，修法是**进配置 + 显式写入 + 加机械校验**，不是加
   `if MaxRequests > 45: MaxRequests = 45` 这类夹带默认值的兜底。
   桶**不在项目侧重建第二个** —— 两个桶互相不知情反而更容易撞 Error 100。
NO-FALLBACK-BEHAVIOR: 通过 —— `RateLimitWatch` 只在配置缺失时抛错，不静默降级；
   限速桶本身仍由库唯一实现，项目只观测、不接管。

TRIGGER-PATHS: N/A:本项目为 Python，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check`，已在 COMMAND-EVIDENCE 记录
