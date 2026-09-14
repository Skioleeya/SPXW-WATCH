# Project State — frontend-render-fix-and-skill-split

本文件只放**"为什么"**：设计取舍、被否掉的选项、坑。变更清单与命令证据在 `handoff.md`。

## 两条工作流的关系

一个会话、一个 session root，但内部是两条**独立**工作流：

1. **前端渲染** —— 属本仓库，改了 4 个 `web/` 文件。
2. **skill 拆解** —— 只动用户级目录 `~/.workbuddy-ai/skills/spxw-live-verify/`，**与本仓库代码无关**。

按 `notes-session-records` 约定不拆成两个 session root，故在此声明。
`handoff.md::CHANGED-PATHS` 已把两者分开列。

## 缺陷 A（热力图边框）—— 取舍与坑

- **为什么改 shader 而不是恢复 ECharts 的 `itemStyle.borderWidth`**：
  热力图已由 `af2e2e4` 换成单次 draw call 的 WebGL 引擎，逐格矩形会退化成上千次绘制，
  与当初重写的动机（列数可到 2370）直接冲突。边框本质是"格内 1 物理像素"的着色问题，
  放进 fragment shader 是零额外 draw call 的。
- **为什么边框默认关闭（`mix=0`）**：GL 引擎保持中性、不替调用方决定视觉；
  要边框必须**显式**调 `setCellBorder()`。`heatmap.js` 是唯一调用方。
- **为什么复用 `theme.grid` 而不新增配置键**：`theme.grid` 在 `af2e2e4` 后成了**死配置**
  （零引用）。它原本的语义就是"网格线颜色"，与本次需求同一件事。
  复活既有键比新增 `heatmap.cellBorderColor` 更符合"不制造重复真相"——
  但代价是**配色与强度分居两处**（色在 `theme.grid`，强度在 `heatmap.cellBorderMix`），
  已在 `config.js` 注释里写明。
- **坑（两次）**：见 `handoff.md` 交付 2。核心教训是
  **`bw = 1/cellPx` 这类归一化阈值在 `cellPx ≤ 2` 时会失效** ——
  阈值一旦 ≥ 0.5，`localX<bw || localX>1-bw` 就覆盖整格。**必须先判"这个方向还画不画"，
  再算阈值**，而不是先算阈值再夹紧。

## 缺陷 B（图例色）—— 取舍与坑

- **坑（本质）**：ECharts 的 legend 图标读 `series.itemStyle.color`，
  **不读 `lineStyle.color`**；两者都没设时才退到按索引的默认调色板。
  ⇒ 只设 `lineStyle.color` 是**看起来对、图例错**的配置。
- **为什么不用 `legend.data[].icon` 之类去对齐**：那是从显示端绕过数据端的错配，
  会把"曲线是什么颜色"变成两处真相。正解是让 series 自带颜色语义（`itemStyle` + `lineStyle` 同值）。
- **为什么留长注释**：`itemStyle.color` 与 `lineStyle.color` 同值**看起来像冗余**，
  后人极易"清理"掉其中一个 —— 这正是本次缺陷的成因。注释的作用是把它钉成契约。

## 工具与探针的坑（与缺陷无关，但会重复踩）

- **透明代理**：`http_proxy=127.0.0.1:61420` 让 `urllib` 把 localhost 也送进代理
  （根路径放行、子路径 502）⇒ **全部静态资源报假失败**。
  `no_proxy` / `NO_PROXY` 在本机**无效**（Windows 走注册表 `ProxyOverride`，`reg.exe` 被安全策略挡）。
  正解：`build_opener(ProxyHandler({}))`。
- **`curl` 在本环境写盘失败**（`Exit Code 23`），且 `%{size_download}` **不可信** ——
  取字节一律用 Python `urllib`。
- **探针 URL 拼接**：页面里资源是相对路径（`src="app.js"`），
  探针漏加前导 `/` 会拼成 `8060app.js` ⇒ `InvalidURL`。
- **`playwright-cli` 的 daemon 在两次独立 `npx` 调用之间会被回收** ——
  `open` / `eval` / `screenshot` 必须在**同一条 shell 命令**里串起来。
- **元素截图抓不到 ECharts 的内部 canvas 图例** —— 对文本容器截图只得到标题行。
  要读图例色块只能**采 canvas 像素**（`getImageData`；WebGL canvas 取 `getContext('2d')` 返回 null，
  所以此法只对 2D canvas 有效）。

## skill 拆解的依据

`spxw-live-verify/SKILL.md` 原 **703** 行，远超"一次能读完并照做"的尺度。
拆法：**主文件只留"决策所需"**（何时用 / 前置条件 / 步骤 / 判定标准 / Top5 陷阱 / 专题索引），
**细节按专题外移**到 `references/`。判定标准**刻意留在主文件**——
它是"能不能下结论"的依据，翻页才能看到就等于没有。
