# Project State — heatmap-pan-drag（2026-09-17）

## 为什么不是"打开一个 ECharts 开关"

第一版实现就是一行配置：`dataZoom.inside.moveOnMouseMove = true`（ECharts 自带拖拽平移）。
**实测不成立**（`tmp/_diag_pan_drag.js`）：

```
drag A（左拖 8 段）: dz 事件 rel 122 / 237 / 344   ← 只有 3 段
                     第 1 次 setOption rel 338     ← 停点正落在这里
drag B（右拖 6 段）: dz 事件 rel 164               ← 只剩 1 段
                     第 1 次 setOption rel 176
```

`datazoom` 事件（= 平移真正生效的证据）在**每一次 setOption 之后就不再出现**，
而 zr 的 `mousemove` 计数一直在涨 ⇒ 事件到了、平移逻辑不跑了。

根因（读 vendor 源码确认）：ECharts 把"正在拖"这个状态存在它自己的
`RoamController._dragging` 里（`echarts.min.js` 内 `_mousedownHandler` 置位、
`_mouseupHandler` 清除、`_mousemoveHandler` 判它才平移）。本面板每 400ms 用
`setOption(option, true)`（`notMerge`）重建整份 option ⇒ 组件模型与它持有的
控制器一起重建 ⇒ `_dragging` 被清掉。**这是一个持续交互 vs 周期性重建的冲突，
不是配置写错。**

## 被否决的三条路

1. **拖拽期间跳过重建**（在 `_render()` 里判断"用户正在交互"就 return）。
   否决理由两条：① 拖拽期间热力图**冻住实时数据**（0DTE 盘口 400ms 一帧，
   拖两秒就是丢 5 帧）；② 要引入一个"正在交互"的状态位，而它靠 `mouseup` /
   `globalout` 清除 —— 一旦漏掉就是**整张图永久冻住**。本仓库一贯偏好
   "少一个可能卡住的状态位"（`heatmap.js` 里那句注释就是这个意思）。
2. **`requestAnimationFrame` 合并重绘**。否决：本形状下单次 `setOption`
   实测 p50 27.4ms / max 44.6ms，rAF 等于允许 60 次/秒 ⇒ 主线程被占满，
   连 Skew 面板和帧解析一起饿死。
3. **改用 `dispatchAction({type:"dataZoom"})` 让 ECharts 自己节流**。否决：
   它同样走 ECharts 内部的渲染调度，节流粒度不受我们控制，且会把窗口状态的
   写入点从"面板 `_xWin`"挪进"ECharts 模型" —— 本面板的窗口**只有一个出口**
   这条不变量（见下）会被破坏。

## 选定的形状：状态归面板，手势只是翻译层

- **唯一状态仍是 `_xWin`（列下标 `{from,to}`）**，拖拽与滚轮共用它。
  滚轮走 `dataZoom` 组件 → `datazoom` 事件 → `_captureX()` 抄回 `_xWin`；
  拖拽直接算 `_xWin` → `_render()` 贴回 option。两条路最后都落在同一个变量上，
  不存在"第二份窗口真相"。
- **绑定位置必须是 `chart.getZr()`**，不是容器 —— 这是 2026-09-17 上一会话已经
  用实测钉死的坑（zrender 在容器内另建 viewport root 并 `stopPropagation()`，
  挂容器上永远收不到事件）。`web/skew_zoom.js` 同样处理，两边一致。
- **只认左键**：`leftHeld()` 先看 zrender 事件的 `which === 1`，取不到再看原生
  `button`（mousedown）/ `buttons`（mousemove）。实测右键拖拽零位移。
  zrender 自己那套（`which === 2 || 3` 视为中/右键）只挡中右键，**不保证左键专属**，
  所以不能只靠它。
- **手指数换算 = "内容跟着指针走"**：`d = round((x0 - x) * span / gridW)`，
  `span` 是当前窗口列数、`gridW` 是网格像素宽。实测 300px ⇒ +66 列
  （`span 332 / gridW 1512` 代入即 65.9）—— 与 ECharts 自带平移的换算**同口径**，
  所以换实现不会让手感变一档。
- **重绘节流 `panThrottleMs: 100`，松手补一次**：状态每次 `mousemove` 都更新，
  只有**渲染**被节流，`mouseup` 时若有未落地的改动强制重绘一次 ⇒ 松手位置一定
  是最终位置（不会出现"看着停在半路"）。100ms 是照 ECharts 自带平移的节流粒度取的。

## 三个自己踩到的边界（都已在实现里堵住）

1. **拖拽途中窗口被复位 ⇒ 空指针**。`_panMove()` 要读 `this._xWin.from`，
   而 `update()` 在列数变化时会**主动把 `_xWin` 置 null**（越界复位并告警）、
   `resetXZoom()` / `clear()` 也会置 null。第一版没挡，会抛
   `Cannot read properties of null`。现加 `if (!this._xWin) { this._pan = null; return; }`，
   并由 `tmp/_probe_pan_reset.js` 守着（中途复位后继续移动鼠标：不报错、不平移、
   松手后拖拽态清空、再拖仍生效）。
2. **全宽时拖拽是空操作**。`_panStart` 直接 return（`_xWin === null`）。
   理由：窗口已是全部列，平移无处可去；让它"顺手缩出一个窗口"会让手势语义
   变得不可预测。实测全宽拖拽零位移。
3. **网格外不算拖拽**。用 `grid.coordinateSystem.getRect().contain(x, y)` 判，
   与 `skew_zoom.js::_inGrid` 同一套判据。实测左轴标签区（x=26）与右侧色标区
   （网格右 +20px）拖拽都零位移 —— 否则用户想选文本或摸色标就会把图推走。

## 与"禁止新增速查卡"的关系

本轮**没有新增任何速查卡**，也没有往 `notes/memory/QUICKREF.md` 加条目。
理由：这条不变量（"每 400ms `notMerge` 重建 ⇒ 依赖 ECharts 内部持续状态的交互
都会断"）**已经能机械判定**（探针跑得出相反判定），按四条出路属于
"① 能机械判定 ⇒ 写检查器"；但 KAI 2026-09-17 明令"不额外搭检查/校验模块"，
故它现在**没有守卫**，只落在本文件与会话 handoff 里 —— 这是欠账，
不是已固化。要转正需 KAI 批。
