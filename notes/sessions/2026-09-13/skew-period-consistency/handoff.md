TASK-ID: skew-period-consistency
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（KAI 直接指派）

# Handoff — skew-period-consistency

STARTUP-PROOF: N/A:会话由 KAI 的三步指派起手（先审后端 skew 引擎并与文献比对 →
再审前端绘制排版 → 最后下达改动指令），`startup.md` 未在改动前建，不补写。
改动前的基线读数（自检 11/11、10 个本地回归 `rc=0`）确实存在，落在
`COMMAND-EVIDENCE` 的 `[pre]` 行，不在本文件另开一节复述。

## Scope Understanding

- In scope:
  1. **P1-a**：Skew 横轴标签防重叠（`axisLabel.hideOverlap`）；
  2. **P1-b**：Skew 纵轴量程口径从「后端下发 `skew_min`/`skew_max` 两个极值」
     改为「后端下发**窗口长度**，前端在窗口内取极值」—— 口径留在后端 L4，
     计算落在前端；
  3. **P2-A**（KAI 选定 A）：**Skew 跟着周期一起聚合**，且热力图与 Skew 必须
     按同一个周期标签显示同一段时间。
- Out of scope: 后端 skew **算法本体**（`features/skew_engine.py` /
  `delta_locator.py`）—— 第一步审计已确认它与 Malz (1997)、Reiswich & Wystup
  (2009)、Bossens et al. 的主流口径一致，本轮一行未动；`heatmap.js`（列网格由
  `app.js` 传给它，不需要它知道周期）；ECharts 版本升级。

CHANGED-PATHS:
- `config/serialization.json` — 新增 `skew_scale_window_seconds: 3600.0` +
  `_skew_scale_comment`（说明它为什么是业务口径而非呈现参数）。
- `serialization/skew_series.py` — `__slots__` 加 `_scale_window_s`；新增
  `scale_policy` 属性（**只下发窗口长度，不下发极值**）；`encode_series` 去掉
  `skew_min`/`skew_max`、新增 `bucket`（`label` 与 `bucket` 同源，逐点对齐）。
- `serialization/frame_encoder.py` — `skew` 块新增 `scale_policy`。
- `tools/selfcheck_core.py` — `REQUIRED_KEYS["serialization"]` 追加
  `skew_scale_window_seconds`（新键必须被登记，否则 [5] 不认它）。
- `web/period.js` — 新增 `alignSkew()` + `nullArray()`：按
  `floor(bucket / group) - drop` 落列、取**组内末值**；docstring 由"热力图聚合"
  扩写为"基线序列 / 矩阵"四件事（含 `alignSkew`）；**修掉一处误告警** —— 被
  `clipTail` 裁掉的历史段（30 秒粒度下每帧 380 个）原本每帧刷一条
  `[period] … 已丢弃`，会把真正该响的"桶口径不符"淹掉，现改为静默。
- `web/skew.js` — docstring 重写量程设计约束；`axisRange(series, policy)` 按
  `window_s` 过滤（基准时刻取最后一个**有时间戳**的列）；`update()` 签名改为
  接收**已对齐**的 series；`axisLabel` 加 `hideOverlap: true`；返回
  `{points, cols, range}`。**同时修掉一个 P0，见下。**
- `web/app.js` — `renderHeatmap()` 改为 `return view`（列网格的唯一来源）；
  新增 `renderSkew(frame, view)`；`render()` 与 `setPeriod()` 都改为
  `renderSkew(frame, renderHeatmap(frame))` —— **顺序被强制**（热力图先算）。
- `tools/check_web_contract.py` — `PAYLOAD_PATHS` 的 skew 段替换为
  `skew.series.ts/bucket/label/skew/atm/put25/call25`、`skew.scale_policy`、
  `skew.scale_policy.window_s`；移除 `skew.series.skew_min/skew_max`。
- `tools/check_page_render.py` — **补记（2026-09-13 复核时补）**：改动发生在
  `handoff.md` 写完之后，故不在原始清单里。新增页面哨兵
  `SENTINELS = ("topbar","heatmap","skew","st-conn")` + `missing_sentinels()`，
  缺任一即判失败并中止 —— 修掉"8060 上没有我们的服务时 Chrome 拿到它自己的
  网络错误页，第 7 组断言在**别人的页面**上假通过"。
- `tools/check_web_syntax.py` — **新增**：`web/*.js` 语法门禁（178 行）。
- `tools/check_skew_alignment.py` — **新增**：Skew 与热力图列网格对齐回归（293 行）。
- `tools/skew_reference.py` — **新增**：上面那个回归的夹具（造数走**生产编码器**
  + 独立 Python 参考实现 + node 驱动，266 行）。
- `README.md` — §1 回归清单加两行；§7 前端：修 ECharts 版本号、补 `period.js` /
  `skew.js` 职责、重写 Skew 量程口径（旧文写"来自后端 `skew_min`/`skew_max`"，
  已过期）、新增「周期一致性」与「前端脚本语法门禁」两节。
- `notes/sessions/2026-09-13/skew-period-consistency/` — 本会话记录 +
  `artifacts/acceptance/2026-09-13/` 7 件。

VALIDATION-SUMMARY:
- `run.py --check` → 全部通过（**11/11**）；关键配置项 41→42、取键调用 137→138
- `python tools/check_skew_alignment.py --selftest` → 全部通过 + **4 个变异全部抓住**
- `python tools/check_web_syntax.py --selftest` → 全部通过（7 个文件）+
  **7 个变异全部抓住**
- `python tools/check_period_aggregation.py --selftest` → 全部通过（未受影响）
- 13 个本地回归批量 → 全部 `rc=0`（含两个新增）
- 离线载荷字段核对（工程外探针，替代需服务的 `check_web_contract` 第 3 段）→
  **55/55 命中**，且 `skew.series.skew_min/max` 确认**已不在帧里**
- `check_reconnect_flow` → **N/A:当前环境缺 `ib_async`**（import 阶段
  `ModuleNotFoundError`，与本次改动无关，改动未触及 `acquisition/`）
- `check_web_contract` / `check_page_render` / `check_ws_compression` /
  `ws_probe` → **N/A:周日无当日 SPXW 到期，服务在 `pick_zero_dte` 处
  fail-closed 退出**；且本机 Python 未装 `aiohttp`（`check_web_contract`
  顶层 import 就失败）。**其中 `check_web_contract` 的第 1、2 段已用桩模块
  离线补跑（PASS），第 3 段用离线等价物替代（55/55 PASS）**；
  `check_page_render` / `check_ws_compression` / `ws_probe` 三项**未跑**
- **真实链路渲染未验证**（同上，服务起不来）—— 见 `OPEN-RISKS` 第 1 条

COMMAND-EVIDENCE:

`[pre]` 改动前基线：`run.py --check` → `rc=0`（11/11）；10 个本地回归
（`check_clock_protocol` / `check_matrix_codec` / `check_period_aggregation` /
`check_persistence` / `check_reconnect_gap` / `check_session_rollover` /
`check_side_flip` / `check_subscription_qualify` / `check_tick_router` /
`smoke_test`）→ 全部 `rc=0`。

`[post]` **P0 事故与修复**（本轮最重的发现，值得单列）：

```
node --check web/skew.js
  web/skew.js:26
   * 为什么不用 visualMap 做正负着色
   ^
  SyntaxError: Unexpected token '*'
```

成因：上一轮重写模块 docstring 时拆成了两段，中间多留了一个
`* ----…---- */`，块注释在第 25 行**提前闭合**，紧随其后的说明文字掉到注释外面，
整个文件成了语法错误 ⇒ `window.SkewPanel` 根本不存在，**Skew 面板整块空白**。
修复后 `node --check` 7 个前端文件全 OK。

⇒ **为什么 13 个回归全绿却没抓住**：`check_period_aggregation.py` 只加载
`period.js`，`check_matrix_codec.py` 只加载 `matrix_codec.js`，
`check_web_contract.py` 只加载 `config.js` —— `skew.js` / `heatmap.js` /
`app.js` / `ws_client.js` **没有任何检查器加载过**。不是断言写错了，是根本没人在
看这几个文件。⇒ 新增 `tools/check_web_syntax.py`（见 `HARNESS-IMPROVEMENT`）。

`[post]` **周期一致性实测**（探针在工程外
`C:/Users/Lenovo/.workbuddy-ai/tmp/skew-layout-probe/`；真实 `period.js` +
`matrix_codec.js` + `skew.js`，按 `app.js::render()` 的顺序求值
`decodeFrame → aggregate → clipTail → alignSkew → SkewPanel.update`）：

```
基线桶宽 = 30 s   maxColumns = 400
热力图 rows=24 cols=780   skew n=780 bucket[0]=0 bucket[-1]=779
scale_policy = {"window_s":3600}
可用周期 = [30,60,180,300,900]

30s (g=1)  热力图 400 列 / 30s   clipped=380   skew 400 列  有值 400/400
60s (g=2)  热力图 390 列 / 60s   clipped=0     skew 390 列  有值 390/390
180s(g=6)  热力图 130 列 / 180s  clipped=0     skew 130 列  有值 130/130
300s(g=10) 热力图  78 列 / 300s  clipped=0     skew  78 列  有值  78/78
900s(g=30) 热力图  26 列 / 900s  clipped=0     skew  26 列  有值  26/26
```

⇒ **五个周期下 Skew 的列数与热力图列数逐列一致，且每列的 `ts` 都落在该列覆盖的
时间区间内** —— 即"选 30 秒两块图都是 30 秒一格，选 1 分钟两块图都是 1 分钟一格"
（KAI 的目标定义）。

`[post]` **量程窗口实测**（同一份数据，尖峰在基线桶 100、值 9.0）：

```
window_s=3600 → 上界 0.839（尖峰已退出窗口）
window_s=0    → 上界 10.620（等于旧的全序列极值，被尖峰撑大）
比值 12.7×
```

⇒ 证明 P1-b 的口径确实生效，且这条判据**不是空转**（关掉窗口必然看到尖峰）。

`[post]` **判据设计的自我纠正**（第一版验证是坏的，记下来防止重犯）：
初版用"`aligned.label` 与 `view.labels` 逐列相同"当断言 —— 但 `alignSkew` 里
`out.label = grid.labels.slice()` 是**直接复制**的，这条断言**永远为真**。同时
初版把**未解码**的位图块直接喂给 `aggregate`，它在 `!block.values` 时原样返回，
聚合悄悄不发生（五个周期都报 780 列 / 30s），而所有断言仍通过。两条都已修正：
判据改用**时间域**（只用 `ts`，不碰 `bucket` 字段），且帧必须走
`decodeFrame`。`artifacts/acceptance/2026-09-13/verify_align.js` 是第一版（保留
作为反例），`tools/check_skew_alignment.py` 是修正后的正式版。

`[post]` **`hideOverlap` 在 vendored 版本上确实存在**：
`grep -o '.\{80\}hideOverlap.\{0,80\}' web/vendor/echarts.min.js` 命中 3 处，其中
`e.get(["axisLabel","hideOverlap"])` 正是坐标轴标签路径。效果实测图
`artifacts/acceptance/2026-09-13/hideoverlap_on.png`。

`[post]` **版本号核实（差点写错）**：`web/vendor/echarts.min.js` 里同时有
`t.version="5.5.1"` 与 `t.dependencies={zrender:"5.6.0"}`，另有一处
`version:"5.6.0"` 属于内部 painter。**ECharts 是 5.5.1，zrender 是 5.6.0** ——
我一度按 5.6.0 改了 README，核实后改回 5.5.1 并加了一句"别把两者的版本号搞混"。

`[post]` **`check_web_contract` 的静态两段离线补跑**（顶层 `import aiohttp`
挡住模块导入，用桩模块绕过 —— 这两段本身不需要 aiohttp，只读 `web/` 静态文件）：

```
[1] DOM id：JS 引用 21 个，HTML 定义 26 个
  [ok] JS 引用的 id 全部存在
[2] CFG 路径：JS 引用 30 条
  [ok] CFG 引用的配置键全部存在
```

⇒ 本次改了 `web/app.js`（新增 `renderSkew`、`renderHeatmap` 改返回值），
**没有引入任何悬空的 DOM id 或 CFG 路径**。脚本与输出见
`artifacts/acceptance/2026-09-13/web_contract_static.py` / `.txt`。

`[post]` 语法与卫生：`node --check` 7 个前端文件全 OK；改动后行数最长
`web/period.js` 352/400、`tools/check_skew_alignment.py` 293/400、
`tools/skew_reference.py` 266/400、`tools/check_web_syntax.py` 178/400。

NO-PATCH-BANDAGE: 量程口径落在**后端 L4**（`serialization.json` 定义窗口长度、
`skew_series.py::scale_policy` 下发），前端只按同一下发值在窗口内取极值 ——
没有在前端写一个默认窗口长度。列对齐同理：列网格由热力图产出**一份**，
`alignSkew` 消费它，没有让两块图各自算一遍分组。

NO-FALLBACK-BEHAVIOR: `aggregate` 缺 `bucket_seconds` 时**不猜**基线桶宽，
报错并按基线原样返回；`alignSkew` 缺 `bucket`/`ts` 时返回 `null`，
`renderSkew` 据此**整体不更新**（宁可保留上一帧，也不拿上一帧的网格去配这一帧的
数据 —— 那会画出时间错位且不报任何错）。

NO-COMPAT-BRANCH: 无。`skew_min`/`skew_max` 是**删除**而非"新旧都发"；
`enc` 名字对不上前端直接报错并保留上一帧，不做格式嗅探。

HARNESS-IMPROVEMENT: 新增 `tools/check_web_syntax.py`。它存在的直接原因是上面
那个 P0 —— 13 个回归全绿而 Skew 面板是死的。门禁按**目录枚举**（`web/*.js`）
而不写死名单，新增前端文件自动纳入；`node` 不可用时**返回 1 而不是跳过**
（"跑不起来"不等于"通过"）；目录为空也返回 1（空集合不得冒充通过）。
非空转自检往每个文件的块注释开头插入一个多余的 `*/`（正是那次事故的形态），
7 个文件全部抓住。

NOTES-PATHS:
- `notes/sessions/2026-09-13/skew-period-consistency/handoff.md`（本文件）
- `notes/sessions/2026-09-13/skew-period-consistency/project_state.md`
- `notes/sessions/2026-09-13/skew-period-consistency/artifacts/acceptance/2026-09-13/`
  （7 件：两个新检查的 `--selftest` 输出、离线载荷字段核对、
  `check_web_contract` 静态两段的离线补跑、`hideOverlap` 实测图、
  第一版验证脚本作为反例）
- `notes/context/handoff.md` · `project_state.md` · `open_tasks.md`（指针与当前态）

## Closed in session

- **P0 已修**：`web/skew.js` 的语法错误（块注释提前闭合）—— 修前 `window.SkewPanel`
  不存在、Skew 面板整块空白。
- **P1-a 已落地**：`axisLabel.hideOverlap = true`，在 vendored ECharts 5.5.1 上
  确认该选项存在。
- **P1-b 已落地**：量程口径改为「后端下发窗口长度 + 前端窗口内取极值」。
  `skew_min`/`skew_max` 已从帧里删除（离线核对确认）。
- **P2-A 已落地（KAI 的目标定义达成）**：五个周期下 Skew 与热力图的列数与列时间
  区间**逐列一致**，实测见 `COMMAND-EVIDENCE`。
- **两处"静默出错值"被消除**：① 每帧 380 条误告警（会把真告警淹掉）；
  ② 两块图各算一遍列网格的风险（现在只有一份来源，`app.js` 强制先算热力图）。
- **两处文档过期已修**：README 的 Skew 量程口径（仍写 `skew_min`/`skew_max`）、
  ECharts 版本号。
- **新增两个门禁**：`check_web_syntax.py`、`check_skew_alignment.py`（后者含
  `skew_reference.py` 夹具），均带非空转自检。

OPEN-RISKS:
- **真实链路渲染未验证。** 周日无当日 SPXW 到期，服务在 `pick_zero_dte` 处
  fail-closed 退出，`check_page_render` / `check_web_contract`（第 1、2 段）/
  `check_ws_compression` / `ws_probe` 全部跑不了。本次改了三个前端文件
  （`app.js` / `period.js` / `skew.js`），**离线验证覆盖了数值与对齐，但没有
  一张真实链路的截图**。下一个交易日开盘后应补跑这四个检查并肉眼确认两块图
  的横轴对齐。
- **`check_web_contract.py` 顶层 `import aiohttp` 使第 1、2 段（DOM id、CFG
  路径，均为纯静态对照）无法用该检查**自己的入口**在无 aiohttp 的环境里运行。**
  本次用桩模块绕过补跑了这两段（全 PASS）、用离线等价物补了第 3 段 ——
  三段都覆盖过，但**走的都不是它的入口**。是否要把 import 挪进函数内（让静态段
  可独立运行），**待 KAI 决定** —— 改动小，但属于"重构现有工具"，未获指令不擅
  自动。
- **本机 Python 未装项目依赖**（`ib_async` / `aiohttp`），`check_reconnect_flow`
  同样跑不了。与本轮改动无关，但每次都会在回归清单里留下两个"跑不了"。
- **`skew_scale_window_seconds = 3600.0` 是经验值，未经盘中数据校准。**
  它的作用是"让早盘尖峰随时间退出量程窗口"。窗口太短则量程频繁跳、曲线呼吸；
  太长则退化成旧的全序列极值。**待下一个交易日用真实数据看 1 小时是否合适。**
- **`alignSkew` 的 `label` 仍是复制自热力图网格**，所以"两块图标签逐列相同"
  这条性质**结构上恒真**，不可作为回归判据。已在新回归里明确避开（改用时间域
  判据），但**读代码的人仍可能误以为它是一条有效断言** —— 已在
  `period.js::alignSkew` 的 docstring 与 README §7 写明。
