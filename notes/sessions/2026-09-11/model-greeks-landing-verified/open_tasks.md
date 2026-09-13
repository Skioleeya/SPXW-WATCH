# Open Tasks — model-greeks-landing-verified

## Active（本会话）

- [x] 探测环境（4002 / 8060）→ 4002 在听，可做直接观测。
- [x] 确认代码链条：热力图 IV ← `OptionTick.iv` ← `_pick_computation()` ←
      `modelGreeks`（`use_model_greeks=true` 时唯一来源）。
- [x] 写探针（工程外）并用与项目逐字相同的参数订阅 SPXW 0DTE 期权。
- [x] 观测：`modelGreeks` 第 5s 出现、`marketDataType=1`、四档 greeks 并存且不同。
- [x] 归档探针 + 输出到 `artifacts/`。
- [x] 落地 KAI 决策：IV 热力图 ΔIV ≈ 0 不退回中性色。

## Closed（本会话）

- [x] **[结论过时] 「实盘 tick 回流后的 106 模型 Greeks 落地」未验证** ——
      直接探针证明 **确实落地**（`modelGreeks` 非空且与 bid/ask/last 三档
      明显不同）。`notes/context/open_tasks.md` 的 Stale 节已改写。
- [x] **[假设被推翻] 「paper 账户无实时 OPRA 权限，只返回延迟数据」** ——
      本次观测到期权 ticker 的 `marketDataType = 1`（**实时**）；Error 10090
      的原文是 "**Part of** ... not subscribed"（部分未订阅），不是无权限。
      记录已同步修正。
- [x] **[待 KAI 定] IV 热力图 0 值是否退回中性色** —— KAI 决策：**不退回**。
      已移入 `notes/context/open_tasks.md` 的「已决策」节。

## 转出（仍挂在 `notes/context/open_tasks.md`）

- [ ] **[待 KAI 定] 数字类记录无单一真相源，正在持续腐烂**（本会话又新增一例：
      "未验证"这条同样是"结论没跟上实测"）。
- [ ] **[低] 色板缺机械回归。**
- [ ] **[低] 联通与限速无常驻回归** —— 本探针同样是手工脚本，未收进 `tools/`。
- [ ] **`notes/` 与 `.workbuddy-ai/memory/` 是否收敛为一套。**
- [ ] **[新增·低] `source_tick_type` 是名义值** —— `TickRouter` 把 modelGreeks
      一律记为 13，而 ib_async 无法区分 13 / 83。若将来需要区分实时与延迟模型，
      得改从 `ticker.marketDataType` 取（本次观测到它是有值的）。
