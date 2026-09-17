TASK-ID: heatmap-two-window
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单

# Handoff — 热力图纵轴「画 40 档 / 露 24 档」

STARTUP-PROOF: N/A:本会话以「读配置、读代码」开场，**改动前未跑过 `--check`**，
  没有可引用的基线。改动前的绿是**上一会话**（2026-09-16 16:0x，`run.py --check`
  16/16）的记录，不是本会话采到的 —— 按 skill 规则**不补写 `startup.md`**，
  故本会话根只有两个文件。

## 需求（KAI 原话）

> 配置前端 iV 热力图：数据分为 20 档，绘制时渲染 40 档，实际只显示中间 24 档。
> 请据此完成热力图的档位映射与显示范围配置，明确档位划分规则、绘制与显示的
> 档数对应关系，以及中间 24 档的截取方式。

## 档位映射（三条规则，全部落在代码里）

1. **选档（后端 L5）** `features/strike_window.py::window_strikes()`
   —— 以现价为中心，取「`≤ 现价` 的最大 N 档」+「`> 现价` 的最小 N 档」，
   N = `heatmap_draw_rows_each_side`（20）⇒ **每帧 40 行**。
   行序由 `HeatmapEngine.build()` 显式排成**降序**（行 0 = 最高行权价）。
   每档只取虚值一侧（`< 现价` 取 Put，`>= 现价` 取 Call）。
2. **可视（前端）** `web/heatmap_window.js::visibleRange()`
   —— 同一口径的 N = `heatmap_visible_rows_each_side`（12）⇒ **24 行**。
   在 40 行里的下标区间 = `[boundary − 12, boundary + 11]`，
   `boundary` = 帧里「行权价 > 现价」的行数。
3. **落图（前端）** `web/heatmap_option.js::buildOption()`
   —— series 里放**全部 40 行**，`yAxis.min/max` 把可视区间收成 24 行。

三个半径的对应关系与三条不变量见 `README.md §4` 的表。

## CHANGED-PATHS

```
config/features.json                    改：heatmap_rows_each_side → heatmap_draw_rows_each_side=20，
                                            新增 heatmap_visible_rows_each_side=12，新增 _heatmap_window_comment
config/subscription.json                改：_window_comment（容差改按【可视】半径算；标注行为回归缺失）
config/surface.json                     改：_min_strikes_comment（喂进曲面的档数≠显示档数）
contracts/feature.py                    改：HeatmapMatrix 新增 visible_rows_each_side: int = 0
features/strike_window.py               改：读新键 heatmap_draw_rows_each_side；模块注释加两个窗口
features/feature_engine.py              改：读可视半径（[7] 归属要求读取点在本层）+ dataclasses.replace 挂上矩阵
features/surface_engine.py              改：修过时注释（原写「±12 档 = 24 个行权价」）
serialization/heatmap_matrix.py         改：帧里新增 "visible_rows_each_side"
tools/selfcheck_config_invariants.py    改：[6] 改为三条窗口不变量（绘制≤订阅 / 可视≤绘制 / 容差按可视算）
tools/selfcheck.py                      改：_MUTATIONS 为 [6] 新增 2 条变异（共 3 条）
tools/check_web_contract.py             改：PAYLOAD_PATHS 新增 heatmap.visible_rows_each_side
web/heatmap_window.js                   新增：可视行窗口的纯函数（93 行）
web/heatmap_option.js                   新增：ECharts option 构建（318 行，从 heatmap.js 拆出）
web/heatmap.js                          改：只剩面板生命周期（167 行）；update() 加第三个参数
web/app_render.js                       改：从**帧**读可视半径并传入；读数改成「可见 24/40 档」
web/index.html                          改：新增两个 script 标签
web/test_heatmap.html                   改：第三个参数 + 现价改到中间档（原来是贴顶，形状不真实）
README.md                               改：features.json 键名 + 新增「三个半径」表
notes/memory/QUICKREF.md                改：卡 P（窗口容差）重写为三窗口口径
notes/memory/RULES.md                   改：§6.6 两条窗口不变量改为三条
```

## COMMAND-EVIDENCE

```
./venv/Scripts/python.exe run.py --check
  → RC=0，16/16 项全部通过
  → [6] 四条读数：档位 ±20 → 81 条；绘制 ±20 ≤ 订阅 ±20；
                  可视 ±12 ≤ 绘制 ±20（每帧发 40 行、屏幕显示 24 行）；
                  窗口容差 8 档 ≥ 重建触发 3 档
  → [1] 94 个 Python + 15 个前端脚本全部合规（最长 ibkr_gateway.py = 399 行）

./venv/Scripts/python.exe tools/selfcheck.py --selftest
  → RC=0，18/18 项全部被抓到（含 [6] 的 **3** 条变异）
  → 对照（未变异副本）→ 全绿

./venv/Scripts/python.exe tools/check_web_contract.py --offline
  → RC=0；DOM id 20 个 / CFG 路径 42 条 / 扫描 15 个 JS 全部对上
./venv/Scripts/python.exe tools/check_web_contract.py --offline --selftest
  → RC=0，两条对照都「已抓住」

./venv/Scripts/python.exe tmp/l5_smoke.py
  → RC=0，PASS 32 / FAIL 0（L5 在新配置下行为不变）
  ⚠️ 该夹具是 ±12 档 ⇒ 覆盖不到 40 行的形状（窗口被可用档数截断到 25 行）

./venv/Scripts/python.exe tmp/_probe_40rows.py      （本轮新写，留在 tmp/）
  → RC=0，19 条判据全通过
  → rows=40；契约带 visible_rows_each_side=12；帧里该键=12 且 rows=40；
     行权价降序 7770…7575；现价上/下各 20 档；可视区间下标 8..31；
     可视最上一行 = 现价+60、最下一行 = 现价−55（现价正好压在档上）；
     ③ 对照：可视半径改成 30 ⇒ **行数仍是 40**（两个半径正交）

node tmp/_probe_window_live.js                       （本轮新写，用完即删）
  → 基线 RC=0：drawnRows=40 / visibleCount=24 / hidden=16 / axisExtent=[8,31]
  → 变异（visibleRange 恒返回全部行）RC=1：
     「FAIL 显示行数不是 24: 40 | 被裁行数不是 16: 0 | 可视区间不是 8..31: 0..39」
  → 已还原，重跑 RC=0

node tmp/_probe_meta_drop.js                         （本轮新写，用完即删）
  → RC=0：把 visible_rows_each_side 挂在 block 上，经 sliceZones 之后**即丢失**
     （aggregate / clipTail 同样丢失）—— 证明「从帧上读」是必须的，不是偏好

node --check web/*.js                                （15 个文件逐个）
  → 全部无输出（语法通过）。**手工拆过 heatmap.js，所以这一步不能省**
     —— 当前 `--check` 里**没有** JS 语法检查器（`check_web_syntax.py` 已随重写删除）
```

## VALIDATION-SUMMARY

```
run.py --check                → RC=0（16/16）
selfcheck.py --selftest       → RC=0（18/18 变异被抓）
check_web_contract --offline  → RC=0（含 --selftest）
l5_smoke.py                   → RC=0（32/0）
_probe_40rows.py              → RC=0（19 条判据）
_probe_window_live.js         → RC=0 基线；变异后 RC=1（已还原）
_probe_meta_drop.js           → RC=0（字段确被吃掉）
node --check web/*.js         → 15 个文件全部通过（无输出）
```

**真机联调（2026-09-17 03:09 补做，IB Gateway PID 1232 + 后端 PID 7784）**

```
run.py（活链路）              → 就绪；日志「帧 N | 客户端 M | 分片 80 | 现价 7614 | 订阅 80/92」
tmp/_dom_check.js             → RC=0（PASS 15 / FAIL 0）
   · WS 已连 · 帧推进「帧 #801 · 丢 0 · 缺口 0」
   · /health 页面连着时 clients=1 · frames=801 · payload_bytes=45211
   · 27 个 DOM id 全在；heatmap_window.js / heatmap_option.js 均 200
   · 纵轴 40 行；yAxis.min/max = 8/31
   · convertToPixel 复核 ⇒ 恰好 24 行落在网格矩形内
   · series 194 点、覆盖 40 行、行号全在 0..39
   · 成交量 Top-N 描边格 3 个，全部落在可视区内
   · 读数「可见 24/40 档 × 421 桶 · 194 格 · 色标 ±0.50 · 全时段 · 1分」
   · Skew 已渲染「6/421 点 · 当前 +3.09 · ATM 16.45」· 无 JS 报错
tools/check_web_contract.py   → RC=0（**在线**，第 [3] 项活链路；载荷 59 条含新路径）
tmp/_probe_window_sweep.js    → RC=0（现价 7730→7490 共 51 点，宽度恒 24、
                                  from 单调、两端夹 0/16、窗口移动 16 次）
tmp/_probe_window_follow.js   → RC=0。两次实测：现价 7614.20 ⇒ 区间 [8..31]；
                                  现价 7618.20 ⇒ 区间 [7..30]（整体上移一行、现价居中）
                                  ⇒ 窗口确实随真实现价移动；但单次采样内现价没动
                                  （见 OPEN-RISKS #1 的残留缺口）
run.py --check（改文档后复跑）  → RC=0（16/16）
```

## NOTES-PATHS

```
notes/sessions/2026-09-17/heatmap-two-window/handoff.md
notes/sessions/2026-09-17/heatmap-two-window/project_state.md
notes/memory/QUICKREF.md
notes/memory/RULES.md
```

## Closed in session

- 纵轴「画 40 / 露 24」落地：后端发 40 行、前端只显示中间 24 行，窗口随现价移动。
- `[6]` 的窗口容差判据从「按绘制半径算」修正为「按可视半径算」——
  改之前这条会**假红**（20 − 20 = 0 < 3），而真实容差是 20 − 12 = 8。
- `[6]` 新增第三条不变量「可视 ≤ 绘制」（本特性引入的**新**静默失效模式）。
- 成交量 Top-N 高亮的排序范围从「全部行」改为「可视行窗口」——
  不改的话黑边会全落在看不见的 16 行上，可视区一个黑边都没有（静默失效）。
- `yInterval` 的分母从帧行数改为**可视行数**（`maxYLabels` 防的是屏幕上挤，不是帧里挤）。
- `web/heatmap.js` 444 行顶破门禁 ⇒ 按职责拆出 `heatmap_option.js`（318）+ 剩 167。
- 修掉三处过时注释（`surface_engine.py` / `surface.json` / `subscription.json` 的窗口口径）。
- **真机联调补做并全绿**（2026-09-17 03:09）：DOM 渲染 `PASS 15 / FAIL 0`、
  在线契约检查 RC=0、窗口扫描 FAIL 0。见 VALIDATION-SUMMARY。
- **纠正一条文档错值**：把「每帧发 40 行」改写成「**上限**，预热期不足」——
  真机实测启动约 1 分钟内 33 行，依据是窗口取自 `TickStore.refs()`
  （"至少收到过一个 tick 的合约"）。改 `README.md §4` + `features.json` 注释。
- 本轮 5 只一次性探针留在 gitignore 的 `tmp/`：`_dom_check.js` / `_diag_front.js` /
  `_diag_series.js` / `_probe_window_follow.js` / `_probe_window_sweep.js`。
  其中 3 处误报是**探针自己的 bug**（`parseInt("帧 #365")=NaN`、
  用整块画布而非网格矩形判可见、ECharts 点有两种形状只读了裸三元组那一种），
  已在探针里修掉并留注释。

## OPEN-RISKS

1. ~~**真机联调未做（最高优先级）**~~ → **2026-09-17 03:09 已补做，RC=0**（见
   VALIDATION-SUMMARY 的"真机联调"块）。真实帧里 40 行、页面读数「可见 24/40 档」、
   在线契约检查全部通过。**残留缺口（已缩小）**：窗口**确实随真实现价移动**
   （现价 7614.20 ⇒ 区间 `[8..31]`；现价 7618.20 ⇒ 区间 `[7..30]`，整体上移一行、
   现价仍居中），但**单次采样内现价没动** ⇒ 「移动**过程中**不闪不空」只有
   **确定性扫描**证据（`tmp/_probe_window_sweep.js`）+ 两次不同稳态的对照，
   **没有"移动途中逐帧观察"的证据**。想彻底钉死：在现价连续穿越行权价的那几十秒里
   连续采样（把 `tmp/_probe_window_follow.js` 的 `SWATCH_SAMPLES` 加大即可）。
   ⚠️ 另记：起服务前先确认 `ibgateway.exe` 真的在（KAI 首次启动后 Gateway 上游断连、
   进程自行退出，`run.py` 4 秒即 `Socket disconnect` 崩掉）。
2. **「每帧发 40 行」是上限不是保证（本轮实测纠正的文档错值）**。
   当帧行数 = `min(20, 池内≤现价) + min(20, 池内>现价)`，池 = `TickStore.refs()`＝
   "至少收到过一个 tick 的合约"（`state/tick_store.py:133`，调用点
   `features/feature_engine.py:243` 再按到期日过滤）。**两种情形不足 40**：
   ① **现价漂移（常态）** —— 订阅窗口锚在**上次重建中心**
   （`acquisition/feed_reconcile.py::centre_moved` 判定 `|current − previous| ≥
   trigger×step` = 15 点才重建），热力图窗口锚在**实时**现价
   （`features/strike_window.py::window_strikes` 的 `below[-20:] + above[:20]`）。
   **实测（同一天同一进程）**：现价 7614.20 ⇒ **40 行**；现价 7618.20 ⇒ **39 行**；
   再采样 300 次 / 120s（现价 7617.10–7618.80）⇒ **恒 39 行**。
   ② **冷启动** —— 实测约 1 分钟内 **33 行 / 0 格**。
   可视 24 行**不受影响**（`S − V ≥ T` 保证最坏情况 ≥ 24 行；前端在 `2V ≥ 行数`
   时退化为全显，行数够时按现价居中，实测 33 行时区间 `[2..25]`）。
   已修 `README.md §4` 与 `config/features.json::_heatmap_window_comment`。
   ✅ **续查（03:45）**：`refs()` **确实会保留**"已退订但曾有过 tick"的档
   （`prune()` 只按时间裁样本、**不删键**，`state/tick_store.py:203`），
   **但不构成用户可见缺陷**：① 可视区（现价 ±12）**永远落在当前订阅区之内**
   （订阅中心与现价差 ≤ `T`=2 档，故 `现价±12 ⊆ C±14 ⊂ C±20`）；
   ② 可能冻住的行只在**绘制窗口最外侧**（距现价 ≥18 档），比可视区外扩 6 行以上。
   **实测** `tmp/_probe_stale_rows.js`（按"每行最后一个非空格所在桶号"判）：
   39 行 **0 行落后** ⇒ 当前无冻住行。
   ⚠️ **守卫就是 `S − V ≥ T`** —— 调到 `S − V < T` 就会把冻住的行移进可视区。
3. **性能未重测**。series 里的矩形从 24 行涨到 40 行（+67%），
   `web/heatmap.js` 头部那张实测表（630/1352/2370 列 = 65.7/159.9/188.1 ms）
   是**24 行**下测的，新形状没测过 —— 已在该文件头标注「未验证」。
4. **`notes/context/*` 已同步**（本会话已把它指过来）：`handoff.md` 顶部新增本会话块、
   `project_state.md` 的 `ACTIVE_SESSION`/`LAST_UPDATED` 已改、`open_tasks.md` 新增
   「Active —— 热力图双窗口」四条。⚠️ 三个文件的**旧内容原样保留、未 retro-fit**
   （其中"24 行"等读数描述的是改动前的形状），旧块前都加了"以下为上一会话"的分隔说明。
   是否要把旧块压成归档指针，由 KAI 定（`notes/context/` 只该是最新态，
   但现在整份文件是历史累积）。
5. **两处知识库引用了已不存在的检查器**：`QUICKREF.md` 卡 P 与 `RULES.md §6.6`
   都写「行为侧由 `tools/check_window_tolerance.py` 守住」，但该文件在白纸重写中
   已删（`tools/` 只剩 14 个文件、`check_*.py` 只剩 1 个）；`RULES.md §6.6` 与
   卡 Q 引用的 `tools.fixtures.display_window_strike()` 同样不存在。
   ⇒ 容差这条**目前只有静态门禁**，没有行为回归。本轮已在卡 P 里如实标注。
6. ~~`tmp/mut14/` 是 2026-09-15 留下的**整棵源码副本**（`tmp/` 下、已被 gitignore）。~~
   **2026-09-17 03:5x 已办**：确认全项目无任何引用后，按项目惯例（`mv` 不用 `rm`）
   **移出项目**到 `C:\Users\Lenovo\AppData\Local\Temp\spxw_mut14_20260915`
   （2.3 MB / 144 文件已核）。移后 `run.py --check` 仍 **16/16**；
   grep `heatmap_rows_each_side` 不再命中 `tmp/mut14/`。**还原**：`mv` 回 `tmp/mut14`。
   ⚠️ 纠正一条我自己的错误判断：`tmp/` **不会**被 ripgrep 自动跳过
   （Grep 工具同样搜得到 `tmp/mut14/...`）；排除法是 `glob: "!tmp/mut14/**"`（已验证）。
7. 上一会话（`runtime-monitors`）的两只探针仍在 `tmp/`，**无回归保护**（KAI 已知）。
8. **两条无害噪声**（本轮新发现，未修）：① `favicon.ico` 404（浏览器自动请求、
   无代码引用）；② 客户端硬关时 asyncio 自己打一条
   `ConnectionResetError [WinError 10054]`（在 `_ProactorBasePipeTransport`
   里，不是本项目代码，不影响流水线）。均登记在 `open_tasks.md`。

