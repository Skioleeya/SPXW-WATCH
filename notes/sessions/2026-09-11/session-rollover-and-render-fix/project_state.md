# Project State — session-rollover-and-render-fix

## 结论一句话

本会话修掉了两个"探针全绿但实际是坏的"缺陷：**Skew 面板从未渲染成功过**，
以及**跨会话时两个交易日的 IV 被当成同一条序列做差分**。

## 当前代码状态

- 文件数：**61 个 Python 文件**，最长 `tools/selfcheck.py` = 386 行（上限 400）
- `run.py --check`：7 项全过（文件长度 / 依赖方向 / 配置可读 / 配置零耦合 /
  关键配置项 40 项 / 订阅容量 ±18→73 条 ≤ 92 / `__slots__` 一致性）
- 回归：7 个全过（smoke / side_flip / subscription_qualify / tick_router /
  session_rollover / web_contract / page_render）
- 端到端探针：`ws_probe` 20/20；实拍页面热力图 36 档 × 48 桶 · 1,368 格，
  Skew 39 点，订阅 74/92

## 本会话修掉的两个缺陷

### 缺陷 A：Skew 面板渲染中断（前端）

- 现象：状态栏 `渲染回调异常: Cannot read properties of undefined (reading 'coord')`，
  `skew-meta` 永远为空；后端数据完全正常、字段名也完全对得上。
- 根因：`web/skew.js` 用 `visualMap` 的 `pieces` 模式做正负着色，
  **ECharts 5.6.0 上必抛异常**。二分实测：`pieces` 的
  `type:'piecewise'` / `show:true` / 二维数据 / 去掉 `seriesIndex` 全部失败；
  `continuous` 正常；`markLine`、`legend` 无关。
- 修法：主序列按正负拆成两条同名曲线（各自固定颜色、另一侧填 `null`），
  图例按名去重、提示框过滤 null 一侧。
- 位置：`web/skew.js`（新增 `splitBySign()`；`ws_client.js` 补 `console.error(e)`）

### 缺陷 B：跨会话数据污染（后端）

- 现象：模拟服务长跑跨过会话边界后，热力图从「36 档 × 304 桶」塌成
  「36 档 × 1 桶 · 0 格」；探针 `矩阵含有效数值` FAIL；`connection=disconnected`。
- 根因：`FeatureEngine.reset()` 一直存在，但**没有任何地方调用它**。
  热力图与 Skew 序列的键都是会话内桶序号（`0..389`），只在一天之内唯一。
- 两条独立泄漏路径：
  1. 桶序号被复用 → 新一天第 1 桶 IV 减上一天第 1 桶 IV（实测污染 **2.00 波动率点**）
  2. 旧会话 tick 被判为 `STALE`（可信质量）→ 旧 IV 写进新会话的桶
     （实测无新 tick 时旧矩阵仍推送 **108 个有值格**）
- 修法：`_sync_session()` 按 `clock.expiry_str()` 判断翻篇并 `reset()`；
  新增 `_session_refs()` 按 `ref.expiry` 过滤合约。
- 位置：`features/feature_engine.py`
- 被否掉的方案：翻篇时清空 `TickStore` —— 依赖调用顺序，模拟模式下时钟连续推进，
  翻篇那一刻新会话的 tick 可能已到，会把新数据一起清掉（实测踩中）。

## 本会话新增的三个回归

| 工具 | 钉住的规则 | 非空转验证 |
|---|---|---|
| `tools/check_tick_router.py` | L1 分流：模型值优先、脏值拦截 | 7 组全过 |
| `tools/check_session_rollover.py` | 跨会话不得共用桶序号 / 不得用旧会话 tick | 摘掉修复复现 2.00 与 108 |
| `tools/check_web_contract.py` | 引用 → 定义三向对照（DOM id / CFG / 载荷字段） | 喂缺字段帧能报 FAIL |
| `tools/check_page_render.py` | 真浏览器打开、断言画出来了 | 放回坏 `visualMap` 能报 FAIL |

## 未改动但已确认

- `config/` 全部 10 份配置未改（本会话不调参）
- 分层方向、`__slots__` 一致性、订阅容量均未受影响
