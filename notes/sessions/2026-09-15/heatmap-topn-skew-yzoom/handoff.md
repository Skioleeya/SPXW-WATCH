# handoff — 2026-09-15 / heatmap-topn-skew-yzoom

- **task-id**: `heatmap-topn-skew-yzoom`
- **日期**: 2026-09-15（EDT，GTH 段）
- **基线 commit**: `0d30943`（工作区起点干净）
- **范围**: `web/config.js` · `web/heatmap.js` · `web/skew.js` · `web/skew_helpers.js` ·
  `web/skew_option.js` · `web/matrix_codec.js`（注释）· `tools/skew_reference.py` ·
  **新增** `tools/check_heatmap_topn_skew_zoom.py` · **新增** `tools/topn_zoom_driver.py`

---

## 1. 需求（KAI 原话要点）

1. **热力图**：黑色边框**无极调节**；拖动边框范围时，**仅对当前前端可视区域内成交量
   排名前 3 的网格**高亮，**其余网格保持普通显示样式**。
2. **25Δ Skew 实时曲线**：Y 轴**取消缩放限制**，滚轮**无限制上/下自由缩放**（可放大到
   极小刻度、也可缩小覆盖更大数值范围），缩放中**曲线渲染流畅**、**X 轴时间范围不变**。
3. 提交远端；提交前确保工作区无临时文件 / 调试代码 / 冗余资源。

### 1.1 KAI 的四条澄清（AskUserQuestion，均已落地）

| 项 | 裁定 |
|---|---|
| "当前可视区域" | **整张图** = 可视区域（不按分块、不按最近 N 列） |
| 高亮视觉 | 就是**已用于编码成交量的黑色边框**（不新增强调色） |
| Y 缩放语义 | **缩放后锁定，双击复位** |
| 边框归属（最终） | **只留 Top3 黑边，其余"普通" = 无黑边** |

> ⚠️ 第 4 条是对第 3 条的**收紧**：第 3 条曾理解为"非 Top3 保留按成交量分级的细边"，
> 最终裁定为**非 Top3 完全无描边**。

---

## 2. 实现

### 2.1 热力图 Top-N 描边（`web/heatmap.js` 314 → 353 行）

配置键**替换**（不是新增双键并存）：`config.js` 的 `heatmap.volumeBorder` →
**`heatmap.volumeTop`**：

```javascript
volumeTop: {
  enabled: true, topN: 3, color: "#000000",
  minPx: null, maxPx: null, maxRatio: 0.30, minRatio: 0.10
},
```

两个新函数：

```javascript
function pickTopCells(volumes, rows, cols, topN)
// 返回 { cells: { "c,r" → 条目 }, hi: 选中集最大成交量, lo: 选中集最小成交量 }
// 排序：b.v !== a.v ? b.v - a.v : (a.c !== b.c ? a.c - b.c : a.r - b.r)   ← 稳定且确定

function borderWidthFor(vol, hi, lo, loPx, hiPx)
// t = (vol - lo) / (hi - lo)   ← 分母是**选中集**的极差，不是第 N 名成交量
// 返回 loPx + (hiPx - loPx) * t
```

数据循环里：`var hit = pick && pick.cells[c + "," + r];`
**只有命中的格子**才拿到带 `itemStyle` 的对象；其余保持裸数组 `[c, r, v]`（普通样式、无描边）。

宽度上下界锚在格子**短边**：`vtHiPx = vt.maxPx > 0 ? vt.maxPx : cellShort * vt.maxRatio`、
`vtLoPx = vt.minPx > 0 ? vt.minPx : cellShort * vt.minRatio`。

### 2.2 Skew Y 轴自由缩放（`web/skew.js` 251 → 378 行）

- 档位状态：`_yLocked`（锁定量程）、`_yDecimals`（当前刻度小数位）
- `_bindWheel()` 绑在容器上，`{ passive: false }`（否则 `preventDefault()` 被浏览器忽略）
- `_inGrid(ev)`：用 `chart.getModel().getComponent("grid", 0).coordinateSystem.getRect()`
  判指针是否落在绘图区
- `_anchoredValue(ev)`：`chart.convertFromPixel({yAxisIndex: 0}, [x, y])[1]`
- 滚轮语义：**指针在绘图区外 ⇒ 直接 return**（把 X 缩放给既有 `dataZoom`）；
  在绘图区内 ⇒ `ev.preventDefault()` 并施加 Y 缩放
- `_applyViewport()` 改走 `H.effectiveRange(this._series, win, this._yLocked)`；
  小数位变化时**原地 patch** `yAxis[0].axisLabel`，避免整图重建
- `_resetZoom()` **同时**复位 X 窗口与 Y 锁定（双击）
- `clear()` 复位 `_yLocked` / `_yDecimals`
- `yFormatter(decimals)` 带 `_fmtCache` —— 避免每次渲染产生新的函数身份导致 ECharts 判脏

`web/skew_helpers.js` 93 → 169 行，新增三个纯函数并挂到 `global.SKEW`：

```javascript
function zoomRange(range, factor, anchor)   // factor<1 放大；>1 缩小
function effectiveRange(series, win, locked)
function axisDecimalsFor(range)             // 量程越窄小数位越多，封顶 6 位
```

`web/skew_option.js` 首屏 option 的**两条 Y 轴** `axisLabel.formatter` 统一走
`H.axisDecimalsFor(range)`。

### 2.3 三个真 Bug（都是实测数字暴露的，不是看代码看出来的）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `zoomRange([0, 0.01], 0.1, …)` 返回 **`[0, 0]`（零宽）** | `want` 比已很小的 span 还小，钳到 `minSpan` 时 `t=0` 把一侧压塌 | 放大时**先把基线 span 抬到 floor**：`if (factor < 1 && span < floor) span = floor` |
| 2 | `zoomRange([2.50, 2.53], 1/1.15, 99)` 返回 **`[98.975, 99.025]`**（视口被"拖"到指针处） | 锚点在量程外 ⇒ `t` 落到 `(0,1)` 之外，外推把整个窗口平移过去 | `t` 出界（含退化）⇒ **退到中心**：`a = (lo+hi)/2; t = 0.5` |
| 3 | **Top-N 各格边框宽度全等**（最要命的一个） | `borderWidthFor` 用**第 N 名成交量**做分母 ⇒ 选中集每格比值都 ≥ 1 ⇒ 全部钳到 `1.0` | `pickTopCells` 改返回**选中集**的 `hi`/`lo`，按 `(vol-lo)/(hi-lo)` 归一 |

Bug 3 的实测证据：`47/45=1.0444`、`46/45=1.0222`、`45/45=1.0` ⇒ 全部 ≈1。
修后：`成交量 [45, 46, 47] → 宽度 [9.37, 18.73, 28.10]`。

---

## 3. 新增常驻回归

`tools/check_heatmap_topn_skew_zoom.py`（**315 行**）+ `tools/topn_zoom_driver.py`（**179 行**）。

- 分组：`[T1]` Top-N 高亮 · `[Y1]` Y 自由缩放 · `[Y2]` 锁定 · `[Y3]` X 轴不受影响
- `EXPECTED_PREFIXES = ("[T1]", "[Y1]", "[Y2]", "[Y3]")`，经 `tools/group_guard.py` 校验
  **独立常量**（不从 `GROUPS` 自推 ⇒ 删组不会被静默吞掉）
- **5 条变异**（5 元组，带目标文件），每条都落回**它该落的**前缀
- 驱动代码独立成文件 —— 因为**一次性把检查器写到 469 行**，被 `run.py --check [1]`
  真判红（`>= MAX_LINES=400`）⇒ 按项目规则拆出驱动器。**这条正是本项目自己的规则**，
  是我自踩后修的。

`tools/skew_reference.py` 的 `WEB_SCRIPTS` 补入 `"heatmap.js"` —— 单一真相，
修 `TypeError: S.HeatmapPanel is not a constructor`（缺 heatmap.js 时驱动器直接崩）。

---

## 4. 验证（全部 `venv/Scripts/python.exe`）

| 命令 | 结果 |
|---|---|
| `run.py --check` | **`RC=0`**；`[1]` 99 Py + 13 JS 全合规，最长 `tools/check_session_grid.py = 399` |
| `tools/check_web_syntax.py` | **`RC=0`**（13 文件） |
| `tools/check_web_contract.py` | **`RC=0`**（JS id / 32 条 CFG 路径 / 59 条载荷路径） |
| `tools/check_heatmap_topn_skew_zoom.py --selftest` | **`RC=0`**，24 判据全通过 + 守卫 2 用例 + **5 变异全抓** |
| `tools/check_period_aggregation.py --selftest` | **`RC=0`**（前序会话已验） |

`--selftest` 关键实测值：
- `[T1] Top-N 内部描边宽度不等（成交量越大越粗）  成交量 [45, 46, 47] → 宽度 [9.37, 18.73, 28.1]`
- `[Y1] 缩放时锚点不动（指针所指 Y 值保持原位）  t: 0.500000 → 0.500000`
- `[Y1] 4000 组随机输入全部产出有效量程  异常 0 组`
- 变异落点：`边框分母退回第 N 名 → [T1]`（1 项）· `取消只描 N 格 → [T1]`（8 项）·
  `锚点出界不退中心 → [Y1]`（1 项）· `缩放下限失效 → [Y1]`（2 项）· `锁定被覆盖 → [Y2]`（1 项）

### 4.1 非空转自证（本会话内的实证）

- 前序会话对 `check_period_aggregation` 做过**故意做坏**：把锚点改成
  `pos = index[b];  // NOPE` ⇒ `[FAIL] 变异点已失效` + **`RC=1`**；还原 ⇒ `RC=0`。
- 本会话修变异 #3 时**证伪了自己的假设**：原以为把 `(0,1)` 改回 `[0,1]` 会破坏边界用例，
  数值分析显示**闭区间版本同样产出合法的 0.05 span**（只是贴边而非居中）⇒ 那条变异
  **本就抓不住**。已**换掉**变异，改成针对真正被判据断言的行为
  （`var t = (a - lo) / (hi - lo);` → `var t = 0.5;`）。**记录在案：这是我判断错了一次。**

---

## 5. 工作区清理

- 删除一次性探针 `tmp/probe_topn_yzoom.js`、`tmp/probe_topn_render.js`
  —— 常驻回归已覆盖同样判据，探针冗余（`tmp/` 本身在 `.gitignore`）。
- 复查 `console.log` / `debugger` / `TODO` / `FIXME` / `XXX` 于
  `web/*.js` + 两个新 tools 文件 ⇒ **0 命中**。
- `git status --porcelain` 只含**本轮有意改动**（见 §7 提交清单），无其它脏物。

---

## 6. 未验证 / 已知边界

- ⚠️ **未做浏览器取像素** ⇒ Top-N 黑边的**实际视觉宽度**、以及滚轮缩放的**手感**（步长
  `step=1.15`、`minSpan=0.05`、`maxSpan=500`）**待 KAI 盘中肉眼确认**。
- ⚠️ "缩放过程保持曲线渲染流畅"**未做帧率实测** —— 只保证了不整图重建
  （原地 patch `axisLabel` + `formatter` 身份缓存）。
- ⚠️ 系统服务为后台进程对，shell 结束后是否存活未验证（前序会话遗留状态）。

---

## 7. 提交

- 提交范围：`web/` 6 文件 + `tools/skew_reference.py` + `tools/check_heatmap_topn_skew_zoom.py`（新）
  + `tools/topn_zoom_driver.py`（新）+ 本会话 `notes/context/handoff.md` 与本文件。
- 见 `notes/context/handoff.md` 顶栏的实际 commit hash 与推送结果。
