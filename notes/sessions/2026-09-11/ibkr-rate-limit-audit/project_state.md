# Project State — ibkr-rate-limit-audit

ACTIVE_SESSION: 2026-09-11/ibkr-rate-limit-audit
LAST_UPDATED: 2026-09-11（第二轮：限速桶显式化 + 观测）

## 核心结论

**限速桶在 `ib_async` 2.1.0 的库层（`Client.sendMsg` 滑动窗口）。本会话已把它
从"库的隐式默认值"变成"项目配置项 + 运行期可观测"，并把项目里那个同名的
Error 300 退避字段改名消歧。**

| 层次 | 机制 | 阈值 | 来源 |
|---|---|---|---|
| 库级（真正生效的桶） | `Client.sendMsg` 滑动窗口 | **45 条 / 1s** | **`config/ibkr.json` 的 `rate_limit_max_requests` / `rate_limit_interval_s`，由 `RateLimitWatch.apply()` 显式写入** |
| 应用级（项目自配） | `min_request_interval_s` 固定间隔 | 20 req/s | `config/subscription.json:5` |
| 应用级（项目自配） | `qualify_batch_size` + 间隔分片 | 40 条/batch，批间 0.3s | `config/ibkr.json:14-15` |
| 应用级（事后被动） | Error 300 指数退避 | 30s → 300s | `config/subscription.json:8-11` |

## 官方配额（本次查证）

- **通用消息速率上限 = 最大行情行数 / 2**。默认 100 行 → **50 msg/s**。
- 超限错误码 **100**（"Max rate of messages per second has been exceeded"）。
- **3 次违规终止 API 会话**，恢复需重连。
- **计入速率**：`reqMktData` / `cancelMktData` / `reqContractDetails` /
  `reqHistoricalData` / `placeOrder` / `cancelOrder` 等主动请求。
  **不计入**：订阅后 TWS 推送的 tick。
- **同时订阅上限** = 行情行数（默认 100），超限 Error 300。
- **多客户端共享预算**：连同一 TWS/Gateway 的客户端累计计数。
- 历史数据有独立 pacing（60/10min 等），**本项目不涉及**。

## 本轮落地（2026-09-11 第二轮）

| 改动 | 位置 |
|---|---|
| 桶容量成为配置项 | `config/ibkr.json`：`rate_limit_max_requests: 45`、`rate_limit_interval_s: 1.0`（+ `_rate_limit_comment` 写明官方规则） |
| 显式写入 + 观测 | **新文件** `acquisition/rate_limit_watch.py::RateLimitWatch`（`apply()` / `snapshot()` / `close_window()`） |
| 网关接线 | `acquisition/ibkr_gateway.py`：`connect()` 里 `self._rate_limit.apply(ib)`；新增 `rate_limit` 属性 |
| 消歧命名 | `subscription_manager`：`throttled`→`in_backoff`、`throttle_events`→`limit_events`、`note_throttled()`→`note_limit_hit()` |
| 契约 | `contracts/tick.py`：新增 `RateLimitStatus`；`FeedStatus.throttled` → `rate_limit` + `sub_limit_backoff`。`contracts/frame.py::HealthBlock` 同步 |
| 载荷 | `serialization/frame_encoder.py` 新增 `_rate_limit()`，帧里出现 `health.rate_limit` 与 `health.sub_limit_backoff` |
| 机械校验 | `tools/selfcheck_config.py` 新增检查 **[11]**；自检从 10 项变 **11 项** |

### 删掉的一处重复真相

`contracts/tick.py::FeedStatus.with_message()` **零调用点**，且它把 10 个字段名
逐一重抄了一遍 —— 每加一个字段就必须改两处，漏一处就静默丢字段。已整段删除。

## 实测证据（IB Gateway 10.50 @ 4002）

审计轮（只读探针）：

```
[port 7497] 连接失败: ConnectionRefusedError [WinError 1225]   ← 项目当时配置的端口
[port 4002] 连接成功 serverVersion=178                          ← 实际监听端口
[limiter] MaxRequests=45 RequestsInterval=1 → 45 msg/s
[burst below] n= 30 wall=1.651s peak_msgQ=  0 throttle_start=0  ← 未触发桶
[burst above] n= 90 wall=2.725s peak_msgQ= 45 throttle_start=1  ← 桶确实拦下 45 条
```

本轮（观测路径的非空转验证，`artifacts/falsify_rate_limit_watch.py.txt`）：

```
A. 裸 IB() 的库默认值确实是 45 / 1s        MaxRequests=45 RequestsInterval=1
   apply() 后 client.MaxRequests == 12      ← 传 12/0.5，证明配置真的驱动桶
B. 真连 IBKR，突发 200 条 reqMarketDataType：
   突发后: events=1 throttling=True total_s=0.002
   排空后: events=1 throttling=False total_s=4.004
   disconnect 后 throttling 归假
```

本轮（实盘冷启动全程，`artifacts/live_rate_limit_probe.py.txt`）：

```
健康块键: ... rate_limit, sub_limit_backoff, subscribed, subscription_cap ...
rate_limit = {"capacity":45,"interval_s":1.0,"events":0,"throttling":false,"throttled_total_s":0.0}
实测：桶事件 0 次 / 累计被限速 0.0s / 当前在限速 False
订阅 72/92，连接 connected，模式 delayed
服务端日志：10:11:02 INFO ibkr.rate_limit 出站限速桶显式设为 45 条 / 1s（不依赖 ib_async 的类属性默认值）
```

**结论：一次完整的实盘冷启动（40 条一批的 qualify + 72 条订阅）没有把桶填满，
`throttleStart` 一次都没跳。45 条/s 这个容量对当前负载是宽的。**
（对照：审计轮的 90 条瞬时突发会跳 1 次 —— 差别在于订阅路径被
`min_request_interval_s=0.05` 摊成了 20 条/s。）

自检 [11] 的非空转验证（`artifacts/falsify_rate_limit_check.py.txt`）：

```
容量 60 超官方上限 50        → FAIL  rc=1
容量 0（会静默关掉限速）      → FAIL  rc=1
滑动窗口 0                  → FAIL  rc=1
qualify 单批 50 超桶 45      → FAIL  rc=1
订阅节奏 200/s 超桶 45/s     → FAIL  rc=1
恢复后复跑                   → 全部通过 rc=0，配置文件逐字节还原
```

## 缺陷清单（8 条；1–5 已处置）

1. **[已处置] 端口配置错误** —— `port: 7497`（TWS 模拟）→ **`4002`**（IB Gateway 模拟）。
2. **[已处置] 桶容量是库的隐式默认值** —— 现为 `config/ibkr.json` 的
   `rate_limit_max_requests`，并由 `RateLimitWatch.apply()` 显式写入实例属性；
   缺键时 `loader` 直接抛 `ConfigError`。
3. **[已处置] 桶状态零观测 + 命名误导** —— 已挂 `throttleStart/End`，
   读数贯通到 `health.rate_limit`；`SubscriptionManager.throttled` 已改名
   `in_backoff`，载荷里拆成 `rate_limit`（桶）与 `sub_limit_backoff`（Error 300）。
4. **[已处置] `qualify_batch_size=40` 与 45/s 桶的隐式耦合** ——
   自检 [11] 强制 `qualify_batch_size ≤ 桶容量`（当前 40 ≤ 45，余量 5）。
5. **[已处置] 官方"行数/2"规则未落地** —— 自检 [11] 用
   `IBKR_SUBSCRIPTION_LIMIT(100) / IBKR_MESSAGES_PER_LINE(2)` 校验桶容量。
   桶容量与订阅容量仍分处两个配置文件（要求第 5 条禁止跨文件引用），
   联动由**检查器读两个文件**完成。
6. **[未处置·低] `_IGNORED_CODES` 豁免表不完整** —— `frozenset({...})` 的 AST
   形态使检查 [10] 既扫不到也豁免不到（`_literal_repr` 对 `ast.Call` 返回 None）。
7. **[未处置·低] `_IGNORED_CODES` 缺 2119 / 10090** —— 本轮实盘 10090 复现 72 次。
8. **[未处置·中] `selfcheck_core.iter_py_files()` 扫描范围过宽** ——
   `ROOT.rglob("*.py")` 会扫到 `notes/`、`.workbuddy-ai/` 下的 `.py`。

原 **[待查] Error 200 × 6** 已查明：是探针自造的合约范围问题，
`run.py --live` 未复现（错误码仅 72 × Error 10090）。

## NEXT

1. 余下缺陷 6–8 待 KAI 决定处置范围与优先级。
2. 限速桶读数**未上前端**（载荷与日志里都有，`web/` 一个字段都没读）—— 待定。
3. `acquisition/feed_service.py` 只剩 4 行余量（396/400），下次加字段需先拆文件。
4. 开盘后（≥2 个时间桶）复跑 `ws_probe`，确认热力图 ΔIV 非空。
