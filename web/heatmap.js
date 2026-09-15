/* 日内 IV 冲量热力图（ECharts 版）
 * ------------------------------------------------------------------
 * 2026-09-14：渲染器由原生 WebGL（gl_heatmap.js）换回 ECharts。
 *
 * 为什么换回来
 * ------------
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
 *
 * 网格线（两套，各司其职）
 * ------------------------
 * 1) **成交量 Top-N 高亮**（`config.heatmap.volumeTop`）——
 *    只给整个可视区域内成交量最大的 N 格（默认 3）描黑边，其余格子**完全不描边**。
 *    这是"标记"而不是"连续编码"：逐格按成交量变粗会让满屏都是黑边、反而看不出
 *    谁最活跃（2026-09-15 KAI 定的语义）。
 *    Top-N **内部**的粗细仍是无极的：按"本格量 / 第 N 名量"线性插值落在
 *    `[minPx, maxPx]`，所以同属 Top-N 也分得出强弱。
 *    代价可忽略：只给 N 个矩形加 itemStyle，不是给 5.7 万个各描一次边。
 * 2) **轴 splitLine 抽样网格**（`cellBorderMinPx` / `cellBorderMix`）——
 *    细档位（30 秒档 2360 列 ⇒ 格宽约 0.44px）下靠它提供间距 ≥ `cellBorderMinPx`
 *    的可读网格：
 *      stride = ceil(cellBorderMinPx / cellPx)，每 stride 个分类画一条 1px 线。
 *    `cellBorderMix` 映射为线的 opacity —— `opacity m` 的线叠在数据色上
 *    ≡ 旧 shader 的 `mix(color, border, m)`，两者数学等价。
 *
 * 为什么保留 2)：Top-N 只描 3 格，提供不了任何"格子"的观感；而"数据密集区
 * 完全看不见网格"正是 2026-09-14 修过的缺陷（见 notes/context/open_tasks.md）。
 * 两套都是深色，Top-N 的黑边画在上层，不冲突。
 * ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  /* 边距与旧 WebGL 版一致，轴标签与色标的位置不变。 */
  var PAD = { left: 66, right: 84, top: 10, bottom: 28 };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m];
    });
  }

  /* 轴标签抽稀：返回值直接喂给 ECharts 的 axisLabel.interval（0 = 全画）。 */
  function xInterval(cols) {
    var want = CFG.heatmap.xLabelCount;
    if (cols <= want) { return 0; }
    return Math.max(Math.floor(cols / want) - 1, 0);
  }

  function yInterval(rows) {
    var want = CFG.heatmap.maxYLabels;
    if (rows <= want) { return 0; }
    return Math.max(Math.floor(rows / want) - 1, 0);
  }

  function nearestIndex(values, target) {
    var best = -1, bestDist = Infinity;
    for (var i = 0; i < values.length; i++) {
      var d = Math.abs(values[i] - target);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  }

  /* 网格线抽样步长。列/行宽于 cellBorderMinPx 时 stride=1（每格一条）。 */
  function strideFor(spanPx, count) {
    var cellPx = spanPx / Math.max(count, 1);
    var minPx = CFG.heatmap.cellBorderMinPx;
    if (!(minPx > 0) || !(cellPx > 0)) { return 1; }
    return Math.max(1, Math.ceil(minPx / cellPx));
  }

  /* ------------------------------------------------------------------ */
  /* 成交量 Top-N 选中                                                   */
  /* ------------------------------------------------------------------ */

  /* 选出整个可视区域内成交量最大的 N 个格子。
     返回 { cells: {键→条目}, hi: 选中集最大成交量, lo: 选中集最小成交量 }；
     无成交量数据时返回 null。

     为什么要记 hi / lo：描边宽度在**选中集内部**按 hi→lo 线性插值，
     这样同属 Top-N 也分得出强弱（第 1 名最粗、第 N 名最细）。

     ⚠️ 不能拿"第 N 名的成交量"当分母 —— 那样选中集里每个成员的比值都 ≥ 1，
     夹取后宽度**全部相等**，Top-N 内部完全失去区分度（2026-09-15 实测抓到的错）。

     同值排序口径：成交量相同则"先列后行"（列号小者优先，同列则行号小者优先）。
     必须稳定 —— 否则每帧同值格子的相对次序会变，高亮在黑边之间跳动。 */
  function pickTopCells(volumes, rows, cols, topN) {
    if (!volumes || !(topN > 0)) { return null; }

    var list = [];
    for (var r = 0; r < rows; r++) {
      var row = volumes[r] || [];
      for (var c = 0; c < cols; c++) {
        var v = row[c];
        if (v === null || v === undefined || !(v > 0)) { continue; }
        list.push({ c: c, r: r, v: v });
      }
    }
    if (!list.length) { return null; }

    list.sort(function (a, b) {
      if (b.v !== a.v) { return b.v - a.v; }
      if (a.c !== b.c) { return a.c - b.c; }
      return a.r - b.r;
    });

    var n = Math.min(topN, list.length);
    var cells = {};
    var hi = list[0].v;
    var lo = list[n - 1].v;
    for (var i = 0; i < n; i++) { cells[list[i].c + "," + list[i].r] = list[i]; }
    return { cells: cells, hi: hi, lo: lo };
  }

  /* 每格描边宽度（CSS px）：选中集内部按 hi→lo 线性插值，非选中格返回 0。
     hi == lo（选中集成交量全等）时全部给最粗值 —— 此时本就无从区分，
     给最粗至少保证"被标记"这件事在图上看得见。 */
  function borderWidthFor(vol, hi, lo, loPx, hiPx) {
    if (!(vol > 0) || !(hi > 0)) { return 0; }
    var t = hi > lo ? (vol - lo) / (hi - lo) : 1;
    if (t > 1) { t = 1; }
    if (t < 0) { t = 0; }
    return loPx + (hiPx - loPx) * t;
  }

  /* ------------------------------------------------------------------ */
  /* Option 构建                                                         */
  /* ------------------------------------------------------------------ */

  function buildOption(panel, block, spot, vmax) {
    var strikes = block.strikes || [];
    var rights = block.rights || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;

    var rect = panel._el.getBoundingClientRect();
    var gridW = Math.max(1, rect.width - PAD.left - PAD.right);
    var gridH = Math.max(1, rect.height - PAD.top - PAD.bottom);
    var strideX = strideFor(gridW, cols);
    var strideY = strideFor(gridH, rows);
    var mix = CFG.heatmap.cellBorderMix > 0 ? CFG.heatmap.cellBorderMix : 0;
    var line = { color: CFG.theme.grid, width: 1, opacity: mix };

    /* ---- 成交量 Top-N 高亮 ----------------------------------------------
       只给**整个可视区域内成交量最大的 N 格**描黑边，其余格子完全不描边。
       这是"标记"不是"连续编码" —— 逐格按成交量变粗会让满屏都是黑边，
       反而看不出谁最活跃（2026-09-15 KAI 定的语义）。

       本图即"整个可视区域"：矩阵没有滚动条，一次画满全部行列。
       volMax 取本视口内的最大值（而非全局），与排序口径一致。 */
    var vt = CFG.heatmap.volumeTop || {};
    var vtOn = vt.enabled !== false;
    var volumes = block.volumes || null;

    /* 描边宽度区间锚在格子**短边**上：锚长边时窄行的上下边框会互相吃穿。
       配置显式给了像素值就用像素值，否则按短边的比例派生。 */
    var cellShort = Math.min(gridW / Math.max(cols, 1), gridH / Math.max(rows, 1));
    var pick = vtOn ? pickTopCells(volumes, rows, cols, vt.topN) : null;
    var vtHiPx = vt.maxPx > 0 ? vt.maxPx : cellShort * (vt.maxRatio > 0 ? vt.maxRatio : 0);
    var vtLoPx = vt.minPx > 0 ? vt.minPx : cellShort * (vt.minRatio > 0 ? vt.minRatio : 0);
    if (vtLoPx > vtHiPx) { vtLoPx = vtHiPx; }

    var data = [];
    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      for (var c = 0; c < cols; c++) {
        var v = row[c];
        if (v === null || v === undefined) { continue; }
        var hit = pick && pick.cells[c + "," + r];
        if (!hit) { data.push([c, r, v]); continue; }
        data.push({
          value: [c, r, v],
          itemStyle: {
            borderWidth: borderWidthFor(hit.v, pick.hi, pick.lo, vtLoPx, vtHiPx),
            borderColor: vt.color
          }
        });
      }
    }

    var yNames = [];
    for (var i = 0; i < rows; i++) { yNames.push(strikes[i] + (rights[i] || "")); }

    var bound = vmax > 0 ? vmax : CFG.heatmap.boundEpsilon;
    var markLine;
    if (CFG.heatmap.showSpotLine && spot > 0) {
      var idx = nearestIndex(strikes, spot);
      if (idx >= 0) {
        markLine = {
          silent: true, symbol: "none", animation: false,
          label: { show: false },
          lineStyle: { color: CFG.theme.accent, type: "dashed", width: 1 },
          data: [{ yAxis: idx }]
        };
      }
    }

    return {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: PAD.left, right: PAD.right, top: PAD.top, bottom: PAD.bottom },
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(17,21,26,.96)",
        borderColor: CFG.theme.border,
        textStyle: { color: CFG.theme.text, fontSize: 11 },
        formatter: function (p) {
          var c = p.value[0], r = p.value[1], v = p.value[2];
          var sign = v > 0 ? "+" : "";
          return escapeHtml(labels[c]) + " · " + escapeHtml(strikes[r]) +
            escapeHtml(rights[r] || "?") + "<br/>ΔIV <b>" + sign +
            Number(v).toFixed(CFG.decimals.impulse) + "</b> 波动率点";
        }
      },
      /* 色标：连续 visualMap，量程 [-vmax, +vmax] 与后端下发一致。
         15 色 = config.heatmap.palette（逐色抄自参考项目的 Plotly Turbo）。 */
      visualMap: {
        type: "continuous",
        show: true,
        min: -bound, max: bound,
        calculable: false,
        orient: "vertical",
        right: 14, top: "center",
        itemWidth: 11, itemHeight: 150,
        precision: 2,
        text: ["IV 上行 +" + bound.toFixed(2), "IV 下行 -" + bound.toFixed(2)],
        textStyle: { color: CFG.theme.textDim, fontSize: 9.5 },
        inRange: { color: CFG.heatmap.palette }
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: true,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        splitLine: { show: mix > 0, interval: strideX - 1, lineStyle: line },
        axisLabel: {
          color: CFG.theme.textFaint,
          fontSize: 10,
          interval: xInterval(cols),
          hideOverlap: true
        }
      },
      yAxis: {
        type: "category",
        data: yNames,
        boundaryGap: true,
        /* 索引 0 = 最高行权价，必须落在屏幕最上方（帧行序即降序行权价）。 */
        inverse: true,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        splitLine: { show: mix > 0, interval: strideY - 1, lineStyle: line },
        axisLabel: {
          color: CFG.theme.textDim,
          fontSize: 10,
          interval: yInterval(rows),
          hideOverlap: true
        }
      },
      series: [{
        type: "heatmap",
        data: data,
        /* 此形状下 progressive 更慢（见文件头实测），恒关。 */
        progressive: 0,
        animation: false,
        /* 默认无边框。带成交量的格子由 data item 自己的 itemStyle 逐格覆盖
           （series 级与 data 级是**合并**关系，data 级优先）。 */
        itemStyle: { borderWidth: 0 },
        markLine: markLine
      }]
    };
  }

  /* ------------------------------------------------------------------ */
  /* 面板                                                                */
  /* ------------------------------------------------------------------ */

  function HeatmapPanel(el) {
    this._el = el;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._block = null;
    this._spot = 0;
    this._chart = global.echarts.init(el, null, { renderer: "canvas" });
  }

  HeatmapPanel.prototype._render = function () {
    var block = this._block;
    if (!block) { return; }
    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    this._chart.setOption(buildOption(this, block, this._spot, vmax), true);
  };

  HeatmapPanel.prototype.resize = function () {
    this._chart.resize();
    /* 网格线步长按画布像素算，尺寸变了要重画。 */
    this._render();
  };

  /* 公共接口与旧 WebGL 版完全一致，app.js / app_render.js 无需改动。 */
  HeatmapPanel.prototype.update = function (block, spot) {
    if (!block || !block.values) { return false; }

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;
    if (!rows || !cols) { return false; }

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
    this._rows = rows;
    this._cols = cols;
    this._cells = cells;

    this._render();
    return { rows: rows, cols: cols, cells: cells, vmax: vmax };
  };

  HeatmapPanel.prototype.clear = function () {
    this._block = null;
    this._spot = 0;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._chart.clear();
  };

  HeatmapPanel.prototype.stats = function () {
    return { rows: this._rows, cols: this._cols };
  };

  global.HeatmapPanel = HeatmapPanel;
})(window);
