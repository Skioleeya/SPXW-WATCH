/* Skew 面板 —— 首次渲染的完整 Option 构建器
 * ------------------------------------------------------------------
 * 从 skew.js 拆分：把 100+ 行的 ECharts option 对象构建独立出来，
 * 让 skew.js 的 update() 只保留"首次走这里、后续走增量"的编排逻辑。
 *
 * 两条纵轴的 `{min,max}` **不在这里算** —— 由 `skew_zoom.js::yAxisPatch()`
 * 统一给（它是"锁定与否"的唯一出口）。本文件只负责把给进来的值贴到轴上。
 *
 * 时间窗的 `dataZoom` 片段由 `buildSkewDataZoom()` 生成，**首次与增量两条路
 * 都用它**：一份片段两处手写，改了一处忘一处会让"窗口"与"实际可视列"分家
 * （症状是拖了没反应、或者窗口自己跳回全宽）。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var H = global.SKEW;

  /*
   * 时间窗（X）—— 本面板**唯一的** dataZoom 组件。
   *
   * · 只用它做"可视窗口"，**不做任何自带手势**：`zoomOnMouseWheel` /
   *   `moveOnMouseWheel` / `moveOnMouseMove` 全关。2026-09-17 KAI 把交互改成
   *   "按住左键拖动"（轴区 = 缩放、网格内 = 平移），全部由 `web/skew_zoom.js`
   *   自己接管；留着自带手势就是"一个手势两个主人"，两边同时改窗口。
   * · `filterMode: "none"`：只改坐标轴范围，**不动 series 数据** ——
   *   与热力图 `web/heatmap_option.js` 同一思路（窗口移动，数据不重建）。
   * · `start` / `end` 按**列下标**换算成百分比（`skew_zoom.js::view()` 唯一算），
   *   每次渲染都必须重贴：横轴每帧往尾部追加新列，百分比窗口会随列数漂移。
   */
  function buildDataZoom(patch) {
    return {
      type: "inside",
      xAxisIndex: [0],
      filterMode: "none",
      zoomOnMouseWheel: false,
      moveOnMouseWheel: false,
      moveOnMouseMove: false,
      start: patch.start,
      end: patch.end
    };
  }

  function buildFullOption(graphs, labels, view, range, yPatch) {
    var legendNames = [];
    graphs.forEach(function (g) {
      if (legendNames.indexOf(g.name) < 0) { legendNames.push(g.name); }
    });

    /* 纵轴刻度位随量程变（放大到很窄时要加位，见 skew_helpers.axisDecimalsFor）。
       首次渲染同样按需取，不要写死 CFG.skew.axisDecimals —— 否则
       "缩过一次 Y 轴之后"与"刚打开页面"两个状态的小数位会不一致。

       两条轴**共用同一个位数**：它们单位相同、自然量程相近（实测约 4.4 vs 5.0），
       且每次缩放用的是同一个倍率，所以位数不会差一档。分成两套只会多一份真相。 */
    var yDecimals = H.axisDecimalsFor(range);
    var yFmt = function (v) { return Number(v).toFixed(yDecimals); };

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
          /* 抽稀按**可视列数**算，不是全部列 —— 时间窗缩窄之后屏幕上的标签
             必须跟着变密，拿全部列当分母会把标签抽稀到看不出时间结构。 */
          interval: H.labelInterval(view.count),
          hideOverlap: true
        }
      },
      /* 时间窗。它同时也是"X 轴没有别的缩放入口"的落点：本图不提供自带手势，
         窗口只能由 `web/skew_zoom.js` 改（轴区左右拖 = 缩窗、网格内拖 = 平移）。 */
      dataZoom: [buildDataZoom(view.patch)],
      yAxis: [
        {
          type: "value",
          name: "25Δ Skew",
          nameTextStyle: { color: CFG.theme.textDim, fontSize: 10, align: "left" },
          min: yPatch[0].min,
          max: yPatch[0].max,
          axisLine: { lineStyle: { color: CFG.theme.border } },
          axisLabel: {
            color: CFG.theme.textDim, fontSize: 10,
            formatter: yFmt
          },
          splitLine: { lineStyle: { color: CFG.theme.border, opacity: .45 } }
        },
        {
          type: "value",
          name: "IV",
          nameTextStyle: { color: CFG.theme.textDim, fontSize: 10, align: "right" },
          /* 未锁定时 min/max 为 null ⇒ 交回 ECharts 自动量程，`scale` 才起作用
             （不让它把 0 硬拉进量程）。锁定后显式值覆盖它。 */
          scale: true,
          min: yPatch[1].min,
          max: yPatch[1].max,
          axisLine: { lineStyle: { color: CFG.theme.border } },
          axisLabel: {
            color: CFG.theme.textFaint, fontSize: 10,
            formatter: yFmt
          },
          splitLine: { show: false }
        }
      ],
      series: graphs
    };
  }

  global.buildSkewFullOption = buildFullOption;
  global.buildSkewDataZoom = buildDataZoom;
})(window);

