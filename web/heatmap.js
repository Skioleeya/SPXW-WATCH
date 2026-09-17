/* 日内 IV 冲量热力图 —— 面板生命周期
 * ------------------------------------------------------------------
 * 职责单一：持有面板状态（当前块 / 现价 / 可视行窗口）、校验进来的帧块、
 * 调用 option 构建器重画。**option 长什么样不在这里** ——
 * 在 web/heatmap_option.js（2026-09-17 拆出，原因见该文件头）。
 *
 * 渲染器为什么是 ECharts 而不是自写 WebGL
 * --------------------------------------
 * 2026-09-14：渲染器由原生 WebGL（gl_heatmap.js）换回 ECharts。
 * 自写 GL 引擎连续产出四个只有真打开页面才看得见的缺陷：行序镜像、格子边框
 * 丢失、调色板纹理被绑错单元（换任何色都不生效）、高 dpi 下网格阈值漂移。
 * ECharts 的坐标轴 / 色标 / 提示框都是被验证过的实现，且 Skew 面板本就在用
 * 同一个库 —— 换回来同时消掉"两套渲染栈"这件事。
 *
 * 代价（实测，必须记住）
 * ----------------------
 * headless Chrome 153 + SwiftShader，1400×520 画布、24 行、27% 填充：
 *   cols=630   ECharts 重绘 65.7ms   vs WebGL 0.6ms
 *   cols=1352  ECharts 重绘 159.9ms  vs WebGL 1.0ms
 *   cols=2370  ECharts 重绘 188.1ms  vs WebGL 1.3ms
 * 帧到达节拍由 web/ws_client.js 合并到 400ms（后端推送间隔）⇒ 宽档位下本面板
 * 会持续占用 40–47% 单核。这是**已知且被接受**的取舍，不是回归。
 * 另：`progressive` 在此形状下是负优化（2370 列 424ms），故恒为 0。
 * ⚠️ 「画 40 露 24」之后 series 里的矩形多了 16 行（约 +67%）。**已按新形状重测**
 * （2026-09-17 03:5x 真机，1680×1000 视口、纵轴 **40 行**、每帧 1554–1581 点、
 * 周期 1 分 ⇒ 446 桶；探针 `tmp/_probe_render_perf.js` 包 `setOption` 计时、40 帧）：
 *
 *   setOption  min 21.8ms | p50 27.4ms | p90 35.3ms | max 44.6ms | avg 28.2ms
 *
 * ⇒ 最大 44.6ms **远低于 400ms 推送间隔**，不会积压。数字比上面那组小得多，
 *   但**不是同一口径**：上面是 headless Chrome 153 + SwiftShader 且按列数分档、
 *   含 WebGL 对照；这次是 Playwright Chromium 真机视口、单一周期、只计时
 *   `setOption` 本身（不含浏览器合成/绘制）。**两组不可直接比较。**
 *
 * * 纵轴的两个半径（画多、看少）
 * ----------------------------
 * 帧里下发 ``2 × heatmap_draw_rows_each_side`` 行（当前 40），屏幕只显示
 * ``2 × heatmap_visible_rows_each_side`` 行（当前 24）。可视窗口的下标区间
 * 由 web/heatmap_window.js 算，可视半径**从帧里读**（``update()`` 的第三个
 * 参数）—— 为什么不让 block 自己带，见 update() 的注释。
 * ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  /* 面板                                                                */
  /* ------------------------------------------------------------------ */

  function HeatmapPanel(el) {
    this._el = el;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._window = null;
    this._block = null;
    this._spot = 0;
    this._chart = global.echarts.init(el, null, { renderer: "canvas" });
  }

  HeatmapPanel.prototype._render = function () {
    var block = this._block;
    if (!block || !this._window) { return; }
    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    this._chart.setOption(
      global.SWATCH_HEATMAP_OPTION.build(
        this, block, this._spot, vmax, this._window
      ),
      true
    );
  };

  HeatmapPanel.prototype.resize = function () {
    this._chart.resize();
    /* 网格线步长按画布像素算，尺寸变了要重画。 */
    this._render();
  };

  /*
   * 公共接口。``update(block, spot, visibleRowsEachSide)``
   *
   * 第三个参数为什么**显式传入**、而不是让 block 自己带
   * ------------------------------------------------------
   * 它是**可视半径**（来自帧的 ``heatmap.visible_rows_each_side``）。
   * 帧里的 block 在到达本面板之前要经过四次**逐字段重建**
   * （``period_align.js::sliceZones`` → ``period.js::aggregate`` →
   * ``period.js::clipTail`` → ``app_render.js::applyViewport``），每一处都只
   * 复制它认识的字段 —— 挂在 block 上的新字段会在第一跳就**静默消失**，
   * 症状是"窗口不生效，画满 40 行"，而且不报任何错。
   * 由调用方从**帧**上取一次再传进来，就没有"被哪一跳吃掉"这个问题。
   *
   * 返回值里同时给 ``rows``（帧里几行）与 ``visible``（屏幕显示几行）——
   * 顶栏读数要能看出这两者的差别，否则"窗口没生效"只能靠肉眼数格子。
   */
  HeatmapPanel.prototype.update = function (block, spot, visibleRowsEachSide) {
    if (!block || !block.values) { return false; }

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;
    if (!rows || !cols) { return false; }

    /* 可视半径来自帧。缺了 / 不是正整数 ⇒ 报错并**保留上一帧**，不猜一个值：
       兜一个"全画"会让"配置没接线"表现成一张看起来正常的图（静默错值）。 */
    var side = Math.floor(Number(visibleRowsEachSide));
    if (!(side > 0)) {
      if (global.console && console.error) {
        console.error("[heatmap] 帧里没有可用的 heatmap.visible_rows_each_side" +
          "（拿到 " + visibleRowsEachSide + "），保留上一帧 —— " +
          "拒绝猜一个可视窗口，猜错会让纵轴窗口落到错误的位置");
      }
      return false;
    }

    var window_ = global.SWATCH_HEATMAP_WINDOW.visibleRange(strikes, spot, side);
    if (!window_) {
      if (global.console && console.error) {
        console.error("[heatmap] 算不出可视行窗口（spot=" + spot +
          " 可视半径=" + side + " 行数=" + rows + "）—— 保留上一帧");
      }
      return false;
    }

    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    var cells = 0;
    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      for (var c = 0; c < cols; c++) {
        if (row[c] !== null && row[c] !== undefined) { cells++; }
      }
    }

    this._block = block;
    this._spot = spot || 0;
    this._window = window_;
    this._rows = rows;
    this._cols = cols;
    this._cells = cells;

    this._render();
    return {
      rows: rows,
      visible: window_.count,
      from: window_.from,
      to: window_.to,
      cols: cols,
      cells: cells,
      vmax: vmax
    };
  };

  HeatmapPanel.prototype.clear = function () {
    this._block = null;
    this._spot = 0;
    this._window = null;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._chart.clear();
  };

  HeatmapPanel.prototype.stats = function () {
    return {
      rows: this._rows,
      cols: this._cols,
      visible: this._window ? this._window.count : 0
    };
  };

  global.HeatmapPanel = HeatmapPanel;

  global.HeatmapPanel = HeatmapPanel;
})(window);
