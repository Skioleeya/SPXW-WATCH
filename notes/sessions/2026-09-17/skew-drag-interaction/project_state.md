# Project State — skew-drag-interaction（2026-09-17）

## 一句话

Skew 图交互已改版完成并全绿：滚轮删除，改为三种按住拖动（轴区缩放 / 网格平移 /
底部轴区缩时间窗），双击复位三条轴。工作区**脏且未提交**。

## 仓库状态

- `HEAD = 390ac6e`（已推送远端）
- 工作区**脏**：本轮 5 个 `web/` 文件 + 3 个 `tmp/` 探针 + `notes/`，
  **外加上一会话** `heatmap-pan-drag` 未提交的 `web/heatmap*.js` 与
  `skew-dual-axis-zoom` 未提交的 `web/skew*.js`
  —— 三轮改动混在同一工作区，引用时注意区分。
- 未跟踪：`notes/analysis/`（本轮新建的目录）

## 文件行数（`run.py --check [1]`，上限 400 严格小于）

| 文件 | 行数 | 说明 |
|---|---|---|
| web/skew_zoom.js | **399** | 距上限只剩 1 行 —— 再加注释就会顶破 |
| web/skew_helpers.js | 348 | 纯函数 + 手势配置访问器 |
| web/skew.js | 310 | 编排 |
| web/skew_option.js | 156 | option 构建 |
| web/config.js | 270 | |
| web/heatmap.js | 342 | 上一会话改动 |
| web/heatmap_option.js | 378 | 上一会话改动 |

⚠️ **`skew_zoom.js` 399 行是本轮最大的结构性压力**：下一次动这个文件
几乎必然需要先拆分（可拆的缝：手势状态机 / 视图状态导出两块）。

## 服务状态（2026-09-17 11:1x EDT 实测）

- `:8060` 后端**在跑**
- `:1232` IB Gateway **在跑**
- 需要服务的检查（`check_web_contract` 在线 / Playwright 探针）**现在都能跑**

## 已验证 / 未验证

**已验证**
- `run.py --check` 16/16
- `check_web_contract` 离线 + 在线 全通过
- `tmp/_probe_skew_drag.js` 三模式：prod 26/0、nozoom 24/0、nopan 25/0（均 `RC=0`）

**未验证**
- 像素级 / 肉眼复核（判据只到 ECharts 内部状态与面板 `_xWin`）
- 真实物理鼠标手感；`throttleMs: 100` 的实际手感
- 触屏 / 触控板（未接，全项目无 `touch*` 监听）

## 下一步（若继续）

1. 提交本轮改动（含前两轮的 `web/heatmap*.js` 与 `web/skew*.js`）—— 需 KAI 定范围
2. 拆 `skew_zoom.js`（399 行）
3. 交互体验缺口按 `notes/analysis/2026-09-17-main-chart-interaction-audit.md`
   的优先级表推进（P0 三项几乎零成本）
