/* Skew 面板 —— 纯辅助函数
 * ------------------------------------------------------------------
 * 从 skew.js 拆分：无 this 依赖，可被 option builder 与面板同时调用。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  /* 由可见列数决定横轴显示多少个时间标签。 */
  function labelInterval(span) {
    var want = CFG.skew.xLabelCount;
    if (!(want > 0) || !(span > want)) { return 0; }
    return Math.max(Math.floor(span / want) - 1, 0);
  }

  /*
   * 把保存的缩放窗口换算成这一帧要用的窗口。
   * 越界就返回 null，由调用方整段丢弃、回到全宽。
   */
  function windowOf(zoom, n) {
    if (!zoom || !(n > 1)) { return null; }
    var a = zoom.start;
    var b = zoom.tail ? n - 1 : zoom.end;
    if (!(a >= 0) || a >= n || b >= n || b <= a) { return null; }
    return { from: a, to: b, start: a / (n - 1) * 100, end: b / (n - 1) * 100 };
  }

  var NAME_POS = "25Δ Skew";
  var NAME_NEG = NAME_POS + "·负";

  function displayName(name) {
    return name === NAME_NEG ? NAME_POS : name;
  }

  /* 把一条序列按正负拆成两条互补的序列（各自的另一侧填 null）。 */
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
   * 纵轴量程：当前可见列内的极值 ∪ {0}，再加留白。
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

  /* ------------------------------------------------------------------ */
  /* Y 轴自由缩放                                                        */
  /* ------------------------------------------------------------------ */

  var FALLBACK_YCFG = {
    enabled: true, step: 1.15, minSpan: 0.05, maxSpan: 500, anchorAtPointer: true
  };

  function yCfg() {
    var c = CFG.skew.yZoom;
    return c ? c : FALLBACK_YCFG;
  }

  /*
   * 按倍率缩放一段量程。
   *
   * factor < 1 放大（量程变窄），factor > 1 缩小（量程变宽）。
   * anchor 是**保持不动的那个 Y 值**（鼠标所指处的值）；给它 null 则锚在量程中心。
   *
   * 为什么要锚点：不锚的话每次缩放都从中心对称扩展，用户盯着的那段曲线会跑出视野，
   * 得反复"缩放 + 平移"来回找。锚在指针下就是"往哪儿滚就往哪儿缩"。
   *
   * 量程被 minSpan / maxSpan 夹住，并且**夹住之后再补一次锚点补偿** ——
   * 先夹后算会让锚点漂移，用户会感觉曲线在被夹住的那一刻"跳"了一下。
   */
  function zoomRange(range, factor, anchor) {
    var cfg = yCfg();
    var lo = Number(range[0]);
    var hi = Number(range[1]);
    if (!isFinite(lo) || !isFinite(hi) || !(hi > lo)) { return [lo, hi]; }
    if (!(factor > 0)) { return [lo, hi]; }

    var span = hi - lo;

    /* 输入量程本身已经窄于下限（例如上一帧被夹到刚好 minSpan，或数据极值全等）
       ⇒ 先把**基准**抬到下限再算，否则一次放大就会把量程压成 0 宽
       （span 0 会让 ECharts 的 min==max，刻度全糊成一个值）。
       这不改变"往下缩"的方向：本分支只在放大时兜底。 */
    var floor = cfg.minSpan;
    if (factor < 1 && span < floor) { span = floor; }

    var want = span * factor;
    if (want < floor) { want = floor; }
    if (want > cfg.maxSpan) { want = cfg.maxSpan; }

    var a = (anchor === null || anchor === undefined || !isFinite(anchor))
      ? (lo + hi) / 2
      : Number(anchor);

    /* 锚点相对位置，**必须落在 (0,1) 开区间**：
       - t 取到 0 或 1 ⇒ 有一侧分不到空间，量程退化成零宽（ECharts min==max）；
       - 锚点落在量程**之外**（比如指针在留有留白的空白区、或 convertFromPixel
         因坐标轴未就绪而返回越界值）⇒ 若直接采用会把整个视口拖到锚点那里，
         用户会看到曲线"瞬移"。
       两种情形统一退到中心锚，量程始终有效。 */
    var t = (a - lo) / (hi - lo);
    if (!(t > 0 && t < 1)) { a = (lo + hi) / 2; t = 0.5; }

    return [a - want * t, a + want * (1 - t)];
  }

  /*
   * 把"锁定量程"与"自动量程"合成这一帧实际要用的量程。
   *
   * locked 非空 ⇒ 用锁定值，**不再跟随数据**（这正是"缩放后锁定"的语义：
   * 量程由用户定，不被新数据覆盖）。
   */
  function effectiveRange(series, win, locked) {
    if (locked && isFinite(locked[0]) && isFinite(locked[1]) && locked[1] > locked[0]) {
      return [Number(locked[0]), Number(locked[1])];
    }
    return axisRange(series, win);
  }

  /* 纵轴刻度小数位：量程被放大到很窄时必须跟着加位，否则标签全变成同一个数。
     跨度 ≥1 → 用配置值；再窄则每缩一个量级加一位，最多 6 位（浮点实用上限）。 */
  function axisDecimalsFor(range) {
    var base = CFG.skew.axisDecimals;
    var span = Math.abs(Number(range[1]) - Number(range[0]));
    if (!isFinite(span) || span <= 0) { return base; }
    var extra = 0;
    if (span < 1) { extra = Math.ceil(-Math.log(span) / Math.LN10); }
    if (extra < 0) { extra = 0; }
    if (extra > 6 - base) { extra = 6 - base; }
    return base + extra;
  }

  global.SKEW = {
    NAME_POS: NAME_POS,
    NAME_NEG: NAME_NEG,
    labelInterval: labelInterval,
    windowOf: windowOf,
    displayName: displayName,
    splitBySign: splitBySign,
    axisRange: axisRange,
    zoomRange: zoomRange,
    effectiveRange: effectiveRange,
    axisDecimalsFor: axisDecimalsFor
  };
})(window);
