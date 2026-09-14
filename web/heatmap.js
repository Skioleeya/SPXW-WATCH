/* 日内 IV 冲量热力图（ECharts 版）
 * ------------------------------------------------------------------
 * 2026-09-14：渲染器由原生 WebGL（gl_heatmap.js）换回 ECharts。
 *
 * 为什么换回来
 * ------------
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
 *
 * 网格线
 * ------
 * 参考项目（live-volatility-surface）用 Plotly 的 `xgap=1 / ygap=1` 做格子间隙，
 * ECharts 的 heatmap 没有等价项。这里改用轴的 splitLine 按步长抽样：
 *   stride = ceil(cellBorderMinPx / cellPx)，每 stride 个分类画一条 1px 线。
 * `cellBorderMix` 映射为线的 opacity —— `opacity m` 的线叠在数据色上
 * ≡ 旧 shader 的 `mix(color, border, m)`，两者数学等价。
 * 用 splitLine 而不是逐格 `itemStyle.borderWidth` 的原因：后者在 2370 列时
 * 等于给 5.7 万个矩形各描一次边，既是性能灾难、又会把细档位糊成一片。
 * ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  /* 边距与旧 WebGL 版一致，轴标签与色标的位置不变。 */
  var PAD = { left: 66, right: 84, top: 10, bottom: 28 };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m];
    });
  }

  /* 轴标签抽稀：返回值直接喂给 ECharts 的 axisLabel.interval（0 = 全画）。 */
  function xInterval(cols) {
    var want = CFG.heatmap.xLabelCount;
    if (cols <= want) { return 0; }
    return Math.max(Math.floor(cols / want) - 1, 0);
  }

  function yInterval(rows) {
    var want = CFG.heatmap.maxYLabels;
    if (rows <= want) { return 0; }
    return Math.max(Math.floor(rows / want) - 1, 0);
  }

  function nearestIndex(values, target) {
    var best = -1, bestDist = Infinity;
    for (var i = 0; i < values.length; i++) {
      var d = Math.abs(values[i] - target);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  }

  /* 网格线抽样步长。列/行宽于 cellBorderMinPx 时 stride=1（每格一条）。 */
  function strideFor(spanPx, count) {
    var cellPx = spanPx / Math.max(count, 1);
    var minPx = CFG.heatmap.cellBorderMinPx;
    if (!(minPx > 0) || !(cellPx > 0)) { return 1; }
    return Math.max(1, Math.ceil(minPx / cellPx));
  }

  /* ------------------------------------------------------------------ */
  /* Option 构建                                                         */
  /* ------------------------------------------------------------------ */

  function buildOption(panel, block, spot, vmax) {
    var strikes = block.strikes || [];
    var rights = block.rights || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;

    var data = [];
    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      for (var c = 0; c < cols; c++) {
        var v = row[c];
        if (v !== null && v !== undefined) { data.push([c, r, v]); }
      }
    }

    var rect = panel._el.getBoundingClientRect();
    var gridW = Math.max(1, rect.width - PAD.left - PAD.right);
    var gridH = Math.max(1, rect.height - PAD.top - PAD.bottom);
    var strideX = strideFor(gridW, cols);
    var strideY = strideFor(gridH, rows);
    var mix = CFG.heatmap.cellBorderMix > 0 ? CFG.heatmap.cellBorderMix : 0;
    var line = { color: CFG.theme.grid, width: 1, opacity: mix };

    var yNames = [];
    for (var i = 0; i < rows; i++) { yNames.push(strikes[i] + (rights[i] || "")); }

    var bound = vmax > 0 ? vmax : CFG.heatmap.boundEpsilon;
    var markLine;
    if (CFG.heatmap.showSpotLine && spot > 0) {
      var idx = nearestIndex(strikes, spot);
      if (idx >= 0) {
        markLine = {
          silent: true, symbol: "none", animation: false,
          label: { show: false },
          lineStyle: { color: CFG.theme.accent, type: "dashed", width: 1 },
          data: [{ yAxis: idx }]
        };
      }
    }

    return {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: PAD.left, right: PAD.right, top: PAD.top, bottom: PAD.bottom },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(17,21,26,.96)",
        borderColor: CFG.theme.border,
        textStyle: { color: CFG.theme.text, fontSize: 11 },
        formatter: function (p) {
          var c = p.value[0], r = p.value[1], v = p.value[2];
          var sign = v > 0 ? "+" : "";
          return escapeHtml(labels[c]) + " · " + escapeHtml(strikes[r]) +
            escapeHtml(rights[r] || "?") + "<br/>ΔIV <b>" + sign +
            Number(v).toFixed(CFG.decimals.impulse) + "</b> 波动率点";
        }
      },
      /* 色标：连续 visualMap，量程 [-vmax, +vmax] 与后端下发一致。
         15 色 = config.heatmap.palette（逐色抄自参考项目的 Plotly Turbo）。 */
      visualMap: {
        type: "continuous",
        show: true,
        min: -bound, max: bound,
        calculable: false,
        orient: "vertical",
        right: 14, top: "center",
        itemWidth: 11, itemHeight: 150,
        precision: 2,
        text: ["IV 上行 +" + bound.toFixed(2), "IV 下行 -" + bound.toFixed(2)],
        textStyle: { color: CFG.theme.textDim, fontSize: 9.5 },
        inRange: { color: CFG.heatmap.palette }
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: true,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        splitLine: { show: mix > 0, interval: strideX - 1, lineStyle: line },
        axisLabel: {
          color: CFG.theme.textFaint,
          fontSize: 10,
          interval: xInterval(cols),
          hideOverlap: true
        }
      },
      yAxis: {
        type: "category",
        data: yNames,
        boundaryGap: true,
        /* 索引 0 = 最高行权价，必须落在屏幕最上方（帧行序即降序行权价）。 */
        inverse: true,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        splitLine: { show: mix > 0, interval: strideY - 1, lineStyle: line },
        axisLabel: {
          color: CFG.theme.textDim,
          fontSize: 10,
          interval: yInterval(rows),
          hideOverlap: true
        }
      },
      series: [{
        type: "heatmap",
        data: data,
        /* 此形状下 progressive 更慢（见文件头实测），恒关。 */
        progressive: 0,
        animation: false,
        itemStyle: { borderWidth: 0 },
        markLine: markLine
      }]
    };
  }

  /* ------------------------------------------------------------------ */
  /* 面板                                                                */
  /* ------------------------------------------------------------------ */

  function HeatmapPanel(el) {
    this._el = el;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._block = null;
    this._spot = 0;
    this._chart = global.echarts.init(el, null, { renderer: "canvas" });
  }

  HeatmapPanel.prototype._render = function () {
    var block = this._block;
    if (!block) { return; }
    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    this._chart.setOption(buildOption(this, block, this._spot, vmax), true);
  };

  HeatmapPanel.prototype.resize = function () {
    this._chart.resize();
    /* 网格线步长按画布像素算，尺寸变了要重画。 */
    this._render();
  };

  /* 公共接口与旧 WebGL 版完全一致，app.js / app_render.js 无需改动。 */
  HeatmapPanel.prototype.update = function (block, spot) {
    if (!block || !block.values) { return false; }

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;
    if (!rows || !cols) { return false; }

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
    this._rows = rows;
    this._cols = cols;
    this._cells = cells;

    this._render();
    return { rows: rows, cols: cols, cells: cells, vmax: vmax };
  };

  HeatmapPanel.prototype.clear = function () {
    this._block = null;
    this._spot = 0;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._chart.clear();
  };

  HeatmapPanel.prototype.stats = function () {
    return { rows: this._rows, cols: this._cols };
  };

  global.HeatmapPanel = HeatmapPanel;
})(window);
