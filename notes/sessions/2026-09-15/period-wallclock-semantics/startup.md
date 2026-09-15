# Startup — 2026-09-15 / period-wallclock-semantics

STARTUP-PROOF: `git status --short` 于会话开始时（08:23 EDT）捕获 —— 6 个文件未提交
（`web/period.js` / `tools/period_reference.py` / `tools/period_selftest.py` /
`tools/skew_reference.py` / `tools/check_skew_colors.py` / `tools/check_skew_viewport.py`），
`HEAD = 2db39eb`，`origin/main = 6828e3a`（本地领先 16 提交）。服务在跑：
`http://127.0.0.1:8060/health` → `frames: 18016`。

## Session

- 承接上一会话（同一 BUG 的第二轮），KAI 在本轮给出**架构层裁定**，需要判断
  "按桶分组"是否违背裁定的"按挂钟整点分对齐"。

## Scope Understanding

- In scope:
  - 判定 `web/period.js::aggregate` 的**桶数分组**与 KAI 裁定的**挂钟整点分对齐**是否等价。
  - 若不等价，定位差异并给出改法；若等价，把等价性钉进代码注释，防止后人重走。
  - 收尾：非空转自测复核、门禁全量复核、`tmp/` 探针清理、会话记录、提交推送。
- Out of scope:
  - **不改分组基准**（KAI 2026-09-15 08:39 明确答"不用"）—— 跨空档那两列保持现状。
  - 不新增后端字段、不新增双向通道（KAI 先选"后端算"，但查证后发现**无需**，
    见 `project_state.md`）。
  - 不动 `check_page_render.py` / `check_ws_compression.py` 两个既存红灯。

## Prior Context Read

- `notes/context/handoff.md`（最新节 `heatmap-topn-skew-yzoom`）→ 取得的**约束**：
  该会话已提交推送，末尾留了两个未验证项（Top-3 黑边视觉宽度、Y 轴缩放手感），
  与本轮无关；本轮**不要**重开那条线。
- `notes/context/open_tasks.md` → 取得的**约束**：存在一条"Top-3 亚像素"待 KAI 裁定，
  和一条"ΔIV 逐格对拍缺常驻检查器"——两者都不是本会话范围，本轮不得顺手改。
- `web/period.js` 现有未提交 diff → 取得的**约束**：`floor(cols/g)` 丢末组已落地，
  本轮**不得回退**（`period_selftest.py` 有一条变异专门守它）。
- `.workbuddy-ai/memory/MEMORY.md` + `notes/memory/QUICKREF.md` 路由 → 取得的**约束**：
  "静默错值型"必进 `QUICKREF`，本轮若产生新条目需先问 KAI，**禁止自行追加**。

## Recent Git Context

- Key commits reviewed: `2db39eb`（当前 HEAD，docs 记录 Top-3 亚像素缺陷）、
  `c0cfa8f`（Top-3 黑边 + Skew Y 缩放）、`0d30943`（period 回归超限文件拆分）。
- 本轮起点为**脏工作区**：6 个文件是上一会话的未提交改动，本轮在其上继续。

## Worker Readiness

- Risks noticed:
  - 上一会话遗留的"旧语义漂移未复现"缺口 —— 本会话在动手前先证伪了它，
    结论见 `project_state.md`（缺口是**采样位置**问题，不是缺陷不存在）。
  - `period.js` 加注释后逼近 400 行上限（实测 391），后续再加内容需拆分。
- Blockers noticed:
  - 无。KAI 的裁定在动手前已全部到齐（见 `project_state.md` 的裁定表）。
