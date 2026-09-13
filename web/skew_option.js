/* Skew 面板 —— 首次渲染的完整 Option 构建器
 * ------------------------------------------------------------------
 * 从 skew.js 拆分：把 100+ 行的 ECharts option 对象构建独立出来，
 * 让 skew.js 的 update() 只保留"首次走这里、后续走增量"的编排逻辑。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var H = global.SKEW;

  function buildFullOption(graphs, labels, win, span, range) {
    var legendNames = [];
    graphs.forEach(function (g) {
      if (legendNames.indexOf(g.name) < 0) { legendNames.push(g.name); }
    });

    return {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 58, right: 62, top: 26, bottom: 26 },
      legend: {
        top: 2, right: 10, itemWidth: 14, itemHeight: 8, itemGap: 12,
        textStyle: { color: CFG.theme.textDim, fontSize: 10 },
        data: legendNames,
        formatter: H.displayName
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(17,21,26,.96)",
        borderColor: CFG.theme.border,
        textStyle: { color: CFG.theme.text, fontSize: 11 },
        axisPointer: { type: "line", lineStyle: { color: CFG.theme.border } },
        formatter: function (params) {
          var head = (params[0] && params[0].axisValue) || "";
          var rows = [];
          for (var i = 0; i < params.length; i++) {
            var p = params[i];
            if (p.value === null || p.value === undefined) { continue; }
            var shown = H.displayName(p.seriesName);
            var dup = false;
            for (var j = 0; j < rows.length; j++) {
              if (rows[j].name === shown) { dup = true; break; }
            }
            if (dup) { continue; }
            rows.push({ name: shown, color: p.color, value: p.value });
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
        boundaryGap: true,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        axisLabel: {
          color: CFG.theme.textFaint,
          fontSize: 10,
          interval: H.labelInterval(span),
          hideOverlap: true
        }
      },
      dataZoom: [{
        type: "inside",
        xAxisIndex: [0],
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
        preventDefaultMouseMove: true,
        start: win ? win.start : 0,
        end: win ? win.end : 100
      }],
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
            formatter: function (v) { return v.toFixed(CFG.skew.axisDecimals); }
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
            formatter: function (v) { return v.toFixed(CFG.skew.axisDecimals); }
          },
          splitLine: { show: false }
        }
      ],
      series: graphs
    };
  }

  global.buildSkewFullOption = buildFullOption;
})(window);
