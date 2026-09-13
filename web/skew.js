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
 *       X 轴写 `boundaryGap: true`（类别轴默认值，热力图也是这个）：数据点
 *       居中在各自的时间带里，与热力图的格子**同宽同位**。若写成 false，点会
 *       落在时间带的边界上 —— 第一个点正好压在左轴线上，看着像多画了一个点，
 *       整条线也相对热力图左偏半列。
 *
 *       缩放：滚轮放大 / 缩小、按住拖动平移，**不设上下限**（可以一路缩到单列，
 *       也能拉回全宽）。窗口按**列索引**保存，不按百分比 —— 见 `_captureZoom`。
 *
 * 纵轴按**眼前这一段**自适应
 * --------------------------
 * 量程 = **当前可见列**内的极值 ∪ {0}，再加留白（`axisRange`）。
 *
 * 为什么不是"让 ECharts 自动 scale"：那会让量程随每一帧的数据跳动，曲线一直
 * "呼吸"，看不清真实的斜率变化。所以极值由本面板自己算，只在**视口变化**时
 * 才重算 —— 表现为"放大到哪一段，纵轴就按那一段的高度撑开"。
 *
 * ⚠️ 这里曾经按**时间窗口**（后端下发的 ``window_s``，最近一小时）取极值，
 * 与视口无关。后果是把横轴放大到早盘段时，早盘读数（例如 +8.4）落在量程
 * （按最近一小时算出的 0~0.84）之外，**整条曲线被画到坐标区外裁掉 —— 屏幕
 * 一片空白且不报任何错**。KAI 2026-09-13 定为按视口算。
 *
 * 0 恒在量程内：skew 的正负是有含义的（正 = 下行保护更贵），零线不能因为
 * 这一段全是正数就被挤出画面。
 *
 * 读数与量程**同一口径**：meta 行的 ``N/M 点`` 也按当前可见列算（``_readout``），
 * 缩放后立刻收窄。缩放发生在两帧之间，宿主拿不到新读数，所以面板用
 * ``setViewportHook`` 回调一次 —— 否则图缩到 21 列、读数仍报 780/780。
 *
 * 为什么不用 visualMap 做正负着色
 * ------------------------------
 * 直觉写法是给主序列挂一个 ``visualMap``（``pieces: [{gt:0},{lte:0}]``）按
 * 正负分段着色。**这条路在本项目 vendor 的 ECharts 5.5.1 上走不通**：只要用
 * ``pieces`` 模式，渲染时必抛 ``Cannot read properties of undefined (reading
 * 'coord')``，整块 Skew 面板渲染中断（实测 ``type:'piecewise'`` / ``show:true`` /
 * 二维数据 / 去掉 seriesIndex 全都一样失败，而 ``continuous`` 模式正常）。
 *
 * 所以改成把主序列按正负拆成**两条曲线**，各自固定颜色，另一侧填 null。
 * 效果与 ``pieces`` 的硬分割完全一致，且不依赖 visualMap 的实现细节。
 *
 * 两条曲线的 series ``name`` 必须**不同**（``25Δ Skew`` / ``25Δ Skew·负``）：
 * ECharts 图例按 name 去重，同名的话图例上只剩一条、且只带第一条的颜色 ——
 * 曲线明明是暖+冷两段，图例却只说明了一半（实测：图例带冷色像素 0，而画布
 * 上冷色 1744px）。显示文案由 ``legend.formatter`` 与提示框统一抹掉 ``·负``
 * 后缀，所以用户看到的仍是两条同名的 ``25Δ Skew``。点选各自独立 —— 这正是
 * 分段着色该有的语义：想看哪一段就点哪一段。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  function SkewPanel(el) {
    this._el = el;
    this._chart = echarts.init(el, null, { renderer: "canvas" });
    this._count = 0;
    /* 横轴缩放窗口，按**列索引**保存（不是百分比）。后端每帧往尾部追加新列，
       百分比窗口会随列数增长而漂移 —— 同一段行情会慢慢滑出视口。null = 全宽。
       `tail` 表示缩放时右端本来就贴住最后一列，此时让它继续跟着尾部走，
       否则盯盘时一放大就再也看不到最新读数。 */
    this._zoom = null;
    this._labelInterval = null;
    /* 最近一帧对齐后的序列。缩放事件发生在两帧之间，纵轴量程与标签密度都要
       立刻按新视口重算，不能干等下一帧（最多 400ms，且断流时永远等不到）。 */
    this._series = null;
    /* 视口变化时的回调（由宿主注册，见 `setViewportHook`）。meta 行要在缩放
       后立刻跟着收窄，而缩放不经过 `update()`。 */
    this._viewportHook = null;

    var self = this;
    this._chart.on("datazoom", function () { self._captureZoom(); });
    /* 双击复位：滚轮只能一格一格往回缩，从深度放大状态回到全宽很费手。 */
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
  };

  /* 由可见列数决定横轴显示多少个时间标签（与 heatmap.js::xInterval 同一规则）。 */
  function labelInterval(span) {
    var want = CFG.skew.xLabelCount;
    if (!(want > 0) || !(span > want)) { return 0; }
    return Math.max(Math.floor(span / want) - 1, 0);
  }

  /*
   * 把保存的缩放窗口换算成这一帧要用的窗口。
   *
   * 越界（周期/时段切换会让列数骤变）就返回 null，由调用方整段丢弃、回到全宽：
   * 硬套旧窗口会画出一段与用户当初选的位置无关的区间，而且没有任何提示。
   */
  function windowOf(zoom, n) {
    if (!zoom || !(n > 1)) { return null; }
    var a = zoom.start;
    var b = zoom.tail ? n - 1 : zoom.end;
    if (!(a >= 0) || a >= n || b >= n || b <= a) { return null; }
    return { from: a, to: b, start: a / (n - 1) * 100, end: b / (n - 1) * 100 };
  }

  /* 当前可见的列数（没缩放就是全部列）。 */
  SkewPanel.prototype._visibleSpan = function (n) {
    var win = windowOf(this._zoom, n);
    return win ? (win.to - win.from + 1) : n;
  };

  /*
   * 设置横轴可见窗口（列索引），并立刻按新视口重算纵轴量程与标签密度。
   *
   * `zoom` 为 null = 全宽。形如 ``{start, end, tail}``；`tail` 表示右端贴住
   * 最后一列，此时让它跟着尾部走（盯盘），否则冻住（查历史段）。
   *
   * 为什么单独开成公开方法：这是"视口变了"的唯一入口 —— `_captureZoom` 从图表
   * 事件里读出窗口后调它，回归工具也能在没有真 ECharts 的环境下驱动同一条路径。
   * 绕开它直接改 `_zoom` 会漏掉量程重算。
   */
  SkewPanel.prototype.setViewport = function (zoom) {
    this._zoom = zoom || null;
    this._applyViewport();
  };

  /*
   * 从图表当前的 dataZoom 状态里读回窗口，交给 `setViewport`。
   *
   * 只认 `start`/`end`（百分比）这一对，**不认** `startValue`/`endValue`：
   * 后者是"设进去"的，滚轮缩放时 ECharts 只更新百分比，值窗口会停留在上一次
   * 设进去的陈旧值，拿它当真相会把视口弹回老位置。类别轴的 extent 是
   * [0, n-1]，百分比与列号线性对应，往返换算稳定。
   */
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

    /* 拉回全宽：不再保存窗口，让后续新列继续全部显示。 */
    if (a <= 0 && b >= n - 1) { this.setViewport(null); } else {
      this.setViewport({ start: a, end: b, tail: b >= n - 1 });
    }
  };

  /*
   * 视口变了：横轴标签密度与纵轴量程都要重算。
   *
   * 这一步只能 merge，**不能** notMerge 全量重画 —— 那会把刚设好的缩放窗口
   * 一起抹掉。
   *
   * ⚠️ `update()` 本身走的是 notMerge，所以**图例开关每帧都会被复位**。这是既有
   * 行为、与缩放无关（实测：`legendToggleSelect` 后下一帧 `selected` 变回 `{}`），
   * 别把它当成缩放引入的问题。
   */
  SkewPanel.prototype._applyViewport = function () {
    if (!this._series) { return; }

    var win = windowOf(this._zoom, this._count);
    var range = axisRange(this._series, win);
    var patch = { yAxis: [{ min: range[0], max: range[1] }, {}] };

    var interval = labelInterval(this._visibleSpan(this._count));
    if (interval !== this._labelInterval) {
      this._labelInterval = interval;
      patch.xAxis = { axisLabel: { interval: interval } };
    }
    this._chart.setOption(patch);
    /* 图缩了、读数也得缩 —— 宿主拿不到这次视口变化，只能由面板回调。 */
    if (this._viewportHook) { this._viewportHook(this._readout()); }
  };

  SkewPanel.prototype._resetZoom = function () {
    if (!this._zoom) { return; }
    this._chart.setOption({ dataZoom: [{ start: 0, end: 100 }] });
    this.setViewport(null);
  };

  /* 主序列拆成两条曲线时用的 name。**必须不同**（图例才能各占一条、各带自己的
     颜色），但**显示**上统一成 `NAME_POS` —— 见模块 docstring。 */
  var NAME_POS = "25Δ Skew";
  var NAME_NEG = NAME_POS + "·负";

  function displayName(name) {
    return name === NAME_NEG ? NAME_POS : name;
  }

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
   * 纵轴量程：**当前可见列**内的极值 ∪ {0}，再加留白。
   *
   * `win` 是当前视口（`{from, to}` 列索引，含端点），null = 全宽。量程只认
   * "眼前这一段"：放大到哪，纵轴就按哪一段的高度撑开 —— 见模块 docstring
   * 「纵轴按眼前这一段自适应」。
   *
   * 为什么基准不是"最近一小时"：那是**时间**口径，与视口无关。缩放到早盘段
   * 时早盘读数会落在量程之外被裁掉，屏幕一片空白且不报错（实测 21/21 点越界）。
   *
   * 可见列一个读数都没有时退到全序列极值：此时视口里本来就没东西可画，给一个
   * 退化的空轴只会让人以为"数据是 0"。
   */
  function axisRange(series, win) {
    var values = series.skew || [];
    var from = win ? win.from : 0;
    var to = win ? win.to : values.length - 1;

    var lo = 0;
    var hi = 0;
    var seen = 0;

    for (var k = from; k <= to; k++) {
      var v = values[k];
      if (v === null || v === undefined) { continue; }
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
      seen += 1;
    }

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
   * `series` 已由 app.js 对齐到热力图那套列网格（逐列数值 + 等长的 label）。
   * 本方法只负责画，不做时间轴换算；纵轴量程按当前视口算（见 `axisRange`）。
   */
  SkewPanel.prototype.update = function (series) {
    if (!series) { return false; }
    var labels = series.label || [];
    var count = labels.length;
    if (!count) { return false; }

    var skew = series.skew || [];
    var atm = series.atm || [];
    var put25 = series.put25 || [];
    var call25 = series.call25 || [];

    /* 上一帧的缩放窗口在列数骤变（切周期 / 切时段）后可能已经越界：整段丢弃。 */
    var win = windowOf(this._zoom, count);
    if (this._zoom && !win) { this._zoom = null; }
    var span = win ? (win.to - win.from + 1) : count;

    var range = axisRange(series, win);
    var sign = splitBySign(skew);
    /* 留给 `_applyViewport`：缩放发生在两帧之间，它要拿这份数据立刻重算量程。 */
    this._series = series;

    /* 主序列按正负拆成两条曲线（name 不同、显示同名）。见模块 docstring
       「为什么不用 visualMap」。 */
    var graphs = [
      {
        name: NAME_POS,
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
        name: NAME_NEG,
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

    /* 图例条目 = 各 series 的 name 去重。两条 skew 曲线的 name **不同**
       （`25Δ Skew` / `25Δ Skew·负`），所以各占一条、各带自己的颜色；显示
       文案由下面的 `formatter` 统一成同名。 */
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
        data: legendNames,
        /* 抹掉内部后缀，让两条 skew 曲线在图例上都显示 `25Δ Skew`。 */
        formatter: displayName
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(17,21,26,.96)",
        borderColor: CFG.theme.border,
        textStyle: { color: CFG.theme.text, fontSize: 11 },
        axisPointer: { type: "line", lineStyle: { color: CFG.theme.border } },
        /* 拆分出的两条 skew 曲线在同一时刻必有一条是 null；不过滤的话提示框
           会出现两行 `25Δ Skew`，一行有值、一行是 "-"。显示名一律过
           `displayName`，免得内部后缀 `·负` 漏到界面上。 */
        formatter: function (params) {
          var head = (params[0] && params[0].axisValue) || "";
          var rows = [];
          for (var i = 0; i < params.length; i++) {
            var p = params[i];
            if (p.value === null || p.value === undefined) { continue; }
            var shown = displayName(p.seriesName);
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
        /* 居中在各自的时间带里，与热力图的列**同宽同位**（热力图走的是类别轴
           默认值 true）。写成 false 的话点会落在时间带的边界上，第一个点正好
           压在左轴线上 —— 见模块 docstring。这里只改对齐方式，不动任何数据。 */
        boundaryGap: true,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        axisLabel: {
          color: CFG.theme.textFaint,
          fontSize: 10,
          interval: labelInterval(span),
          /* interval 是**强制**间隔：一旦算成 0，ECharts 就不再自动防重叠。
             窄窗口（或列数恰好落在 15 附近）时标签会糊成一团，所以额外允许
             它按实际宽度自行省略。 */
          hideOverlap: true
        }
      },
      /* 横轴缩放：滚轮放大 / 缩小，按住拖动平移。**不设 minSpan / maxSpan**，
         所以可以一路缩到单列、也能拉回全宽（KAI 要求"无限制"）。
         filterMode:'none' 而不是默认的 'filter'：默认值会把跨越视口边界的
         折线段整段滤掉，看起来像数据断了；'none' 只按网格裁剪，曲线始终连续。 */
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
    /* 记下这一帧实际用的间隔，免得 _applyViewport 紧接着又 merge 一次。 */
    this._labelInterval = labelInterval(span);
    return this._readout();
  };

  /*
   * 面板读数（meta 行用）。**口径与纵轴量程一致**：只认当前可见列（`_zoom`）。
   *
   * `points` = 可见列里**有读数的列数**，`cols` = **可见列数**。两者分开报：
   * 对齐之后列网格由热力图决定，可能出现"有列无值"（该周期内这一点没有读数），
   * 只报列数会让人以为满屏都有数据。
   *
   * ⚠️ 两者都按**可见列**算，不是全序列。缩放后屏幕上是 21 列却报 `780/780 点`
   * 是旧口径的残留（量程按视口、读数按全序列，同一块面板两套口径）。
   *
   * `view` 里那个 `cols` 是**总列数**（"缩放 601–621/780 列"的分母），与上面
   * 的 `cols`（可见列数）不是一回事 —— 故意分开，别合并。
   */
  SkewPanel.prototype._readout = function () {
    var series = this._series;
    if (!series) { return null; }
    var values = series.skew || [];
    var n = values.length;
    var win = windowOf(this._zoom, n);
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
      range: axisRange(series, win),
      view: win ? { from: win.from + 1, to: win.to + 1, cols: n } : null
    };
  };

  /*
   * 注册"视口变了"的回调。缩放发生在两帧之间，宿主此刻拿不到新读数 ——
   * 面板在 `_applyViewport` 末尾回调一次，meta 行就能与图同步收窄。
   */
  SkewPanel.prototype.setViewportHook = function (fn) {
    this._viewportHook = fn || null;
  };

  global.SkewPanel = SkewPanel;
})(window);
