/* 25Δ Skew 实时曲线
 * ------------------------------------------------------------------
 * 主序列：25Δ Skew（Put25 − Call25），按正负分段着色。
 * 辅序列：ATM IV / 25Δ Put IV / 25Δ Call IV（右侧纵轴）。
 *
 * 横轴由 app.js 对齐到热力图列网格；本面板不做时间轴换算。
 * 纯函数已拆分到 skew_helpers.js，首次渲染 option 构建拆分到 skew_option.js。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var H = global.SKEW;

  function SkewPanel(el) {
    this._el = el;
    this._chart = echarts.init(el, null, { renderer: "canvas" });
    this._count = 0;
    this._zoom = null;
    this._labelInterval = null;
    this._series = null;
    this._initialized = false;
    this._viewportHook = null;
    this._viewportChangeHook = null;

    var self = this;
    this._chart.on("datazoom", function () { self._captureZoom(); });
    this._chart.getZr().on("dblclick", function () { self._resetZoom(); });

    global.addEventListener("resize", function () { self._chart.resize(); });
  }

  SkewPanel.prototype.resize = function () {
    this._chart.resize();
  };

  SkewPanel.prototype.clear = function () {
    this._chart.clear();
    this._count = 0;
    this._zoom = null;
    this._labelInterval = null;
    this._series = null;
    this._initialized = false;
  };

  SkewPanel.prototype._visibleSpan = function (n) {
    var win = H.windowOf(this._zoom, n);
    return win ? (win.to - win.from + 1) : n;
  };

  SkewPanel.prototype.setViewport = function (zoom) {
    this._zoom = zoom || null;
    if (this._viewportChangeHook) { this._viewportChangeHook(zoom); }
    this._applyViewport();
  };

  SkewPanel.prototype._captureZoom = function () {
    var n = this._count;
    if (!(n > 1)) { this.setViewport(null); return; }

    var opt = this._chart.getOption();
    var dz = (opt && opt.dataZoom && opt.dataZoom[0]) || {};
    var start = Number(dz.start);
    var end = Number(dz.end);
    if (!isFinite(start) || !isFinite(end)) { return; }

    var a = Math.round(start / 100 * (n - 1));
    var b = Math.round(end / 100 * (n - 1));
    if (a < 0) { a = 0; }
    if (b > n - 1) { b = n - 1; }

    if (a <= 0 && b >= n - 1) { this.setViewport(null); } else {
      this.setViewport({ start: a, end: b, tail: b >= n - 1 });
    }
  };

  SkewPanel.prototype._applyViewport = function () {
    if (!this._series) { return; }

    var win = H.windowOf(this._zoom, this._count);
    var range = H.axisRange(this._series, win);
    var patch = { yAxis: [{ min: range[0], max: range[1] }, {}] };

    var interval = H.labelInterval(this._visibleSpan(this._count));
    if (interval !== this._labelInterval) {
      this._labelInterval = interval;
      patch.xAxis = { axisLabel: { interval: interval } };
    }
    this._chart.setOption(patch);
    if (this._viewportHook) { this._viewportHook(this._readout()); }
  };

  SkewPanel.prototype._resetZoom = function () {
    if (!this._zoom) { return; }
    this._chart.setOption({ dataZoom: [{ start: 0, end: 100 }] });
    this.setViewport(null);
  };

  SkewPanel.prototype.update = function (series) {
    if (!series) { return false; }
    var labels = series.label || [];
    var count = labels.length;
    if (!count) { return false; }

    var skew = series.skew || [];
    var atm = series.atm || [];
    var put25 = series.put25 || [];
    var call25 = series.call25 || [];

    var win = H.windowOf(this._zoom, count);
    if (this._zoom && !win) { this._zoom = null; }
    var span = win ? (win.to - win.from + 1) : count;

    var range = H.axisRange(series, win);
    var sign = H.splitBySign(skew);
    this._series = series;

    /* 图例色陷阱：ECharts 的 legend 图标读 `series.itemStyle.color`，
       不读 `lineStyle.color`；两者都没设时才退到按 series 索引的默认调色板。
       ⇒ 每条的 `itemStyle.color` 必须与 `lineStyle.color` 同值 —— **两处必须一起改**，
       `itemStyle` 不是冗余（`showSymbol:false` 时它不参与画线，只喂图例）。 */
    var graphs = [
      {
        name: H.NAME_POS,
        type: "line",
        yAxisIndex: 0,
        data: sign.positive,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2.2, color: CFG.theme.hot },
        itemStyle: { color: CFG.theme.hot },
        connectNulls: false,
        z: 5
      },
      {
        name: H.NAME_NEG,
        type: "line",
        yAxisIndex: 0,
        data: sign.negative,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2.2, color: CFG.theme.cool },
        itemStyle: { color: CFG.theme.cool },
        connectNulls: false,
        z: 5
      }
    ];

    /* 三条 IV 曲线走 `CFG.skew.colors`，**不要退回 `CFG.theme.hot/cool`** ——
       那两个是主序列的分段色，复用会让图上出现两红两蓝、图例再同名，彻底分不清。
       颜色清单与理由见 config.js 的 skew.colors。 */
    if (CFG.skew.showAtm) {
      graphs.push({
        name: "ATM IV", type: "line", yAxisIndex: 1, data: atm,
        showSymbol: false, smooth: false,
        lineStyle: { width: 1.1, type: "dotted", color: CFG.skew.colors.atm },
        itemStyle: { color: CFG.skew.colors.atm },
        connectNulls: true, z: 2
      });
    }
    if (CFG.skew.showPut25) {
      graphs.push({
        name: "25Δ Put IV", type: "line", yAxisIndex: 1, data: put25,
        showSymbol: false, smooth: false,
        lineStyle: { width: 1.1, type: "dashed", color: CFG.skew.colors.put25, opacity: .75 },
        itemStyle: { color: CFG.skew.colors.put25 },
        connectNulls: true, z: 3
      });
    }
    if (CFG.skew.showCall25) {
      graphs.push({
        name: "25Δ Call IV", type: "line", yAxisIndex: 1, data: call25,
        showSymbol: false, smooth: false,
        lineStyle: { width: 1.1, type: "dashed", color: CFG.skew.colors.call25, opacity: .75 },
        itemStyle: { color: CFG.skew.colors.call25 },
        connectNulls: true, z: 3
      });
    }

    if (CFG.skew.zeroLine) {
      graphs[0].markLine = {
        silent: true,
        symbol: "none",
        data: [{
          yAxis: 0,
          lineStyle: { color: CFG.theme.border, type: "dashed", width: 1 },
          label: { show: false }
        }]
      };
    }

    if (!this._initialized) {
      var fullOption = global.buildSkewFullOption(graphs, labels, win, span, range);
      this._chart.setOption(fullOption, { notMerge: true });
      this._initialized = true;
    } else {
      var delta = {
        xAxis: { data: labels },
        yAxis: [{ min: range[0], max: range[1] }, {}],
        dataZoom: [{
          start: win ? win.start : 0,
          end: win ? win.end : 100
        }],
        series: graphs
      };
      var interval = H.labelInterval(span);
      if (interval !== this._labelInterval) {
        delta.xAxis.axisLabel = { interval: interval };
      }
      this._chart.setOption(delta);
    }

    this._count = count;
    this._labelInterval = H.labelInterval(span);
    return this._readout();
  };

  SkewPanel.prototype._readout = function () {
    var series = this._series;
    if (!series) { return null; }
    var values = series.skew || [];
    var n = values.length;
    var win = H.windowOf(this._zoom, n);
    var from = win ? win.from : 0;
    var to = win ? win.to : n - 1;

    var filled = 0;
    for (var i = from; i <= to; i++) {
      var v = values[i];
      if (v !== null && v !== undefined) { filled += 1; }
    }

    return {
      points: filled,
      cols: to - from + 1,
      range: H.axisRange(series, win),
      view: win ? { from: win.from + 1, to: win.to + 1, cols: n } : null
    };
  };

  SkewPanel.prototype.setViewportHook = function (fn) {
    this._viewportHook = fn || null;
  };

  SkewPanel.prototype.setViewportChangeHook = function (fn) {
    this._viewportChangeHook = fn || null;
  };

  global.SkewPanel = SkewPanel;
})(window);
