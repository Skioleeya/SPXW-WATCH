# Project State — skew 双纵轴缩放

> 这里只放**为什么**：设计取舍、被否决的方案、踩到的坑。
> "做了什么 / 跑出什么"在 `handoff.md`；组件契约（技术栈 / 输入属性 / 输出形式）
> 在 `web/skew_zoom.js` 的文件头 —— 那才是它自己的家，这里只指路。

---

## 1. 触发方式：为什么是滚轮，不是拖拽 / 控件

| 候选 | 判断 |
|---|---|
| **滚轮（采用）** | KAI 2026-09-15 已裁定（原话要点："滚轮无限制上/下自由缩放""X 轴时间范围不变""缩放后锁定，双击复位"）。沿用既有语义，不引入第二套心智 |
| 左键在纵轴刻度条上上下拖拽 | 手感更好、更接近 TradingView，但要新占一个手势（拖拽已经归 dataZoom 平移 X），且 KAI 未提出。**未做** |
| 显式缩放控件（+ / − / 复位按钮） | 要动 `index.html` + `style.css` 加控件与状态回填，属 UI 改版。本次只在面板头加**一行文字**说明手势（`index.html` 的 `.hint`），不新增控件 |
| Ctrl / Shift + 滚轮 | 可绕开与 dataZoom 的争抢，但把功能藏进修饰键、可发现性最差。**未做** |

> 判定依据不是偏好，是**可发现性**：2026-09-15 那版功能做完后，界面上**没有任何文字**
> 提示纵轴能缩，而它实际又从未生效 —— 用户不可能发现。所以这次至少要把手势写出来。

## 2. 坑（实测，不是推测）

### 2.1 绑在图表容器上的 wheel 监听**永远收不到事件**

- zrender 在 `echarts.init(el)` 的容器**内部**另建一个 viewport root `<div>`，
  事件只到达它；zrender 自己的 wheel 处理会调 `stopPropagation()`
  （vendor 里即 `de = function(t){ t.preventDefault(); t.stopPropagation(); t.cancelBubble = true; }`）。
- 实测计数：`zr.on("mousewheel")` = **1**，容器 `#skew` = **0**，`document` = **0**。
- ⇒ 2026-09-15 那版 `this._el.addEventListener("wheel", …)` 是**从未执行过的死代码**。
  静态看每一行都对（`_inGrid` / `_anchoredValue` / `zoomRange` 都写对了），
  只有把真实滚轮事件打进去才看得见。
- **为什么旧回归没抓住**：旧 `tools/check_heatmap_topn_skew_zoom.py` 只调纯函数
  （`grep -rn "wheel" tools/*.py` → **0 命中**）。这是"判据全绿 ≠ 真的能用"的又一例，
  与 `open_tasks.md` 里 Top-3 亚像素那条同族。

### 2.2 `convertFromPixel` 的 finder：只有 `{gridIndex: 0}` 走通

实测（`tmp/_diag_xanchor.js`）：`convertFromPixel({xAxisIndex: 0}, …)` 与
`convertFromPixel({yAxisIndex: n}, …)` **都返回空数组**（下标取出来是 `undefined`，
所以第一版探针里那两个 key 直接没出现在 JSON 里），只有 `{gridIndex: 0}` 返回真值。

而 `{gridIndex: 0}` 只认**第一条** y 轴 —— 拿不到右轴的值。所以锚点改成
**自己按网格矩形线性换算**（`_anchors` / `_xAnchor`）。这不算绕过：
值轴到像素本就是线性映射，且实测显式 min/max 写进去后 ECharts **不做 nice 取整**
（缩后 extent 就是原样那两个数：`-0.2932695652173918 / 3.505269565217392`）。

### 2.3 同一格滚轮会**同时**缩 X 和缩 Y

`dataZoom.zoomOnMouseWheel: true` 时，实测一次滚轮下 dataZoom 与自定义处理器
**都会生效**（`[0,100] → [4.5738,95.4262]` 之外 Y 也动了）。zrender 的事件分发会
跑到**所有** zr 级监听，`cancelBubble` 只挡元素树上的传播，挡不住同一层的第二个监听。
⇒ 只能"一个手势一个主人"：把 `zoomOnMouseWheel` 关掉，X 分支由本模块自己算。

## 3. 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 保留 dataZoom 的滚轮 X 缩放，Y 另找一个手势（Ctrl+滚轮 / 拖拽） | 与 KAI 2026-09-15 的裁定冲突（他要的就是"滚轮缩纵轴、X 不变"）；且把功能藏进修饰键 |
| 网格内滚轮时**回滚** dataZoom 刚做的 X 变更 | 依赖"我的监听在 dataZoom 之后跑"这一注册顺序，且回滚本身会再触发 `datazoom` 事件；脆 |
| 两条轴各自独立锁定（滚左半区缩左轴、右半区缩右轴） | 与"双轴同步"直接矛盾；且同一屏幕高度在两条轴上会各自漂移，两条轴的对应关系失去意义 |
| 只锁被缩的那一条轴，另一条继续自动 | 被锁的那条不动、另一条随数据跑 ⇒ 下一帧两条轴的相对关系就断了。"同步"名存实亡。故：**任一条动了，两条一起进锁定态** |
| 每帧按数据重算量程（不用 ECharts 的 extent 当基准） | 锁定态下"屏上的量程"与"按数据算的"本就不同，拿后者当基准会让锁定后第一次滚轮跳一下 |
| 给右轴单独配一套 `minSpan/maxSpan` | 两条轴单位相同（都是波动率点）、自然量程相近（实测 4.37 vs 6.00），且缩放倍率相同 ⇒ 分两套只是多一份真相 |
| 在 `skew_helpers.js` 里留一份 `FALLBACK_YCFG` 默认配置 | **已删除**。它是配置的第二份真相：配置改名后会**静默**按旧值夹取。改为缺键即抛错（fail-fast），符合项目"禁止静默兜底" |
| 把新逻辑塞进 `web/skew.js` | 378 行 + 约 90 行 ⇒ 顶破 400 行门禁。按 `heatmap_window.js` 的既有范式拆出 `skew_zoom.js` |

## 4. 组件契约（只指路）

技术栈 / 输入属性 / 对外接口 / 输出形式 → **`web/skew_zoom.js` 文件头**。
分层（都只依赖 `global`，不反向引用）：

```text
skew_helpers.js  纯函数：量程、窗口、小数位、缩放的数学（可离线对拍）
skew_zoom.js     交互与锁定态的唯一出口（挂 zr 事件、算新量程、派发 dataZoom）
skew_option.js   首屏完整 option（两条轴的 min/max 由 yAxisPatch 给）
skew.js          编排：帧数据 → series → option → 图表
```

## 5. 残留风险

- **两条轴的下限会先后触底**：左轴自然量程小（约 4.4），先夹到 `minSpan`；
  此后继续放大只有右轴在动。这是共用一组限值的**固有**结果，不是缺陷，
  但会让"同步"在极端缩放下名不副实。若要严格同步，得改成"按比例缩放"而不是"按倍率"。
- **锚点按网格横向比例线性换算**，与 `_captureZoom` 的百分比口径一致；
  category 轴带 `boundaryGap` 时列心偏半格（483 列时约 0.1% 窗宽）。刻意不"修正"到半格，
  否则会与 `_captureZoom` 的口径打架。
- 探针留在 `tmp/`，**无回归保护**（按 KAI 明令不新增 `tools/` 检查器）。
  代价：日后改 `skew_zoom.js` 不会被自动跑到。若要纳入 `tools/`，需先申请。
