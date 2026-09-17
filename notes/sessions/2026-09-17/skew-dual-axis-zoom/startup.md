# Startup: skew-dual-axis-zoom

STARTUP-PROOF: 基线由 `tmp/_diag_skew_wheel.js` + `tmp/_probe_skew_yzoom.js` 在
**任何源码改动之前**跑出（2026-09-17 04:1x，真机 `:8060` + 真实帧）：

- 网格内滚轮一格：左轴 span `4.3683 → 4.3683`（**没变**）、右轴 `[14,19] → [14,19]`
  （**没变**）、而 X 轴 dataZoom `[0,100] → [4.5738, 95.4262]`（**被带偏了**）。
- 事件计数（同一格滚轮）：`zr.on("mousewheel")` = **1**；
  挂在容器 `#skew` 上的 wheel 监听 = **0**；挂在 `document` 上的 = **0**。
- 双击复位后：两条轴仍在 `[-0.57816,3.79016]` / `[14,19]`（本就没锁，看不出差别）。
- `min:null,max:null` 能否清掉显式量程：`auto=[14,19]` → pin `[9,24]` → 置 null →
  回 `[14,19]`（**能清掉**，复位可走 merge）。

⚠️ 本文件写于修复**之后**；以上数字是**逐字转录**修复前那次探针运行的输出，
未回填、未重算。之所以不重跑：修复后再跑已经拿不到"未变异"的基线。

## Session

- **task-id**: `skew-dual-axis-zoom`
- **日期**: 2026-09-17（EDT，GTH 段）
- **层级**: T2
- **起点**: `HEAD = 390ac6e`，工作区干净（`git status --short` 为空）

## Scope Understanding

- **In scope**：`web/skew.js` 的纵轴缩放扩成**左右两条轴同步**；
  把缩放交互（滚轮 / 双击）从"绑在图表容器上"改成能真正收到事件的位置；
  给 X / Y 两个分支定清触发方式、步长与上下限；两条轴的刻度、数值范围、
  坐标映射随缩放同步；读数报出双轴锁定区间；面板上写明操作手势。
- **Out of scope**：
  - 热力图侧的任何改动（它的 Y 轴窗口是另一套机制，`heatmap_window.js`）；
  - 新增"缩放控件"按钮 / 滑块（`index.html` 只加了一行文字提示）；
  - 左右轴**独立**缩放的交互（一次手势只缩一个轴）——见 `project_state.md` 的否决项；
  - `tools/` 下新增常驻检查器（KAI 2026-09-15 明令"不额外搭检查/校验模块"）。

## Prior Context Read

| 来源 | 取到的约束 / 决定 |
|---|---|
| `notes/context/open_tasks.md` | 未登记本项；热力图双窗口那轮（`130acdc`）已收尾，无冲突 |
| `_ref_spxw_head/notes/sessions/2026-09-15/heatmap-topn-skew-yzoom/handoff.md` | KAI 2026-09-15 对纵轴缩放的裁定：**滚轮**、**X 轴时间范围不变**、**缩放后锁定**、**双击复位**。本次沿用，不改语义 |
| `_ref_spxw_head/tools/check_heatmap_topn_skew_zoom.py` + `topn_zoom_driver.py` | 旧检查器只调 `SKEW` 的**纯函数**验缩放数学；`grep -rn "wheel" tools/*.py` **0 命中** ⇒ 从来没有驱动过真实滚轮事件。这解释了死绑定为何能一路全绿 |
| `notes/memory/QUICKREF.md` / `RULES.md` | 文件 < 400 行；禁止静默兜底；配置缺键即抛错 |
| `web/heatmap_window.js` | 拆文件的既有范式：新文件头写清"为什么单独放 + 契约与后端同源" |

## Recent Git Context

- Key commits reviewed: `390ac6e`（HEAD，notes 同步）、`130acdc`（热力图双窗口）、
  `857d4e5`、`76e00d3`（白纸重写落盘）。

## Worker Readiness

- **Risks noticed**：
  - `web/skew.js` 已 378 行，贴着 400 行门禁 ⇒ 新逻辑必须拆出去（拆出 `skew_zoom.js`）。
  - 后端 `:8060`（PID 7784）与 IB Gateway `:4002`（PID 1232）当时都在跑，
    **可以**做真机验证；但要先确认没有别的进程占用 `:8060`。
  - `index.html` 引用的 `runtime-config.js` 由后端 `transport/server.py:113` 动态生成，
    不是缺文件；控制台里那条 404 是 `favicon.ico`（已在 `open_tasks.md` 登记为低优先）。
- **Blockers noticed**：无。
