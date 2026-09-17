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
   * 纵轴量程：**可视窗口内**的极值 ∪ {0}，再加留白。
   *
   * ⚠️ 必须收窗口（`from` / `to` 是列下标、含两端；传 null 表示全宽）。
   * 2026-09-17 之前横轴没有可视窗口（全宽自动滚动），按全部列算是对的；
   * 时间窗一加进来就不成立了 —— 按**看不见的列**算，症状是曲线被压扁，
   * 而屏幕上找不出原因（静默错值）。这条在旧注释里就预告过，现在兑现。
   */
  function axisRange(series, from, to) {
    var values = series.skew || [];

    var lo = 0;
    var hi = 0;

    var last = values.length - 1;
    var a = (from === null || from === undefined) ? 0 : Math.max(0, Math.round(from));
    var b = (to === null || to === undefined) ? last : Math.min(last, Math.round(to));

    for (var k = a; k <= b; k++) {
      var v = values[k];
      if (v === null || v === undefined) { continue; }
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }

    var span = Math.max(hi - lo, 1);
    var pad = span * CFG.skew.padRatio;
    return [lo - pad, hi + pad];
  }

  /* ------------------------------------------------------------------ */
  /* 缩放（Y 量程）—— 纯数学，不含任何图表或 DOM 依赖                      */
  /* ------------------------------------------------------------------ */

  /*
   * 按倍率缩放一段量程。
   *
   * factor < 1 放大（量程变窄），factor > 1 缩小（量程变宽）。
   * anchor 是**保持不动的那个 Y 值**（鼠标所指处的值）；给它 null 则锚在量程中心。
   * limits 是 `{minSpan, maxSpan}` —— **必须显式传入**（调用方从配置取）。
   * 这里刻意不读配置、也不留默认值：一份常量两处写，就是两份真相，
   * 配置改了这里不改会**静默**按旧值夹取。
   *
   * 为什么要锚点：不锚的话每次缩放都从中心对称扩展，用户盯着的那段曲线会跑出视野，
   * 得反复"缩放 + 平移"来回找。锚在指针下就是"往哪儿滚就往哪儿缩"。
   *
   * 量程被 minSpan / maxSpan 夹住，并且**夹住之后再补一次锚点补偿** ——
   * 先夹后算会让锚点漂移，用户会感觉曲线在被夹住的那一刻"跳"了一下。
   */
  function zoomRange(range, factor, anchor, limits) {
    var lo = Number(range[0]);
    var hi = Number(range[1]);
    if (!isFinite(lo) || !isFinite(hi) || !(hi > lo)) { return [lo, hi]; }
    if (!(factor > 0)) { return [lo, hi]; }
    if (!limits || !(limits.minSpan > 0) || !(limits.maxSpan >= limits.minSpan)) {
      return [lo, hi];
    }

    var span = hi - lo;

    /* 输入量程本身已经窄于下限（例如上一帧被夹到刚好 minSpan，或数据极值全等）
       ⇒ 先把**基准**抬到下限再算，否则一次放大就会把量程压成 0 宽
       （span 0 会让 ECharts 的 min==max，刻度全糊成一个值）。
       这不改变"往下缩"的方向：本分支只在放大时兜底。 */
    var floor = limits.minSpan;
    if (factor < 1 && span < floor) { span = floor; }

    var want = span * factor;
    if (want < floor) { want = floor; }
    if (want > limits.maxSpan) { want = limits.maxSpan; }

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
   * 自动量程只按**可视窗口**算 —— 窗口参数一路传下去，理由见 axisRange。
   */
  function effectiveRange(series, locked, from, to) {
    if (locked && isFinite(locked[0]) && isFinite(locked[1]) && locked[1] > locked[0]) {
      return [Number(locked[0]), Number(locked[1])];
    }
    return axisRange(series, from, to);
  }

  /* ------------------------------------------------------------------ */
  /* 平移与时间窗 —— 同样是纯数学                                        */
  /* ------------------------------------------------------------------ */

  /* 整段量程平移（网格内上下拖动用）：上下各移 delta，宽度不变。 */
  function shiftRange(range, delta) {
    var lo = Number(range[0]);
    var hi = Number(range[1]);
    if (!isFinite(lo) || !isFinite(hi) || !(hi > lo) || !isFinite(delta)) {
      return [lo, hi];
    }
    return [lo + delta, hi + delta];
  }

  /*
   * 时间窗归一化：夹回 [0, lastCol]（含两端），**全宽一律返回 null**。
   *
   * 为什么全宽要归一化成 null：与热力图 `web/heatmap.js::_xWin` 同一约定 ——
   * "有没有窗口"只允许一个状态，否则"全宽"会同时存在 `null` 与 `{0, last}` 两种
   * 写法，比较窗口时就得两处都判，迟早漏一处。
   */
  function clampWindow(from, to, lastCol) {
    if (!(lastCol > 0)) { return null; }
    var lo = Math.max(0, Math.min(lastCol, Math.round(Number(from))));
    var hi = Math.max(0, Math.min(lastCol, Math.round(Number(to))));
    if (!(hi > lo)) { return null; }
    if (lo === 0 && hi === lastCol) { return null; }
    return { from: lo, to: hi };
  }

  /*
   * 时间窗缩放（列下标、含两端）。与 `zoomRange` 同一套语义，只是单位是**列**
   * 且必须落在整数下标上：
   *   factor < 1 放大（窗口变窄）、> 1 缩小；anchorCol 是保持不动的那一列；
   *   minCols / lastCol 夹取（至少留 minCols 列、至多铺满）。
   * 锚点落在窗口之外（或不是有限数）⇒ 退到窗口中心：直接采用会把整个窗口
   * 拖到锚点那里，用户看到的是"图瞬移"。
   */
  function zoomWindow(win, factor, anchorCol, minCols, lastCol) {
    if (!(lastCol > 0)) { return null; }
    var lo = Math.max(0, Math.min(lastCol, Math.round(Number(win.from))));
    var hi = Math.max(0, Math.min(lastCol, Math.round(Number(win.to))));
    if (!(hi >= lo) || !(factor > 0)) { return null; }

    var minC = minCols > 0 ? Math.round(minCols) : 1;
    var want = Math.round((hi - lo + 1) * factor);
    if (want < minC) { want = minC; }
    if (want > lastCol + 1) { want = lastCol + 1; }

    var a = isFinite(anchorCol) ? Number(anchorCol) : (lo + hi) / 2;
    var t = (a - lo) / Math.max(hi - lo, 1);
    if (!(t > 0 && t < 1)) { a = (lo + hi) / 2; t = 0.5; }

    var from = Math.round(a - want * t);
    var to = from + want - 1;
    if (from < 0) { from = 0; to = want - 1; }
    if (to > lastCol) { to = lastCol; from = Math.max(0, lastCol - want + 1); }
    return clampWindow(from, to, lastCol);
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

  /* ------------------------------------------------------------------ */
  /* 图表几何 —— 仍是无 this 的纯函数，只是入参是 chart 实例               */
  /* ------------------------------------------------------------------ */

  /* 绘图网格矩形（图表局部坐标）。取不到返回 null。 */
  function gridRect(chart) {
    var model = chart && chart.getModel && chart.getModel();
    var grid = model && model.getComponent("grid", 0);
    var cs = grid && grid.coordinateSystem;
    return (cs && cs.getRect()) || null;
  }

  /*
   * 四个手势区的矩形（图表局部坐标）：`y0` / `y1` = 左 / 右 Y 轴区，
   * `x` = 底部 X 轴区，`pan` = 网格内。
   *
   * **唯一一份边界定义** —— `regionOf()` 与可见反馈层（`web/skew_regions.js`
   * 的区域高亮框）都用它。分成两处各写一遍迟早对不上，症状是"高亮框和真能拖的
   * 地方差几像素"，而且只在边界上才看得出来。
   *
   * 区域**互不重叠**是硬要求（见 regionOf 的注释），矩形本身在边界线上相邻
   * （例如 `y0` 的右边 = `pan` 的左边），重叠只发生在"正好等于边界"的像素上，
   * 由 regionOf 的判定顺序定死，不留给调用方猜。
   */
  function regionsOf(chart) {
    var rect = gridRect(chart);
    if (!rect || !(rect.width > 0) || !(rect.height > 0)) { return null; }
    var w = (chart.getWidth && chart.getWidth()) || 0;
    var h = (chart.getHeight && chart.getHeight()) || 0;
    var x1 = rect.x + rect.width;
    var y1 = rect.y + rect.height;
    return {
      y0: { x: 0, y: rect.y, width: rect.x, height: rect.height },
      y1: { x: x1, y: rect.y, width: Math.max(0, w - x1), height: rect.height },
      pan: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      x: { x: rect.x, y: y1, width: rect.width, height: Math.max(0, h - y1) }
    };
  }

  function inRect(r, x, y) {
    return x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height;
  }

  /*
   * 指针落在哪个区：`"y0"` / `"y1"` = 左 / 右 Y 轴区，`"x"` = 底部 X 轴区，
   * `"pan"` = 网格内，`null` = 谁也不管（顶部留白、图例、以及两个角落）。
   *
   * 归属必须**唯一**：重叠区会让归属变成"看谁先判"，同一位置时灵时不灵。
   * 角落（x 与 y 都出界）刻意划给 null —— 那里既不是时间轴也不是值轴，
   * 按下不该有任何效果。
   * ⚠️ 判定顺序是契约的一部分：边界像素同时落在两个矩形里（闭区间），
   * 顺序一改，边界上的归属就变。当前顺序 = 旧实现的语义（`pan` 优先）。
   */
  function regionOf(chart, x, y) {
    var rs = regionsOf(chart);
    if (!rs) { return null; }
    if (inRect(rs.pan, x, y)) { return "pan"; }
    if (inRect(rs.y0, x, y)) { return "y0"; }
    if (inRect(rs.y1, x, y)) { return "y1"; }
    if (inRect(rs.x, x, y)) { return "x"; }
    return null;
  }

  /* 只认左键。zrender 事件带 `which`（中 / 右 = 2 / 3），取不到时回退原生
     `button`（mousedown）/ `buttons`（mousemove）—— 三个都取不到就当没按。
     放这里是因为手势层（`skew_zoom.js`）与反馈层（`skew_regions.js`）都要用，
     各写一份迟早分家（一份认右键、一份不认，症状是"某个区能用另一个区不能"）。 */
  function leftHeld(e) {
    if (Number(e.which) === 1) { return true; }
    var n = e.event;
    if (!n) { return false; }
    if (e.type === "mousedown") { return Number(n.button) === 0; }
    return Number(n.buttons) === 1;
  }

  /* 指针处的 Y 值（缩放锚点）：网格矩形内的线性换算。
     指针落在网格的上下之外（轴区比网格高）⇒ 返回 null，由 zoomRange 退到中心锚。 */
  function valueAt(range, y, rect) {
    var t = (y - rect.y) / rect.height;   /* 0 = 网格顶 = max，1 = 网格底 = min */
    if (!(t >= 0 && t <= 1)) { return null; }
    return range[1] - t * (range[1] - range[0]);
  }

  /* 给定各轴**当前屏上**的量程，直接问 ECharts。取不到（还没首次渲染）给 null。
     下标即轴号，与调用方传入的轴号一一对应。 */
  function axisExtents(chart, axes) {
    var model = chart && chart.getModel && chart.getModel();
    var out = [];
    for (var i = 0; i < axes.length; i++) {
      var comp = model && model.getComponent("yAxis", axes[i]);
      var scale = comp && comp.axis && comp.axis.scale;
      if (!scale) { out[axes[i]] = null; continue; }
      var ext = scale.getExtent();
      out[axes[i]] = (ext && isFinite(ext[0]) && isFinite(ext[1]) && ext[1] > ext[0])
        ? [Number(ext[0]), Number(ext[1])]
        : null;
    }
    return out;
  }

  /* ------------------------------------------------------------------ */
  /* 手势配置访问器 —— 仍是纯函数（只读 `global.SWATCH_CONFIG`，无状态）    */
  /* ------------------------------------------------------------------ */

  /* 缺键即抛，不兜底：给个默认值会让"配置改名 / 漏写"表现成"手势悄悄按旧值走"
     —— 图能动，只是动得不对，这是最难查的一类。
     三块配置（`drag` / `zoom` / `pan`）**各自独立**：关掉 `pan` 不影响轴区缩放，
     反之亦然。"轴区缩放与网格平移互不冲突"这条要求，机械判据就落在这里。 */
  function cfgBlock(key) {
    var c = CFG.skew && CFG.skew[key];
    if (!c) {
      throw new Error("SWATCH_CONFIG.skew." + key + " 缺失 —— 手势无配置来源，拒绝静默兜底");
    }
    return c;
  }

  function dragCfg() { return cfgBlock("drag"); }
  function zoomCfg() { return cfgBlock("zoom"); }
  function panCfg() { return cfgBlock("pan"); }

  /* 纵轴量程的缩放上下限（**波动率点**，两条轴共用一组 —— 缩放作用在**跨度**上，
     与轴的绝对水平无关；两条轴跨度实测相近，见 `config.js` 的记录）。 */
  function zoomLimits() {
    var c = zoomCfg();
    var minSpan = Number(c.minSpan);
    var maxSpan = Number(c.maxSpan);
    if (!(minSpan > 0) || !(maxSpan >= minSpan)) {
      throw new Error("SWATCH_CONFIG.skew.zoom.minSpan/maxSpan 非法");
    }
    return { minSpan: minSpan, maxSpan: maxSpan };
  }

  /* ------------------------------------------------------------------ */
  /* 状态比较 —— 纯函数，供手势层判"到底变了没有"                          */
  /* ------------------------------------------------------------------ */

  /* 量程比较容差。量程是双精度浮点，直接 `===` 会把"其实没变"判成"变了"，
     于是一次边界上的拖动被吞掉、页面反而卡住不动。 */
  var EPS = 1e-9;

  function nearRange(a, b) {
    if (!a && !b) { return true; }
    if (!a || !b) { return false; }
    return Math.abs(a[0] - b[0]) < EPS && Math.abs(a[1] - b[1]) < EPS;
  }

  function nearWindow(a, b) {
    if (!a && !b) { return true; }
    if (!a || !b) { return false; }
    return a.from === b.from && a.to === b.to;
  }

  global.SKEW = {
    NAME_POS: NAME_POS,
    NAME_NEG: NAME_NEG,
    labelInterval: labelInterval,
    displayName: displayName,
    splitBySign: splitBySign,
    axisRange: axisRange,
    zoomRange: zoomRange,
    effectiveRange: effectiveRange,
    shiftRange: shiftRange,
    clampWindow: clampWindow,
    zoomWindow: zoomWindow,
    axisDecimalsFor: axisDecimalsFor,
    gridRect: gridRect,
    regionsOf: regionsOf,
    regionOf: regionOf,
    leftHeld: leftHeld,
    valueAt: valueAt,
    axisExtents: axisExtents,
    dragCfg: dragCfg,
    zoomCfg: zoomCfg,
    panCfg: panCfg,
    zoomLimits: zoomLimits,
    nearRange: nearRange,
    nearWindow: nearWindow
  };
})(window);
