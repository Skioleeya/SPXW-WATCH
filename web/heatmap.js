/* 日内 IV 冲量热力图
 * ------------------------------------------------------------------
 * 纵轴 = 行权价（升序，下方为低行权价）
 * 横轴 = 会话时间桶
 * 颜色 = ΔIV（波动率点），暖色上行 / 冷色下行
 *
 * 性能取舍
 * --------
 * 满场是 36 行 × 390 列 ≈ 1.4 万个网格。ECharts 的 heatmap 在 canvas 上渲染
 * 这个量级没有问题，但每次 setOption 都要重建坐标系，所以：
 *   * animation 全程关闭（动画在盯盘场景只会制造"数据在动"的错觉）；
 *   * progressive 打开，把大数组分片绘制，避免长帧卡住 UI 线程；
 *   * 空值（null）直接不入数据，而不是填 0 —— 0 表示"IV 没变"，
 *     空表示"还没到那个时间"，两者语义完全不同，混掉会让整张图撒谎。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  function HeatmapPanel(el) {
    this._el = el;
    this._chart = echarts.init(el, null, { renderer: "canvas" });
    this._option = null;
    this._lastRows = 0;
    this._lastCols = 0;

    var self = this;
    global.addEventListener("resize", function () { self.resize(); });
  }

  HeatmapPanel.prototype.resize = function () {
    this._chart.resize();
  };

  HeatmapPanel.prototype.clear = function () {
    this._chart.clear();
    this._option = null;
    this._lastRows = 0;
    this._lastCols = 0;
  };

  /* 由列数决定横轴显示多少个时间标签 */
  function xInterval(cols) {
    var want = CFG.heatmap.xLabelCount;
    if (cols <= want) { return 0; }
    return Math.max(Math.floor(cols / want) - 1, 0);
  }

  /* 由行数决定纵轴显示多少个行权价标签 */
  function yInterval(rows) {
    var want = CFG.heatmap.maxYLabels;
    if (rows <= want) { return 0; }
    return Math.max(Math.floor(rows / want) - 1, 0);
  }

  function nearestIndex(values, target) {
    var best = -1;
    var bestDist = Infinity;
    for (var i = 0; i < values.length; i++) {
      var d = Math.abs(values[i] - target);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  }

  HeatmapPanel.prototype.update = function (block, spot) {
    /* 后端在没有矩阵时会给 null；此时保留上一帧画面，避免闪白 */
    if (!block || !block.values) { return false; }

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rights = block.rights || [];
    var rows = strikes.length;
    var cols = labels.length;

    if (!rows || !cols) { return false; }

    /* 量程信后端：vmax 已按配置的分位截断与下限保护算好 */
    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    var data = [];
    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      for (var c = 0; c < cols; c++) {
        var v = row[c];
        if (v === null || v === undefined) { continue; }
        data.push([c, r, v]);
      }
    }

    var yLabels = strikes.map(function (s) { return String(s); });
    var xLabels = labels.slice();

    var spotLine = [];
    if (CFG.heatmap.showSpotLine && spot > 0) {
      var idx = nearestIndex(strikes, spot);
      if (idx >= 0) {
        spotLine = [{
          yAxis: idx,
          lineStyle: { color: CFG.theme.accent, width: 1.4, type: "dashed" },
          label: {
            formatter: "现价 " + spot.toFixed(CFG.decimals.spot),
            position: "insideEndTop",
            color: CFG.theme.accent,
            fontSize: 10
          }
        }];
      }
    }

    var option = {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 66, right: 84, top: 10, bottom: 28 },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(17,21,26,.96)",
        borderColor: CFG.theme.border,
        textStyle: { color: CFG.theme.text, fontSize: 11 },
        formatter: function (p) {
          var strike = strikes[p.value[1]];
          var right = rights[p.value[1]] || "?";
          var time = xLabels[p.value[0]] || "?";
          var val = p.value[2];
          var sign = val > 0 ? "+" : "";
          return time + " · " + strike + right +
            "<br/>ΔIV <b>" + sign + val.toFixed(CFG.decimals.impulse) + "</b> 波动率点";
        }
      },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        axisLabel: {
          color: CFG.theme.textFaint,
          fontSize: 10,
          interval: xInterval(cols)
        },
        splitLine: { show: false }
      },
      yAxis: {
        type: "category",
        data: yLabels,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        axisLabel: {
          color: CFG.theme.textDim,
          fontSize: 10,
          interval: yInterval(rows),
          formatter: function (v) { return v; }
        },
        splitLine: { show: false }
      },
      visualMap: {
        min: -vmax,
        max: vmax,
        calculable: false,
        orient: "vertical",
        right: 10,
        top: "middle",
        itemWidth: 11,
        itemHeight: 150,
        precision: 2,
        textStyle: { color: CFG.theme.textDim, fontSize: 9.5 },
        text: ["IV 上行", "IV 下行"],
        inRange: { color: CFG.heatmap.palette }
      },
      series: [{
        type: "heatmap",
        data: data,
        progressive: 6000,
        progressiveThreshold: 4000,
        animation: false,
        itemStyle: { borderWidth: 0 },
        emphasis: {
          itemStyle: { borderColor: "#ffffff", borderWidth: 1 }
        },
        markLine: {
          silent: true,
          symbol: "none",
          data: spotLine
        }
      }]
    };

    this._chart.setOption(option, { notMerge: true });
    this._option = option;
    this._lastRows = rows;
    this._lastCols = cols;

    return {
      rows: rows,
      cols: cols,
      cells: data.length,
      vmax: vmax
    };
  };

  HeatmapPanel.prototype.stats = function () {
    return { rows: this._lastRows, cols: this._lastCols };
  };

  global.HeatmapPanel = HeatmapPanel;
})(window);
