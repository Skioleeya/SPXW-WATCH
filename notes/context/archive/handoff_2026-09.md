# Handoff Archive — 2026-09

本文件收录已不再是最新会话的历史 handoff 摘要。当前最新会话见
`notes/context/handoff.md`。

---

## 2026-09-11 / session-rollover-and-render-fix

状态：完成 —— 修掉 Skew 面板渲染中断与跨会话数据污染两个缺陷；新增四个回归
（`check_tick_router` / `check_session_rollover` / `check_web_contract` /
`check_page_render`，后三者已做非空转验证）；`run.py --check` 7/7、7 个回归全过、
`ws_probe` 20/20。遗留：实盘"连上之后能否收到数据"未验证。

会话 handoff：
`notes/sessions/2026-09-11/session-rollover-and-render-fix/handoff.md`

---

## 2026-09-11 / 当日其余会话（归档索引）

- **`model-greeks-landing-verified`** —— 完成。回答 KAI「106 模型 Greeks 落地
  是什么意思」时**不靠复述记录，直接跑探针当场验证**：
  `generic_tick_list="106"` 确实让 IBKR 推送 `tickOptionComputation`，
  `ticker.modelGreeks` 第 5s 出现（iv=0.12483 / delta=0.43913），且与 bid/ask/last
  三档 greeks **四者并存且值不同** ⇒ MODEL_OPTION 是独立通道。**记录里的"未验证"
  被证伪。** 同时推翻旧假设：期权 ticker 报 `marketDataType=1`（**实时**），
  Error 10090 原文是"**部分**未订阅"。另落地 KAI 决策：**IV 热力图 ΔIV ≈ 0
  不退回中性色**（维持 Turbo）。**零生产代码改动**；收尾 `--check` 11/11。
  `notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md`
- **`record-reconciliation`** —— 完成。校正 4 处「记录 vs 现实」不一致
  （`feed_service.py` 行数、README §9 数字、`[5]` 关键键数）；README §10
  「实盘未验证」改为「已实测联通」；端口默认值改 `4002`。
  `notes/sessions/2026-09-11/record-reconciliation/handoff.md`
- **`iv-heatmap-turbo-palette`** —— 完成。色板 11 色发散 → 15 色 Turbo 顺序色阶；
  `borderWidth: 0 → 1` + `theme.grid: "#1a2029"`。逐色比对已证伪。
  `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md`
- **`ibkr-rate-limit-audit`** —— 完成。确认限速桶在 `ib_async` 库层；
  显式化 + 可观测；载荷拆 `health.rate_limit` / `health.sub_limit_backoff`。
  `notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md`
- **`selfcheck-hardening`** —— 完成。收窄 `iter_py_files()` 扫描范围 +
  修 `_literal_repr` 漏检 + 上线检查 [7]。
  `notes/sessions/2026-09-11/selfcheck-hardening/handoff.md`
- **`dead-key-resolution`** —— 完成。7 个死配置键 → 4 接线 + 3 删除；
  `UNWIRED_IS_FAILURE` → `True`；拆出 `acquisition/spot_tap.py`。
  `notes/sessions/2026-09-11/dead-key-resolution/handoff.md`

