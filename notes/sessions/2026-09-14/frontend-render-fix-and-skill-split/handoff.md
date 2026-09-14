TASK-ID: frontend-render-fix-and-skill-split
DATE: 2026-09-14
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change
STARTUP-PROOF: N/A:本会话首个写操作（`web/skew.js` 修复）早于基线捕获，按约定**不回填** `startup.md`

# Handoff — frontend-render-fix-and-skill-split

一个会话，两条独立工作流（见 `project_state.md` 的说明）：**前端渲染**与**skill 拆解**。
前者改了代码，后者只动用户级 skill 目录。

## 交付 1 —— 前端渲染核查（无代码改动）

KAI 要求"启动系统 → 检查前端网页渲染详情 → 用 Playwright 连真实 Chrome 检查 DOM 容器"。

- 服务启动：`05:07:24 流水线已就绪`；活帧证明合成链路在跑（现价 `7603.32 → 7603.58 → 7603.83`，
  同期 IBKR 指数仍冻结在 `7656.98`）。
- 静态核查（`tmp/probe_frontend.py`）：首页 **3146** 字节、**27** 个 DOM id、
  **17** 个静态资源全 `200`、`ws_probe` **27/27**。
- 真实 Chrome DOM 容器：`{"total":27,"missing":[],"zeroSize":[]}` —— 唯一 console 报错是 favicon 404。

⚠️ 探针曾把 17 个静态资源全报 `502`（**假失败**）：透明代理 `http_proxy=127.0.0.1:61420`
让 `urllib` 把 localhost 也走了代理（根路径放行、子路径 502）。
`no_proxy` / `NO_PROXY` 在本机**无效**（Windows 走注册表 `ProxyOverride`，`reg.exe` 被安全策略挡）。
修法：`urllib.request.build_opener(urllib.request.ProxyHandler({}))`。

## 交付 2 —— 缺陷 A：热力图"网格线"消失（已修）

**根因**：不是坐标轴 `splitLine`（旧版就是 `show: false`）。真正的"网格线"是旧 ECharts 版
`heatmap.js` 里每格的 `itemStyle: { borderWidth: 1, borderColor: CFG.theme.grid }`，
在 `af2e2e4` 的 WebGL 重写中**被删掉且未在新引擎实现** ⇒ `config.js:116` 的 `theme.grid`
成了**死配置**（`grep -rn "theme\.grid" web/` 命中 0 处引用）。

**修法**：在 `gl_heatmap.js` 的 fragment shader 里补逐格边框，新增 uniform
`u_cellBorder` / `u_resolution` / `u_borderMix`，并给 `GlHeatmap` 加 `setCellBorder(r,g,b,mix)`。
`heatmap.js` 用 `hexToRgb(CFG.theme.grid)` 调用它；`config.js` 新增 `heatmap.cellBorderMix: 0.55`。

**两次踩坑（关键，别重犯）**：
1. 首版守卫写成 `cwpx>=2.0 && chpx>=2.0`（**与**）——1 分档 ~570 列时格宽 1.95px，整条边框被跳过。
2. 改 `bw = 1/cellPx` 后，`cellPx ≤ 2` 时 `bw ≥ 0.5`，`localX<bw || localX>1-bw` **覆盖整格**
   ⇒ 热力图会糊成一片深灰。
   **正解**：两个方向**独立**判断，某方向格子 < 3 物理像素时**该方向不画**。

实测：1 分档（~570 列）横向网格线可见；5 分档（115 列）完整双向网格。

## 交付 3 —— 缺陷 B：Skew 图例色与曲线色系统性不符（已修）

**根因**：ECharts 的 legend 图标取 `series.itemStyle.color`（否则按 series 索引取默认调色板），
**不读 `lineStyle.color`**。而 5 条 series 当时**只设了** `lineStyle.color`。
实测图例色块 `#5470c6/#91cc75/#fac858/#ee6666/#73c0de`
vs 曲线色 `#ff5a5a/#4ea8ff/#5d6874/#ff5a5a/#4ea8ff` —— **5 项中 3 项不符**。

**修法**：5 条 series 全部补 `itemStyle.color`（与 `lineStyle.color` 同值），
并在 `skew.js` 里写明注释"**两处必须一起改**，itemStyle 不是冗余"，
防止后人当重复配置删掉（这正是本次缺陷的成因）。
修后 `itemStyle` 与 `lineStyle` **5/5 一致**。

## 交付 4 —— `spxw-live-verify` skill 拆解（703 → 209 行）

主 `SKILL.md` 保留：何时用 / 前置条件 / 步骤 / 判定标准 / Top5 陷阱 / 专题索引；
细节外移到 `references/` 六份：`pitfalls.md`(161) · `frontend.md`(222) · `config-changes.md`(129) ·
`live-link.md`(120) · `spot-synthesis.md`(108) · `bandwidth.md`(65)。
六条引用路径已逐一核实存在。

CHANGED-PATHS:
- web/skew.js — 5 条 series 补 `itemStyle.color` + 说明注释
- web/gl_heatmap.js — shader 逐格边框（3 uniform + 独立方向守卫）+ `setCellBorder()`
- web/heatmap.js — 新增 `hexToRgb()`，构造函数接 `setCellBorder(theme.grid, cellBorderMix)`
- web/config.js — 新增 `heatmap.cellBorderMix: 0.55`
- tmp/probe_frontend.py — 一次性探针（`tmp/` 已 gitignore，不入库）
- notes/context/open_tasks.md — 两条缺陷转"已修"并附根因/修法/证据
- notes/context/handoff.md · notes/context/project_state.md — 索引改指向本会话
- .workbuddy-ai/memory/2026-09-14.md — 当日记录
- ~/.workbuddy-ai/skills/spxw-live-verify/SKILL.md — 703 → 209 行
- ~/.workbuddy-ai/skills/spxw-live-verify/references/{pitfalls,frontend,config-changes,live-link,spot-synthesis,bandwidth}.md — 新建 6 份

COMMAND-EVIDENCE:
- `.venv/Scripts/python.exe tools/check_web_syntax.py` → `RC=0`，`全部通过（14 个文件）`
- `.venv/Scripts/python.exe run.py --check` → `RC=0`，13 项全通过；
  `[13] 联通与数据通道` 实测活链路：`connected / mode=delayed`、订阅 `48/92`、
  热力图 `24 档 × 1179 桶`、Skew 序列 `186 点`（服务在跑，故 `[13]` 未走 warning 分支）
- `md5sum web/{skew,gl_heatmap,heatmap,config}.js` →
  `1c98e5575944ee275e417a0107677dde` / `c257dd1efeb92d6fbb45d35a37d3a485` /
  `351c7bb75f65ac2a44827edec3c6d93e` / `d3789ebf10d320944f6d944cb75d866c`
- `grep -c itemStyle web/skew.js` → `8`（5 条 series 各 1 + 注释/其余）
- `grep -n "setCellBorder\|borderMix\|cellBorder" web/gl_heatmap.js` → 12 处命中
  （含 `gl_heatmap.js:157-158` 默认 `mix=0`）
- 非空转 A：`cellBorderMix=0` → 网格**完全消失**（截图 `mut-mix0.png`），改回即恢复
- 非空转 B：`series[0].itemStyle.color` 改回 `#5470c6` → 图例第 1 项立刻变回蓝紫
- 改动前后 4 个 `web/` 文件已恢复为上述 md5（逐字节一致）
- Playwright 真实 Chrome：`{"total":27,"missing":[],"zeroSize":[]}`

VALIDATION-SUMMARY:
- `check_web_syntax.py` → `exit 0`
- `run.py --check` → `exit 0`（13/13）
- 非空转变异 2/2 均被抓（`cellBorderMix=0` / `itemStyle` 还原）
- 前端渲染肉眼确认：1 分档横线可见、5 分档双向网格、图例 5/5 与曲线同色

NOTES-PATHS:
- notes/sessions/2026-09-14/frontend-render-fix-and-skill-split/handoff.md（本文件）
- notes/sessions/2026-09-14/frontend-render-fix-and-skill-split/project_state.md
- notes/context/open_tasks.md
- notes/context/handoff.md
- notes/context/project_state.md
- .workbuddy-ai/memory/2026-09-14.md

OPEN-RISKS:
- **图例两项同名 `25Δ Skew`** —— `skew_helpers.js::displayName()` 把 `25Δ Skew·负` 也显示为
  `25Δ Skew`（正负分段渲染的设计）。改名属**产品决策，待 KAI 定**，本轮未动。
- **`check_page_render` 的 3 条 FAIL 判据可能有计时问题** —— 探针报 `meta 为空` ×2 与
  `选中: 全时段、1分`，已用 HEAD worktree 对照证明**非本轮引入**；
  但**真实浏览器里 `#heatmap-meta` 是有值的** ⇒ 怀疑是该检查的取值时机早于首次渲染。
  **仅标记，未排查。**
- **RTH 段实盘验证仍未做**（承接上一会话，`notes/context/open_tasks.md` 有账）——
  GTH 段已冒烟通过，09:25 交班 / 09:30 指数恢复实时**只能在盘中验**。
- **本会话 4 个 `web/` 改动未提交** —— 全树 `18 M + 7 ??`（基线 `HEAD=92a516c`）。
- **6 个既有失败回归仍未修**（`check_page_render` / `check_skew_alignment` /
  `check_skew_viewport` / `check_web_contract` / `check_ws_compression` /
  `check_period_aggregation`）—— 均 HEAD 对照确认非本轮引入，修法明确，**未获指令不动**。

## Closed in session

- ~~热力图格子边框（"网格线"）在 WebGL 重写时丢失~~ —— **已修**（见交付 2）
- ~~Skew 图例色与曲线色系统性不符~~ —— **已修**（见交付 3）
- ~~`spxw-live-verify` skill 703 行过长~~ —— **已拆为 209 行 + 6 份 references**（见交付 4）
- ~~前端 DOM 容器是否正常~~ —— **27/27 无缺失、无零尺寸**（见交付 1）
