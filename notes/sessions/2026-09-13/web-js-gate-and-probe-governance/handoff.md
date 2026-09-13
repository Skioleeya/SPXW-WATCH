TASK-ID: web-js-gate-and-probe-governance
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（KAI 直接指派四项）

# Handoff — web-js-gate-and-probe-governance

STARTUP-PROOF: N/A:本轮由 KAI 一次指派四项起手（纳入 web 门禁 / 落地常驻回归 /
删死代码 / 探针落点治理），改动前未建 `startup.md`，按 skill 规定**不回填**。
改动前的基线读数引自 `notes/sessions/2026-09-13/skew-zoom-yscale/handoff.md`
（自检 11/11、`[1]` 报 82 个 `.py` 合规、本地 17 个工具 13 个 `RC=0`），不在本文件复述。

## Scope Understanding

- In scope（同一会话内的四项）：
  1. **把 `web/*.js` 纳入 `[1]` 文件长度门禁** —— KAI 拍板"纳入 + 先出拆分方案"，
     即本轮**不动 `web/` 代码**，并接受 `--check` 因此变红（红的是真实违规）；
  2. **`tools/skew_reference.py` 的 node 沙箱抽出，落成常驻回归**
     `tools/check_skew_viewport.py` —— 把上一轮只存在于一次性探针里的三项判据固化；
  3. **删除 `SkewPanel.prototype.stats()`** —— 无人调用的死代码，KAI 批准、不备份；
  4. **临时探针落点治理** —— 落点定为 `<项目根>/tmp/`（KAI 拍板），
     并在 `.gitignore` + `NON_SOURCE_DIRS` **两处**登记。
- Out of scope: **`web/` 代码一行未动**（KAI 2026-09-13 拍板"不拆文件" —— 详见
  `project_state.md::决策记录`）；`~/.workbuddy-ai/tmp/` 下约 40 个历史探针**未迁移**
  （动用户目录，KAI 定为"下一个会话做"的待办）。

CHANGED-PATHS:
- `tools/selfcheck_core.py` — 新增 `WEB_DIR` / `iter_web_scripts()`；`NON_SOURCE_DIRS`
  加 `"tmp"` 条目，并把 `"web"` 的理由从"整目录排除"改写为"不进任何 AST 类检查，
  但其中的 `.js` 由 `iter_web_scripts()` 单独送进 `[1]`"
- `tools/selfcheck_structure.py` — `check_file_sizes()` 改为同时扫 `.py` 与 `web/*.js`；
  docstring 增加"[1] 为什么把 `web/*.js` 也算进来"
- `tools/selfcheck.py` — `[1]` 的描述改为"每个 `.py` 与 `web/*.js` 必须少于 400 行"
- `tools/skew_reference.py` — 抽出 `SANDBOX_JS`（沙箱 + `F`/`P`/`CFG`/`out` 公共量）
  与 `ALIGN_BODY`；`run_node_in()` 增加 `driver` 参数（既有对齐回归共用同一沙箱）
- `tools/check_skew_viewport.py` — **新建**（394 行）：四组判据 `[G1]`–`[G4]`、
  6 条变异表、`expected_points()` 独立参考、空集合守卫
- `tools/group_guard.py` — **新建**（65 行 → 84 行本会话扩 docstring + 类型说明）：
  判据分组完整性守卫 + 守卫自身的非空转用例；`prefixes` 接口契约收为
  `tuple[str, ...]`（不要传 `str`，否则会被当成字符序列拆开）。
- `tools/check_period_aggregation.py` — 加 `EXPECTED_PREFIXES` 独立常量 + `[7]` 组
  入 `GROUPS` + `guard_problems` / `guard_cases` 守卫接入；docstring 与函数注释精简
  压回 **398 行**（≤ 400）。`--selftest` 守卫 2 条用例 + 5 条变异全抓。
- `tools/check_skew_alignment.py` — 加 `EXPECTED_PREFIXES` + 守卫接入（GROPS 已是
  tuple 形状不改）；318 行。`--selftest` 守卫 2 条用例 + 4 条变异全抓。
- `web/skew.js` — 540 → **536** 行（删除死代码 `stats()`）
- `.gitignore` — 新增 `tmp/` 段（与 `NON_SOURCE_DIRS` 配套，缺一条即误报或入库）
- `tmp/README.md` — **新建**：探针落点规矩 + 两处登记表 + 历史遗留说明
- `README.md` — §8 加"临时探针写在哪"；辅助工具清单加 `check_skew_viewport.py`；
  `[1]` 表格行改"全量行数统计（`.py` + `web/*.js`）"；`[5]` 计数 41 → **40**（旧值是错的）；
  §9 加 `tools/group_guard.py` 段（含两个同族缺口待办）；"覆盖边界"三处 → **四处**；
  当前状态改"[1] 覆盖 90 个文件（83 `.py` + 7 `web/*.js`），其中 3 个前端超限"
- `.workbuddy-ai/memory/MEMORY.md` — 探针约定改写为 `<项目根>/tmp/` + 两处登记；
  `web/*.js` 已纳入 `[1]`；回归计数 16 → **17 个 `check_*.py`**（14 `RC=0` / 4 `RC=1`）；
  新增"分组式回归的期望前缀不得由分组表自推"一条；压回 **7975** 字符（≤8000）

VALIDATION-SUMMARY:
- `python run.py --check` → `RC=1`：`[1]` 3 项 FAIL，其余 10 项全通过 —— **预期红**
- `python tools/check_skew_viewport.py` → `RC=0`，21 项全通过
- `python tools/check_skew_viewport.py --selftest` → `RC=0`，6 条变异 + 守卫 2 条用例全抓
- `python tools/check_skew_alignment.py --selftest` → `RC=0`，4 条变异全抓（沙箱重构未破坏既有回归）
- `python tools/check_web_syntax.py` → `RC=0`（7 个文件）
- 全量 18 个工具（17 个 `check_*.py` + `smoke_test.py`）→ **14 `RC=0` / 4 `RC=1`**
- 手工做坏（守卫封口验证）→ 清空判据集合、删掉 `[G4]` 组，**均被拦截**（`RC=1`）
- 覆盖计数：`iter_py_files()` **83** + `iter_web_scripts()` **7** = **90**

COMMAND-EVIDENCE:
- `python run.py --check` → `RC=1`
  ```
  [1] 文件长度（上限 400 行）
    [FAIL] web/app.js 共 524 行，超出上限
    [FAIL] web/period.js 共 490 行，超出上限
    [FAIL] web/skew.js 共 536 行，超出上限
  [5] 关键配置项存在
    [ok] 40 个关键配置项齐备
  结果: 3 项不通过
  ```
  ⇒ 纳入前 `[1]` 打印"82 个文件全部合规"（只数 `.py`）；纳入后扫 **90** 个文件、
  报出 3 个**真实违规**。**枚举非空且可区分**（其余 5 个 `web/*.js` 通过），
  不是一刀切变红。
- `python tools/check_skew_viewport.py` → `RC=0`，21 项：
  ```
  [G1] 图例：两条同名曲线各占一条           7 项
  [G2] 纵轴刻度精度（读配置，非硬编码）      3 项（含"探针位数 3 ≠ 默认 1"的非空转前置）
  [G3] meta 读数按可见列                    8 项（含两个取样窗口 × 收窄断言）
  [G4] 视口回调                            3 项
  ```
  关键读数：两条 skew 曲线 name `['25Δ Skew','25Δ Skew·负']`、颜色 `['#ff5a5a','#4ea8ff']`；
  默认位数 `['1.5','1.5']` vs 配置改 3 后 `['1.500','1.500']`；视口 `[10,30]` → `21/21`
  点（全宽 `780/780`）；视口 `[95,105]` → `11/11` 点。
- `python tools/check_skew_viewport.py --selftest` → `RC=0`：
  ```
  [非空转自检] 守卫：削掉一组必须被报出来
    [ok] 清空分组表 → 已抓住：分组表前缀 [] ≠ 期望 ['[G1]','[G2]','[G3]','[G4]']
    [ok] 去掉最后一组 [G4] → 已抓住：分组表前缀 ['[G1]','[G2]','[G3]'] ≠ 期望 [...]
  [非空转自检] 逐条把修复改回旧行为
    [ok] skew 两条曲线改回同名        → 已抓住 [G1]（1 项）
    [ok] 图例 formatter 不再抹内部后缀 → 已抓住 [G1]（1 项）
    [ok] 左轴刻度改回硬编码 toFixed(2) → 已抓住 [G2]（2 项）
    [ok] 右轴刻度改回硬编码 toFixed(2) → 已抓住 [G2]（2 项）
    [ok] 读数退回全序列计数            → 已抓住 [G3]（6 项）
    [ok] 去掉视口回调                  → 已抓住 [G4]（2 项）
  ```
- **守卫缺口的证伪与封口**（本轮自查时发现并修掉，是本会话最有价值的一条）：
  ```
  基线判据 21 条，失败 0 条
  把 3 条 [G4] 判据做坏 → 失败 3 条
  原样 GROUPS      守卫=放行  报告出的失败数=3  ✓ 正确（组表完整，失败被报出）
  删掉 [G4] 组      守卫=拦截  报告出的失败数=0  ✓ 封口
  清空 GROUPS      守卫=拦截  报告出的失败数=0  ✓ 封口
  ```
  修复前同一探针的输出是：`删掉 [G4] 组 → 守卫=放行、报告出的失败数=0` ——
  即**该组 3 条失败被静默吞掉、退出码仍为 0**。探针源码与前后两次读数见
  `artifacts/guard_hole_probe.txt`。
- `python tools/check_skew_alignment.py --selftest` → `RC=0`，4 条变异全抓
  （`[C4]` 4 项 / `[C1]` 8 项 / `[C2]` 1 项 / `[C6]` 2 项）—— 沙箱抽出未破坏既有回归。
- 全量 18 个工具：
  `RC=0` **14** 个 —— `clock_protocol` / `matrix_codec` / `period_aggregation` /
  `persistence`(5/5) / `reconnect_gap` / `session_grid` / `session_rollover` /
  `side_flip` / `skew_alignment` / **`skew_viewport`** / `subscription_qualify` /
  `tick_router` / `web_syntax`(7 文件) / `smoke_test`。
  `RC=1` **4** 个，**与基线一致，非本次引入**：`page_render`（页面不是本项目面板）、
  `reconnect_flow`（缺 `ib_async`）、`web_contract`（缺 `aiohttp`）、
  `ws_compression`（8060 无服务）。

NOTES-PATHS:
- `notes/sessions/2026-09-13/web-js-gate-and-probe-governance/handoff.md`（本文件）
- `notes/sessions/2026-09-13/web-js-gate-and-probe-governance/project_state.md`
  （**已加"决策记录"段 + "原拆分方案"标"已否决"**；`被否决的方案` 表加方案 A 决策依据）
- `notes/sessions/2026-09-13/web-js-gate-and-probe-governance/artifacts/guard_hole_probe.txt`
- `notes/context/handoff.md`（index 指向本会话）
- `notes/context/open_tasks.md`（清掉两条已闭环项，登记拆分与同族守卫缺口）
- `notes/context/project_state.md`
- `.workbuddy-ai/memory/MEMORY.md`、`.workbuddy-ai/memory/2026-09-13.md`（当日日志）

## Closed in session

- **`web/*.js` 纳入 `[1]`**（KAI 拍板"纳入 + 先出拆分方案"）—— `iter_web_scripts()`
  **按目录枚举**（不写死名单）；`[1]` 从"82 个 `.py`"变为"90 个文件"。纳入即暴露
  3 项真实违规（`skew.js` 536 / `app.js` 524 / `period.js` 490）。**本轮不动 `web/` 代码**，
  拆分方案见 `project_state.md`。
- **`tools/check_skew_viewport.py` 落地**（394 行）—— 上一轮三项修复（图例两条同名曲线 /
  刻度精度读配置 / 读数随视口）此前只在一次性探针里守着，现为常驻回归：
  21 项判据、6 条变异、两个取样窗口、期望值由帧里 bucket 列表**独立**算出。
- **`tools/group_guard.py` 落地**（65 行）—— 封掉"删掉一组 ⇒ 该组失败被静默吞掉"的缝。
  期望前缀改为**独立常量**（原先由分组表自推），三条都查：分组表**恰好**覆盖期望集合 /
  每条判据都被某个组认领 / 每个期望前缀都真有判据；`guard_cases` 再对守卫自身做非空转验证。
- **删除 `SkewPanel.prototype.stats()`** —— 全工程确认无残留引用，`node --check` 通过。
- **探针落点治理** —— 落点 `<项目根>/tmp/`；`.gitignore` 与 `NON_SOURCE_DIRS` 两处登记
  （缺前者探针入库，缺后者被 `[1][2][9][10]` 当产品代码误报）；`tmp/README.md` 写明规矩
  与历史遗留。本轮的两个探针已按"用完即弃"处理，源码留档到 `artifacts/`。
- **`README.md` 一处旧值**：`[5]` 写"41 个关键配置项"，实测 **40**（上一轮删
  `skew_scale_window_seconds` 时漏改）。
- **`MEMORY.md` 一处旧值**：回归计数写"16 个（13 本地 + 3 需 8060）"，实测
  **17 个 `check_*.py`**（14 `RC=0` / 4 `RC=1`）。
- **KAI 三条决策落地**（本会话第二轮拍板）：
  1. **`web/*.js` 不拆** —— `iter_web_scripts()` 已按目录枚举实现（决策#1
     的"做法"已落地）；`--check` 报 3 项 FAIL = **长期预期状态**（不是"修好
     方案落地前的临时状态"）。详见 `project_state.md::决策记录`。
  2. **同族守卫缺口一并修** —— `check_period_aggregation.py` 与
     `check_skew_alignment.py` 已接入 `tools/group_guard.py`；`--selftest`
     各自抓全守卫 2 条用例 + 全部变异。故意做坏验证：
     删 `[7]` 组 → RC=1；清空 GROUPS → RC=1；空 checks → 守卫报 10 条 missing。
  3. **`~/.workbuddy-ai/tmp/` 40 个历史探针迁移** —— **推迟到下一个会话**
     （动用户目录需 KAI 明令；本会话"代办"，登记进 `notes/context/open_tasks.md`）。
- **`tools/group_guard.py` 接口收紧**（决策 #2 的副作用）—— `prefixes` 契约
  收为 `tuple[str, ...]`，docstring 明文写出"不要传 `str`，否则会被当成字符序列拆开"
  + 三条都查（覆盖 / 认领 / 真有判据）的语义说明。

OPEN-RISKS:
- **`~/.workbuddy-ai/tmp/` 下约 40 个历史探针未迁移** —— 下一个会话的待办
  （KAI 拍板本轮不做），已登记 `notes/context/open_tasks.md::NEXT`。
- **真实链路渲染仍未验证**（周日 fail-closed）—— 由 KAI 手动在 GTH 时段验收，不设自动任务。
- **`run.py --check` 长期 RC=1**：3 项 FAIL 是 KAI 决策的**预期长期状态**（不拆
  `web/*.js`）。不是回归恶化、不要试图"修绿"。**新改动不能引入第 4 项**。
- **本轮全部改动未提交**（git 工作区已有多处 M 标记 + 4 个新文件 + 1 个 `.gitignore` 段）。
