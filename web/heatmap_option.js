/* 热力图的 ECharts option 构建
 * ------------------------------------------------------------------
 * 职责单一：把「矩阵块 + 现价 + 色标量程 + 可视行窗口」翻译成一个 ECharts
 * option 对象。不持有面板状态、不碰 DOM 生命周期（那是 web/heatmap.js）。
 *
 * 2026-09-17 从 heatmap.js 拆出：那边加到 444 行，顶破了「每个 .js < 400 行」
 * 的门禁（`run.py --check [1]`）。拆的判据是**职责**，不是行数：本文件全是
 * "把数据翻译成 option"的纯函数，heatmap.js 剩下的是面板生命周期。
 *
 * 网格线（两套，各司其职）
 * ------------------------
 * 1) **成交量 Top-N 高亮**（`config.heatmap.volumeTop`）——
 *    只给整个可视区域内成交量最大的 N 格（默认 3）描黑边，其余格子**完全不描边**。
 *    这是"标记"而不是"连续编码"：逐格按成交量变粗会让满屏都是黑边、反而看不出
 *    谁最活跃（2026-09-15 KAI 定的语义）。
 *    Top-N **内部**的粗细仍是无极的：按"本格量 / 选中集内极值"线性插值落在
 *    `[minPx, maxPx]`，所以同属 Top-N 也分得出强弱。
 *    代价可忽略：只给 N 个矩形加 itemStyle，不是给 5.7 万个各描一次边。
 *    ⚠️ 排序范围是**纵轴可视行窗口**，不是帧里的全部行 —— 见 pickTopCells。
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
 *
 * 「画多、看少」在这里的落点
 * --------------------------
 * series 的 data 里放**全部行**（当前 40），由 ``yAxis.min`` / ``yAxis.max``
 * 把可视区间收成 24 行。为什么不干脆只放 24 行：那样现价一动就要重建整个
 * series 数据，而"画 40"的全部意义就是让**窗口移动而不动数据**。
 * 实测口径（ECharts 5.6.0 + ``inverse: true``）见 buildOption 内的注释。
 * ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var PAD = { left: 66, right: 84, top: 10, bottom: 28 };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m];
    });
  }

  /* 轴标签抽稀：返回值直接喂给 ECharts 的 axisLabel.interval（0 = 全画）。
     ⚠️ 纵轴这里必须传**可视行数**，不是帧里的行数 —— maxYLabels 防的是
     "屏幕上的标签挤在一起"，而帧里的行有一半是裁在可视区之外的，拿它当分母
     会让标签被无谓地抽稀（40 行 ÷ 26 ⇒ 明明只显示 24 行却按 40 行抽）。 */
  function xInterval(cols) {
    var want = CFG.heatmap.xLabelCount;
    if (cols <= want) { return 0; }
    return Math.max(Math.floor(cols / want) - 1, 0);
  }

  function yInterval(visibleRows) {
    var want = CFG.heatmap.maxYLabels;
    if (visibleRows <= want) { return 0; }
    return Math.max(Math.floor(visibleRows / want) - 1, 0);
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

  /* 选出**整个可视区域**内成交量最大的 N 个格子。
     返回 { cells: {键→条目}, hi: 选中集最大成交量, lo: 选中集最小成交量 }；
     无成交量数据时返回 null。

     ⚠️ "可视区域"= 纵轴的**可视行窗口** [rowFrom, rowTo]，不是帧里的全部行。
     2026-09-17 之前两者相同（帧只有 24 行、全显示），改成"画 40 露 24"之后
     它们不再相同：若仍按全部 40 行排序，Top-N 会选中**用户看不见的行**里的格子，
     于是可视区里一个黑边都没有 —— 而"没有黑边"与"这段确实没有成交量"
     在图上无法区分（静默失效）。横向仍是全部列（横轴没有可视裁剪）。

     为什么要记 hi / lo：描边宽度在**选中集内部**按 hi→lo 线性插值，
     这样同属 Top-N 也分得出强弱（第 1 名最粗、第 N 名最细）。

     ⚠️ 不能拿"第 N 名的成交量"当分母 —— 那样选中集里每个成员的比值都 ≥ 1，
     夹取后宽度**全部相等**，Top-N 内部完全失去区分度（2026-09-15 实测抓到的错）。

     同值排序口径：成交量相同则"先列后行"（列号小者优先，同列则行号小者优先）。
     必须稳定 —— 否则每帧同值格子的相对次序会变，高亮在黑边之间跳动。 */
  function pickTopCells(volumes, rowFrom, rowTo, cols, topN) {
    if (!volumes || !(topN > 0)) { return null; }

    var list = [];
    for (var r = rowFrom; r <= rowTo; r++) {
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

  function buildOption(panel, block, spot, vmax, window_) {
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
    /* 网格线的行步长按**可视行数**算：可视区之外的行的行高不参与
       "线间距够不够"的判断（它们根本不画）。 */
    var strideY = strideFor(gridH, window_.count);
    var mix = CFG.heatmap.cellBorderMix > 0 ? CFG.heatmap.cellBorderMix : 0;
    var line = { color: CFG.theme.grid, width: 1, opacity: mix };

    /* ---- 成交量 Top-N 高亮 ----------------------------------------------
       只给**整个可视区域内成交量最大的 N 格**描黑边，其余格子完全不描边。
       这是"标记"不是"连续编码" —— 逐格按成交量变粗会让满屏都是黑边，
       反而看不出谁最活跃（2026-09-15 KAI 定的语义）。

       可视区域 = 纵轴的可视行窗口（见 web/heatmap_window.js）——
       "画 40 露 24"之后它**不再等于**帧的全部行，所以这里必须传窗口，
       不能传 0..rows-1（传错会让黑边全落在看不见的行上，见 pickTopCells）。 */
    var vt = CFG.heatmap.volumeTop || {};
    var vtOn = vt.enabled !== false;
    var volumes = block.volumes || null;

    /* 描边宽度区间锚在格子**短边**上：锚长边时窄行的上下边框会互相吃穿。
       配置显式给了像素值就用像素值，否则按短边的比例派生。 */
    var cellShort = Math.min(gridW / Math.max(cols, 1), gridH / Math.max(window_.count, 1));
    var pick = vtOn
      ? pickTopCells(volumes, window_.from, window_.to, cols, vt.topN)
      : null;
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
        /* ---- 「画多、看少」的落点 ----------------------------------------
           min / max 是**分类下标**（不是行权价），给出纵轴的可视区间：
           帧里有 40 行，这里只让 [from, to] 这 24 行落在轴上，其余 16 行
           仍在 series 数据里（所以现价移动时挪窗口即可，不必重建数据）。

           ⚠️ 实测口径（2026-09-17，页面里读到的 `echarts.version` = **5.5.1**、
           `zrender.version` = 5.6.0；**别拿 `vendor/echarts.min.js` 里的字符串判版本**，
           那个文件里 5.5.1 与 5.6.0 两个串都在）。`inverse:true` 下：
           min/max 按**数据下标**解释，与 inverse 无关 —— min=8 / max=31
           选中的就是 strikes[8..31]。用 convertToPixel 逐行验证过：
           40 行里恰好 24 行落在网格矩形内。
           备选方案 dataZoom(inside) 实测结果相同，但要多挂一个交互组件
           （还得 disabled 掉），这里选更少活动部件的那个。

           ⚠️ 绝不能只在渲染前把 40 行裁成 24 行：那样现价一动就要重建整个
           series 数据，而"画 40"的全部意义就是**让窗口移动不动数据**。 */
        min: window_.from,
        max: window_.to,
        axisLine: { lineStyle: { color: CFG.theme.border } },
        axisTick: { show: false },
        splitLine: { show: mix > 0, interval: strideY - 1, lineStyle: line },
        axisLabel: {
          color: CFG.theme.textDim,
          fontSize: 10,
          interval: yInterval(window_.count),
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

  global.SWATCH_HEATMAP_OPTION = { build: buildOption, PAD: PAD };
})(window);
