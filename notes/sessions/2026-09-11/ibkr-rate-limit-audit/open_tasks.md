# Open Tasks — ibkr-rate-limit-audit

## Active

- [ ] **[低] 补 `EXEMPT_CONSTANTS`** —— 登记 `feed_service.py::_IGNORED_CODES`；
      并考虑修 `_literal_repr` 让 `frozenset({...})` / `tuple((...))` 等
      调用式字面量构造也能被扫描（当前是**漏检**，不是豁免）。
- [ ] **[低] 补 `_IGNORED_CODES`** —— 加入 `2119`、`10090`，避免权限类消息刷面板。
      （10090 本轮实盘复现 72 次，全是 paper 账户无实时 OPRA 权限。）
- [ ] **[低] 联通与限速无常驻回归** —— 本会话的联通验证靠手工跑
      `run.py --live` + `ws_probe`；仓库无覆盖实盘联通或限速的测试。
      本轮新增的三个探针（见 artifacts）也仍是手工脚本，**未**收进 `tools/`。
- [ ] **[低] 修 `heatmap_engine.py::_row_values` 的 docstring 措辞** ——
      写的是"只有**第 0 桶**时差分全为空"，实际条件是"**只有一个桶有值**时"。
      冷启动/重启时当前桶常非第 0 桶（实测是第 23 桶）。行为正确，仅注释误导排查。

## 已决策（KAI，2026-09-11）—— 不要再当待办重提

- **限速桶读数不上前端。** 数据已到帧里（`health.rate_limit`），日志也有
  `throttleStart` 的 WARN / `throttleEnd` 的 INFO，但**刻意不改 `web/`**。
  → 对应 `notes/context/open_tasks.md` 里原「限速桶读数未上前端」条目已关闭。
- **`acquisition/feed_service.py` 不拆分。** 当前 396/400（余 4 行），KAI 决定保持现状。
  → **仍然成立的约束**：下次往 `feed_service.py` 加任何字段/行之前，
  必须先解决行数上限（拆文件或压缩别处），不能硬加。

## Stale / Needs Verification

- [ ] **实盘 tick 回流后的 106 模型 Greeks 落地** —— 2026-09-11 **前后端已全链路实测通过**：
  - `run.py --live`（`port=4002`）联通成功，11～14 秒就绪，错误码仅 72 × Error 10090；
  - `ws_probe` 全过（35 档 × 50 桶、**210 格有效数值**、25Δ=2.936、spot=7669.61）；
  - `check_web_contract` 全过（DOM 20 / CFG 26 / 载荷 43 全对上）；
  - `check_page_render` 全过（真 Chrome，热力图 36 档 × 47 桶 · 108 格、2 canvas）；
  - HTTP 静态资源 9 条全 200；页面实拍见 `artifacts/panel_live_20260911.png`。

  仍**未验证**：tick 回流后 `tickOptionComputation`（MODEL_OPTION）是否落地
  —— paper 账户无实时 OPRA 权限，只返回延迟数据（Error 10090）。
  另：**服务冷启动后 <1 分钟跑 `ws_probe` 会报"矩阵 0 格"，属预期**
  （ΔIV 是差分，需 ≥2 个时间桶都有值，约等 1 分钟）。
- [ ] **`notes/` 与 `.workbuddy-ai/memory/` 是否收敛为一套** —— 待定。

## Closed

- [x] **[高] 把限速桶显式化** —— 2026-09-11：`config/ibkr.json` 新增
      `rate_limit_max_requests: 45` / `rate_limit_interval_s: 1.0`；
      `RateLimitWatch.apply()` 显式写 `ib.client.MaxRequests` /
      `RequestsInterval`。**已证伪验证**：库默认 45/1 → 传 12/0.5 后
      `client.MaxRequests == 12`（`artifacts/falsify_rate_limit_watch.py.txt` 段 A）。
- [x] **[高] 观测桶状态 + 消歧命名** —— 2026-09-11：新增
      `acquisition/rate_limit_watch.py::RateLimitWatch`，挂 `Client.throttleStart`
      / `throttleEnd`（`IB.events` 确实不转发）；读数经
      `FeedStatus.rate_limit` → `HealthBlock.rate_limit` → 帧 JSON 的
      `health.rate_limit` 贯通。`SubscriptionManager.throttled` 改名
      `in_backoff`、`throttle_events` → `limit_events`、`note_throttled()` →
      `note_limit_hit()`；载荷里原 `health.throttled` 拆成
      `health.rate_limit`（桶）与 `health.sub_limit_backoff`（Error 300）。
      **已证伪验证**：真连 IBKR 突发 200 条 → `events=1`、`throttling=True`、
      排空后 `throttled_total_s=4.004s`（同文件段 B）。
- [x] **[中] 解除 `qualify_batch_size=40` 与 45/s 桶的隐式耦合** ——
      2026-09-11：由新增自检 **[11]** 强制 `qualify_batch_size ≤ 桶容量`。
- [x] **[中] 把"速率 = 行情行数/2"落地** —— 2026-09-11：自检 [11] 用
      `IBKR_SUBSCRIPTION_LIMIT / IBKR_MESSAGES_PER_LINE` 校验桶容量。
      **注意**：桶容量与订阅容量仍分别写在 `ibkr.json` / `subscription.json`
      （要求第 5 条禁止跨文件引用），联动由**检查器读两个文件**完成 ——
      不是靠配置派生。
- [x] **[阻断] 修 `config/ibkr.json` 的 `port`** —— 2026-09-11：`7497` → **`4002`**
      （IB Gateway 模拟盘），`_comment` 同步。双路实测联通：`run.py --live`
      11 秒就绪、错误码仅 72 × Error 10090（无 100/300/200）；`ws_probe`
      72/92 订阅、spot=7592.3、25Δ=10.339、载荷 9,678 字节。
- [x] **确认限速桶是否存在** —— 2026-09-11：**存在，在 `ib_async` 库层
      （45 msg/s），实测生效**；项目侧无自建桶，只有固定间隔节流。
      证据见本会话 `handoff.md` 与 `artifacts/`。
- [x] **查证 IBKR 官方限速与配额** —— 2026-09-11：通用上限 = 行情行数/2
      （默认 50 msg/s），超限 Error 100，3 次违规断连。
