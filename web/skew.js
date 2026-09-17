/* 25Δ Skew 实时曲线
 * ------------------------------------------------------------------
 * 主序列：25Δ Skew（Put25 − Call25），按正负分段着色。
 * 辅序列：ATM IV / 25Δ Put IV / 25Δ Call IV（右侧纵轴）。
 *
 * 横轴由 app.js 对齐到热力图列网格；本面板不做时间轴换算。它默认是一条自动
 * 滚动的全宽时间轴（每帧尾部追加新列、自动跟随最新），**只有用户自己拖出时间窗
 * 之后才不再跟随最新**（窗口状态归 `skew_zoom.js`，本文件每帧把它贴回 option）。
 *
 * 分层（都只依赖 global，互不反向引用）：
 *   skew_helpers.js  纯函数（量程、标签间隔、小数位、缩放与平移的数学）
 *   skew_option.js   完整 option 与 dataZoom 片段构建
 *   skew_zoom.js     手势交互（轴区缩放 / 网格平移 / 双击复位）与**视图状态**的唯一出口
 *   本文件           编排：帧数据 → series → option → 图表
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
    this._labelInterval = null;
    this._series = null;
    this._initialized = false;
    this._zoomHook = null;
    this._yDecimals = null;

    var self = this;
    this._zoom = new global.SkewZoom(this._chart, {
      onZoom: function () { self._applyZoom(); }
    });
    this._zoom.bind();

    /* 手势区的可见反馈（游标 + 区域高亮 + 空操作提示）。它只**读**视图状态，
       不参与手势判定 —— 归属判定仍然只有 `skew_zoom.js` 一处。 */
    this._regions = new global.SkewRegions(el, this._chart, function () {
      return !!self._zoom.xWindow();
    });
    this._regions.attach();

    global.addEventListener("resize", function () { self._chart.resize(); });
  }

  /* ------------------------------------------------------------------ */
  /* 量程                                                                */
  /* ------------------------------------------------------------------ */

  /* 这一帧左轴要用的量程：锁定则用锁定值，否则按**可视窗口**自动算。
     右轴不在这里 —— 它未锁定时由 ECharts 自己伸缩（见 _zoom.yAxisPatch）。 */
  SkewPanel.prototype._yRange = function (view) {
    return H.effectiveRange(this._series || {}, this._zoom.locked(0), view.from, view.to);
  };

  /*
   * 纵轴补丁 = 量程 + 锁定态**同源**（锁定态跟着量程一起从 `skew_zoom.js` 出来），
   * 再由本文件翻译成样式：被锁的那一侧换成警示色。
   *
   * 为什么必须看得见：两条纵轴各缩各的之后，同一屏幕高度在左右两边含义不同，
   * 而此前两条轴的刻度颜色、字重、字号**完全相同**，唯一提示是 meta 行里的一段
   * 文字 —— 用户完全可能把"左轴放大、右轴没放大"的图当成正常的双轴图读数。
   */
  SkewPanel.prototype._yPatch = function (range) {
    var patch = this._zoom.yAxisPatch(range);
    /* 两条轴的**默认**色，与 `skew_option.js` 首次渲染时写的一致。
       未锁定也要显式写回去：ECharts 的 setOption 是**合并**语义，
       只发"锁定色"不发"解锁色"的话，复位之后那一侧的刻度会**留在警示色**上
       （症状：点了复位，图也回去了，但刻度还是黄的）。 */
    var labelColor = [CFG.theme.textDim, CFG.theme.textFaint];
    for (var i = 0; i < patch.length; i++) {
      var locked = patch[i].locked === true;
      patch[i].axisLabel = { color: locked ? CFG.theme.warn : labelColor[i] };
      patch[i].axisLine = {
        lineStyle: { color: locked ? CFG.theme.warn : CFG.theme.border }
      };
      patch[i].nameTextStyle = { color: locked ? CFG.theme.warn : CFG.theme.textDim };
    }
    return patch;
  };

  /* 纵轴小数位随量程变 —— 合并进补丁，**不能整个覆盖 `axisLabel`**：
     覆盖会把上面刚写进去的锁定色一起抹掉（症状：缩放一次之后锁定色就没了）。 */
  SkewPanel.prototype._applyDecimals = function (patch, range) {
    var decimals = H.axisDecimalsFor(range);
    if (decimals === this._yDecimals) { return; }
    this._yDecimals = decimals;
    var label = patch[0].axisLabel || {};
    label.formatter = yFormatter(decimals);
    patch[0].axisLabel = label;
  };

  /*
   * 视图状态快照 —— 面板头徽标与复位按钮的**唯一**数据来源。
   * 不从读数（`_readout`）里取：那条路在没有数据时会提前返回，
   * 徽标就会停在上一帧的样子（"图没数据但徽标说有时间窗"，最难查的一类）。
   */
  SkewPanel.prototype.viewState = function () {
    var win = this._zoom.xWindow();
    var l0 = this._zoom.locked(0);
    var l1 = this._zoom.locked(1);
    return {
      windowed: !!win,
      from: win ? win.from : 0,
      to: win ? win.to : Math.max(this._count - 1, 0),
      cols: this._count,
      locked: [!!l0, !!l1],
      ranges: [l0, l1],
      dirty: !!win || !!l0 || !!l1
    };
  };

  /* 空操作提示的回调（由 `app.js` 接到徽标上）。图表层不直接碰 DOM。 */
  SkewPanel.prototype.setNoopHook = function (fn) {
    this._regions.hint(fn || null);
  };

  SkewPanel.prototype.yLocked = function () {
    return this._zoom.locked(0);
  };

  /* 复位全部三条轴（两条纵轴量程 + 时间窗）。双击走的就是这条路；
     切周期 / 换时段时由调用方再点一次 —— 那时列的含义已经变了，
     旧窗口必然落到一段无关的时间上。 */
  SkewPanel.prototype.resetZoom = function () {
    this._zoom.reset();
  };

  /* 这一帧的时间窗（下标 + 百分比补丁 + 是否刚被挤动），同时把列数告诉交互层。
     ⚠️ 每帧都必须问、必须贴：横轴在长，窗口按**列下标**存，
     不重贴就会按旧列数画（症状：右边永远少一截）。
     窗口被挤动 / 被复位都**必须响** —— 静默复位是"图自己跳回全宽"这类
     无源症状的根因（2026-09-17 实测：列数帧间抖动曾把用户窗口整个抹掉）。 */
  SkewPanel.prototype._view = function (count) {
    this._zoom.setCols(count);
    var view = this._zoom.view();
    if (global.console && console.warn) {
      if (view.reset) {
        console.warn("[skew] 时间窗已越界（当前 " + count + " 列）—— 复位为全宽");
      } else if (view.clamped) {
        console.warn("[skew] 时间窗超出当前列数（" + count + " 列）—— 已夹回可见范围 " +
          (view.from + 1) + "–" + (view.to + 1));
      }
    }
    return view;
  };

  SkewPanel.prototype.resize = function () {
    this._chart.resize();
  };

  SkewPanel.prototype.clear = function () {
    this._chart.clear();
    this._count = 0;
    this._labelInterval = null;
    this._series = null;
    this._initialized = false;
    /* 数据被清空（切周期 / 换时段）⇒ 锁定的量程失去参照，一并复位。 */
    this._zoom.clear();
    this._yDecimals = null;
  };

  /* ------------------------------------------------------------------ */
  /* 渲染                                                                */
  /* ------------------------------------------------------------------ */

  /* 手势改完视图之后的重绘：只改量程 / 时间窗 / 刻度，不动 series。 */
  SkewPanel.prototype._applyZoom = function () {
    if (!this._series) { return; }

    var view = this._view(this._count);
    var range = this._yRange(view);
    var patch = {
      yAxis: this._yPatch(range),
      dataZoom: [global.buildSkewDataZoom(view.patch)]
    };

    var interval = H.labelInterval(view.count);
    if (interval !== this._labelInterval) {
      this._labelInterval = interval;
      patch.xAxis = { axisLabel: { interval: interval } };
    }

    /* 放大到很窄时必须给刻度加小数位，否则一屏标签全变成同一个数
       （量程 0.05 波动率点、1 位小数 ⇒ 全是 "0.1"）。 */
    this._applyDecimals(patch.yAxis, range);

    this._chart.setOption(patch);
    if (this._zoomHook) { this._zoomHook(this._readout()); }
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

    var view = this._view(count);
    var range = H.effectiveRange(series, this._zoom.locked(0), view.from, view.to);
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
      var fullOption = global.buildSkewFullOption(
        graphs, labels, view, range, this._yPatch(range)
      );
      this._chart.setOption(fullOption, { notMerge: true });
      this._initialized = true;
      this._yDecimals = null;   /* 整份 option 重建，缓存作废 */
    } else {
      var delta = {
        xAxis: { data: labels },
        yAxis: this._yPatch(range),
        series: graphs,
        dataZoom: [global.buildSkewDataZoom(view.patch)]
      };
      var interval = H.labelInterval(view.count);
      if (interval !== this._labelInterval) {
        delta.xAxis.axisLabel = { interval: interval };
      }
      /* 纵轴刻度位随量程变 —— 与 _applyZoom 同一规则，两处都要发，
         否则纵轴缩放后第一帧的标签会用旧位数。 */
      this._applyDecimals(delta.yAxis, range);
      this._chart.setOption(delta);
    }

    /* ⚠️ 必须是**总列数**，不是窗口列数。`_applyZoom()` 拿它去 `setCols()`，
       而 `setCols()` 是"当前有多少列"的唯一来源 —— 这里写成 `view.count`
       （窗口列数）会让 `_cols` 逐帧**自我折叠**：拖一次窗口 → 下一帧
       `_cols` = 窗口宽 → 再拖时按这个小列数算窗口 → 再下一帧更小……
       实测（2026-09-17 探针）654 列被折成 4 列，而图上只看到"窗口越缩越小"，
       找不到原因。这条是**我引入的**，不是数据层抖动 —— 已证伪的假设不要留在注释里。 */
    this._count = count;
    this._labelInterval = H.labelInterval(view.count);
    return this._readout();
  };

  /* 面板读数：只有"画了多少点 / 一共多少列"。
     视图状态（时间窗在哪、哪条纵轴被锁）**不在这里** —— 那是 `viewState()`
     的归属，由面板头的徽标呈现。同一件事两处报，迟早有一处忘了改。 */
  SkewPanel.prototype._readout = function () {
    var series = this._series;
    if (!series) { return null; }
    var values = series.skew || [];
    var n = values.length;

    var filled = 0;
    for (var i = 0; i < n; i++) {
      var v = values[i];
      if (v !== null && v !== undefined) { filled += 1; }
    }

    return { points: filled, cols: n };
  };

  /* 缩放回调：视图变了要**立刻**重写 meta 行（否则读数要等下一帧才更新，
     而下一帧最长 400ms —— 拖动时会看到读数一跳一跳）。 */
  SkewPanel.prototype.setZoomHook = function (fn) {
    this._zoomHook = fn || null;
  };

  global.SkewPanel = SkewPanel;
})(window);
