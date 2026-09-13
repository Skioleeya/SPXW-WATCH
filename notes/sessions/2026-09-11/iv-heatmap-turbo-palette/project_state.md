# Project State — iv-heatmap-turbo-palette

（本会话最新状态，非历史堆叠）

## 改动

**单文件、单数组**：`web/config.js` → `SWATCH_CONFIG.heatmap.palette`

- 改动前（11 段自拟发散色标，中点为中性暗灰 `#1a1f26`）：
  `#0b3a6f #155ea8 #3d8fd1 #8ec9ee #1a1f26 #1a1f26 #f6c98a #f4a259 #ef6f4c #d63b2f #a81f1c`
- 改动后（Plotly `Turbo`，15 色顺序色阶，逐色抄自参考项目）：
  `#30123b #4145ab #4675ed #39a2fc #1bcfd4 #24eca6 #61fc6c #a4fc3b #d1e834 #f3c63a #fe9b2d #f36315 #d93806 #b11901 #7a0402`
- 同时改写了该数组上方的注释（原「发散色标」表述在 Turbo 下不再成立），
  并在注释里写明色源、取位规则、以及"0 值不再中性"这一后果。

**其他文件零改动** —— `git`-less 工作树下用 grep 确认色板消费点唯一
（`web/heatmap.js:169`）。

## 色源链条（可复核）

1. KAI 截图标题 `QQQ Current OTM IV Heatmap` →
2. 参考项目 `dash_surface.py::make_iv_heatmap_figure`，用 `colorscale=IV_COLORSCALE` →
3. `DASHBOARD_CONFIG_DEFAULTS["IV_COLORSCALE"] == "Turbo"`（**未反转**）→
4. Plotly `_plotly_utils/colors/sequential.py::Turbo`（15 色，已逐色比对一致）。

## 取位规则（为什么两端能对上）

ECharts `visualMap.inRange.color` 传数组时，与 Plotly 传 list 色阶时**取位规则
相同**：在数组上等距取点。15 色 → 位置 `0, 1/14, …, 1`。本图 `visualMap` 是
`min: -vmax, max: vmax` 的对称量程，故 `-vmax` = `#30123b`、`+vmax` = `#7a0402`，
与原项目一致。

## 验证结果（本会话实跑）

| 命令 | 结果 |
|---|---|
| `node --check web/config.js` | exit 0 |
| `python run.py --check` | **11/11 全部通过**（结果: 全部通过） |
| `python tools/check_web_contract.py` | 全过 —— DOM id 20 / CFG 路径 26 / 载荷字段 43 |
| `python tools/check_page_render.py` | 全过 —— 真 Chrome，热力图 **34 档 × 74 桶 · 544 格 · 色标 ±0.64**、Skew 17 点、2 canvas、现价 7673.8 |
| `curl http://127.0.0.1:8060/config.js` | 线上已含 `#30123b` / `#7a0402`，旧色 `#0b3a6f` 已消失 |
| 无头 Chrome 实拍 | `artifacts/panel_turbo_palette_20260911.png`（117,036 字节） |

## 已知后果（已上报 KAI，待其定夺）

本图 `visualMap` 仍是 `[-vmax, +vmax]` 的**发散**结构，而 Turbo 是**顺序**色阶：
0 值落在第 8 色黄绿 `#a4fc3b`。因 ΔIV 绝大多数格子的值贴近 0，实拍显示面板
整体偏亮黄绿，异常格（深红/紫）对比度反而不如原中性灰方案醒目。
**这是"只改色调"的直接后果，不是缺陷**；若 KAI 要 0 重新退回中性，色板单改
做不到 —— 需换用带浅色中性点的发散色阶（参考项目 change 热力图用的 `RdBu_r`
即属此类），那已超出本次授权范围，须先问。
