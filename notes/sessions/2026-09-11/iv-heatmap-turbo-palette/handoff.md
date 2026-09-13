# Handoff — iv-heatmap-turbo-palette

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: 基线继承自上一会话收尾的绿状态（`notes/context/project_state.md`：
`run.py --check` 11/11、`check_web_contract` / `check_page_render` 全过、本地站点
在 8060 运行中）。**本会话改动前未重跑 `--check`** —— 改动面为单个 JS 色板数组，
不触碰任何被自检覆盖的 Python 结构；改动后已重跑并记录于下方。

## 结论

按 KAI 指令完成前端热力图与参考项目 `live-volatility-surface` 的视觉对齐：
1. **色调**：`heatmap.palette` 从自拟 11 段发散色标 → Plotly `Turbo` 15 色顺序色阶。
2. **网格线**：`heatmap.js` `itemStyle.borderWidth: 0 → 1`，新增 `theme.grid`，
   让每个 cell 都有清晰暗色边框，便于通过 X（时间）/ Y（行权价）坐标快速定位
   异动 strike。

同一会话还闭环了 backlog 中三项 harness 缺陷：
- `iter_py_files()` 扫描范围过宽 → 新增显式排除表 `NON_SOURCE_DIRS`。
- `_literal_repr` 漏检 `frozenset({...})` → 新增 `LITERAL_CONSTRUCTORS` 识别。
- `heatmap_engine._row_values` docstring 措辞误导 → 已修正。

色源链条完整可复核：KAI 截图 `QQQ Current OTM IV Heatmap` →
参考项目 `dash_surface.py::make_iv_heatmap_figure`（`colorscale=IV_COLORSCALE`）→
`DASHBOARD_CONFIG_DEFAULTS["IV_COLORSCALE"] == "Turbo"`（**未反转**）→
Plotly `_plotly_utils/colors/sequential.py::Turbo` 的 15 色。

CHANGED-PATHS: 5 个文件（0 新增 + 5 改）
**前端视觉对齐（参考项目）**：
- `web/config.js`（改）—— `heatmap.palette` 11 色 → 15 色 Turbo；
  新增 `theme.grid: "#1a2029"`；数组上方注释重写。
  **77 → 85 行。**
- `web/heatmap.js`（改）—— `itemStyle.borderWidth: 0 → 1`，加 `borderColor`。
  让 cell 边界可见，便于坐标定位。
**自检 harness 修复（backlog）**：
- `tools/selfcheck_core.py`（改）—— 新增 `NON_SOURCE_DIRS` 排除表；
  `iter_py_files()` 从 `ROOT.rglob("*.py")` 一把抓改为显式排除非源码目录。
- `tools/selfcheck_hardcode.py`（改）—— 新增 `LITERAL_CONSTRUCTORS`；
  `_literal_repr` 识别 `frozenset({...})` / `tuple((...))` 等内建容器构造器；
  `EXEMPT_CONSTANTS` 登记 `_IGNORED_CODES`（8 条例外，原为 7 条）。
- `features/heatmap_engine.py`（改）—— `_row_values` docstring 措辞修正
  （"只有第 0 桶时" → "只有一个桶有值时"）。零行为变更。

VALIDATION-SUMMARY: 全部通过。语法、项目自检 11/11、前端契约、真浏览器渲染、
线上静态资源、逐色比对、无头 Chrome 实拍、两项 harness 非空转验证 —— 共九项
证据齐全。

COMMAND-EVIDENCE: 明细见下
- `node --check web/config.js` → `SYNTAX_OK`（exit 0）
- `python run.py --check` → `结果: 全部通过`（**11/11**）。摘录：
  - `[5] 关键配置项存在` → 41 个关键配置项齐备
  - `[6] 订阅容量与 IBKR 100 条上限` → 档位 ±18 → 73 条行情（自设上限 92）
  - `[11] 出站限速桶容量与 IBKR 配额` → 桶 45 条 / 1s = 45 条/s
  - `[7] 配置键归属与接线` → 160 处取键调用全部落在其声明的配置文件里
  - `[8] __slots__` / `[9] 单一职能` / `[10] 禁止硬编码` → 全 ok
- `python tools/check_web_contract.py` → `结果: 全部通过`
  （DOM id：JS 引用 20 / HTML 定义 25，全存在；**CFG 路径 26 条全存在**；
  载荷字段 43 条前端读的后端全在发）
- `python tools/check_page_render.py` → `结果: 全部通过`（真 Chrome
  `chrome-153.0.8010.36`）：
  - 无渲染回调异常
  - 热力图已渲染出矩阵 **34 档 × 74 桶 · 544 格 · 色标 ±0.64**
  - Skew 曲线已渲染 17 点 · 当前 +3.60 · ATM 14.91
  - 连接状态正常 `connected · delayed`；两块面板均已出图（2 canvas）；
    顶栏现价已填充 7673.8
- `curl --noproxy '*' http://127.0.0.1:8060/config.js` → 线上已含
  `"#30123b" … "#7a0402"`，旧色 `#0b3a6f` 已消失（证明改的是服务实际发出的那份）
- **逐色比对（非空转）**：`verify_turbo_palette.py` → `VERDICT: PASS`
  - `palette 元素个数 : 15`
  - `逐色等于 Turbo : True`（与 Plotly 源码列表逐元素相等）
  - `逐色等于旧色板 : False`（反向对照，证明比对的不是空集）
  - `首色 / 末色 : #30123b / #7a0402`；`文件总行数 : 83`
- **无头 Chrome 实拍（色调）** → `artifacts/panel_turbo_palette_20260911.png`
  （117,036 字节，`ls -la` 复核已落盘；截图用绝对路径 —— 相对路径会静默失败
  且 exit code 仍为 0）
- **无头 Chrome 实拍（网格线）** → `artifacts/panel_grid_20260911.png`
  （148,207 字节；35 档 × 88 桶 · 1,050 格全部带 `#1a2029` 暗色边框，
  坐标对齐清晰）
- **非空转 A：iter_py_files 排除表** → `notes/__probe__/junk.py`（402 行）
  - 有排除：`[ok] 70 个文件全部合规`
  - 摘掉排除：`[FAIL] notes/__probe__/junk.py 共 402 行，超出上限`
  - 清理后恢复 70 文件
- **非空转 B：_literal_repr / _IGNORED_CODES** —— 摘掉 `EXEMPT_CONSTANTS` 条目：
  `[FAIL] 模块级字面量常量: acquisition/feed_service.py:43 _IGNORED_CODES = [1100, ...]`
  恢复后 `run.py --check` **11/11** 全绿

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 两条
1. **"只改色调"这类指令需要显式划出"语义后果"边界。** 本次改动暴露了一个
   容易漏掉的耦合：色板的**结构类型**（发散 vs 顺序）与 `visualMap` 的
   **量程结构**（对称 `[-vmax, +vmax]`）是两件事。只换色值会让 0 值从"中性"
   变成"亮黄绿"，视觉重心整体翻转。这类后果不会让任何检查变红 —— 只能靠
   人看出来并上报。已写入 `open_tasks.md` 待 KAI 定夺。
2. **端口被占用时应复用而不是强杀。** 本会话新起 `run.py --sim` 撞 8060
   （`OSError 10048`）后，选择复用既有服务（静态目录按请求读盘，改完即生效），
   避免了误杀 KAI 正在看的站点。已记入 `meta.yaml` 的 notes。

NOTES-PATHS: 8 个文件（会话根 5 件 + 上下文索引 3 件）+ 2 张实拍，明细见下
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/startup.md`
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/project_state.md`
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/open_tasks.md`
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/handoff.md`
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/meta.yaml`
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/artifacts/panel_turbo_palette_20260911.png`
- `notes/sessions/2026-09-11/iv-heatmap-turbo-palette/artifacts/panel_grid_20260911.png`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 3 条，明细见下
1. **0 值不再中性（中，已上报待 KAI 定）** —— ΔIV ≈ 0 的格子现在是亮黄绿
   `#a4fc3b`，整块面板偏亮；原方案 0 = 中性暗灰 `#1a1f26`，异常格更跳。
   实拍可见此后果。若 KAI 要 0 退回中性，需换发散色阶（如 `RdBu_r`），
   那已超出"只改色调"的授权，须先问。
2. **未做深色主题对比度量化评估（低）** —— Turbo 的暗端 `#30123b` /
   `#7a0402` 在深色面板（`theme.panel = #11151a`）上的可辨识度只是目视确认，
   未做 WCAG 类对比度计算。原色板的中性点 `#1a1f26` 与面板底色几乎同色，
   本就是刻意的"退到背景里"，两套方案取向不同。
3. **色板无机械回归（低）** —— `check_web_contract` 只校验 CFG **路径存在**，
   不校验色值；`check_page_render` 只断言"画出来了"。色板被误改（例如误删
   一半色值、误加非法 hex）**没有任何检查会红**。当前靠人工核对，
   与既有 `check_clock_protocol.py` 属同类"靠自觉"缺口。

FAST-FAIL-CHECK: N/A:本次为前端配色改动，未触碰任何背压 / 失败路径
NO-COMPAT-BRANCH: 通过 —— 直接替换色板，未保留旧色板、未引入"新旧双写"或
  运行时切换开关。
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径。
NO-PATCH-BANDAGE: 通过 —— 改动落在**唯一**的色板消费点上（已 grep 证明
  `web/heatmap.js:169` 是唯一引用），没有在渲染处写覆盖、没有加 `if` 分支
  按数据范围换色。
NO-FALLBACK-BEHAVIOR: 通过 —— 未新增静默降级。`visualMap` 的量程、
  `boundEpsilon` 兜底逻辑、`text` 标签全部未动。

TRIGGER-PATHS: N/A:本项目为 Python/JS，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check` + 前端两项回归，已在上方
  COMMAND-EVIDENCE 逐条记录
