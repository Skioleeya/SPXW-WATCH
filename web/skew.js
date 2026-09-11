/* 25Δ Skew 实时曲线
 * ------------------------------------------------------------------
 * 主序列：25Δ Skew（Put25 − Call25，单位波动率点），按正负分段着色 ——
 *         正值代表下行保护更贵，是恐慌突变最灵敏的读数。
 * 辅序列：ATM IV / 25Δ Put IV / 25Δ Call IV（右侧纵轴），
 *         用来区分"整体波动率抬升"与"单纯偏度形变"。
 *
 * 纵轴不自动缩放
 * --------------
 * 后端每帧会带上 ``skew_min`` / ``skew_max``，前端取二者与 0 的并集再加留白。
 * 若让 ECharts 每帧自动 scale，曲线会因为量程随数据跳动而"呼吸"，反而看不清
 * 真实的斜率变化。
 *
 * 为什么不用 visualMap 做正负着色
 * ------------------------------
 * 直觉写法是给主序列挂一个 ``visualMap``（``pieces: [{gt:0},{lte:0}]``）按
 * 正负分段着色。**这条路在本项目的 ECharts 5.6.0 上走不通**：只要用 ``pieces``
 * 模式，渲染时必抛 ``Cannot read properties of undefined (reading 'coord')``，
 * 整块 Skew 面板渲染中断（实测 ``type:'piecewise'`` / ``show:true`` / 二维
 * 数据 / 去掉 seriesIndex 全都一样失败，而 ``continuous`` 模式正常）。
 *
 * 所以改成把主序列按正负拆成**两条同名曲线**，各自固定颜色，另一侧填 null。
 * 效果与 ``pieces`` 的硬分割完全一致，且不依赖 visualMap 的实现细节。拆出的
 * 两条同名，图例去重后只有一条、点选时一起切换；提示框则过滤掉 null 那一侧，
 * 避免出现两行同名条目。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  function SkewPanel(el) {
    this._el = el;
    this._chart = echarts.init(el, null, { renderer: "canvas" });
    this._count = 0;

    var self = this;
    global.addEventListener("resize", function () { self._chart.resize(); });
  }

  SkewPanel.prototype.resize = function () {
    this._chart.resize();
  };

  SkewPanel.prototype.clear = function () {
    this._chart.clear();
    this._count = 0;
  };

  /*
   * 把一条序列按正负拆成两条互补的序列（各自的另一侧填 null）。
   *
   * 这样 0 处是一个硬分割：正值段整体暖色，负值段整体冷色，颜色不随数值大小
   * 渐变，读数与颜色一一对应。代价是零穿越处会空一格——那一格本来也是跨越
   * 两个桶才发生的符号变化，留空比插一个假点更诚实。
   */
  function splitBySign(values) {
    var positive = [];
    var negative = [];
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      var known = v !== null && v !== undefined;
      positive.push(known && v >= 0 ? v : null);
      negative.push(known && v < 0 ? v : null);
    }
    return { positive: positive, negative: negative };
  }

  function axisRange(series) {
    var lo = 0;
    var hi = 0;
    if (series.skew_min !== null && series.skew_min !== undefined) {
      lo = Math.min(lo, series.skew_min);
      hi = Math.max(hi, series.skew_min);
    }
    if (series.skew_max !== null && series.skew_max !== undefined) {
      lo = Math.min(lo, series.skew_max);
      hi = Math.max(hi, series.skew_max);
    }
    var span = Math.max(hi - lo, 1);
    var pad = span * CFG.skew.padRatio;
    return [lo - pad, hi + pad];
  }

  SkewPanel.prototype.update = function (block) {
    if (!block || !block.series) { return false; }
    var series = block.series;
    var labels = series.label || [];
    var count = labels.length;
    if (!count) { return false; }

    var skew = series.skew || [];
    var atm = series.atm || [];
    var put25 = series.put25 || [];
    var call25 = series.call25 || [];
    var range = axisRange(series);
    var sign = splitBySign(skew);

    /* 主序列按正负拆成两条同名曲线。见模块 docstring「为什么不用 visualMap」。 */
    var graphs = [
      {
        name: "25Δ Skew",
        type: "line",
        yAxisIndex: 0,
        data: sign.positive,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2.2, color: CFG.theme.hot },
        connectNulls: false,
        z: 5
      },
      {
        name: "25Δ Skew",
        type: "line",
        yAxisIndex: 0,
        data: sign.negative,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2.2, color: CFG.theme.cool },
        connectNulls: false,
        z: 5
      }
    ];

    if (CFG.skew.showAtm) {
      graphs.push({
        name: "ATM IV", type: "line", yAxisIndex: 1, data: atm,
        showSymbol: false, smooth: false,
        lineStyle: { width: 1.1, type: "dotted", color: CFG.theme.textFaint },
        connectNulls: true, z: 2
      });
    }
    if (CFG.skew.showPut25) {
      graphs.push({
        name: "25Δ Put IV", type: "line", yAxisIndex: 1, data: put25,
        showSymbol: false, smooth: false,
        lineStyle: { width: 1.1, type: "dashed", color: CFG.theme.hot, opacity: .75 },
        connectNulls: true, z: 3
      });
    }
    if (CFG.skew.showCall25) {
      graphs.push({
        name: "25Δ Call IV", type: "line", yAxisIndex: 1, data: call25,
        showSymbol: false, smooth: false,
        lineStyle: { width: 1.1, type: "dashed", color: CFG.theme.cool, opacity: .75 },
        connectNulls: true, z: 3
      });
    }

    /* 主序列拆成了两条同名曲线，图例按名字去重后只出现一条；
       点图例时 ECharts 按名字切换，两条会一起隐藏/显示。 */
    var legendNames = [];
    graphs.forEach(function (g) {
      if (legendNames.indexOf(g.name) < 0) { legendNames.push(g.name); }
    });

    var option = {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 58, right: 62, top: 26, bottom: 26 },
      legend: {
        top: 2, right: 10, itemWidth: 14, itemHeight: 8, itemGap: 12,
        textStyle: { color: CFG.theme.textDim, fontSize: 10 },
        data: legendNames
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(17,21,26,.96)",
        borderColor: CFG.theme.border,
        textStyle: { color: CFG.theme.text, fontSize: 11 },
        axisPointer: { type: "line", lineStyle: { color: CFG.theme.border } },
        /* 拆分出来的两条同名曲线在同一时刻必有一条是 null；不过滤的话
           提示框会出现两行同名条目，一行有值、一行是 "-"。 */
        formatter: function (params) {
          var head = (params[0] && params[0].axisValue) || "";
          var rows = [];
          for (var i = 0; i < params.length; i++) {
            var p = params[i];
            if (p.value === null || p.value === undefined) { continue; }
            var dup = false;
            for (var j = 0; j < rows.length; j++) {
              if (rows[j].name === p.seriesName) { dup = true; break; }
            }
            if (dup) { continue; }
            rows.push({ name: p.seriesName, color: p.color, value: p.value });
          }
          if (!rows.length) { return head; }
          var body = rows.map(function (r) {
            return '<span style="display:inline-block;margin-right:5px;' +
              "border-radius:50%;width:8px;height:8px;background-color:" +
              r.color + '"></span>' + r.name + " <b>" +
              Number(r.value).toFixed(CFG.decimals.skew) + "</b>";
          });
          return head + "<br/>" + body.join("<br/>");
        }
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        axisLabel: {
          color: CFG.theme.textFaint,
          fontSize: 10,
          interval: Math.max(Math.floor(count / 14) - 1, 0)
        }
      },
      yAxis: [
        {
          type: "value",
          name: "25Δ Skew",
          nameTextStyle: { color: CFG.theme.textDim, fontSize: 10, align: "left" },
          min: range[0],
          max: range[1],
          axisLine: { lineStyle: { color: CFG.theme.border } },
          axisLabel: {
            color: CFG.theme.textDim, fontSize: 10,
            formatter: function (v) { return v.toFixed(1); }
          },
          splitLine: { lineStyle: { color: CFG.theme.border, opacity: .45 } }
        },
        {
          type: "value",
          name: "IV",
          nameTextStyle: { color: CFG.theme.textDim, fontSize: 10, align: "right" },
          scale: true,
          axisLine: { lineStyle: { color: CFG.theme.border } },
          axisLabel: {
            color: CFG.theme.textFaint, fontSize: 10,
            formatter: function (v) { return v.toFixed(1); }
          },
          splitLine: { show: false }
        }
      ],
      series: graphs
    };

    /* 正负着色由「拆成两条同名曲线」实现，不用 visualMap —— 见模块 docstring。 */

    if (CFG.skew.zeroLine) {
      option.series[0].markLine = {
        silent: true,
        symbol: "none",
        data: [{
          yAxis: 0,
          lineStyle: { color: CFG.theme.border, type: "dashed", width: 1 },
          label: { show: false }
        }]
      };
    }

    this._chart.setOption(option, { notMerge: true });
    this._count = count;
    return { points: count, range: range };
  };

  SkewPanel.prototype.stats = function () {
    return { points: this._count };
  };

  global.SkewPanel = SkewPanel;
})(window);
