/* 热力图的指针反馈层（十字线 + 命中格描边）
 * ==================================================================
 * 职责单一：把「指针在图上的位置」翻译成**屏幕上的可见标记**。
 * 不读帧数据、不碰 option、不改任何视图状态。
 *
 * 为什么用 DOM 覆盖层，而不是 ECharts 的 emphasis / axisPointer
 * ------------------------------------------------------------
 * 实测（2026-09-17 真机 + 真实帧，探针 `tmp/_diag_heatmap_hover7.js` /
 * `_diag_heatmap_hover8.js`）：
 *   ① 悬停态**活不过一次重建**。鼠标停在格子上不动：格子的 `currentStates`
 *      与提示框在 +250ms 都还在，**+450ms 一起消失** —— 本面板每 400ms 用
 *      `setOption(option, true)` 重建整份 option，而 ECharts 的悬停是**内部
 *      连续态**，随组件重建一起丢掉。（与 `web/heatmap.js` 里"自带的拖拽平移
 *      活不过一帧"是同一类坑。）
 *   ② 原生 `axisPointer` 在这张图上**根本不画**。三种写法逐个试过：
 *      `tooltip(item).axisPointer=cross` / 根级 `axisPointer{show,triggerOn:'mousemove'}` /
 *      `tooltip(axis).axisPointer=cross`。把 display list 连 `ignore` 元素一起 dump
 *      出来做几何差分，**一条新增线都没有**（142 → 142 条）。
 *   ⇒ 需要**持续可见**的反馈不能交给 ECharts 内部状态。本层用 DOM 承载：
 *     与 400ms 重建完全无关，也不占 `setOption` 那 27ms（p50）的重绘预算。
 *
 * 几何从哪来
 * ----------
 * 命中格子的矩形取自 `zr.handler.findHover()` 返回的**真图元**包围盒 ——
 * 不自己推留白与 band 宽（手推一次就会差半格，而且轴一改就得跟着改）。
 * ⚠️ zrender 5.6 的 `findHover` 返回的是 `{target, topTarget}` **对象**，
 * 不是数组（第一版探针按数组用，`.length` 得 `undefined`，误报"找不到元素"）。
 * ================================================================== */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  /* 配置缺键即抛，不兜底：给个默认值会让"配置改名 / 漏写"表现成
     "十字线悄悄按旧值画"，图能动、只是不对，最难查的一类。 */
  function cfg() {
    var c = CFG.heatmap && CFG.heatmap.hover;
    if (!c) {
      throw new Error("SWATCH_CONFIG.heatmap.hover 缺失 —— 指针反馈无配置来源，拒绝静默兜底");
    }
    return c;
  }

  /* 指针下的**格子**矩形（图表局部坐标）；不是格子就返回 null。
     只认 rect：网格线是 line、色标是 group。尺寸上限是防"整块 series 矩形"
     被当成格子（格子在当前形状下只有几像素宽）。 */
  function cellAt(chart, x, y) {
    var hv = chart.getZr().handler.findHover(x, y, null);
    var el = hv && (hv.target || hv.topTarget);
    if (!el || el.type !== "rect") { return null; }
    var b = el.getBoundingRect();
    if (!(b.width > 1) || !(b.height > 1)) { return null; }
    if (b.width > 40 || b.height > 40) { return null; }
    return { x: b.x, y: b.y, width: b.width, height: b.height };
  }

  function HeatmapHover(container, chart) {
    this._el = container;
    this._chart = chart;
    this._h = null;
    this._v = null;
    this._box = null;
    this._at = null;
  }

  HeatmapHover.prototype.attach = function () {
    if (this._h) { return; }
    var mk = function (cls) {
      var d = document.createElement("div");
      d.className = "xhair " + cls;
      d.setAttribute("aria-hidden", "true");
      return d;
    };
    this._h = mk("h");
    this._v = mk("v");
    this._box = mk("box");
    this._box.style.borderWidth = Number(cfg().cellBorderPx) + "px";
    /* 顺序即层级：描边在两条线之上，否则线会盖住格子边框的一角。 */
    this._el.appendChild(this._h);
    this._el.appendChild(this._v);
    this._el.appendChild(this._box);

    /* 绑 zrender，不绑容器 —— zrender 在容器内另建 viewport root 并
       `stopPropagation()`，事件冒泡不到容器（实测：容器监听计数 0）。 */
    var self = this;
    var zr = this._chart.getZr();
    zr.on("mousemove", function (e) { self._move(e); });
    zr.on("globalout", function () { self.end(); });
  };

  /* 网格矩形。问 ECharts 自己，不推留白 —— 手推一次，轴一改就得跟着改。 */
  HeatmapHover.prototype.gridRect = function () {
    var model = this._chart.getModel && this._chart.getModel();
    var grid = model && model.getComponent("grid", 0);
    var cs = grid && grid.coordinateSystem;
    return (cs && cs.getRect()) || null;
  };

  HeatmapHover.prototype._move = function (e) {
    var x = Number(e.offsetX);
    var y = Number(e.offsetY);
    if (!isFinite(x) || !isFinite(y)) { return; }
    var grid = this.gridRect();
    var inside = grid && x >= grid.x && x <= grid.x + grid.width &&
      y >= grid.y && y <= grid.y + grid.height;
    if (!inside) { this.end(); return; }
    this._at = { x: x, y: y };
    this.probe(x, y, grid);
  };

  /*
   * 面板每次重建（最长 400ms 一次）之后调用：把提示框重新弹出来。
   *
   * 提示框是 ECharts 的**内部态**，`setOption(opt, true)` 会把它连同悬停态一起
   * 丢掉（实测：指针停住不动，+450ms 就没了）—— 这正是"得正好停上去才有数"的
   * 根因。按**像素位置**重新弹，不用上一帧的 dataIndex：横轴每帧往尾部追加列，
   * dataIndex 会指到别的格子上（症状：提示框内容与指针底下的格子对不上，越挂越偏）。
   */
  HeatmapHover.prototype.reapply = function () {
    if (!this._at) { return; }
    this._chart.dispatchAction({ type: "showTip", x: this._at.x, y: this._at.y });
  };

  HeatmapHover.prototype.end = function () {
    if (!this._at) { return; }
    this._at = null;
    this.hide();
    this._chart.dispatchAction({ type: "hideTip" });
  };

  /* 指针落在网格内时调用：算出命中格并画出来。返回命中格（无则 null）。 */
  HeatmapHover.prototype.probe = function (x, y, grid) {
    if (!grid || !(grid.width > 0) || !(grid.height > 0)) { this.hide(); return null; }
    var cell = cellAt(this._chart, x, y);
    this._show(x, y, grid, cell);
    return cell;
  };

  HeatmapHover.prototype._show = function (x, y, grid, cell) {
    if (cfg().enabled === false) { this.hide(); return; }
    var px = function (v) { return Math.round(v) + "px"; };
    var cx = Math.min(Math.max(x, grid.x), grid.x + grid.width);
    var cy = Math.min(Math.max(y, grid.y), grid.y + grid.height);

    /* 显隐一律走 `on` 类（与手势区高亮框同一套语义），内联样式只写几何 ——
       两处各用一套（一处 class、一处 style.display）迟早对不上。 */
    if (cfg().crosshair === false) {
      this._h.classList.remove("on");
      this._v.classList.remove("on");
    } else {
      this._h.classList.add("on");
      this._h.style.left = px(grid.x);
      this._h.style.width = px(grid.width);
      this._h.style.top = px(cy);
      this._v.classList.add("on");
      this._v.style.top = px(grid.y);
      this._v.style.height = px(grid.height);
      this._v.style.left = px(cx);
    }

    if (cell) {
      this._box.classList.add("on");
      this._box.style.left = px(cell.x);
      this._box.style.top = px(cell.y);
      this._box.style.width = px(cell.width);
      this._box.style.height = px(cell.height);
    } else {
      this._box.classList.remove("on");
    }
  };

  HeatmapHover.prototype.hide = function () {
    if (!this._h) { return; }
    this._h.classList.remove("on");
    this._v.classList.remove("on");
    this._box.classList.remove("on");
  };

  global.SWATCH_HEATMAP_HOVER = {
    create: function (container, chart) { return new HeatmapHover(container, chart); },
    cellAt: cellAt,
    cfg: cfg
  };
})(window);
