/* 日内 IV 冲量热力图 (WebGL 版)
 * ------------------------------------------------------------------
 * 底层用原生 WebGL (gl_heatmap.js) 渲染格子，上层用 HTML/CSS 覆盖轴标签
 * 与交互。接口与旧版（ECharts）保持兼容，app.js 无需改动。
 *
 * 布局（与旧版 ECharts grid 对齐）：
 *   left=66  right=84  top=10  bottom=28
 * ------------------------------------------------------------------ */
(function(global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var PAD = { left: 66, right: 84, top: 10, bottom: 28 };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(m) {
      return { "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[m];
    });
  }

  function xInterval(cols) {
    var want = CFG.heatmap.xLabelCount;
    if (cols <= want) return 0;
    return Math.max(Math.floor(cols / want) - 1, 0);
  }

  function yInterval(rows) {
    var want = CFG.heatmap.maxYLabels;
    if (rows <= want) return 0;
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

  /* ------------------------------------------------------------------ */
  /* 构造函数                                                            */
  /* ------------------------------------------------------------------ */

  function HeatmapPanel(el) {
    this._el = el;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;

    el.style.position = "relative";
    el.innerHTML = "";

    var canvas = document.createElement("canvas");
    canvas.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;";
    el.appendChild(canvas);

    var overlay = document.createElement("div");
    overlay.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;";
    el.appendChild(overlay);
    this._overlay = overlay;

    var tip = document.createElement("div");
    tip.style.cssText =
      "position:absolute;display:none;padding:6px 10px;" +
      "background:rgba(17,21,26,.96);border:1px solid " + CFG.theme.border + ";" +
      "color:" + CFG.theme.text + ";font-size:11px;z-index:10;" +
      "pointer-events:none;white-space:nowrap;line-height:1.6;";
    el.appendChild(tip);
    this._tooltip = tip;

    var spotLine = document.createElement("div");
    spotLine.style.cssText =
      "position:absolute;display:none;border-top:1px dashed " + CFG.theme.accent + ";" +
      "pointer-events:none;z-index:5;";
    el.appendChild(spotLine);
    this._spotLine = spotLine;

    /* WebGL 初始化 */
    try {
      this._gl = new global.GlHeatmap(canvas);
    } catch (err) {
      canvas.style.display = "none";
      var msg = document.createElement("div");
      msg.style.cssText = "padding:40px;text-align:center;color:" + CFG.theme.hot;
      msg.textContent = "WebGL 不可用，无法渲染热力图";
      el.appendChild(msg);
      this._gl = null;
    }

    this._block = null;
    this._spot = 0;

    this._bindEvents();
    this._onResize();
    var self = this;
    global.addEventListener("resize", function() { self._onResize(); });
  }

  /* ------------------------------------------------------------------ */
  /* 几何                                                                */
  /* ------------------------------------------------------------------ */

  HeatmapPanel.prototype._onResize = function() {
    if (!this._gl) return;
    var r = this._el.getBoundingClientRect();
    this._gl.resize(Math.floor(r.width), Math.floor(r.height));
    if (this._block) this._draw();
  };

  HeatmapPanel.prototype._gridRect = function() {
    var r = this._el.getBoundingClientRect();
    var w = r.width, h = r.height;
    return {
      x: PAD.left, y: PAD.top,
      w: Math.max(1, w - PAD.left - PAD.right),
      h: Math.max(1, h - PAD.top - PAD.bottom),
      totalW: w, totalH: h
    };
  };

  /* ------------------------------------------------------------------ */
  /* 绘制                                                                */
  /* ------------------------------------------------------------------ */

  HeatmapPanel.prototype._drawOverlay = function() {
    var block = this._block;
    if (!block) return;
    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var rows = strikes.length;
    var cols = labels.length;
    var g = this._gridRect();
    var html = "";

    /* Y 轴：行权价（左侧） */
    var yi = yInterval(rows);
    for (var i = 0; i < rows; i++) {
      if (yi > 0 && i % (yi + 1) !== 0) continue;
      var y = g.y + (i + 0.5) / rows * g.h;
      html += '<div style="position:absolute;left:8px;top:' + y.toFixed(1) +
        'px;transform:translateY(-50%);color:' + CFG.theme.textDim +
        ';font-size:10px;">' + escapeHtml(strikes[i]) + '</div>';
    }

    /* X 轴：时间标签（底部） */
    var xi = xInterval(cols);
    for (var i = 0; i < cols; i++) {
      if (xi > 0 && i % (xi + 1) !== 0) continue;
      var x = g.x + (i + 0.5) / cols * g.w;
      html += '<div style="position:absolute;left:' + x.toFixed(1) +
        'px;bottom:6px;transform:translateX(-50%);color:' + CFG.theme.textFaint +
        ';font-size:10px;">' + escapeHtml(labels[i]) + '</div>';
    }

    /* Visual map：色标条（右侧） */
    var vmW = 11, vmH = 150;
    var vmX = g.totalW - PAD.right + 30;
    var vmY = g.totalH / 2;
    var grad = "linear-gradient(to top," + CFG.heatmap.palette.join(",") + ")";
    html += '<div style="position:absolute;left:' + vmX + 'px;top:' + vmY +
      'px;transform:translateY(-50%);width:' + vmW + 'px;height:' + vmH +
      'px;border-radius:2px;background:' + grad + ';"></div>';
    /* 数值 */
    var vmax = (block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon).toFixed(2);
    html += '<div style="position:absolute;left:' + (vmX + vmW + 6) + 'px;top:' +
      (vmY - vmH / 2 - 2) + 'px;color:' + CFG.theme.textDim +
      ';font-size:9.5px;">+' + vmax + '</div>';
    html += '<div style="position:absolute;left:' + (vmX + vmW + 6) + 'px;top:' +
      (vmY + vmH / 2 - 8) + 'px;color:' + CFG.theme.textDim +
      ';font-size:9.5px;">-' + vmax + '</div>';
    /* 语义 */
    html += '<div style="position:absolute;left:' + (vmX + vmW + 6) + 'px;top:' +
      (vmY - vmH / 2 + 10) + 'px;color:' + CFG.theme.textDim +
      ';font-size:9.5px;">IV 上行</div>';
    html += '<div style="position:absolute;left:' + (vmX + vmW + 6) + 'px;top:' +
      (vmY + vmH / 2 - 22) + 'px;color:' + CFG.theme.textDim +
      ';font-size:9.5px;">IV 下行</div>';

    this._overlay.innerHTML = html;
  };

  HeatmapPanel.prototype._drawSpotLine = function() {
    var line = this._spotLine;
    if (!CFG.heatmap.showSpotLine || this._spot <= 0 || !this._block) {
      line.style.display = "none";
      return;
    }
    var strikes = this._block.strikes || [];
    var idx = nearestIndex(strikes, this._spot);
    if (idx < 0) { line.style.display = "none"; return; }
    var g = this._gridRect();
    var y = g.y + (idx + 0.5) / strikes.length * g.h;
    line.style.display = "block";
    line.style.left = g.x + "px";
    line.style.top = y.toFixed(1) + "px";
    line.style.width = g.w + "px";
  };

  HeatmapPanel.prototype._draw = function() {
    if (!this._gl) return;
    var block = this._block;
    if (!block || !block.values) return;

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;
    if (!rows || !cols) return;

    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;

    var g = this._gridRect();
    var gl = this._gl;
    gl.setGrid(
      PAD.left / g.totalW,
      1.0 - PAD.top / g.totalH,
      (PAD.left + g.w) / g.totalW,
      1.0 - (PAD.top + g.h) / g.totalH
    );
    gl.setBg(0.067, 0.078, 0.102, 1.0);
    gl.update(rows, cols, values, vmax, block.volumes);
    gl.render();

    this._drawOverlay();
    this._drawSpotLine();
  };

  /* ------------------------------------------------------------------ */
  /* 公共接口（与旧版完全兼容）                                          */
  /* ------------------------------------------------------------------ */

  HeatmapPanel.prototype.update = function(block, spot) {
    if (!block || !block.values) return false;

    var strikes = block.strikes || [];
    var labels = block.labels || [];
    var values = block.values || [];
    var rows = strikes.length;
    var cols = labels.length;
    if (!rows || !cols) return false;

    var vmax = block.vmax > 0 ? block.vmax : CFG.heatmap.boundEpsilon;
    var cells = 0;
    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      for (var c = 0; c < cols; c++) {
        if (row[c] !== null && row[c] !== undefined) cells++;
      }
    }

    this._block = block;
    this._spot = spot || 0;
    this._rows = rows;
    this._cols = cols;
    this._cells = cells;

    if (!this._gl) return false;
    this._draw();

    return { rows: rows, cols: cols, cells: cells, vmax: vmax };
  };

  HeatmapPanel.prototype.resize = function() {
    this._onResize();
  };

  HeatmapPanel.prototype.clear = function() {
    this._block = null;
    this._rows = 0;
    this._cols = 0;
    this._cells = 0;
    this._overlay.innerHTML = "";
    this._spotLine.style.display = "none";
    this._tooltip.style.display = "none";
    if (!this._gl) return;
    var g = this._gridRect();
    this._gl.setBg(0.067, 0.078, 0.102, 1.0);
    this._gl.setGrid(0, 1, 0, 0);
    this._gl.render();
  };

  HeatmapPanel.prototype.stats = function() {
    return { rows: this._rows, cols: this._cols };
  };

  /* ------------------------------------------------------------------ */
  /* 交互：Tooltip                                                       */
  /* ------------------------------------------------------------------ */

  HeatmapPanel.prototype._bindEvents = function() {
    if (!this._gl) return;
    var self = this;
    var canvas = this._gl._canvas;

    canvas.addEventListener("mousemove", function(e) {
      var block = self._block;
      if (!block) return;
      var rect = canvas.getBoundingClientRect();
      var mx = e.clientX - rect.left;
      var my = e.clientY - rect.top;
      var g = self._gridRect();

      if (mx < g.x || mx > g.x + g.w || my < g.y || my > g.y + g.h) {
        self._tooltip.style.display = "none";
        return;
      }

      var col = Math.floor((mx - g.x) / g.w * self._cols);
      var row = Math.floor((my - g.y) / g.h * self._rows);
      col = Math.max(0, Math.min(self._cols - 1, col));
      row = Math.max(0, Math.min(self._rows - 1, row));

      var strikes = block.strikes || [];
      var rights = block.rights || [];
      var labels = block.labels || [];
      var values = block.values || [];
      var v = values[row] ? values[row][col] : null;

      if (v === null || v === undefined) {
        self._tooltip.style.display = "none";
        return;
      }

      var sign = v > 0 ? "+" : "";
      var elRect = self._el.getBoundingClientRect();
      self._tooltip.innerHTML = escapeHtml(labels[col]) + " · " +
        escapeHtml(strikes[row]) + escapeHtml(rights[row] || "?") +
        "<br/>ΔIV <b>" + sign + v.toFixed(CFG.decimals.impulse) + "</b> 波动率点";
      self._tooltip.style.display = "block";
      self._tooltip.style.left = (e.clientX - elRect.left + 14) + "px";
      self._tooltip.style.top = (e.clientY - elRect.top + 10) + "px";
    });

    canvas.addEventListener("mouseleave", function() {
      self._tooltip.style.display = "none";
    });
  };

  global.HeatmapPanel = HeatmapPanel;
})(window);
