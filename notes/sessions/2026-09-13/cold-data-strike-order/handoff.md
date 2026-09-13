TASK-ID: cold-data-strike-order
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（审计起手，改动在拿到证据后才做）

# Handoff — cold-data-strike-order

STARTUP-PROOF: N/A:会话从一个审计问题（"冷数据里记没记行权价排序方法"）起手，
`startup.md` 未在改动前建，不补写。改动前的基线读数（探针非单调 / `check_persistence`
4/4）确实存在，落在 `COMMAND-EVIDENCE` 的 `[pre]` 行，不在本文件另开一节复述。

## Scope Understanding

- In scope: 冷数据（`data/session.db`）里行权价键序的**来源、可达性、消费者**；
  前端渲染顺序与帧顺序的关系；把"键序升序"变成**有回归守着的不变量**。
- Out of scope: 前端 `web/`（**未动一行** —— KAI 2026-09-13 裁定"前端是空壳，
  不给它加门禁"）；`recover()` / `load_snapshot()` 的读取路径（无需重排）；
  schema 加列（判为过重，见 `project_state.md`）。

CHANGED-PATHS:
- `features/heatmap_engine.py` — `dump_bucket()` 改为按行权价升序遍历 `_buckets`，
  docstring 记下"为什么必须在这里排序"（287 行）。
- `tools/check_persistence.py` — 新增 `_case_key_order_ascending`，覆盖点加第 6 条，
  `import json`（234 行）。
- `notes/sessions/2026-09-13/cold-data-strike-order/` — 本会话记录 + `artifacts/`
  6 件（2 个探针、铸帧脚本、探针页、2 张截图）。

VALIDATION-SUMMARY:
- `run.py --check` → 全部通过（11/11）
- 11 个离线回归（`check_*` 10 个 + `smoke_test`）→ 全部 `rc=0`
- `tools/check_persistence.py` → `5/5 通过`（含新增用例）
- 非空转证伪：摘掉 `sorted()` → 新用例 `[FAIL] dump_bucket 未升序`、`EXIT=1`；还原后复跑 5/5
- 4 个需服务的检查（`check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`）→ **N/A:周日无当日 SPXW 到期，服务在
  `pick_zero_dte` 处 fail-closed 退出，端到端跑不了**

COMMAND-EVIDENCE:

`[pre]` 改动前 —— 非单调可达（真 `StrikeWindow.rows()` + 真 `HeatmapEngine`，
只喂 spot 路径 7700→7820→7600，±12 档）:

```
  6    7740    7685    7800   24      True
  7    7680    7625    7740   24     False   ← 乱序从这里开始
  9    7600    7545    7660   24     False
完整键序: [... 7735.0, 7740.0, 7625.0, 7630.0, 7635.0, 7640.0]
落盘键序单调? False · recover 后单调? False · 与内存键序一致? True
```

`[pre]` `data/session.db` 现状：40 桶 **40/40 升序**（0 降序 / 0 乱序）
—— 乱序尚未发生过，是**可达但未触发**，不是历史遗留脏数据。

`[pre]` 前端顺序实测（离线探针：`HeatmapSerializer.encode()` 铸帧 →
真实 `web/*.js`；工程零污染，`cp -r web/` 到临时目录）:

```
帧 A 升序 24 档       → yAxis[0].data 逐字相同 · 屏幕最上 7755 / 最下 7640
帧 B 低档晚到(非单调) → yAxis[0].data 逐字相同 · 屏幕最上 7630 / 最下 7640
帧 C 完全降序 24 档   → yAxis[0].data 逐字相同 · 屏幕最上 7640 / 最下 7755
convertToPixel(索引0)=266.5  >  convertToPixel(索引23)=15.5  ⇒ 索引 0 在屏幕最下方
```

`[post]` 纵轴方向对照（KAI 追问"前端看到的是降序"后补测）：同一帧
（`strikes` 升序 7640→7755）渲染两次，只差 `yAxis.inverse` —— 无 `inverse` 时
`px(索引0)=481.96 > px(索引23)=20.04` ⇒ 屏幕自上而下 = 降序 `7755→7640`；
`inverse=true` 时翻转 ⇒ `7640→7755`（对照图 `artifacts/axis_compare.png`）。

`[post]` **KAI 裁定：保持现状（高行权价在上），`web/` 一行未改。**
判据补充：`git log -S inverse -- web/heatmap.js` 为空 ⇒ 该方向自始未变、不是
回归；09-11 实盘参考截图（36 档）同为 `7750→7575`；`heatmap.js:3` 注释
「下方为低行权价」即此约定。**"屏幕自上而下是降序"是约定，不是缺陷。**

`[post]` 同一路径复跑：10 个桶**全部 `True`**（`dump_bucket` 已排序，
探针走到"非单调不可达"分支）—— 同一输入、输出翻转，翻转点正是本次改动。

`[post]` 消费者审计：全工程 `grep` 无任何模块/工具直接读 `session.db`；
唯一消费者 `app/pipeline.py:164 recover()` → `feature_engine.load_snapshot()`，
而矩阵行序由 `build(rows, …)` 的 `rows` 决定 ⇒ **本次改动对系统行为零影响**，
消除的是"直接读库的人/未来脚本默认键序即升序 → 静默错配行号"这一类风险。

NO-PATCH-BANDAGE: 排序落在**快照的产出点**（`dump_bucket` 是 `ivs_json` 的唯一
产出者），不是给消费者加防御性重排，也没有加兼容分支。`recover()` /
`load_snapshot()` **刻意不动**：写侧已保证升序，读侧重排等于第二处真相。

NO-FALLBACK-BEHAVIOR: 无。空桶仍返回空字典；有值的档位集合不变，只改键序。

NOTES-PATHS:
- `notes/sessions/2026-09-13/cold-data-strike-order/handoff.md`（本文件）
- `notes/sessions/2026-09-13/cold-data-strike-order/project_state.md`
- `notes/sessions/2026-09-13/cold-data-strike-order/artifacts/`（5 件）
- `notes/context/handoff.md` · `project_state.md`（指针与当前态）

## Closed in session

- 冷数据键序"是不是升序"有了确定答案：**是，且现在由产出点保证**，
  `tools/check_persistence.py::_case_key_order_ascending` 守着（含非空转证伪）。
- 前端顺序问题定案：`web/heatmap.js:93` 只做 `strikes.map(String)`，
  `yAxis` 无 `inverse` ⇒ **不排序、不反转，逐字照抄帧**；ECharts category 轴
  把索引 0 画在最下方 ⇒ 屏幕自上而下 = 帧 strikes 的逆序
  （`heatmap.js` 头部注释「升序，下方为低行权价」即此意）。**`web/` 未改一行。**
- **纵轴方向已裁定（KAI）：保持现状，高行权价在上** —— 无需任何改动。
  已记入项目 `MEMORY.md` 的「已定稿 / 已决策」，避免日后被当成 bug 重提。
- `features/persistence.py` 的表结构**不记录**排序方法（无 strikes 列、
  无 order/schema_version）—— 这是事实陈述，不是缺陷：顺序是隐式的，
  现在由 `dump_bucket` 保证。
- 周日启动结论：链路正常走到 `pick_zero_dte` 才 fail-closed，**前面每一步都成功**。

OPEN-RISKS:
- **4 个需服务的检查仍未跑**（`check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`）—— 硬切实盘后只有盘中能跑。本次改动
  未触及 `web/` 与传输层，风险低，但**未验证就是未验证**。
- **09-13 之前落盘的 `session.db` 不会被重排** —— 读侧无校验。实测现有 40 桶
  全升序，故无实际脏数据；若日后手工改库注入乱序，`recover()` 会原样继承。
- **改动未提交**（`git status --short` 显示 2 个 M）—— 等 KAI 决定是否入库。
