# Project State

ACTIVE_SESSION: 2026-09-11/session-rollover-and-render-fix
LAST_UPDATED: 2026-09-11
ARCHIVE: notes/context/archive/project_state_2026-09.md

CURRENT_STATE: spxw_swatch 61 个 Python 文件（最长 386 行）；run.py --check 7/7；
7 个回归全过；ws_probe 20/20。本会话修掉两个"探针全绿但实际是坏的"缺陷。
- **Skew 面板从未渲染成功过**：`visualMap` 的 `pieces` 模式在 ECharts 5.6.0 上
  必抛 `reading 'coord'`。已改为双同名序列按正负着色。
- **跨会话数据污染**：桶序号跨会话复用 + 旧会话 tick 被判为 `STALE` 后写入新会话
  的桶。已在 `FeatureEngine` 加 `_sync_session()` 与 `_session_refs()`。
- 新增四个回归：`check_tick_router.py` / `check_session_rollover.py` /
  `check_web_contract.py` / `check_page_render.py`（后三者已验证非空转）。

NEXT: 3 项
1. 实盘验证 `run.py --live` 的"连上之后能否收到数据"（需真实 TWS / IB Gateway）。
2. 决定 `notes/` 与本项目既有证据体系（`.workbuddy-ai/memory/` + README + 回归工具）
   是否长期并行，或收敛为一套。
3. （可选）前端按 `session.expiry` 变化主动清空面板，消除翻篇瞬间的短暂误读风险。
