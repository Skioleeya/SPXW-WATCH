/* 渲染函数集
 * ------------------------------------------------------------------
 * 从 app.js 拆分：单一职责 —— 把帧数据渲染到顶栏读数、热力图、Skew 曲线。
 * 依赖 global.SWATCH_APP（由 app.js 创建）。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var app = global.SWATCH_APP;

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
      return null;
    }

    /* 可视行半径**从帧上取**，不从 block 上取。block 到这里已经被三次逐字段
       重建过（sliceZones → aggregate → clipTail），挂在上面的新字段会在
       第一跳静默消失；帧对象自始至终没被重建，取它才是稳的。
       取不到时 HeatmapPanel.update() 会报错并保留上一帧（不猜值）。 */
    var visibleEach = frame.heatmap ? frame.heatmap.visible_rows_each_side : undefined;

    /* 横轴缩放窗口由面板自己持有（`heatmap.js::_xWin`），这里不掺和 ——
       2026-09-17 取消两图联动后，热力图的行/列窗口都只归它自己管。 */
    var info = app.heatmapPanel.update(display.view, frame.spot, visibleEach);
    if (info) {
      /* 横轴"有没有窗口"**不写在这里** —— 它是徽标（`heatmap-mode`）的归属。
         同一件事写两处，迟早有一处忘了改，用户就得在两个地方对照着读。 */
      app.setText("heatmap-meta", "可见 " + info.visible + "/" + info.rows + " 档 × " +
        info.cols + " 桶 · " + info.cells.toLocaleString() + " 格 · 色标 ±" +
        info.vmax.toFixed(2) + " · " + global.currentViewLabel() + " · " +
        global.currentPeriodLabel());
    }
    syncViewChips();
    app.setText("heatmap-foot", movers(display.view));
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

  /*
   * 面板头徽标 + 复位按钮可用态。数据源是**面板自己的状态查询**
   * （`heatmapPanel.xZoom()` / `skewPanel.viewState()`），**不是**上面那些读数 ——
   * 读数在没有数据时会提前返回，徽标就会停在上一帧的样子
   * （"图没数据但徽标说有时间窗"，最难查的一类）。
   *
   * 为什么这些状态要从 meta 行搬出来：此前它们只是 meta 行里的一段 10.5px 灰字，
   * 与提示文字（操作说明书）位置分离、字号极小。用户离开一会儿回来，
   * 无法一眼判断图还是不是自己调过的样子。
   */
  function syncViewChips() {
    var xz = app.heatmapPanel.xZoom();
    var st = app.heatmapPanel.stats();
    var rl = app.heatmapPanel.xRoll();
    /* 窗口态与"要不要跟着最新列走"是**两件事**：前者是"变焦没变焦"，
       后者是"盯着正在发生的、还是在翻历史"。两者写进同一个徽标，
       但文案必须让人一眼分开 —— 否则"图不动了"会被读成卡死。
       自动滚动**功能被关掉**时只报窗口本身，不报"已停滚"：那是两回事，
       后者会让人以为是自己停的。 */
    var text = "跟随最新";
    var cls = "chip follow";
    if (xz) {
      /* 文案压紧：只报"状态 + 看得见的列区间"，**不报总数** ——
         总数已经在左边 meta 的「× N 桶」里，写两处是重复真相；
         而缩进后这个徽标比默认态宽约 70px，会把 meta 行挤到省略号。 */
      var span = (xz.from + 1) + "–" + (xz.to + 1);
      if (!rl.enabled) { text = "窗口 " + span; cls = "chip window"; }
      else if (rl.following) { text = "自动滚动 " + span; cls = "chip window"; }
      else { text = "已停滚 " + span; cls = "chip paused"; }
    }
    global.ViewChips.set("heatmap-mode", text, cls);
    /* 两个按钮都只在"现在点它有作用"时点亮：复位 = 视图被改过；
       回到最新 = 右缘**没**贴住最新列（判据与自动滚动开关无关 ——
       它是用户指令，关掉自动滚动之后照样该能手动追最新）。 */
    global.ViewChips.button("heatmap-reset", !!xz);
    global.ViewChips.button("heatmap-latest", !!xz && !rl.atTail);

    var s = app.skewPanel.viewState();
    global.ViewChips.set("skew-mode",
      s.windowed ? "窗口 " + (s.from + 1) + "–" + (s.to + 1) + "/" + s.cols + " 列" : "跟随最新",
      s.windowed ? "chip window" : "chip follow");
    /* 锁定徽标**带区间**：只说"锁了"看不出锁到哪，而"锁到哪"正是读图要看的东西。 */
    global.ViewChips.set("skew-lock-0", lockText("左轴锁 ", s.ranges[0], CFG.decimals.skew), "chip lock");
    global.ViewChips.set("skew-lock-1", lockText("右轴锁 ", s.ranges[1], CFG.decimals.iv), "chip lock");
    global.ViewChips.button("skew-reset", s.dirty);
  }

  function lockText(prefix, range, digits) {
    if (!range) { return ""; }
    return prefix + range[0].toFixed(digits) + "–" + range[1].toFixed(digits);
  }

  function writeSkewMeta(info) {
    syncViewChips();
    if (!info || !app.lastSkewLatest) { return; }
    /* 时间窗与纵轴锁定态**不写在这里** —— 它们各自归一个徽标
       （`skew-mode` / `skew-lock-0` / `skew-lock-1`）。同一件事写两处，
       迟早有一处忘了改。 */
    app.setText("skew-meta", info.points + "/" + info.cols + " 点 · 当前 " +
      app.signed(app.lastSkewLatest.skew, CFG.decimals.skew) + " · ATM " +
      app.num(app.lastSkewLatest.atm, CFG.decimals.iv) + " · " + global.currentViewLabel() +
      " · " + global.currentPeriodLabel());
  }

  /* 导出到 global，供 app.js 主循环调用 */
  global.renderHeader = renderHeader;
  global.renderStatus = renderStatus;
  global.renderHeatmap = renderHeatmap;
  global.renderSkew = renderSkew;
  global.writeSkewMeta = writeSkewMeta;
  global.syncViewChips = syncViewChips;
  global.movers = movers;
  global.displayView = displayView;
})(window);
