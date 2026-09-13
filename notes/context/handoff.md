# Handoff Index
- Latest session: 2026-09-13/frame-strike-order-descending
- Current session handoff: notes/sessions/2026-09-13/frame-strike-order-descending/handoff.md
- Archive: notes/context/archive/handoff_2026-09.md
- Status: 帧 `strikes` 与屏幕纵轴统一为**降序**（高行权价在前/在上）——
  `HeatmapEngine.build()` 显式 `sorted(..., reverse=True)` +
  `web/heatmap.js::yAxis.inverse = true` **成对**保证（缺一即翻转）。
  实测**屏幕视觉零变化**（`SAME_AS_BEFORE: true`）；回归在
  `tools/smoke_test.py`「矩阵 strikes 降序」（含非空转证伪）。
  改动 6 文件 + 新 session 目录，**尚未提交**（与上一会话累积 8 个 M）。
- Previous: 2026-09-13/cold-data-strike-order（notes/sessions/2026-09-13/cold-data-strike-order/handoff.md）
- Previous: 2026-09-13/live-verify-and-release（notes/sessions/2026-09-13/live-verify-and-release/handoff.md）
- Previous: 2026-09-13/notes-dedup-tiering（notes/sessions/2026-09-13/notes-dedup-tiering/handoff.md）
- Previous: 2026-09-13/simulator-hard-cut（notes/sessions/2026-09-13/simulator-hard-cut/handoff.md）
- Previous: 2026-09-11/model-greeks-landing-verified（notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md）
- Previous: 2026-09-11/record-reconciliation（notes/sessions/2026-09-11/record-reconciliation/handoff.md）
- Previous: 2026-09-11/iv-heatmap-turbo-palette（notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md）
- Previous: 2026-09-11/ibkr-rate-limit-audit（notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md）
