# Handoff Index
- Latest session: 2026-09-13/web-js-gate-and-probe-governance
- Current session handoff: notes/sessions/2026-09-13/web-js-gate-and-probe-governance/handoff.md
- Archive: notes/context/archive/handoff_2026-09.md
- Status: **`web/*.js` 纳入 `[1]` 文件长度门禁 + Skew 三项修复落成常驻回归 + 探针落点治理**：
  ①新增 `iter_web_scripts()`（按目录枚举），`[1]` 从"82 个 `.py`"变为 **90 个文件**，
  纳入即报出 3 项**真实违规**（`skew.js` 536 / `app.js` 524 / `period.js` 490），
  **本轮不动 `web/` 代码**（KAI 拍板"纳入 + 先出拆分方案"，方案见本会话
  `project_state.md`）；②新建 `tools/check_skew_viewport.py`（394 行，`[G1]`–`[G4]`
  共 21 项判据 + 6 条变异），把上一轮只在一次性探针里的三项修复固化成常驻回归；
  ③删除死代码 `SkewPanel.prototype.stats()`（`skew.js` 540 → 536）；
  ④临时探针落点定为 **`<项目根>/tmp/`**，在 `.gitignore` + `NON_SOURCE_DIRS` 两处登记。
  ⑤**自查中抓到一个真缺陷并修掉**：`check_skew_viewport.py` 的"判据集合不完整"守卫
  期望集合由 `GROUPS` **自推** ⇒ 删掉一组后该组失败被**静默吞掉、`RC` 仍 0**
  （实测删 `[G4]` ⇒ 3 条失败被吞）；抽出 `tools/group_guard.py`（期望前缀 = 独立常量
  + 三条都查 + `guard_cases` 自证）。同族缺口：`check_period_aggregation` /
  `check_skew_alignment` **同结构但无守卫**，只登记未修。
  终态：`run.py --check` **`RC=1`**（`[1]` 3 项 FAIL = 真实违规，**预期红**；
  其余 10 项全通过、关键配置项 **40**）；全量 **18** 个工具 **14 `RC=0`** / 4 `RC=1`
  （与基线一致：缺 `ib_async`/`aiohttp`/无 8060/非本项目页面）；
  `check_skew_viewport --selftest` **6 条变异 + 守卫 2 条用例全抓**；
  `check_skew_alignment --selftest` 4 条变异全抓（沙箱抽出未破坏既有回归）。
  ⚠️ **本会话改动未提交**；真实链路渲染仍未验证（周日 fail-closed），
  由 KAI 手动在 GTH 时段验收。
  ⚠️ **待 KAI 拍板**：`web/*.js` 拆分方案（文件划分 / 迁移清单 /
  检查器 4 处写死的 web 文件清单如何收敛到 `index.html` 单一真源）。
- Previous: 2026-09-13/skew-zoom-yscale（notes/sessions/2026-09-13/skew-zoom-yscale/handoff.md）
- Previous: 2026-09-13/recheck-keyorder-memory（notes/sessions/2026-09-13/recheck-keyorder-memory/handoff.md）
- Previous: 2026-09-13/skew-period-consistency（notes/sessions/2026-09-13/skew-period-consistency/handoff.md）
- Previous: 2026-09-13/frame-strike-order-descending（notes/sessions/2026-09-13/frame-strike-order-descending/handoff.md）
- Previous: 2026-09-13/cold-data-strike-order（notes/sessions/2026-09-13/cold-data-strike-order/handoff.md）
- Previous: 2026-09-13/live-verify-and-release（notes/sessions/2026-09-13/live-verify-and-release/handoff.md）
- Previous: 2026-09-13/notes-dedup-tiering（notes/sessions/2026-09-13/notes-dedup-tiering/handoff.md）
- Previous: 2026-09-13/simulator-hard-cut（notes/sessions/2026-09-13/simulator-hard-cut/handoff.md）
- Previous: 2026-09-11/model-greeks-landing-verified（notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md）
- Previous: 2026-09-11/record-reconciliation（notes/sessions/2026-09-11/record-reconciliation/handoff.md）
- Previous: 2026-09-11/iv-heatmap-turbo-palette（notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md）
- Previous: 2026-09-11/ibkr-rate-limit-audit（notes/sessions/2026-09-11/ibkr-rate-limit-audit/handoff.md）
