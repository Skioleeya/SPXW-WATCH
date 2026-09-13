TASK-ID: frame-strike-order-descending
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（KAI 直接指派）

# Handoff — frame-strike-order-descending

STARTUP-PROOF: N/A:会话由 KAI 的口头指派起手（"帧 strikes 数组和屏幕渲染结果
统一为降序"），`startup.md` 未在改动前建，不补写。改动前的基线读数（自检
11/11、8 个离线回归 `rc=0`）确实存在，落在 `COMMAND-EVIDENCE` 的 `[pre]` 行，
不在本文件另开一节复述。

## Scope Understanding

- In scope: 把「帧 `strikes` 的书写顺序」与「屏幕自上而下的视觉顺序」统一为
  **降序**（行权价高的在前 / 在上），消除"帧升序、屏幕降序"这对反向语义。
- Out of scope: `web/` 的其余部分 —— 只加一个 `inverse` **渲染参数**，不加任何
  门禁（维持 KAI「前端是空壳，后端报多少就渲染多少」的裁定）；冷数据
  `dump_bucket()` 的**升序**（它是内部恢复产物，与帧是两个层，本轮不动，见
  `OPEN-RISKS` 第 1 条）；`recover()` / `load_snapshot()`。

CHANGED-PATHS:
- `features/heatmap_engine.py` — `build()` 遍历 rows 改为
  `sorted(rows, key=lambda r: r.strike, reverse=True)`；docstring 记下"为什么
  在产出点显式排序、而不依赖 `StrikeWindow.rows()` 恰好升序"（299 行）。
- `web/heatmap.js` — `yAxis` 新增 `inverse: true` + 注释；文件头注释由
  「升序，下方为低行权价」改为「降序：帧 strikes 从高到低，屏幕自上而下同序」
  （212 行）。
- `contracts/feature.py` — `HeatmapMatrix` 契约的纵轴声明：升序 → 降序，
  并注明行序由 `build()` 产出点保证。
- `serialization/heatmap_matrix.py` — 帧结构示例的 `strikes` 注释 升序 → 降序。
- `tools/smoke_test.py` — 新增断言「矩阵 strikes 降序（与屏幕自上而下同向）」
  （370 行）。
- `tools/period_reference.py` — 夹具 `block()` 的 `strikes` 改为降序，与真实帧
  同形状（233 行）。
- `README.md` — 第 7 行纵轴描述补「降序，高行权价在上」。
- `notes/sessions/2026-09-13/frame-strike-order-descending/` — 本会话记录 +
  `artifacts/` 2 件（三组合对照截图、探针页源码）。

VALIDATION-SUMMARY:
- `run.py --check` → 全部通过（11/11）
- 10 个离线回归（`check_*` 9 个 + `smoke_test`）→ 全部 `rc=0`
- `tools/smoke_test.py` 新断言 → `[ok] 矩阵 strikes 降序 6560.0 → 6445.0`
- 非空转证伪：摘掉 `reverse=True` → `[FAIL] 矩阵 strikes 降序 6445.0 → 6560.0`、
  `rc=1`；还原后复跑通过
- 前端方向实测（Playwright `--channel=chrome`，三组合）→
  `SAME_AS_BEFORE: true` · `WRONG_IS_FLIPPED: true`
- `check_reconnect_flow` → **N/A:当前环境缺 `ib_async`**（import 阶段
  `ModuleNotFoundError`，与本次改动无关；改动未触及 `acquisition/`）
- 4 个需服务的检查（`check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`）→ **N/A:周日无当日 SPXW 到期，服务在
  `pick_zero_dte` 处 fail-closed 退出，端到端跑不了**

COMMAND-EVIDENCE:

`[pre]` 改动前基线：`run.py --check` → `rc=0`；8 个离线回归
（`check_matrix_codec` / `check_period_aggregation` / `check_persistence` /
`check_side_flip` / `check_session_rollover` / `check_clock_protocol` /
`check_reconnect_gap` / `smoke_test`）→ 全部 `rc=0`。

`[pre]` 顺序声明清点（`grep -rn "升序\|降序\|inverse\|行序"`）：帧侧 3 处
（`contracts/feature.py:105`、`serialization/heatmap_matrix.py:13`、
`web/heatmap.js:3`）全写"升序"；冷数据侧 6 处（`heatmap_engine.py:244,256`、
`check_persistence.py` 5 处）写"升序"。**没有任何工具断言帧 strikes 的顺序**
⇒ 它此前是一条无回归的隐式假设。

`[post]` 消费者审计（改动前先做，确认影响面）：`web/matrix_codec.js` 纯行主序
还原、`web/app.js:229` 与 `tools/check_side_flip.py` / `check_session_rollover.py`
/ `smoke_test.py` / `heatmap_stats.py` 全部用**索引或枚举查找**，不假设顺序 ⇒
改行序不会静默错配。

`[post]` **前端方向实测**（探针在工程外
`C:/Users/Lenovo/.workbuddy-ai/tmp/strike_order_probe/`，`cp` 新 `heatmap.js`
到临时站点；Playwright + 系统 Chrome，`file://` 直开）：

```
① 改动前   帧 A_ascending_24  inverse=false  px(索引0)=431 px(索引23)=15
            → screen_top=7755  screen_bottom=7640
② 改动后   帧 C_descending_24 inverse=true   px(索引0)=15  px(索引23)=431
            → screen_top=7755  screen_bottom=7640
③ 只改帧   帧 C_descending_24 inverse=false  px(索引0)=431 px(索引23)=15
            → screen_top=7640  screen_bottom=7755
SAME_AS_BEFORE: true · WRONG_IS_FLIPPED: true
```

⇒ **②与①视觉完全一致（本次改动屏幕零变化）**，同时证实 ③"只改帧不设
`inverse`"会翻转成"低价在上"。证据图 `artifacts/axis_three_way.png`。

`[post]` 语法与卫生：`node --check` 4 个前端文件全 OK；`git diff --check` 无
空白问题；改动后行数最长 `tools/smoke_test.py` 370/400。

NO-PATCH-BANDAGE: 排序落在**帧的产出点**（`build()` 是 `HeatmapMatrix` 行序的
唯一决定者，`strikes`/`rights`/`values` 由同一循环产出，顺序只定一次），不是
给前端加防御性重排。前端只加了方向参数 `inverse`，没有复制任何后端不变量。

NO-FALLBACK-BEHAVIOR: 无。行数、列数、有值格数、`vmax` 全部不变，只改行的顺序。

NO-COMPAT-BRANCH: 无。不保留"升序帧也能画"的兼容分支 —— 帧顺序是契约，不是
可选项。

NOTES-PATHS:
- `notes/sessions/2026-09-13/frame-strike-order-descending/handoff.md`（本文件）
- `notes/sessions/2026-09-13/frame-strike-order-descending/project_state.md`
- `notes/sessions/2026-09-13/frame-strike-order-descending/artifacts/`（2 件）
- `notes/context/handoff.md` · `project_state.md`（指针与当前态）

## Closed in session

- **帧与屏幕的纵轴语义已统一为降序**：`build()` 产出降序，`heatmap.js` 的
  `inverse` 让索引 0 落在最上方 ⇒ 帧数组从头读到尾 = 屏幕从上往下 =
  `7755 → 7640`。**KAI 提出的"避免歧义"已落地。**
- **屏幕视觉零变化**（实测 `SAME_AS_BEFORE: true`）—— 本次只对齐了"数据顺序"
  与"视觉顺序"，没有改变任何画面。
- **"帧升序"这条无回归的隐式假设被替换为显式契约 + 回归**：
  `tools/smoke_test.py` 的「矩阵 strikes 降序」，含非空转证伪。
- **依赖关系反转**：`build()` 不再依赖 `StrikeWindow.rows()` 恰好升序这个跨模块
  巧合；顺序由产出点自己保证。
- 消费者审计完成：全工程无任何模块假设帧 strikes 的顺序（见 `COMMAND-EVIDENCE`）。

OPEN-RISKS:
- **冷数据（`data/session.db`）与帧现在方向相反** —— `dump_bucket()` 输出
  **升序**（2026-09-13 `cold-data-strike-order` 会话刚加的 `sorted()` + 回归），
  帧输出**降序**。两者是不同层（内部恢复产物 vs 对外契约），各自有文档与回归，
  但**读代码的人可能在两者之间串味**。已在本文件与 `project_state.md` 说明；
  是否要把冷数据也统一为降序，**待 KAI 决定**（改动小：`sorted(..., reverse=True)`
  + `check_persistence.py` 的键序用例取反）。
- **4 个需服务的检查仍未跑**（同上一会话）—— 硬切实盘后只有盘中能跑。本次
  改了 `web/heatmap.js`，`check_page_render` / `check_web_contract` 的覆盖价值
  比上次高，但**未验证就是未验证**。
- **`check_reconnect_flow` 在本环境跑不了** —— 缺 `ib_async`。本机 Python
  3.13.14 未装项目依赖，只有纯标准库的回归能跑。
- **改动已提交并推送 `7ffe882`**（24 文件，+1071/−68）—— 含本会话与上一会话
  （`cold-data-strike-order`）的全部改动；工作区干净，远端 `git ls-remote` 已核实。
  （本条原记"未提交"，于本会话内闭环。）
