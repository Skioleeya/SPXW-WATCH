/* 25Δ Skew 实时曲线
 * ------------------------------------------------------------------
 * 主序列：25Δ Skew（Put25 − Call25，单位波动率点），按正负分段着色 ——
 *         正值代表下行保护更贵，是恐慌突变最灵敏的读数。
 * 辅序列：ATM IV / 25Δ Put IV / 25Δ Call IV（右侧纵轴），
 *         用来区分"整体波动率抬升"与"单纯偏度形变"。
 *
 * 横轴：由 app.js 先对齐到热力图那套列网格（web/period.js::alignSkew），
 *       所以本面板收到的 `series.label` 与热力图的列**逐列对应** —— 选 1 分钟
 *       周期时两块图都是 1 分钟一格。本面板不做任何时间轴换算。
 *
 * 纵轴不自动缩放
 * --------------
 * 量程按后端下发的 ``skew.scale_policy.window_s``（窗口长度）在**窗口内**取
 * 极值，再与 0 取并集、加留白。两条设计约束：
 *
 *   1. 若让 ECharts 每帧自动 scale，曲线会因为量程随数据跳动而"呼吸"，
 *      反而看不清真实的斜率变化；
 *   2. 但若按**整条序列**取极值，早盘一次瞬时尖峰（例如 +9）会把量程永久撑大，
 *      之后全天 0~1 的波动被压成一条平线。窗口取最近一小时，尖峰会随时间
 *      退出窗口，量程自动收回。
 *
 * 为什么窗口长度由后端下发：它是业务口径，不是呈现参数。前端自己写一个
 * 默认值就等于把口径抄了一份，后端调整时两边会悄悄不一致。
 *
 * 为什么不用 visualMap 做正负着色
 * ------------------------------
 * 直觉写法是给主序列挂一个 ``visualMap``（``pieces: [{gt:0},{lte:0}]``）按
 * 正负分段着色。**这条路在本项目 vendor 的 ECharts 5.5.1 上走不通**：只要用
 * ``pieces`` 模式，渲染时必抛 ``Cannot read properties of undefined (reading
 * 'coord')``，整块 Skew 面板渲染中断（实测 ``type:'piecewise'`` / ``show:true`` /
 * 二维数据 / 去掉 seriesIndex 全都一样失败，而 ``continuous`` 模式正常）。
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

  /*
   * 纵轴量程：窗口内的极值 ∪ {0}，再加留白。
   *
   * 窗口按**时间**定义（后端下发的 window_s），与用户选的周期无关 —— 30 秒
   * 视图和 15 分视图看到的是同一段行情，量程可比，切换周期时纵轴不会跳。
   *
   * 基准时刻取序列里**最后一个有时间戳的列**，而不是最后一个有 skew 值的列：
   * 断流恢复后末尾可能挂着若干空列，拿空列当基准会把整个窗口往后挪。
   */
  function axisRange(series, policy) {
    var values = series.skew || [];
    var stamps = series.ts || [];

    var windowS = policy ? Number(policy.window_s) : 0;
    if (!isFinite(windowS) || windowS < 0) { windowS = 0; }

    var latest = null;
    for (var i = stamps.length - 1; i >= 0; i--) {
      var s = stamps[i];
      if (typeof s === "number" && isFinite(s)) { latest = s; break; }
    }

    var lo = 0;
    var hi = 0;
    var seen = 0;

    for (var k = 0; k < values.length; k++) {
      var v = values[k];
      if (v === null || v === undefined) { continue; }
      if (windowS > 0 && latest !== null) {
        var st = stamps[k];
        if (typeof st === "number" && isFinite(st) && latest - st > windowS) {
          continue;
        }
      }
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
      seen += 1;
    }

    /* 窗口内一个点都没有：可见数据整体短于窗口，或最近一段断流而更早还有
       读数。两种情况下"窗口内的极值"都退化成"全部可见数据的极值" —— 若这时
       仍按空窗口给 ±0.18，画出来的曲线会整条跑到轴外被裁掉。 */
    if (!seen) {
      for (var j = 0; j < values.length; j++) {
        var w = values[j];
        if (w === null || w === undefined) { continue; }
        lo = Math.min(lo, w);
        hi = Math.max(hi, w);
      }
    }

    var span = Math.max(hi - lo, 1);
    var pad = span * CFG.skew.padRatio;
    return [lo - pad, hi + pad];
  }

  /*
   * `series` 已由 app.js 对齐到热力图那套列网格（逐列数值 + 等长的 label），
   * `policy` 是后端下发的纵轴量程策略。本方法只负责画，不做时间轴换算。
   */
  SkewPanel.prototype.update = function (series, policy) {
    if (!series) { return false; }
    var labels = series.label || [];
    var count = labels.length;
    if (!count) { return false; }

    var skew = series.skew || [];
    var atm = series.atm || [];
    var put25 = series.put25 || [];
    var call25 = series.call25 || [];
    var range = axisRange(series, policy);
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
          interval: Math.max(Math.floor(count / 14) - 1, 0),
          /* interval 是**强制**间隔：一旦算成 0，ECharts 就不再自动防重叠。
             窄窗口（或列数恰好落在 15 附近）时标签会糊成一团，所以额外允许
             它按实际宽度自行省略。 */
          hideOverlap: true
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

    /* points 是**有读数的列数**，cols 是列总数。两者分开报：对齐之后列网格
       由热力图决定，可能出现"有列无值"（该周期内这一点没有读数），只报列数
       会让人以为满屏都有数据。 */
    var filled = 0;
    for (var q = 0; q < skew.length; q++) {
      if (skew[q] !== null && skew[q] !== undefined) { filled += 1; }
    }
    return { points: filled, cols: count, range: range };
  };

  SkewPanel.prototype.stats = function () {
    return { points: this._count };
  };

  global.SkewPanel = SkewPanel;
})(window);
