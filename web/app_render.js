/* 渲染函数集
 * ------------------------------------------------------------------
 * 从 app.js 拆分：单一职责 —— 把帧数据渲染到顶栏读数、热力图、Skew 曲线。
 * 依赖 global.SWATCH_APP（由 app.js 创建）。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var app = global.SWATCH_APP;

  /* P2: 按共享 viewport 裁剪矩阵列。zoom 为 null 时原样返回。 */
  function applyViewport(block, zoom) {
    if (!zoom || !block || !block.labels || !block.labels.length) { return block; }
    var n = block.labels.length;
    var from = zoom.start;
    var to = zoom.tail ? n - 1 : zoom.end;
    if (from < 0) { from = 0; }
    if (to >= n) { to = n - 1; }
    if (from >= to) { return block; }
    return {
      strikes: block.strikes,
      rights: block.rights,
      labels: block.labels.slice(from, to + 1),
      values: block.values.map(function(row) { return row.slice(from, to + 1); }),
      volumes: block.volumes ? block.volumes.map(function(row) { return row.slice(from, to + 1); }) : undefined,
      vmax: block.vmax
    };
  }

  /*
   * 基线矩阵 → 实际要画的矩阵。三步都是纯呈现变换，本体在 web/period.js。
   */
  function displayView(block, session) {
    if (!block) { return null; }
    var sliced = global.SWATCH_PERIOD.sliceZones(
      block, (session && session.zones) || [], global.keepIds()
    );
    if (!sliced) { return null; }
    return {
      view: global.SWATCH_PERIOD.clipTail(
        global.SWATCH_PERIOD.aggregate(sliced.block, global.groupOf(app.state.periodSeconds)),
        CFG.heatmap.maxColumns
      ),
      index: sliced.index
    };
  }

  function renderHeader(frame) {
    app.setText("ro-spot", app.num(frame.spot, CFG.decimals.spot));

    var atm = frame.atm;
    if (atm) {
      app.setText("ro-atm", (atm.atm_strike === null ? "--" : atm.atm_strike) +
        " / " + app.num(atm.atm_iv, CFG.decimals.iv));
      app.setText("ro-straddle", app.num(atm.straddle, CFG.decimals.price));
      app.setText("ro-put25", app.num(atm.put25_iv, CFG.decimals.iv));
      app.setText("ro-call25", app.num(atm.call25_iv, CFG.decimals.iv));
      app.setText("ro-fly", app.signed(atm.butterfly, CFG.decimals.skew));

      var skewValue = atm.skew_25d;
      app.setText("ro-skew", app.signed(skewValue, CFG.decimals.skew));
      if (skewValue === null || skewValue === undefined) {
        app.setClass("ro-skew", "hero flat");
      } else {
        app.setClass("ro-skew", "hero " + (skewValue > 0 ? "hot" : "cool"));
      }
    }
  }

  function renderStatus(frame) {
    var session = frame.session || {};
    var health = frame.health || {};

    var totalMin = Math.round(
      ((session.elapsed_s || 0) + (session.seconds_to_close || 0)) / 60
    );
    app.setText("st-session", (session.expiry || "--") + " · " +
      global.activeSessionLabel(session.bucket_index || 0) + " · " +
      Math.round((session.elapsed_s || 0) / 60) + "/" + totalMin + " 分");

    var sub = (health.subscribed || 0) + "/" + (health.subscription_cap || 0);
    var age = health.last_tick_age_s;
    app.setText("st-feed", sub + " 订阅 · 分片 " + (health.store_cells || 0) +
      " · " + (age === null || age === undefined ? "--" : age.toFixed(1) + "s"));

    app.setText("st-frames", "帧 #" + frame.seq + " · 丢 " + app.socket.stats.dropped +
      " · 缺口 " + app.socket.stats.gapCount);

    app.setText("st-conn", String(health.connection || "?") + " · " +
      String(health.mode || "?"));

    if (session.bucket_count) {
      var pct = Math.min((session.bucket_index + 1) / session.bucket_count, 1) * 100;
      app.el("sessionbar-fill").style.width = pct.toFixed(2) + "%";
    }

    if (health.messages && health.messages.length) {
      app.state.lastHealth = health.messages[health.messages.length - 1];
    }
    app.setText("sb-msg", app.state.lastHealth || "等待数据…");
    app.setText("sb-right", "本机 " + new Date().toLocaleTimeString() +
      " · 推送 " + (global.SWATCH_RUNTIME.pushIntervalMs || 400) + "ms");
  }

  function renderHeatmap(frame) {
    global.syncPeriods(frame.heatmap);
    global.syncSessions(frame.session);

    var display = displayView(frame.heatmap, frame.session);
    if (!display) {
      app.setText("heatmap-meta", global.currentViewLabel() + " · 该时段尚未开始");
      app.state.lastDisplay = null;
      return null;
    }

    /* P2: 缓存完整 display，供 viewport 变化回调复用 */
    app.state.lastDisplay = display;

    /* P2: 按共享 viewport 裁剪列（Skew 缩放驱动） */
    var view = app.state.viewport ? applyViewport(display.view, app.state.viewport) : display.view;

    /* 可视行半径**从帧上取**，不从 block 上取。block 到这里已经被四次逐字段
       重建过（sliceZones → aggregate → clipTail → applyViewport），挂在上面的
       新字段会在第一跳静默消失；帧对象自始至终没被重建，取它才是稳的。
       取不到时 HeatmapPanel.update() 会报错并保留上一帧（不猜值）。 */
    var visibleEach = frame.heatmap ? frame.heatmap.visible_rows_each_side : undefined;

    var info = app.heatmapPanel.update(view, frame.spot, visibleEach);
    if (info) {
      var zoomText = "";
      if (app.state.viewport) {
        var totalCols = display.view.labels.length;
        var to = app.state.viewport.tail ? totalCols - 1 : app.state.viewport.end;
        zoomText = " · 缩放 " + (app.state.viewport.start + 1) + "–" + (to + 1) + "/" + totalCols + " 列";
      }
      /* 读数写成「可见 24/40 档」而不是只写一个档数：纵轴现在是"画多、看少"，
         只写一个数就分不出窗口有没有生效 —— 而那正是这一版最容易静默失效的地方。 */
      app.setText("heatmap-meta", "可见 " + info.visible + "/" + info.rows + " 档 × " +
        info.cols + " 桶 · " + info.cells.toLocaleString() + " 格 · 色标 ±" +
        info.vmax.toFixed(2) + " · " + global.currentViewLabel() + " · " +
        global.currentPeriodLabel() + zoomText);
    }
    app.setText("heatmap-foot", movers(view));
    return display;
  }

  function movers(block) {
    if (!block || !block.values || !block.values.length) { return ""; }

    var lastCol = block.labels.length - 1;
    var rows = [];
    for (var i = 0; i < block.values.length; i++) {
      var v = block.values[i][lastCol];
      if (v === null || v === undefined) { continue; }
      rows.push({ strike: block.strikes[i], right: block.rights[i], value: v });
    }
    if (!rows.length) { return ""; }

    rows.sort(function (a, b) { return Math.abs(b.value) - Math.abs(a.value); });

    var parts = rows.slice(0, 5).map(function (r) {
      return r.strike + r.right + " " + app.signed(r.value, CFG.decimals.impulse);
    });
    return "本桶(" + global.currentPeriodLabel() + ")冲量 Top: " + parts.join("   ");
  }

  function renderSkew(frame, display) {
    var block = frame.skew;
    if (!block || !block.series) { return; }
    if (!display || !display.view || !display.view.labels) { return; }

    var aligned = global.SWATCH_PERIOD.alignSkew(
      block.series,
      global.groupOf(app.state.periodSeconds),
      {
        labels: display.view.labels,
        drop: display.view.clipped || 0,
        index: display.index
      }
    );
    if (!aligned) { return; }

    /* 缩放回调发生在两帧之间，那时 `block` 早已出栈 —— 缓存"当前值"供它复用。 */
    app.lastSkewLatest = block.latest || null;
    writeSkewMeta(app.skewPanel.update(aligned));
  }

  function writeSkewMeta(info) {
    if (!info || !app.lastSkewLatest) { return; }
    var zoom = info.view
      ? " · 缩放 " + info.view.from + "–" + info.view.to + "/" + info.view.cols + " 列"
      : "";
    app.setText("skew-meta", info.points + "/" + info.cols + " 点 · 当前 " +
      app.signed(app.lastSkewLatest.skew, CFG.decimals.skew) + " · ATM " +
      app.num(app.lastSkewLatest.atm, CFG.decimals.iv) + " · " + global.currentViewLabel() +
      " · " + global.currentPeriodLabel() + zoom);
  }

  /* 导出到 global，供 app.js 主循环调用 */
  global.renderHeader = renderHeader;
  global.renderStatus = renderStatus;
  global.renderHeatmap = renderHeatmap;
  global.renderSkew = renderSkew;
  global.writeSkewMeta = writeSkewMeta;
  global.movers = movers;
  global.applyViewport = applyViewport;
  global.displayView = displayView;
})(window);
