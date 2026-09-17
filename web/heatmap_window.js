/* 热力图「可视行窗口」
 * ------------------------------------------------------------------
 * 职责单一：从「帧下发的行序 + 现价 + 可视半径」算出**屏幕上真正显示的那几行**
 * 在帧里的下标区间。只做这一件事，不碰 ECharts，不读配置。
 *
 * 为什么要有这个文件（而不是写在 heatmap.js 里）
 * ----------------------------------------------
 * 热力图现在是「画多、看少」：帧里每行权价下发 40 行，屏幕只显示其中 24 行。
 * 这个换算是一段**有明确边界条件**的纯函数（现价在两端、链短、帧行序不对），
 * 值得单独放着、单独说清楚；heatmap.js 已经贴着 400 行的门禁，塞进去会顶破。
 *
 * 「下 / 上」的约定必须与后端同源
 * -------------------------------
 * 后端 ``features/strike_window.py::StrikeWindow.window_strikes()`` 的口径是：
 * ``下`` = 行权价 **≤ 现价**，``上`` = 行权价 **> 现价**（``otm_right()`` 同此）。
 * 本文件的 ``boundaryIndex()`` 用同一口径数「现价上方有几行」。
 *
 * 两处若错开一档，症状是**静默的**：可视窗口整体偏一行权价，图看起来完全正常，
 * 只是中心档不是现价所在的那一档。所以这里不重新发明判据，只照抄那一条。
 *
 * 帧行序（降序）是契约，不是巧合
 * ------------------------------
 * ``HeatmapEngine.build()`` 显式按行权价**降序**产出（高在前），前端纵轴
 * ``inverse: true`` 让行 0 落在屏幕最上方。本文件的下标全部按这个行序定义。
 * 行序反了（升序帧）会让可视窗口跳到错误的一端 —— 那是静默的错位，
 * 所以这里**显式检查行序**并返回 ``null`` 让调用方报错，而不是照算。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  /* 现价上方有几行。行序为降序 ⇒ 从行 0 开始数"行权价 > 现价"的连续前缀。 */
  function boundaryIndex(strikes, spot) {
    var i = 0;
    while (i < strikes.length && Number(strikes[i]) > spot) { i += 1; }
    return i;
  }

  /* 行序必须降序（行 0 的行权价最高）。只查两端：判据是"整体方向"，
     中间即使有缺口（后端对无数据的档会跳过整行）也不影响这条判断。 */
  function isDescending(strikes) {
    if (strikes.length < 2) { return true; }
    return Number(strikes[0]) > Number(strikes[strikes.length - 1]);
  }

  /*
   * 算出可视行的下标区间 ``[from, to]``。
   *
   * 参数
   * ----
   * ``strikes``   帧下发的行权价序列（降序）。
   * ``spot``      现价。必须 > 0 —— 没有现价就定位不了窗口中心。
   * ``eachSide``  可视半径（档），来自帧的 ``heatmap.visible_rows_each_side``。
   *
   * 返回 ``{from, to, count, wanted}``，或 ``null``（参数不成立 / 行序不对）。
   *
   * 边界条件（都返回一个**确定的**区间，不做静默兜底）
   * ------------------------------------------------
   * 1. ``2 × eachSide ≥ 行数``：帧本身就不够宽（会话早期链还没解析全），
   *    返回**全部行**，``count < wanted`` 让调用方能在读数里显示出来。
   * 2. 现价贴近两端时窗口会越过边界：整体平移回帧内，行数**不缩水**
   *    （宁可中心偏一点，也不要少露一行 —— 少露的那一行是静默的）。
   * 3. 现价 ≤ 0、半径 ≤ 0、行序不是降序：返回 ``null``，由调用方报错并保留
   *    上一帧。**绝不"随便给一个窗口"** —— 画错的窗口比空图更危险。
   */
  function visibleRange(strikes, spot, eachSide) {
    if (!strikes || !strikes.length) { return null; }
    if (!isDescending(strikes)) { return null; }

    var side = Math.floor(Number(eachSide));
    if (!(side > 0)) { return null; }

    var price = Number(spot);
    if (!(price > 0)) { return null; }

    var rows = strikes.length;
    var wanted = 2 * side;
    if (wanted >= rows) {
      return { from: 0, to: rows - 1, count: rows, wanted: wanted };
    }

    var from = boundaryIndex(strikes, price) - side;
    if (from < 0) { from = 0; }
    if (from + wanted > rows) { from = rows - wanted; }
    return { from: from, to: from + wanted - 1, count: wanted, wanted: wanted };
  }

  global.SWATCH_HEATMAP_WINDOW = {
    visibleRange: visibleRange,
    boundaryIndex: boundaryIndex,
    isDescending: isDescending
  };
})(window);
