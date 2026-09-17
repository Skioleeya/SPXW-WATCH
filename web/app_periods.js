/* 时间周期切换
 * ------------------------------------------------------------------
 * 从 app.js 拆分：单一职责 —— 周期按钮的生成与基线桶宽同步。
 * 依赖 global.SWATCH_APP.state（由 app.js 创建）。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var app = global.SWATCH_APP;
  var periodBar = document.getElementById("heatmap-periods");

  function currentPeriodLabel() {
    for (var i = 0; i < app.state.periods.length; i++) {
      if (app.state.periods[i].seconds === app.state.periodSeconds) {
        return app.state.periods[i].label;
      }
    }
    return "--";
  }

  function renderPeriodButtons() {
    if (!periodBar) { return; }
    periodBar.innerHTML = "";
    app.state.periods.forEach(function (p) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = p.label;
      btn.className = p.seconds === app.state.periodSeconds ? "on" : "";
      btn.addEventListener("click", function () { setPeriod(p.seconds); });
      periodBar.appendChild(btn);
    });
  }

  function setPeriod(seconds) {
    if (seconds === app.state.periodSeconds) { return; }
    app.state.periodSeconds = seconds;
    /* 周期切换后列数骤变，旧窗口必然越界 —— 复位热力图自己的横轴缩放。
       窗口归**面板**持有（`heatmap.js::_xWin`），所以复位要问面板，不是改共享状态。 */
    app.heatmapPanel.resetXZoom();
    /* Skew 的时间窗同样按**列下标**存，周期一换列的含义就全变了（1 列 = 30 秒
       还是 5 分钟）⇒ 必须跟着复位，否则窗口会落到一段完全无关的时间上。
       两个面板各管各的，这里只是**同一时刻各问一次**，不是联动。 */
    app.skewPanel.resetZoom();
    renderPeriodButtons();
    if (app.state.lastFrame) {
      global.renderSkew(app.state.lastFrame, global.renderHeatmap(app.state.lastFrame));
    }
  }

  function pickDefaultPeriod() {
    var wanted = CFG.heatmap.defaultPeriodSeconds;
    for (var i = 0; i < app.state.periods.length; i++) {
      if (app.state.periods[i].seconds === wanted) { return wanted; }
    }
    return app.state.periods.length ? app.state.periods[0].seconds : 0;
  }

  function syncPeriods(block) {
    var base = block ? Number(block.bucket_seconds) : 0;
    if (!(base > 0) || base === app.state.periodBase) { return; }

    app.state.periodBase = base;
    app.state.periods = global.SWATCH_PERIOD.options(base);

    var available = false;
    for (var i = 0; i < app.state.periods.length; i++) {
      if (app.state.periods[i].seconds === app.state.periodSeconds) { available = true; }
    }
    if (!available) { app.state.periodSeconds = pickDefaultPeriod(); }
    renderPeriodButtons();
  }

  function groupOf(seconds) {
    if (!(app.state.periodBase > 0) || !(seconds > 0)) { return 1; }
    var g = Math.round(seconds / app.state.periodBase);
    return g > 0 ? g : 1;
  }

  /* 导出到 global，供 app.js / app_render.js 调用 */
  global.syncPeriods = syncPeriods;
  global.setPeriod = setPeriod;
  global.currentPeriodLabel = currentPeriodLabel;
  global.groupOf = groupOf;
})(window);
