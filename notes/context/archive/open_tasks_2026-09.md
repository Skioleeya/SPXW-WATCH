# Open Tasks Archive — 2026-09

历史任务列表归档。当前活动任务见 `notes/context/open_tasks.md`。

---

## 2026-09-11 / session-rollover-and-render-fix（当时的 Stale / Needs Verification）

- [ ] **实盘"连上之后能否收到数据"** —— 需真实 TWS / IB Gateway，当时无法验证。
      已验证：连接被拒时抛出可操作的 `ConnectionFailed`。未验证：合约确认、
      订阅、tick 路由、106 模型 Greeks 的实际到达。
- [ ] **`notes/` 与既有证据体系并行** —— 本项目原用 `.workbuddy-ai/memory/` +
      README「已知边界」+ 回归工具承载证据，`notes/` 是随全局 skill 引入的第二套。
      是否收敛为一套待定。
- [ ] **前端在会话翻篇瞬间会短暂保留上一场的画面** —— 刻意取舍（避免闪白），
      已在 README 记为已知边界。

---

## 2026-09-11 / 当日关闭的任务（归档）

以下均在 2026-09-11 关闭，细节见对应会话根 `notes/sessions/2026-09-11/<task-id>/`。

- [x] **[阻断] 修 `config/ibkr.json` 的 `port`** —— `7497` → **`4002`**，双路实测联通。
- [x] **[高] 把限速桶显式化** —— `rate_limit_max_requests=45` / `rate_limit_interval_s=1.0`。
      已证伪：库默认 45/1 → 传 12/0.5 后 `client.MaxRequests == 12`。
- [x] **[高] 观测桶状态并消歧命名** —— `RateLimitWatch` 挂 `Client.throttleStart/End`；
      载荷拆成 `health.rate_limit` 与 `health.sub_limit_backoff`。
      已证伪：突发 200 条 → `events=1`、排空后 `throttled_total_s=4.004s`。
- [x] **[中] 解除 `qualify_batch_size=40` 与 45/s 桶的隐式耦合** —— 自检 [11] 强制
      `qualify_batch_size ≤ 桶容量`。
- [x] **[中] 把官方"速率 = 行情行数 / 2"落地** —— 自检 [11] 用
      `IBKR_SUBSCRIPTION_LIMIT / IBKR_MESSAGES_PER_LINE` 校验。
- [x] **[中] 收窄 `iter_py_files()` 扫描范围** —— 排除表 `NON_SOURCE_DIRS`。
      已证伪：`notes/__probe__/junk.py`（402 行）→ 有排除时全合规；摘掉排除 → `[FAIL]`。
- [x] **[低] `EXEMPT_CONSTANTS` 登记 + `_literal_repr` 漏检修复** —— 新增
      `LITERAL_CONSTRUCTORS`。已证伪：摘掉条目 → `[FAIL] feed_service.py:43 _IGNORED_CODES`。
- [x] **[低] 补 `_IGNORED_CODES`** —— 加入 `2119`、`10090`。
- [x] **7 个死配置键的去留** —— **4 接线 + 3 删除**，`UNWIRED_IS_FAILURE` → `True`。
- [x] **前端热力图色调改为 `Turbo` + 网格线 `borderWidth: 1`** —— 逐色比对已证伪。
- [x] **[低] 修 `heatmap_engine.py::_row_values` docstring 措辞** —— 纯注释。
- [x] **确认限速桶存在 / 查证 IBKR 官方限速配额** —— 桶在 `ib_async` 库层（45 msg/s）；
      官方上限 = 行情行数/2，超限 Error 100，3 次断连。
- [x] **106 模型 Greeks 落地证实** —— 直接探针证实 MODEL_OPTION 是独立 tick 通道。
- [x] **`notes/` 与 `.workbuddy-ai/memory/` 的收敛方案** —— **2026-09-13 KAI 定**：
      `notes/` 为记录落点，`memory/` 为根路由器（只留指针与跨项目约定）。
