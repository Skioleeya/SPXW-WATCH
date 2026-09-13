# Startup: iv-heatmap-turbo-palette

STARTUP-PROOF: 基线来自上一会话（`ibkr-rate-limit-audit`）收尾时的绿状态 ——
`notes/context/project_state.md` 记录 `run.py --check` **11/11**、
`check_web_contract` / `check_page_render` 全过、本地站点在 8060 上运行中。
**本会话未在改动前重跑 `--check`**（改动面为单个 JS 色板数组，不触碰任何被
自检覆盖的 Python 结构）；改动后已重跑，结果见 `handoff.md`。

## Session

- 任务 id：`iv-heatmap-turbo-palette`
- 日期：2026-09-11
- 触发：KAI 指令「将前端 IV 变化的色调改为原项目的热力图色调，只改色调」
  + 参考项目链接 <https://github.com/Skioleeya/live-volatility-surface>
  + 一张参考截图（标题 `QQQ Current OTM IV Heatmap`）。

## Scope Understanding

- In scope：
  - `web/config.js::SWATCH_CONFIG.heatmap.palette` 的色值。
  - 该数组上方那句注释（原写「发散色标」，换成 Turbo 后不再成立）。
- Out of scope：
  - `web/heatmap.js` —— 色板唯一消费点（`:169` 的
    `visualMap.inRange.color`）不动；`min: -vmax / max: vmax` 的量程不动；
    `text: ["IV 上行", "IV 下行"]` 不动。
  - `web/app.js` / `web/style.css` / `web/index.html` 不动。
  - 任何后端文件、`vmax` 截断策略（属 `config/serialization.json`）、
    坐标轴、tooltip、数据结构 —— 全部不动。
  - 不新增/删除任何配置键，故自检项数量不变（仍 11 项）。

## Prior Context Read

- `notes/context/project_state.md`、`notes/context/open_tasks.md`、
  `notes/context/handoff.md`（工作记忆已注入）。
- `web/config.js`（77 行，改动前）、`web/heatmap.js`（207 行，只读）。
- `tools/check_web_contract.py` 的校验范围（DOM id / CFG 路径 / 载荷字段
  三向引用一致性 —— **只校验路径存在，不校验色值**）。
- 参考项目 `dash_surface.py`、`DASHBOARD_CONFIG_DEFAULTS`；Plotly
  `_plotly_utils/colors/sequential.py`。

## Recent Git Context

- Key commits reviewed：`N/A:本仓库当前工作树由 KAI 直接管理，本会话未取 git 历史。`

## Worker Readiness

- Risks noticed：
  1. **语义漂移（已识别并上报）**：原色标是 `[-vmax, +vmax]` 的**发散**色标
     （0 = 中性暗灰）；Turbo 是**顺序**色阶，0 值落在第 8 色（黄绿 `#a4fc3b`），
     不再中性。已向 KAI 明示，并给出替代方案（见 `open_tasks.md`）。
  2. **误改风险**：色板在 `web/` 下只有一个消费点，已用 grep 确认（`tools/`
     下无任何针对 palette 的校验），改动面可控。
- Blockers noticed：无。8060 端口被既有服务占用（PID 23240）—— 选择复用而非
  强杀，不影响验证。
