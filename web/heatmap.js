/* 日内 IV 冲量热力图 —— 面板生命周期
 * ------------------------------------------------------------------
 * 职责单一：持有面板状态（当前块 / 现价 / 可视行窗口）、校验进来的帧块、
 * 调用 option 构建器重画。**option 长什么样不在这里** ——
 * 在 web/heatmap_option.js（2026-09-17 拆出，原因见该文件头）。
 *
 * 渲染器为什么是 ECharts 而不是自写 WebGL
 * --------------------------------------
 * 2026-09-14：渲染器由原生 WebGL（gl_heatmap.js）换回 ECharts。
 * 自写 GL 引擎连续产出四个只有真打开页面才看得见的缺陷：行序镜像、格子边框
 * 丢失、调色板纹理被绑错单元（换任何色都不生效）、高 dpi 下网格阈值漂移。
 * ECharts 的坐标轴 / 色标 / 提示框都是被验证过的实现，且 Skew 面板本就在用
 * 同一个库 —— 换回来同时消掉"两套渲染栈"这件事。
 *
 * 代价（实测，必须记住）
 * ----------------------
 * headless Chrome 153 + SwiftShader，1400×520 画布、24 行、27% 填充：
 *   cols=630   ECharts 重绘 65.7ms   vs WebGL 0.6ms
 *   cols=1352  ECharts 重绘 159.9ms  vs WebGL 1.0ms
 *   cols=2370  ECharts 重绘 188.1ms  vs WebGL 1.3ms
 * 帧到达节拍由 web/ws_client.js 合并到 400ms（后端推送间隔）⇒ 宽档位下本面板
 * 会持续占用 40–47% 单核。这是**已知且被接受**的取舍，不是回归。
 * 另：`progressive` 在此形状下是负优化（2370 列 424ms），故恒为 0。
 * ⚠️ 「画 40 露 24」之后 series 里的矩形多了 16 行（约 +67%）。**已按新形状重测**
 * （2026-09-17 03:5x 真机，1680×1000 视口、纵轴 **40 行**、每帧 1554–1581 点、
 * 周期 1 分 ⇒ 446 桶；探针 `tmp/_probe_render_perf.js` 包 `setOption` 计时、40 帧）：
 *
 *   setOption  min 21.8ms | p50 27.4ms | p90 35.3ms | max 44.6ms | avg 28.2ms
 *
 * ⇒ 最大 44.6ms **远低于 400ms 推送间隔**，不会积压。数字比上面那组小得多，
 *   但**不是同一口径**：上面是 headless Chrome 153 + SwiftShader 且按列数分档、
 *   含 WebGL 对照；这次是 Playwright Chromium 真机视口、单一周期、只计时
 *   `setOption` 本身（不含浏览器合成/绘制）。**两组不可直接比较。**
 *
 * * 纵轴的两个半径（画多、看少）
 * ----------------------------
 * 帧里下发 ``2 × heatmap_draw_rows_each_side`` 行（当前 40），屏幕只显示
 * ``2 × heatmap_visible_rows_each_side`` 行（当前 24）。可视窗口的下标区间
 * 由 web/heatmap_window.js 算，可视半径**从帧里读**（``update()`` 的第三个
 * 参数）—— 为什么不让 block 自己带，见 update() 的注释。
 *
 * 横轴缩放（滚轮）—— 本图自己的交互，与 Skew 面板无关
 * ------------------------------------------------
 * 2026-09-17 KAI 裁定取消两个面板之间的滚轮联动。此前：在 Skew 上滚轮 →
 * Skew 缩放 → 经 ``app.state.viewport`` 驱动**本图的列裁剪**；本图自己
 * 没有任何滚轮交互。现在：联动整条删除，滚轮落在**本图**上 = 左右缩放时间轴，
 * Skew 面板照常自动滚动，两者互不影响。
 *
 * 窗口存成**列下标** ``{from, to}``（不是百分比）：横轴每帧往尾部追加新列，
 * 百分比窗口会随列数漂移。缩放的**执行**交给 ``dataZoom(inside)``（option 里
 * 那一项），本面板只做两件事：
 *   ① 用户缩完之后把窗口**抄下来**（``_captureX``）—— 本面板每帧
 *      ``notMerge`` 重建整份 option，不抄下来下一帧就被冲掉（症状是
 *      "滚轮缩了一下、400ms 后自己弹回全宽"）；
 *   ② 每帧把抄下来的窗口**贴回** option（``_render`` → ``build(..., xWin)``）。
 * 两者必须成对：只做 ② 窗口永远是全宽，只做 ① 缩放活不过一帧。
 *
 * 窗口右缘要不要跟着最新列走 = 自动滚动，策略全在 web/heatmap_roll.js。
 * ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  function clampCols(from, to, cols) {
    var max = cols - 1;
    if (to > max) { from -= to - max; to = max; }
    if (from < 0) { to -= from; from = 0; }
    if (to > max) { to = max; }
    if (from < 0) { from = 0; }
    return { from: from, to: to };
  }

  function leftHeld(e) {
    if (Number(e.which) === 1) { return true; }
    var n = e.event;
    if (!n) { return false; }
    if (e.type === "mousedown") { return Number(n.button) === 0; }
    return Number(n.buttons) === 1;
  }

  /* 面板                                                                */
  /* ------------------------------------------------------------------ */

  function HeatmapPanel(el) {
    this._el = el;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._window = null;
    this._block = null;
    this._spot = 0;
    /* 横轴缩放窗口 ``{from, to}``（列下标，含两端）；null = 全宽。
       全宽一律归一化成 null —— 这样"有没有缩放"只有一个状态，
       不用比较两个数。 */
    this._xWin = null;
    this._pan = null;
    this._panDirty = false;
    this._panAt = 0;
    this._panHinted = false;
    /* 横轴自动滚动（触发 / 方向 / 速度 / 何时松手全在 web/heatmap_roll.js）。 */
    this._roll = global.SWATCH_HEATMAP_ROLL.create(CFG.heatmap.xRoll);
    /* 指针反馈层（十字线 + 命中格描边 + 提示框存活）。位置状态归它自己 ——
       它才是"指针在哪"的唯一归属，本面板只管在每次重建后让它把提示框补回来。 */
    this._hoverLayer = null;
    this._onNoop = null;
    this._chart = global.echarts.init(el, null, { renderer: "canvas" });

    var self = this;
    /* 用户滚轮缩完之后 ECharts 会派发 datazoom —— 这里只是**抄结果**。
       ⚠️ `_render()` 自己 setOption 也会派发同一个事件，但那条路上抄回来的是
       刚贴进去的同一组值（幂等），所以不需要"正在渲染"的开关去挡它 ——
       少一个可能卡住的状态位。 */
    this._chart.on("datazoom", function () { self._captureX(); });
    this._chart.getZr().on("dblclick", function () { self.resetXZoom(); });

    var zr = this._chart.getZr();

    if (CFG.heatmap.hover.enabled !== false) {
      this._hoverLayer = global.SWATCH_HEATMAP_HOVER.create(this._el, this._chart);
      this._hoverLayer.attach();
    }

    if (CFG.heatmap.xZoom.panOnDrag === true) {
      zr.on("mousedown", function (e) { self._panStart(e); });
      zr.on("mousemove", function (e) { self._panMove(e); });
      zr.on("mouseup", function () { self._panEnd(); });
      zr.on("globalout", function () { self._panEnd(); });
    }
  }

  HeatmapPanel.prototype._render = function () {
    var block = this._block;
    if (!block || !this._window) { return; }
    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    this._chart.setOption(
      global.SWATCH_HEATMAP_OPTION.build(
        this, block, this._spot, vmax, this._window, this._xWin
      ),
      true
    );
    /* 提示框是 ECharts 的**内部态**，这次 notMerge 重建会把它连同悬停态一起丢掉
       （实测：指针停住不动，+450ms 就没了）—— 指针还在图上就补回来。 */
    if (this._hoverLayer) { this._hoverLayer.reapply(); }
  };

  /* 复位横轴缩放（双击 / 复位按钮 / 切周期 / 换时段）。窗口清掉后立刻重画，
     不依赖调用方"紧接着还会再渲染一次"。 */
  HeatmapPanel.prototype.resetXZoom = function () {
    this._xWin = null;
    this._pan = null;
    this._panDirty = false;
    this._roll.reengage();
    if (this._block && this._window) { this._render(); }
  };

  /* 把用户缩出来的横轴窗口从图表里抄回本面板。读不到就**保留原值**（不猜）。 */
  HeatmapPanel.prototype._captureX = function () {
    var n = this._cols;
    if (!(n > 1)) { this._xWin = null; return; }

    var opt = this._chart.getOption();
    var dz = (opt && opt.dataZoom && opt.dataZoom[0]) || null;
    if (!dz) { return; }
    var s = Number(dz.start);
    var e = Number(dz.end);
    if (!isFinite(s) || !isFinite(e) || !(e > s)) { return; }

    /* 百分比 ↔ 列下标，口径与 option 里写 start/end 的那一处**必须一致**。 */
    var a = Math.round(s / 100 * (n - 1));
    var b = Math.round(e / 100 * (n - 1));
    if (a < 0) { a = 0; }
    if (b > n - 1) { b = n - 1; }

    this._xWin = (a <= 0 && b >= n - 1) ? null : { from: a, to: b };
  };

  HeatmapPanel.prototype._gridRect = function () {
    var model = this._chart.getModel && this._chart.getModel();
    var grid = model && model.getComponent("grid", 0);
    var cs = grid && grid.coordinateSystem;
    return (cs && cs.getRect()) || null;
  };

  HeatmapPanel.prototype._panStart = function (e) {
    if (!leftHeld(e)) { return; }
    if (!(this._cols > 1)) { return; }
    var rect = this._gridRect();
    if (!rect || !(rect.width > 0)) { return; }
    var x = Number(e.offsetX);
    var y = Number(e.offsetY);
    if (!isFinite(x) || !isFinite(y)) { return; }
    var inGrid = typeof rect.contain === "function"
      ? rect.contain(x, y)
      : (x >= rect.x && x <= rect.x + rect.width &&
         y >= rect.y && y <= rect.y + rect.height);
    if (!inGrid) { return; }
    /* 全宽时也记下来：横向拖动在这是**空操作**（设计如此，见文件头），
       但必须能报出来 —— 静默无操作会被读成"图坏了"。
       `live` 在按下那一刻定死，整段拖动不再改判（与手势归属同一原则）。 */
    this._pan = {
      x: x,
      from: this._xWin ? this._xWin.from : 0,
      to: this._xWin ? this._xWin.to : 0,
      w: rect.width,
      live: !!this._xWin
    };
    this._panDirty = false;
    this._panHinted = false;
    /* 一按下就接管：拖动期间不许自动滚动插进来，否则两者会互相拉扯。 */
    this._roll.takeOver();
  };

  HeatmapPanel.prototype._panMove = function (e) {
    var p = this._pan;
    if (!p) { return; }
    if (!leftHeld(e)) { this._pan = null; return; }
    var x = Number(e.offsetX);
    if (!isFinite(x)) { return; }
    if (!p.live || !this._xWin) { this._panNoop(p, x); return; }

    var span = p.to - p.from + 1;
    var d = Math.round((p.x - x) * span / Math.max(p.w, 1));
    if (!d) { return; }
    var next = clampCols(p.from + d, p.to + d, this._cols);
    if (next.from === this._xWin.from && next.to === this._xWin.to) { return; }
    if (e.event && e.event.preventDefault) { e.event.preventDefault(); }

    this._xWin = next;
    this._panDirty = true;
    this._panRender(false);
  };

  /* 全宽时横向拖 = 空操作，但**不许静默**：超过 hintPx 就报一声，
     每段拖动只报一次（不然会刷屏）。 */
  HeatmapPanel.prototype._panNoop = function (p, x) {
    if (this._panHinted) { return; }
    if (Math.abs(x - p.x) < CFG.heatmap.xZoom.hintPx) { return; }
    this._panHinted = true;
    if (this._onNoop) { this._onNoop(); }
  };

  HeatmapPanel.prototype._panRender = function (force) {
    var wait = CFG.heatmap.xZoom.panThrottleMs;
    var now = (global.performance && global.performance.now)
      ? global.performance.now() : Date.now();
    if (!force && wait > 0 && (now - this._panAt) < wait) { return; }
    this._panAt = now;
    this._panDirty = false;
    this._render();
  };

  HeatmapPanel.prototype._panEnd = function () {
    if (!this._pan) { return; }
    this._pan = null;
    /* 结算跟随态：拖回右缘 ⇒ 恢复跟随；停在历史里 ⇒ 保持停滚（用户要看那段）。 */
    this._roll.settle(this._xWin, this._cols);
    if (this._panDirty) { this._panRender(true); }
  };

  HeatmapPanel.prototype.xZoom = function () {
    return this._xWin ? { from: this._xWin.from, to: this._xWin.to } : null;
  };

  HeatmapPanel.prototype.xRoll = function () {
    return this._roll.state(this._xWin, this._cols);
  };

  /* 「回到最新」：**保住缩放跨度**，只把右缘拉回最新列并恢复跟随。
     与 `resetXZoom()` 的分工：复位 = 丢掉缩放回到全宽；这个是回到最新但不变焦。
     用 `snap()` 而不是 `advance()` —— 用户指令不受 `xRoll.enabled` 管。 */
  HeatmapPanel.prototype.rollToLatest = function () {
    this._roll.reengage();
    this._xWin = this._roll.snap(this._xWin, this._cols);
    if (this._block && this._window) { this._render(); }
  };

  /* 空操作提示的回调（由 `app.js` 接到面板头的徽标上）。
     图表层不直接碰 DOM —— 与 Skew 的 `setNoopHook` 同一模式：
     状态在面板里，呈现归 UI 层。 */
  HeatmapPanel.prototype.setNoopHook = function (fn) {
    this._onNoop = fn || null;
  };

  HeatmapPanel.prototype.resize = function () {
    this._chart.resize();
    /* 网格线步长按画布像素算，尺寸变了要重画。 */
    this._render();
  };

  /*
   * 公共接口。``update(block, spot, visibleRowsEachSide)``
   *
   * 第三个参数为什么**显式传入**、而不是让 block 自己带
   * ------------------------------------------------------
   * 它是**可视半径**（来自帧的 ``heatmap.visible_rows_each_side``）。
   * 帧里的 block 在到达本面板之前要经过三次**逐字段重建**
   * （``period_align.js::sliceZones`` → ``period.js::aggregate`` →
   * ``period.js::clipTail``），每一处都只
   * 复制它认识的字段 —— 挂在 block 上的新字段会在第一跳就**静默消失**，
   * 症状是"窗口不生效，画满 40 行"，而且不报任何错。
   * 由调用方从**帧**上取一次再传进来，就没有"被哪一跳吃掉"这个问题。
   *
   * 返回值里同时给 ``rows``（帧里几行）与 ``visible``（屏幕显示几行）——
   * 顶栏读数要能看出这两者的差别，否则"窗口没生效"只能靠肉眼数格子。
   * 横轴同理：``xFrom`` / ``xTo`` 是**看得见的列**，``cols`` 是帧里的全部列。
   */
  HeatmapPanel.prototype.update = function (block, spot, visibleRowsEachSide) {
    if (!block || !block.values) { return false; }

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;
    if (!rows || !cols) { return false; }

    /* 可视半径来自帧。缺了 / 不是正整数 ⇒ 报错并**保留上一帧**，不猜一个值：
       兜一个"全画"会让"配置没接线"表现成一张看起来正常的图（静默错值）。 */
    var side = Math.floor(Number(visibleRowsEachSide));
    if (!(side > 0)) {
      if (global.console && console.error) {
        console.error("[heatmap] 帧里没有可用的 heatmap.visible_rows_each_side" +
          "（拿到 " + visibleRowsEachSide + "），保留上一帧 —— " +
          "拒绝猜一个可视窗口，猜错会让纵轴窗口落到错误的位置");
      }
      return false;
    }

    var window_ = global.SWATCH_HEATMAP_WINDOW.visibleRange(strikes, spot, side);
    if (!window_) {
      if (global.console && console.error) {
        console.error("[heatmap] 算不出可视行窗口（spot=" + spot +
          " 可视半径=" + side + " 行数=" + rows + "）—— 保留上一帧");
      }
      return false;
    }

    /* 横轴窗口：自动滚动 + 越界复位，两件事都在 roll 模块里，这里只落结果。 */
    this._xWin = this._roll.advance(this._xWin, cols);

    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    var cells = 0;
    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      for (var c = 0; c < cols; c++) {
        if (row[c] !== null && row[c] !== undefined) { cells++; }
      }
    }

    this._block = block;
    this._spot = spot || 0;
    this._window = window_;
    this._rows = rows;
    this._cols = cols;
    this._cells = cells;

    this._render();
    return {
      rows: rows,
      visible: window_.count,
      from: window_.from,
      to: window_.to,
      cols: cols,
      cells: cells,
      vmax: vmax,
      xZoom: !!this._xWin,
      xFrom: this._xWin ? this._xWin.from : 0,
      xTo: this._xWin ? this._xWin.to : cols - 1
    };
  };

  HeatmapPanel.prototype.clear = function () {
    this._block = null;
    this._spot = 0;
    this._window = null;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._xWin = null;
    this._pan = null;
    this._panDirty = false;
    this._roll.reengage();
    if (this._hoverLayer) { this._hoverLayer.end(); }
    this._chart.clear();
  };

  HeatmapPanel.prototype.stats = function () {
    return {
      rows: this._rows,
      cols: this._cols,
      visible: this._window ? this._window.count : 0
    };
  };

  global.HeatmapPanel = HeatmapPanel;
})(window);
