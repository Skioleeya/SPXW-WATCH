/* Skew 面板 —— 手势区的可见反馈（游标 + 区域高亮 + 空操作提示）
 * ==================================================================
 * 职责单一：把「指针在哪个手势区」翻译成**屏幕上的可见线索**。
 * **不改任何视图状态** —— 视图状态归 `web/skew_zoom.js`，本层只读它。
 *
 * 为什么必须有这一层
 * ------------------
 * 本面板有四个手势区（左 Y 轴区 / 网格 / 右 Y 轴区 / 底部 X 轴区），边界在图上
 * **完全不可见**，四个区的手势还各不相同。用户只能靠"读一遍提示文字 + 试错"
 * 才知道哪里能拖、拖了会怎样。游标是可发现性的第一道线索，此前却完全没用上
 * （`style.css` 里 `cursor` 只出现在两个按钮组）。
 *
 * 为什么是 DOM 覆盖层，不是画在画布上
 * ----------------------------------
 * 本面板每帧（最长 400ms 一次）重建整份 option，画在画布上的任何"临时标记"
 * 都活不过一次重建；而指针反馈必须与指针同步。DOM 层与重建完全无关。
 * 区域几何取自 `SKEW.regionsOf()` —— 与 `SKEW.regionOf()` 是**同一份矩形**，
 * 不另写一套边界（两份边界迟早对不上，症状是"高亮框和真能拖的地方差几像素"）。
 * ================================================================== */

(function (global) {
  "use strict";

  var H = global.SKEW;

  /* 区域 → 游标类名。两个 Y 轴区共用 `ns-resize`（都是"上下拖"），
     左右之分靠高亮框与徽标表达，不靠游标（游标表达的是**动作**，不是**对象**）。 */
  var CURSOR = { y0: "cur-y", y1: "cur-y", x: "cur-x", pan: "cur-pan" };

  function cfg() {
    var c = global.SWATCH_CONFIG.skew && global.SWATCH_CONFIG.skew.feedback;
    if (!c) {
      throw new Error("SWATCH_CONFIG.skew.feedback 缺失 —— 手势反馈无配置来源，拒绝静默兜底");
    }
    return c;
  }

  /* windowed：返回"当前有没有时间窗"的回调（空操作提示要用）。
     hint：空操作发生时的回调（由宿主接到徽标上）。 */
  function SkewRegions(container, chart, windowed) {
    this._el = container;
    this._chart = chart;
    this._windowed = windowed;
    this._hint = null;
    this._box = null;
    this._region = null;
    this._held = false;
    this._hinted = false;
    this._x0 = 0;
    this._bound = false;
  }

  SkewRegions.prototype.attach = function () {
    if (this._bound) { return; }
    var self = this;
    var zr = this._chart.getZr();

    this._box = document.createElement("div");
    this._box.className = "region-hint";
    this._box.setAttribute("aria-hidden", "true");
    this._el.appendChild(this._box);

    zr.on("mousemove", function (e) { self._move(e); });
    zr.on("mousedown", function (e) { self._press(e); });
    zr.on("mouseup", function () { self._release(); });
    zr.on("globalout", function () { self._leave(); });
    this._bound = true;
  };

  SkewRegions.prototype.hint = function (fn) {
    this._hint = fn || null;
  };

  SkewRegions.prototype._move = function (e) {
    if (cfg().enabled === false) { return; }
    var x = Number(e.offsetX);
    var y = Number(e.offsetY);
    if (!isFinite(x) || !isFinite(y)) { return; }
    var region = H.regionOf(this._chart, x, y);
    if (region !== this._region) {
      this._region = region;
      this._cursor();
      this._paintBox(region);
    }
    this._noop(region, x, e);
  };

  /* 游标：区域给动作语义；按下时网格区换成 grabbing（"正在拖"）。 */
  SkewRegions.prototype._cursor = function () {
    var cls = "chart" + (this._region ? " " + CURSOR[this._region] : "") +
      (this._held ? " dragging" : "");
    if (this._el.className !== cls) { this._el.className = cls; }
  };

  /* 区域高亮：把"能拖的地方"当场画出来。网格区只画虚线框不填色 ——
     它占满整个图，填色会压住曲线。 */
  SkewRegions.prototype._paintBox = function (region) {
    if (!region || cfg().regionHint === false) {
      this._box.className = "region-hint";
      return;
    }
    var rects = H.regionsOf(this._chart);
    var r = rects && rects[region];
    if (!r || !(r.width > 0) || !(r.height > 0)) {
      this._box.className = "region-hint";
      return;
    }
    this._box.style.left = Math.round(r.x) + "px";
    this._box.style.top = Math.round(r.y) + "px";
    this._box.style.width = Math.round(r.width) + "px";
    this._box.style.height = Math.round(r.height) + "px";
    this._box.className = "region-hint on " + region;
  };

  SkewRegions.prototype._press = function (e) {
    if (!H.leftHeld(e)) { return; }
    this._held = true;
    this._hinted = false;
    this._x0 = Number(e.offsetX);
    this._cursor();
  };

  SkewRegions.prototype._release = function () {
    if (!this._held) { return; }
    this._held = false;
    this._cursor();
  };

  SkewRegions.prototype._leave = function () {
    this._held = false;
    this._region = null;
    this._cursor();
    this._paintBox(null);
  };

  /*
   * 全宽时在网格内横向拖 = **空操作**（设计如此：凭空长窗会让横轴静默停止
   * 跟随最新列）。必须**响**一声 —— 静默无操作会被读成"图坏了"。
   * 只在"真的横向移动了 hintPx 像素"时才报，免得单击也弹提示。
   */
  SkewRegions.prototype._noop = function (region, x, e) {
    if (this._hinted || region !== "pan") { return; }
    if (!this._held || !H.leftHeld(e)) { return; }
    if (this._windowed()) { return; }
    var c = global.SWATCH_CONFIG.skew.pan;
    if (!(c && c.hintPx > 0)) {
      throw new Error("SWATCH_CONFIG.skew.pan.hintPx 非法 —— 空操作提示无阈值来源");
    }
    if (Math.abs(x - this._x0) < c.hintPx) { return; }
    this._hinted = true;
    if (this._hint) { this._hint(); }
  };

  global.SkewRegions = SkewRegions;
})(window);
