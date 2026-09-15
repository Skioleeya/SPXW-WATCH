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

  /* 纵轴刻度格式化。小数位随量程变（`H.axisDecimalsFor`），
     所以 formatter 必须按位缓存 —— 每次都造新函数会让 ECharts 认为
     option 变了、触发无谓重绘。 */
  var _fmtCache = {};
  function yFormatter(decimals) {
    var key = String(decimals);
    if (!_fmtCache[key]) {
      _fmtCache[key] = function (v) { return Number(v).toFixed(decimals); };
    }
    return _fmtCache[key];
  }

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
    /* Y 轴锁定量程（滚轮缩放用）。null = 走自动量程。 */
    this._yLocked = null;
    this._yDecimals = null;

    var self = this;
    this._chart.on("datazoom", function () { self._captureZoom(); });
    this._chart.getZr().on("dblclick", function () { self._resetZoom(); });
    this._bindWheel();

    global.addEventListener("resize", function () { self._chart.resize(); });
  }

  /* ------------------------------------------------------------------ */
  /* Y 轴滚轮自由缩放                                                    */
  /* ------------------------------------------------------------------ */

  /*
   * 只认"落在网格矩形内、且不带 X 轴意图"的滚轮。
   *
   * **为什么拦住 X**：ECharts 的 `dataZoom{type:"inside"}` 自己监听同一元素的
   * wheel 事件来做 X 轴缩放。若不拦截，一次滚轮会同时缩 X 和 Y —— 而需求明确
   * 要求 X 轴时间范围在缩放过程中不变。
   *
   * 分工（配置见 config.js::skew.yZoom）：
   *   - 指针在网格内 → 只缩 Y，X 完全不动
   *   - 指针在网格外（轴标签 / 图例区）→ 放行给 dataZoom，仍按原样缩 X
   */
  SkewPanel.prototype._bindWheel = function () {
    var self = this;
    this._el.addEventListener("wheel", function (ev) {
      var cfg = CFG.skew.yZoom;
      if (!cfg || cfg.enabled === false) { return; }
      if (!self._series) { return; }

      var factor = ev.deltaY > 0 ? cfg.step : (1 / cfg.step);
      var anchor = self._anchoredValue(ev);
      if (!self._inGrid(ev)) { return; }   /* 网格外：交给 dataZoom 缩 X */

      var base = self._yRange();
      var next = H.zoomRange(base, factor, anchor);
      /* 与当前量程实质相同（已顶到 minSpan / maxSpan）⇒ 不再吞事件，
         免得滚轮在边界上"卡住"整个页面。 */
      if (!(Math.abs(next[1] - next[0] - (base[1] - base[0])) > 1e-12) &&
          !(Math.abs(next[0] - base[0]) > 1e-12)) {
        return;
      }
      self._yLocked = next;
      ev.preventDefault();
      self._applyViewport();
    }, { passive: false });
  };

  /* 指针是否落在绘图网格矩形内（用 ECharts 自己的几何，不自己算 PAD）。 */
  SkewPanel.prototype._inGrid = function (ev) {
    var rect = this._el.getBoundingClientRect();
    var x = ev.clientX - rect.left;
    var y = ev.clientY - rect.top;
    var model = this._chart.getModel && this._chart.getModel();
    var grid = model && model.getComponent("grid", 0);
    if (!grid) { return true; }
    var gr = grid.coordinateSystem.getRect();
    return x >= gr.x && x <= gr.x + gr.width &&
           y >= gr.y && y <= gr.y + gr.height;
  };

  /* 指针处对应的 Y 值 —— 缩放锚点。取不到就返回 null（由 zoomRange 锚中心）。 */
  SkewPanel.prototype._anchoredValue = function (ev) {
    var cfg = CFG.skew.yZoom;
    if (!cfg || cfg.anchorAtPointer === false) { return null; }
    try {
      var rect = this._el.getBoundingClientRect();
      return this._chart.convertFromPixel(
        { yAxisIndex: 0 }, [ev.clientX - rect.left, ev.clientY - rect.top]
      )[1];
    } catch (e) {
      return null;   /* 图尚未出，或坐标轴未就绪 —— 退回锚中心 */
    }
  };

  /* 这一帧的基准量程：已锁定则用锁定值，否则用自动量程。 */
  SkewPanel.prototype._yRange = function () {
    var series = this._series || {};
    var n = this._count;
    var win = H.windowOf(this._zoom, n);
    return H.effectiveRange(series, win, this._yLocked);
  };

  /* 复位到自动量程（双击 / 切周期 / 数据重置时调用）。 */
  SkewPanel.prototype.resetY = function () {
    if (!this._yLocked) { return; }
    this._yLocked = null;
    this._applyViewport();
  };

  SkewPanel.prototype.yLocked = function () {
    return this._yLocked ? [this._yLocked[0], this._yLocked[1]] : null;
  };

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
    /* 数据被清空（切周期 / 换时段）⇒ 锁定的量程失去参照，一并复位。 */
    this._yLocked = null;
    this._yDecimals = null;
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
    var range = H.effectiveRange(this._series, win, this._yLocked);
    var patch = { yAxis: [{ min: range[0], max: range[1] }, {}] };

    var interval = H.labelInterval(this._visibleSpan(this._count));
    if (interval !== this._labelInterval) {
      this._labelInterval = interval;
      patch.xAxis = { axisLabel: { interval: interval } };
    }

    /* 放大到很窄时必须给刻度加小数位，否则一屏标签全变成同一个数
       （量程 0.05 波动率点、1 位小数 ⇒ 全是 "0.1"）。 */
    var decimals = H.axisDecimalsFor(range);
    if (decimals !== this._yDecimals) {
      this._yDecimals = decimals;
      patch.yAxis[0].axisLabel = { formatter: yFormatter(decimals) };
    }

    this._chart.setOption(patch);
    if (this._viewportHook) { this._viewportHook(this._readout()); }
  };

  SkewPanel.prototype._resetZoom = function () {
    /* 双击 = 一次性复位**两种**缩放：X 轴窗口与 Y 轴量程。
       用户的心智是"双击回默认视图"，只复位一半会让人以为程序卡住。 */
    if (this._zoom) {
      this._chart.setOption({ dataZoom: [{ start: 0, end: 100 }] });
      this.setViewport(null);
    }
    this.resetY();
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

    /* 已锁定 Y 量程时用锁定值（新数据不覆盖它），否则用自动量程。 */
    var range = H.effectiveRange(series, win, this._yLocked);
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
      this._yDecimals = null;   /* 整份 option 重建，缓存作废 */
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
      /* 纵轴刻度位随量程变 —— 与 _applyViewport 同一规则，两处都要发，
         否则滚轮缩放后第一帧的标签会用旧位数。 */
      var decimals = H.axisDecimalsFor(range);
      if (decimals !== this._yDecimals) {
        this._yDecimals = decimals;
        delta.yAxis[0].axisLabel = { formatter: yFormatter(decimals) };
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
