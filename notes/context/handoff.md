# Handoff Index
- Latest session: 2026-09-13/simulator-hard-cut
- Current session handoff: notes/sessions/2026-09-13/simulator-hard-cut/handoff.md
- Archive: notes/context/archive/handoff_2026-09.md
- Status: 完成。**硬切删除模拟盘全部依赖**（`simulator/` 4 文件 582 行 +
  `config/simulator.json`），系统成为纯实盘系统 —— 无特性开关、无兼容分支、
  无回退路径。`run.py` 只剩 `--check`；`app/pipeline.py` 367 → 341 行；
  `FeedMode.SIM` 移除。**关键交付物 `tools/fixtures.py`（新增 188 行）**：
  把被删模拟源的最小确定性内核抽成测试夹具（`FakeClock` 零 `time.monotonic()`，
  比原 `SimClock` 更确定），让 4 个原本依赖模拟盘的离线回归活下来。
  自检里的 3 处 `simulator` 登记项同轮清理（漏删只会**静默少查一层**）。
  验证：`--check` **11/11**、本地回归 **11/11 exit 0**；4 个需服务的检查因
  8060 无服务未跑通，已定位与硬切无关。
  同会话第二部分：skill `notes-session-records` 导入并放宽、5 条工程要求提升到
  用户级 `MEMORY.md`、`notes/` 复活。
  ⚠️ **改动未提交**（18 文件 +186/−814 + 2 未跟踪项），待 KAI 指示。
- Previous: 2026-09-11/model-greeks-landing-verified（notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md）
- Previous: 2026-09-11/record-reconciliation（notes/sessions/2026-09-11/record-reconciliation/handoff.md）
- Previous: 2026-09-11/iv-heatmap-turbo-palette（notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md）
- Previous: 2026-09-11/ibkr-rate-limit-audit（notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md）
