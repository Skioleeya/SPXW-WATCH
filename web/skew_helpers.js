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

  global.SKEW = {
    NAME_POS: NAME_POS,
    NAME_NEG: NAME_NEG,
    labelInterval: labelInterval,
    windowOf: windowOf,
    displayName: displayName,
    splitBySign: splitBySign,
    axisRange: axisRange
  };
})(window);
