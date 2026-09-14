TASK-ID: webgl-to-echarts
DATE: 2026-09-14
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change
STARTUP-PROOF: N/A:本会话首个写操作（`web/gl_heatmap.js` 调色板纹理绑定诊断）早于基线捕获，按约定**不回填** `startup.md`

# Handoff — webgl-to-echarts

承接 `notes/sessions/2026-09-14/heatmap-mirror-ffill-grid`。KAI 报"前端绿色周围有黑色色块"，
排查定位到**调色板纹理被顶掉**（见交付 1），随后 KAI 裁定：**换掉原生 WebGL，改用库渲染**。
本会话 = 定位 + 换渲染器 + 重建因事故丢失的改动（见"事故"节）。

## 事故（必须读）

**2026-09-14 08:1x，执行 `git rm -f --quiet web/gl_heatmap.js && git mv web/test_gl.html ...` 期间，
整个 `web/` 目录从工作区消失**（`git status` 显示 ` D web/*.js` ×17 + `D  web/gl_heatmap.js`）。
`git mv` 报 `fatal: bad source`；无任何命令显式删除目录，**成因未查明**。

- **恢复**：`git checkout -- web/` 从索引恢复（索引仍持有 HEAD 内容）⇒ 未提交的 `web/` 改动全丢。
- **丢失清单**（会话开始时 `git status` 记录为 ` M`）：`web/config.js`、`web/heatmap.js`、`web/skew.js`。
- **重建情况**：
  - `web/heatmap.js` —— 本就要被 ECharts 版替换，无需重建。
  - `web/config.js` —— 按上下文重建（新增 `cellBorderMix` / `cellBorderMinPx` 块）。
    **非逐字节还原**：重建版比会话版长 142 字节（注释内标点宽度差异），功能等价。
    会话版 md5 `42108155f4b4ed6ddf0a78e406449813` 无法复现，**不作宣称**。
  - `web/skew.js` —— 按 `frontend-render-fix-and-skill-split` 的验收判据重建：
    `grep -c itemStyle` → **8**（与会话记录一致）、`itemStyle` 与 `lineStyle` 颜色 **5/5 同值**。
- **纪律**：此后本仓库**不再使用 `git rm` / `git mv`**，改用 `rm` / `mv` + `git add`。

## 交付 1 —— 根因：WebGL 调色板纹理被数据纹理顶掉

**现象**（KAI 报）：绿色色块周围有黑色色块；换任何调色板都不改变渲染。

**根因**（读代码即可确证，非推测）：

- `gl_heatmap.js:157-165`（构造）把调色板绑在 **TEXTURE1**，并 `gl.uniform1i(u_palette, 1)`。
- `gl_heatmap.js:261-270`（首次 `update()`）在**未先 `activeTexture(TEXTURE0)`** 的情况下
  创建并 `bindTexture(this._dataTex)` —— 此刻活动单元仍是 TEXTURE1 ⇒ **数据纹理顶掉调色板**。
  此后 `pal` 再未被绑回，unit 1 永久是数据纹理。
- ⇒ `texture2D(u_palette, vec2(t,0.5))` 采到的是**数据纹理中间行**：
  有效格得 `(R,255,0)`（绿），落在空格处得 `(0,0,0)`（黑）。**同时解释了绿与黑**，
  也解释了"换色不改渲染"。

**判据**：调色板纹理在首次 `update()` 后不可达 —— 读 `gl_heatmap.js:261-270` 即可验证。
**未做**：黑块是否**恰好全部**源于此处，未做逐像素归因（换渲染器后该问题消失，未再追）。

## 交付 2 —— 换渲染器：原生 WebGL → ECharts（KAI 裁定）

**为什么选 ECharts 而不是 Plotly**（我定，已向 KAI 说明）：ECharts 已内置
（`web/vendor/echarts.min.js`，Skew 在用）⇒ 零新增依赖；且 `af2e2e4` 之前的热力图本
就是 ECharts。Plotly 要新增约 3.5MB vendor，且其 heatmap 同为逐格绘制，性能不占优。

**代价（实测，KAI 已知情并接受）** —— headless Chrome 153 + SwiftShader、1400×520、24 行、27% 填充：

| 列数 | 格数 | ECharts 重绘中位 | WebGL | 倍数 | 占 400ms 节拍 |
|---|---|---|---|---|---|
| 630 | 15,120 | 65.7 ms | 0.6 ms | 110× | 16% |
| 1352 | 32,448 | 159.9 ms | 1.0 ms | 160× | 40% |
| 2370 | 56,880 | 188.1 ms | 1.3 ms | 145× | 47% |

- 节拍来源：`web/ws_client.js:137` `minInterval = 1000/maxFps` = 200ms；后端推送 400ms ⇒ 实际 2.5Hz。
- **`progressive` 在此形状下是负优化**：2370 列 `progressive:5000` = 424ms，不开 = 188ms ⇒ 恒设 0。
- 原始画布 `fillRect` 地板：630→9.5ms / 1352→21.3ms / 2370→40.5ms ⇒ ECharts 的额外开销主要在
  JS 侧逐格数据处理，**换 GPU 也降不下来**。

**关键映射（避免被当成自创）**：
- 参考项目 `dash_surface.py:599,675` 用 Plotly `xgap=1 / ygap=1` 做格子间隙；ECharts 无等价项。
  改用轴 `splitLine` + `interval = stride-1` 抽样画线。
- `cellBorderMix` → 线的 `opacity`。`opacity m` 叠在数据色上 ≡ 旧 shader 的 `mix(color, border, m)`，
  **数学等价**，故两个配置键都保持有效，无死配置。
- `yAxis.inverse: true` —— 帧行序是降序行权价，索引 0 必须落在屏幕最上方。

**改动**：
- `web/heatmap.js` —— 整文件重写为 ECharts 实现（266 行）。公共接口
  `HeatmapPanel(el)` / `update(block, spot)` / `clear()` / `resize()` / `stats()` **不变**，
  `app.js` / `app_render.js` 零改动。手写 overlay（轴标签 / 色标 / 提示框）全部删除，
  交给 ECharts 原生能力。
- `web/gl_heatmap.js` —— **删除**（283 行）。
- `web/index.html` —— 移除 `gl_heatmap.js` script 标签。
- `web/test_gl.html` → `web/test_heatmap.html` —— 改名（原名已不成立）+ 换 script 标签 + 补 echarts。
- `web/test_sync.html` —— 换 script 标签 + 补 echarts。
- `web/config.js` —— 网格线注释改写为 ECharts/splitLine 语义（原文"在 shader 里按 canvas 分辨率换算"已不成立）。

## 验证证据

| 项 | 命令 | 结果 |
|---|---|---|
| 主门禁 | `venv/Scripts/python.exe run.py --check` | **RC=0 全部通过** |
| 前端语法 | `tools/check_web_syntax.py` | RC=0（13 文件） |
| 前端契约 | `tools/check_web_contract.py` | RC=0（DOM id / CFG 26 条 / 载荷 59 条） |
| 页面渲染 | `tools/check_page_render.py --budget 60000` | 热力图/ Skew / canvas≥2 / 现价 全部 ok |
| 真实页面取色 | `tmp/cdp_eval.mjs` + `tmp/expr_verify.js` | `nearBlackPixels: 0`、颜色桶 **516**、2 个 canvas |
| 截图 | `tmp/after_echarts_final.png` | 色标走完整 Turbo 谱；纵轴 7665C→7530P 降序；现货虚线落在现价对应档 |

**非空转验证（故意做坏）**：把 `config.heatmap.palette` 15 色全改成 `#ff00ff` → 页面
`#f808f8` 像素 145,124 个、颜色桶 **553 → 37**、绿色全消失；还原后 md5 逐字节回到
`eae7e64f694a2f15679be190b936e0f0`、颜色桶回到 516。⇒ 格子颜色确实来自 `config`，
这正是 WebGL 版失效的那条路径。

**`check_page_render` 默认 budget=14000 会失败**：虚拟时间跑在真实 WebSocket 帧之前，
`0 个 canvas` / `meta 为空`。`--budget 60000` 即恢复。**与渲染器无关**（既有失败，见
`notes/context/open_tasks.md`）。

## 未做 / 已知残留

- `features/persistence.py::recover()` 仍读全部桶 ⇒ 20:15 假 0 带（≤10 分钟），未修。
- RTH 段（09:30–16:00）实盘未验证。
- `check_page_render` 的"有且仅有一个周期处于选中态"断言：会话按钮 + 周期按钮各有一个 `on`
  ⇒ 恒为 2 个，断言本身过期（`app_sessions.js` 引入后未同步）。**未修**。
- 图例同名去重机制无常驻回归。
- 工作区改动未提交。
