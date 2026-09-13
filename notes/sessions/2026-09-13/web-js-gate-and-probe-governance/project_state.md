# Project State — web-js-gate-and-probe-governance

本文件装"为什么"。改了什么 → `handoff.md`；命令读数 → `handoff.md::COMMAND-EVIDENCE`。

## 为什么 `[1]` 必须扫 `web/*.js`

长度约束（文件 < 400 行）**与语言无关**。`iter_py_files()` 用**排除表**
`NON_SOURCE_DIRS` 而非白名单 —— 排除表漏了会**误报（响）**，白名单漏了会**漏检（静默）**。
`web` 原先被整目录排除，于是 `web/` 下的 JS 完全不受长度门禁。

后果：`run.py --check` 打印"82 个文件全部合规"是**真的**（对这 82 个 `.py` 而言），
但 `app.js` / `period.js` / `skew.js` 三个超 400 行的文件**不在它的视野里**。
绿灯不等于合规 —— 这是"探针全绿但实际是坏的"的又一变体：**门禁覆盖不到的目录，绿灯无意义**。

**做法**：新增 `iter_web_scripts()`（`web/*.js`，**按目录枚举**），只把 `.js` 送进 `[1]`。
`.js` 进不了 AST 类检查（`[2]` 分层 / `[9]` 单一职能 / `[10]` 硬编码都按 Python AST 扫），
但 `[1]` 是纯文本行数统计，跨语言成立。**只加 `[1]`，不加别的** —— 这是"覆盖面按目录清点"
的最小正确增量。

**为什么不能"纳入就顺手放宽上限"**：纳入即报 3 项 FAIL，那是**真实违规**。
把上限提到 550 就等于把门禁调成"永远绿"，比不纳入更糟。

## 守卫的期望集合**不能**从被守卫的对象自推（本轮新发现的第五例）

分组式回归（`GROUPS = ((标题, (前缀,)), …)`）报告时按前缀过滤。原先的完整性守卫是：

```python
known = [p for _, prefixes in GROUPS for p in prefixes]   # ← 期望集合自推
missing = [p for p in known if not any(c[0].startswith(p) for c in checks)]
if not checks or missing: ... 判据集合不完整 ...
```

**删掉 `[G4]` 那一组 ⇒ `known` 里也没有 `[G4]` ⇒ `missing` 为空 ⇒ 守卫放行**；
而 `_report()` 按 `GROUPS` 过滤，`[G4]` 的判据**连报告都进不去** ⇒ 失败计数为 0 ⇒
`RC=0`、报告照样打印"全部通过"。清空整个 `GROUPS` 同样放行。

**实测**（探针源码与前后读数见 `artifacts/guard_hole_probe.txt`）：
把 3 条 `[G4]` 判据做坏后，删掉 `[G4]` 组 → **守卫放行、报告出的失败数 0**。

**修法**：期望前缀改成**独立常量** `EXPECTED_PREFIXES`，三条都查：

1. `GROUPS` 的前缀集合必须**恰好**等于 `EXPECTED_PREFIXES`（多、少都报）；
2. 每条判据都必须被某个组**认领**（否则它失败了也不计数）；
3. 每个期望前缀都必须**真有**判据（否则该组是空的）。

守卫与它自身的非空转用例抽进 `tools/group_guard.py`（共享设施，别的回归可直接接）。

**教训**：这是"报绿但是假的"的**第五例**，形态与前四例不同 ——
前四例是"对照函数没接进汇总"，这次是**守卫的期望值来自被守卫的对象**：
删掉要守卫的东西，同时也删掉了守卫本身。⇒ 期望值必须来自**独立常量**，
且"分组表是否恰好覆盖它"要单独查。

## 临时探针为什么落在 `<项目根>/tmp/`

旧约定写的是"工程目录之外（`…/.workbuddy-ai/tmp/`）"。两个问题：

1. **路径含糊** —— 省略号没指明哪一级，而**只有用户级那个真实存在**，
   于是每次都落到 `C:/Users/Lenovo/.workbuddy-ai/tmp/`：**被所有项目共用**，
   里面混着别的项目的产物，没法按项目清理；
2. **理由不成立** —— 当时的理由是"避免被自检扫到"，可 `.workbuddy-ai` 本就在
   `NON_SOURCE_DIRS` 里，那个位置同样扫不到。真正的风险不是"被扫到"，
   而是**跨项目串味**。

**KAI 拍板（2026-09-13）**：落点 = `<项目根>/tmp/`。配套要求：探针里几乎必然有硬编码
（端口、URL、阈值），那正是 `[10]` 要抓的东西，所以**必须同时在两处登记**：

| 位置 | 作用 | 缺了会怎样 |
|---|---|---|
| `.gitignore` 的 `tmp/` | 探针不入库 | 探针被提交进仓库 |
| `NON_SOURCE_DIRS` 的 `"tmp"` | 不进 `iter_py_files()` | 探针被 `[1][2][9][10]` 当产品代码误报 |

**配套原则**：探针用完即弃，**判据要落成常驻回归**（`tools/check_*.py`）才算数。
只在探针里守着的东西，下次谁改坏了不会有任何东西报红 —— 本会话的
`check_skew_viewport.py` 正是为这条原则补的账。

---

## 决策记录（KAI 2026-09-13）

**不拆文件，只纳管。** 实施方案 = `iter_web_scripts()` 把 `web/*.js` 送进 `[1]`；
AST 类检查（`[2]` 分层 / `[9]` 单一职能 / `[10]` 硬编码）按 Python AST 扫，
**`.js` 进不去**，所以**只加 `[1]`，不加别的**。

理由：① 长度约束是**可读性**约束，与语言无关 —— `[1]` 是跨语言的最小正确
增量；② 前端是**被动空壳**（KAI 2026-09-13 定）—— 给它加语义门禁就是"在前端
复制一份后端才该有的不变量"，制造第二份真相；③ `web/*.js` 进 Python AST
是结构性做不到的事，硬塞会扭曲检查器或引入 JS 解析器 —— 收益不抵成本。

**`--check` RC=1 是长期预期状态**：`[1]` 会永久报 `web/app.js` 524 /
`web/period.js` 490 / `web/skew.js` 536 三项 FAIL。这不是门禁坏，是"门禁诚实
但决策就是不拆"。已在 `spxw-live-verify` skill 的判定标准段写明。

下方"原拆分方案（已否决）"作为决策档案保留 —— **不再列入待办**。如未来要
重新讨论，请先证伪"KAI 不拆"的两个理由（被动空壳 + 跨语言 AST 成本）。

---

## 原拆分方案（已否决）

> 下列是设计，**不实施**。当前 `--check` 报 3 项 FAIL 即这三个文件，且**预期
> 长期保留**。

## 目标与约束

| 文件 | 现况 | 目标 |
|---|---|---|
| `web/skew.js` | 536 行 | < 400 |
| `web/app.js` | 524 行 | < 400 |
| `web/period.js` | 490 行 | < 400 |

约束：① 单一文件单一职能（用户级 `MEMORY.md` 工程要求 2）；② **不得引入构建步骤**
（项目刻意保持"无构建、双击即跑"）；③ 不得制造第二份真相（同一事实只写一处）；
④ 行为**零变化** —— 拆分是搬运，不是改写。

## 方案 A（推荐）：按职能三向拆，`period.js` 保留为门面

### 1. `period.js`（490）→ 3 个文件

| 新文件 | 装什么 | 预计行数 |
|---|---|---|
| `web/period_grid.js` | **列网格几何**：`identityIndex` / `sliceZones` / `clipTail` / `nullArray` / `alignSkew` | ≈ 195 |
| `web/period_scale.js` | **聚合与色标**：`options` / `groupLabel` / `aggregate` / `bound` | ≈ 210 |
| `web/period.js` | **门面**：`warn`/`error` + 汇总导出 `global.SWATCH_PERIOD` | ≈ 58 |

**关键收益：`global.SWATCH_PERIOD` 的名字与形状一字不变** ⇒ 调用方（`app.js`、
以及全部 node 沙箱夹具）**零改动**。这是三个拆分里最干净、风险最低的一个。

**代价**：`check_period_aggregation.py` 的变异锚点会移动 ——
`aggregate` / `bound` 的注入点从 `period.js` 改到 `period_scale.js`；
node 加载清单从 `period.js` 变为三个文件。

### 2. `skew.js`（536）→ 3 个文件

| 新文件 | 装什么 | 预计行数 |
|---|---|---|
| `web/skew_viewport.js` | **视口几何（纯函数，不碰 ECharts/DOM）**：`labelInterval` / `windowOf` / `visibleSpan` / `axisRange` | ≈ 110 |
| `web/skew_plot.js` | **option 组装**：`NAME_POS`/`NAME_NEG`/`displayName` / `splitBySign` / `legendNames` / `tooltipFormatter` / `buildOption` | ≈ 260 |
| `web/skew.js` | **面板控制器**：constructor / `resize` / `clear` / `setViewport` / `_captureZoom` / `_applyViewport` / `_resetZoom` / `update`（薄化）/ `_readout` / `setViewportHook` | ≈ 225 |

`update()` 从 213 行降到约 40 行：它退化为"算 `win`/`range` → 调
`SWATCH_SKEW_PLOT.buildOption(...)` → `setOption` → 返回 `_readout()`"。
`axisRange` 是纯函数、无副作用，放进 `skew_viewport.js` 与 `windowOf` 同属"视口几何"。

**注意**：`update()` 走 `notMerge: true`、`_applyViewport()` 走 merge ——
这两条通路是**行为契约**，拆分时必须原样保留（回归 `[G3]`/`[G4]` 盯着）。

### 3. `app.js`（524）→ 4 个文件（最侵入，建议最后做）

| 新文件 | 装什么 | 预计行数 |
|---|---|---|
| `web/ui_dom.js` | **DOM 文本/类名读写 + 数值格式化**：`el` / `setText` / `setClass` / `num` / `signed` | ≈ 50 |
| `web/app_views.js` | **视图状态**：时段切换（GTH/RTH/全时段）+ 周期切换 + `displayView` / `groupOf` | ≈ 245 |
| `web/app_render.js` | **帧 → 屏幕**：`renderHeader` / `renderStatus` / `renderHeatmap` / `movers` / `renderSkew` / `writeSkewMeta` / `render` | ≈ 215 |
| `web/app.js` | **引导**：`state` + 面板装配 + 看门狗 + 连接 | ≈ 115 |

**这是唯一需要"依赖注入"的一个**，必须先把契约定死，否则会造出一堆隐式全局：

- `state`（含 `zones` / `periods` / `viewId` / `lastFrame` …）由 `app.js` 创建后
  传给两个模块：`SWATCH_VIEWS.init({ state, redraw })`、
  `SWATCH_RENDER.init({ state, dom, views, panels, getSocketStats })`；
- ⚠️ `renderStatus()` 读 `socket.stats.dropped` / `gapCount` —— 而 `socket` 在
  `app.js` 末尾才建。**不能**让 `app_render.js` 直接引用全局 `socket`（那是隐式双向依赖），
  必须由 `app.js` 注入 `getSocketStats()` 回调；
- ⚠️ `renderSkew` 的 `lastSkewLatest` 缓存与 `writeSkewMeta` 必须**同住一个模块**
  （`app_render.js`），否则视口回调会跨模块取缓存。

**为什么建议最后做**：`app.js` 是唯一有"跨块共享可变状态"的文件（`state` + 面板实例 +
socket），拆分必然引入注入契约；前两个拆分不引入任何新契约。

### 建议执行顺序

`period.js` → `skew.js` → `app.js`。理由：风险递增，且第一个能验证"门面 + 零改动调用方"
这条模式是否好用，再决定后两个是否也留门面。

## 检查器里的 web 文件清单：现状与收敛

拆分**不只是搬代码** —— 有 4 个回归工具依赖写死的文件名。现状（逐处核对过）：

| 位置 | 写死的内容 | 拆分后 |
|---|---|---|
| `web/index.html:89–97` | 8 个 `<script src>`（含 `vendor/`、`runtime-config.js`） | 加 7 个新文件，**顺序**必须满足依赖 |
| `tools/check_web_contract.py:163–164` | 6 个 js（CFG 路径扫描） | 不加 ⇒ 新文件里的 `CFG.a.b` 不被对照 |
| `tools/check_web_contract.py:104` | `("app.js",)`（DOM id 扫描） | `renderHeader`/`renderStatus` 搬走 ⇒ 这里要跟着改 |
| `tools/check_skew_alignment.py:212` | 4 个 js（node 加载清单） | 加新文件 |
| `tools/check_skew_viewport.py:295` | 4 个 js（node 加载清单） | 加新文件 |
| `tools/skew_reference.py:107` | 4 个 js（JS 沙箱加载清单） | 加新文件 |
| `tools/check_period_aggregation.py:370–371` | `period.js` + `config.js` | 加新文件 |
| `tools/check_period_aggregation.py:314` | 变异锚点在 `period.js` 内 | 锚点文件改 `period_scale.js` |
| `tools/check_skew_alignment.py:62–74` | 变异锚点文件名 | `alignSkew` → `period_grid.js`；`axisRange` → `skew_viewport.js` |
| `tools/check_skew_viewport.py:72–96` | 6 条变异锚点全在 `skew.js` | 分散到 `skew_plot.js` / `skew_viewport.js` / `skew.js` |
| `tools/check_web_syntax.py:75` | **已按目录枚举** ✅ | 无需改 |
| `tools/selfcheck_core.py:155` | **已按目录枚举** ✅ | 无需改 |

### 收敛做法（方案 A 的配套）：把 `index.html` 当加载顺序的唯一真源

新增共享设施 `tools/web_manifest.py`：

- `scripts() -> list[str]` —— 解析 `web/index.html` 的 `<script src="...">`，
  **只取同目录**脚本（排除 `vendor/`、`runtime-config.js` 这类非本项目脚本）；
- `load_order() -> list[Path]` —— 转成路径列表，直接喂给 node 沙箱与 CFG 扫描；
- `check_consistent()` —— **新增不变量**：`web/*.js` 与 `index.html` 引用的同目录脚本
  **必须一一对应**（孤儿文件、断链引用都算失败）。

**收益**：拆分只需改 `index.html` **一处**，4 个工具的加载清单自动跟上；
且顺手补上一条当前**完全没有**的防线 —— "新文件写好了但没接进页面"这类漏接，
今天没有任何检查会红（与 `web/skew.js` 曾经整文件语法错误却无人加载同族）。

**不收敛的部分（应当保持显式）**：变异锚点的**文件名**。那是"这段代码归哪个文件"的
事实，随拆分移动是必然的，而且**必须被人看见** —— 不该藏进 manifest 里自动推导。

### 建议同时加的检查项（可选，待 KAI 定）

`[12] web/index.html ↔ web/*.js 一一对应`，进 `run.py --check`（11 → 12 项）。
落地即 `web_manifest.check_consistent()`。⚠️ 会连带改 `README.md` §9 的表与
`MEMORY.md` 的"11 项"字样。

## 被否决的方案

| 方案 | 结论 |
|---|---|
| **B**：每个新文件加 `// deps: [...]` 注释，工具解析它来定顺序 | 否决。又多一份要维护的声明，且与 `index.html` 的真实顺序可能不一致 —— **两份真相**，正是本项目反复栽的那个坑。 |
| **C**：写构建步骤，从 manifest 生成 `index.html` | 否决。项目刻意保持"无构建、双击即跑"；引入构建会改变部署方式，也会让"打开 `index.html` 看现状"这条最常用的取证路径失效。 |
| **D**：把 `[1]` 的上限从 400 提到 550，让 3 个文件"合规" | 否决。那是把门禁调成永远绿，比不纳入更糟。 |
| **E**：只拆 `skew.js` 与 `app.js`，`period.js` 靠"聚合与色标本就是一个职能"辩解 | 否决。`options`/`groupLabel`/`aggregate`/`bound` 与 `sliceZones`/`alignSkew` 确实是两件事（前者改数值、后者改几何），490 行也不是"一个职能"能解释的规模。 |
| **A（推荐）**：按职能三向拆（详见上方原方案段） | **2026-09-13 否决（KAI 决策：不拆文件）**。理由：① 长度约束已由 `[1]` 纳管，② 前端是空壳不必加语义门禁，③ 跨语言 AST 成本不抵收益。详见"决策记录"。 |

## 拆分本身的风险（必须先说清）

- `web/` **没有任何运行时回归** —— 全部前端回归都是离线沙箱（node 替身），
  真浏览器只有 `check_page_render`，而它**需要服务在跑**（非交易日跑不了）。
  ⇒ 拆分后**必须在盘中**用真浏览器复核一次两块图都正常出图。
- 拆分会**移动 4 个回归工具依赖的变异锚点**。锚点失效是**响的**（工具会打印
  "变异点已失效，请更新 MUTATIONS"），不是静默的 —— 但仍需逐个更新并复跑 `--selftest`。
- `index.html` 的脚本**顺序**是隐性契约：加载顺序错 ⇒ `undefined` at runtime，
  而 `check_web_syntax.py` 只验语法、验不出顺序。这正是上面建议
  `web_manifest.check_consistent()` 的原因（一一对应能挡住"漏接"，挡不住"顺序错"）。
  若要连顺序也钉住，需要"每个脚本引用的 `global.SWATCH_*` 必须由**更早**的脚本定义"
  这类检查 —— 属可选增强，成本明显更高。
