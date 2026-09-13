TASK-ID: multi-session-grid
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（KAI 以一句 `continue` 指派）
STARTUP-PROOF: 见 `startup.md`（基线读数采集于任何编辑之前）

# Handoff — multi-session-grid

## Scope Understanding

见 `startup.md::## Scope Understanding`。一句话：**接手一段未提交、无会话记录的在建
改动，把它推到自洽可交付** —— 修 1 处生产缺陷 + 3 处门禁缺陷、全量复验、写记录。

## 这段在建改动是什么

多会话交易日网格：`config/app.json` 的 `sessions`（GTH 20:15→次日 09:25、
RTH 09:30→16:00）被 `SessionClock` 展开成"会话 / 空档"交替的区段表，网格锚在
首个会话开盘、跨午夜，共 2370 桶 × 30s；区段表随帧下发到 `session.zones`，
前端据此生成 GTH / RTH / 全时段三个按钮，并把空档的列**整段切掉**。

起因（在建改动的注释里写得很清楚）：旧网格锚在 RTH 开盘 09:30，GTH 时段
`elapsed_s()` 被钳到 0，隔夜与盘前数据**全部落进第 0 桶**，GTH 根本无法验证。

CHANGED-PATHS（**本会话改动**）:
- `web/period.js` — `alignSkew` 消费 `grid.index`（生产缺陷修复，见
  `project_state.md::C`）；模块头 docstring 第 5 条与函数 docstring 同步。
- `tools/check_period_aggregation.py` — `evaluate()` 串入 `_slice_checks` /
  `_index_checks`（缺陷 B）。399 行。
- `tools/check_session_grid.py` — 退出码 `return 0 if failures else 1` →
  `return 1 if failures else 0`（缺陷 A）。395 行。
- `tools/skew_reference.py` — 新增 `_serial_config()`，`build()` 的 `_config()` →
  `_serial_config()`（缺陷 D）。
- `README.md` — 同步被改动推翻的口径：§0 摘要横轴、§1 工具清单加
  `check_session_grid.py`、§2 桶序号口径、§3 `app.json` 描述、§7 前端表与
  新增「时段切列」小节、§8 周期一致性、§10 时间桶约束与 `0/2370`、
  §10 新增"多会话网格只做过离线验证"边界条。
- `notes/sessions/2026-09-13/multi-session-grid/` — 本会话记录（三件套）。
- `notes/context/{handoff,project_state,open_tasks}.md` — 索引与当前态。

CHANGED-PATHS（**不在 git 跟踪内**，随本会话一并交付）:
- `.workbuddy-ai/memory/2026-09-13.md` — 追加本会话条目（**本项目 memory 目录不入库**）。
- `~/.workbuddy-ai/skills/harness-silent-pass-audit/SKILL.md` — **新建**的跨项目 skill：
  审计一套"全绿"的回归是否真的在跑、真的会红（6 项判据 + 4 个造坏输入手法）。
- `~/.workbuddy-ai/skills/spxw-live-verify/SKILL.md` — 补上多会话网格的验收点、
  三处容量上限联动、`check_session_grid` 必跑、`FakeClock` 签名变更；
  frontmatter description 同步（六项检查 → 七项）。
- `~/.workbuddy-ai/MEMORY.md` — 路由表新增 `harness-silent-pass-audit` 一行。

CHANGED-PATHS（**本轮接手的在建改动，同一次交付里带着，尚未提交**）:
- `config/app.json`（`session_open`/`session_close` → `sessions` 数组）、
  `config/serialization.json`（`heatmap_max_buckets` / `skew_series_max_points`
  780 → 2370 + 容量注释）
- `core/clock.py`（`SessionClock` 多会话化，+363 行）、`contracts/frame.py`
  （新增 `SessionZone`、`SessionBlock.zones`）、
  `serialization/frame_encoder.py`（帧里发 `session.zones`）、
  `state/market_state.py`（`session_zones()` 升格成契约对象）、
  `app/pipeline.py`（`_build_clock` 读 `sessions`）
- `features/feature_engine.py`、`features/heatmap_engine.py`（区段起点桶留白）
- `web/app.js`（时段按钮 + `displayView` 三步变换）、`web/period.js`
  （`sliceZones`）、`web/config.js`（`maxColumns` 400 → 2370、`sessions.allId`）、
  `web/heatmap.js`、`web/index.html`、`web/style.css`
- `tools/check_session_grid.py`（**新文件**）、`tools/period_reference.py`
  （区段/映射夹具 + `ref_align_indexed`）、`tools/skew_reference.py`、
  `tools/check_web_contract.py`（`PAYLOAD_PATHS` +6 条、`_resolve` 支持数组下标）、
  `tools/check_clock_protocol.py`、`check_period_aggregation.py`、
  `check_persistence.py`、`check_reconnect_gap.py`、`check_session_rollover.py`、
  `check_side_flip.py`、`check_skew_alignment.py`、`fixtures.py`、`selfcheck_core.py`、
  `smoke_test.py`、`ws_probe.py`

VALIDATION-SUMMARY:
- `python run.py --check` → `rc=0`（11/11）
- 13 个本地回归批量 → 全部 `rc=0`（含新门禁 `check_session_grid`）
- `check_period_aggregation.py --selftest` → 5/5 变异全抓，`rc=0`
- `check_skew_alignment.py --selftest` → 4/4 变异全抓，`rc=0`
- `check_session_grid.py --selftest` → 3/3 变异全抓，`rc=0`
- `check_web_syntax.py --selftest` → 7/7 变异全抓，`rc=0`
- `node --check web/*.js` → 7/7 OK
- 退出码非空转证伪（工程外探针）→ 做坏网格时 `RC=1`
- `check_web_contract` 三段离线等价物 → 第 1 段 22 个 DOM id 全存在 /
  第 2 段 32 条 CFG 路径全存在 / 第 3 段 61 条载荷路径 0 缺失
- 4 个需服务的检查（`check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`）+ `check_reconnect_flow` →
  `N/A:周日无当日到期、服务 fail-closed；本机缺 aiohttp / ib_async`
- 验收定时任务 → 上一轮的 `8b4fe600-…` 与本次创建的 `cdf2faac-…` 均**不在系统里**
  （`list` 空、`view` not found）。**2026-09-13 KAI 明确：这是他有意为之 ——
  不要设自动任务，由他手动在 GTH 时段验证。** 故本轮**不再重建**，并已删除本会话
  创建的那个（`automation delete cdf2faac-…` → `success:true`；`list` → `[]`）。
- 提交并推送 → `4b9a0b0..2b5c313`，远端 == 本地 HEAD（详见 `[commit]` 段）

COMMAND-EVIDENCE:

`[baseline]` 会话开头、首次编辑之前的只读读数（复现缺陷 A/B/C）：

```
run.py --check                    → 11/11 通过（rc=0）
check_session_grid.py             → 打印"结果: 全部通过" 但 RC=1
check_skew_alignment.py           → NameError: name '_config' is not defined
                                    （tools/skew_reference.py:151）
check_period_aggregation --selftest → [FAIL] 切列忽略区段过滤 → **未被抓住**
                                      [FAIL] 变异点已失效：找不到 'pos = index[b];'
13 个回归批量                     → 11 个 rc=0；check_session_grid / check_skew_alignment rc=1
```

`[fix-A]` 退出码非空转证伪（工程外 `python -c` 内联，不落文件；把 `sessions`
打成单会话 RTH 后调 `main()`）：

```
[FAIL] 区段表含至少一个非会话空档  1 个区段 / 1 个会话
[FAIL] 网格跨午夜
[FAIL] 存在'空档之后的首个会话'边界
结果: 3 项失败
RC = 1                              ← 修好后的失败路径确实返回 1（修前返回 0）
```

`[fix-B]` 接线后 `[5] [6]` 两组真的执行了（节选）：

```
[5] 时段切列 sliceZones()
  [ok] sliceZones(keep=gth+rth) 列数  56 vs 56
  [ok] sliceZones(keep=gth+rth) 映射表（基线列 → 切后列，-1 = 已切掉）  逐元素一致
  [ok] sliceZones(keep=nosuch) 无匹配区段时必须返回空  js=None
[6] 时段映射下的 Skew 落列
  [ok] 时段映射下 Skew 落列与参考实现逐值一致  17 个非空列
  [ok] 时段映射路径 ≡ 预映射路径  两条路径逐值相同
  [ok] 时段切列非空转：忽略映射必须给出不同结果
```

`[fix-B]` 同一份 `--selftest`，接线前后对照（这就是缺陷 B 的证据）：

```
接线前：  [FAIL] 切列忽略区段过滤（空档被留下） → **未被抓住**
          [FAIL] 变异点已失效：period.js 里找不到 '        pos = index[b];'
接线后：  [ok] 切列忽略区段过滤（空档被留下） → 已抓住（16 项失败）
          [ok] alignSkew 忽略时段映射 → 已抓住（3 项失败）
```

⇒ 五个变异全部被抓，`--selftest` `rc=0`。**这两条正是"忽略映射"这个缺陷的
非空转判据**，修 C 之前它一次都没跑过。

`[fix-C]` `alignSkew` 的两条入口给同一结果（`[6]` 组，见上）；
`check_skew_alignment.py` 在**不传 index** 的路径上逐周期全绿
（C0/C1 11 项 + C2/C3 10 项 + C4/C5/C7 15 项 + C6 4 项 = **40 项**），
说明改动没有影响"未切列"的老路径。

`[fix-D]` `check_skew_alignment.py` 从 `NameError` 崩溃恢复为全绿：

```
[C0/C1] 解码与聚合      → 11 项 ok（30s/60s/180s/300s/900s 列数与列宽）
[C2/C3] 时间轴一致性    → 10 项 ok（每列 ts 落在本列区间内 + 严格单调）
[C4/C5/C7] 末值语义     → 15 项 ok（取末值、首列 ts、面板读数）
[C6] 量程窗口           → 4 项 ok（开 0.839 / 关 10.620，12.7×）
结果: 全部通过（rc=0）
```

`[web-contract]` 三段离线等价物（本机缺 `aiohttp`，走不了它自己的入口；
探针在工程外 `C:/Users/Lenovo/.workbuddy-ai/tmp/`）：

```
web_contract_static.py（桩模块绕过顶层 import aiohttp）
  [1] DOM id：JS 引用 22 个，HTML 定义 27 个 → 全部存在
  [2] CFG 路径：JS 引用 32 条 → 全部存在
payload_paths_probe.py（真实流水线造帧：合成曲面 + FakeClock + 生产编码器）
  线格式载荷顶层键: atm cells health heatmap seq session skew spot ts type
  session.zones:
    {id: gth, label: GTH, is_session: True,  first: 0,    last: 1579, 20:15–09:25}
    {id: gap, label: 空档, is_session: False, first: 1580, last: 1589, 09:25–09:30}
    {id: rth, label: RTH, is_session: True,  first: 1590, last: 2369, 09:30–16:00}
  共 61 条路径，缺失/异常 0 条
  反向断言：skew.series.skew_min / skew_max 应已移除 → 确认不在帧里
```

⇒ DOM 引用从 21 → **22**（新增 `heatmap-sessions`）、CFG 路径从 30 → **32**
（新增 `sessions.allId` / `sessions.allLabel`），载荷路径从 55 → **61**
（新增 `session.zones` 及其 5 个子路径）—— 三处增量都随在建改动一起来了。

`[final]` 全部改动落盘后的终态复跑：

```
run.py --check            → rc=0
13 个本地回归批量         → 全部 rc=0
4 个 --selftest           → 全部 rc=0
node --check web/*.js     → 7/7 OK
```

`[automation]` 定时任务 —— **先误判成缺陷，KAI 澄清后关闭**：

```
automation list                            → automations: []（会话开头）
automation view 8b4fe600-261f-4ab8-9930-217dbf6b9eef
                                           → not found
automation create（2026-09-14 09:45 ET）    → id cdf2faac-df51-4c5e-ad79-90616985e8e3
automation list / view cdf2faac-…          → 当场可见，status=ACTIVE
date -d @1789393500                        → Mon Sep 14 09:45:00 EDT 2026（与 nextRunAt 一致）

—— KAI 澄清后 ——
automation delete cdf2faac-…               → success:true, deletedAutomationId=cdf2faac-…
automation list                            → automations: []
```

⇒ **KAI 2026-09-13 明确**：自动任务"不见了"是**他有意为之**，
验收由他**手动在 GTH 时段**做，**不要设自动任务**。
故本轮不再重建，并删掉本会话创建的那个。
⚠️ 教训修正：**"系统里没有"不等于"系统坏了"** —— 我把它当成工具缺陷并重建了两次，
在 KAI 澄清前属于**误判**（详见 `project_state.md::记录教训`）。

`[commit]` 提交并推送：

```
git rev-parse --short HEAD                → 4b9a0b0（提交前）
git ls-remote origin                      → refs/heads/main = 4b9a0b0（远端 = 本地，快进）
git add -A && git commit                  → 2b5c313（37 files changed, +2273/−402）RC=0
git push origin main                      → 4b9a0b0..2b5c313  main -> main，RC=0
git ls-remote origin                      → refs/heads/main = 2b5c313（远端 == 本地 HEAD）
```

NO-PATCH-BANDAGE: 退出码取反改在**表达式本身**（`return 1 if failures else 0`），
不在调用侧加 `|| true`、不在批量脚本里特判；两组对照接回 `evaluate()` 的**唯一
汇总点**，不在 `_report` 里另加分支；`alignSkew` 的映射在**消费点**处理，
**不**让 `sliceZones` 额外产出一份"已预映射的 skew 序列"（那等于把映射抄两份）。

NO-FALLBACK-BEHAVIOR: 无。`alignSkew` 的 `index === null` **不是**兜底分支 ——
它是契约的另一条入口（序列里的桶号已是切后位置），由 `[6]` 组的
"时段映射路径 ≡ 预映射路径"钉住；少了这条等式，它才会退化成兜底。
`check_session_grid` 不提供"宽容模式"开关。

NO-COMPAT-BRANCH: 无。`config/app.json` 的 `session_open` / `session_close` 是
**直接删除**、不留"两套会话定义都认"的分支（`grep` 已确认全工程无残留引用，
只剩 `SessionClock.session_open_dt()` 这个**方法名**，它是 `grid_start_dt()` 的
显式别名）。

HARNESS-IMPROVEMENT: 本轮新增的是**接线**（两组已写好的对照回到 `evaluate()`）
与**一处取反修正**，没有新造检查。但记一条工具外的教训：
**"检查里写了 ≠ 检查里跑了"** —— `_slice_checks` 存在、`GROUPS` 有标题、
README 说"七组对照"，三处都写着，它却一次都没执行过，而报告照样打印"全部通过"。
判据是**数一遍实际执行了几组**，不是读代码里有没有这个函数。
（与上一轮的"记录里写了 ≠ 系统里有"、更早的 `check_page_render` 假通过同族。）

NOTES-PATHS:
- `notes/sessions/2026-09-13/multi-session-grid/handoff.md`（本文件）
- `notes/sessions/2026-09-13/multi-session-grid/startup.md`
- `notes/sessions/2026-09-13/multi-session-grid/project_state.md`
- `notes/context/handoff.md` · `project_state.md` · `open_tasks.md`

## Closed in session

- **4 处缺陷全部修复并复验**：1 处生产（`alignSkew` 忽略 `grid.index`，会让切列后
  两块图横轴错位 10 列）+ 3 处门禁（退出码取反 / 两组对照没接线 / `_config` NameError）。
- **13 个本地回归 + 4 个 `--selftest` + `run.py --check` + 前端语法全绿**。
- **缺陷 A 与 B 都做过非空转证伪**：A 用工程外探针确认失败路径返回 1；
  B 用"接线前未被抓住 / 接线后已抓住"的对照确认两组真的在跑。
- **`check_web_contract` 三段用离线等价物补齐**（61/61 载荷路径命中，
  含新增的 `session.zones`）。
- **`README.md` 口径同步**：`0..389` / `780` / `09:30→16:00` / `0/390` 等已被改动
  推翻的说法全部更新，并新增「时段切列」小节与 §10 的离线验证边界条。
- **会话记录补齐**：这段在建改动此前**没有任何会话记录**，现落在本会话三件套里。
- **提交并推送**（KAI 2026-09-13 指令）—— 见 `[commit]` 段与 `OPEN-RISKS`。
- **两条 KAI 裁定关闭了两个悬置项**（2026-09-13）：
  ① RTH 收盘 `16:00` 是**有意设定**（KAI 只在正股 RTH 09:30–16:00 交易），
  与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**；
  ② **不设任何验收自动任务** —— 由 KAI 手动在 GTH 时段验证。
  本会话创建的 `cdf2faac-…` **已删除**（`automation delete` → `success:true`，`list` → `[]`）。

OPEN-RISKS:
- **真实链路渲染仍未验证** —— 两个会话累计改了 `web/` 6 个文件
  （`app.js` / `period.js` / `config.js` / `heatmap.js` / `index.html` / `style.css`），
  **没有一张真实链路截图**。2026-09-13 是周日、无当日 SPXW 到期 ⇒
  `ChainResolveError`（fail-closed 正确），服务起不来。
  ⇒ **由 KAI 手动在 GTH 时段验证**（不设自动任务，见「已决策」）。
- **4 个需服务的检查从此只有盘中能跑**（`check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`）—— 模拟盘已物理删除，服务无法在非交易日常驻。
  盘前/盘后/周末"回归全绿"永远不成立，这是取舍的必然结果而非回归破坏。
  其中 `check_web_contract` 的三段本轮已用离线等价物覆盖，**但走的不是它自己的入口**。
- **`skew_scale_window_seconds = 3600.0` 仍是经验值**，未经盘中数据校准。
- **本机缺 `ib_async` / `aiohttp`** ⇒ `check_reconnect_flow` 与 `check_web_contract`
  在本环境直接 `ModuleNotFoundError`。
- **两个待 KAI 定的旧项未动**（见 `notes/context/open_tasks.md`）：
  `check_web_contract.py` 顶层 `import aiohttp` 是否内移；`check_clock_protocol.py`
  是否并入 `--check` 常驻。

