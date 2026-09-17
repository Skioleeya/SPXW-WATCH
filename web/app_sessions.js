/* 时段切换（GTH / RTH / 全时段）
 * ------------------------------------------------------------------
 * 从 app.js 拆分：单一职责 —— 会话区段按钮的生成与状态同步。
 * 依赖 global.SWATCH_APP.state（由 app.js 创建）。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var app = global.SWATCH_APP;
  var sessionBar = document.getElementById("heatmap-sessions");

  function zoneKeyOf(zones) {
    var parts = [];
    for (var i = 0; i < zones.length; i++) {
      parts.push(zones[i].id + ":" + zones[i].first + "-" + zones[i].last);
    }
    return parts.join("|");
  }

  function sessionIds() {
    var ids = [CFG.sessions.allId];
    for (var i = 0; i < app.state.zones.length; i++) {
      if (app.state.zones[i].is_session) { ids.push(app.state.zones[i].id); }
    }
    return ids;
  }

  function viewLabel(id) {
    if (id === CFG.sessions.allId) { return CFG.sessions.allLabel; }
    for (var i = 0; i < app.state.zones.length; i++) {
      if (app.state.zones[i].id === id) { return app.state.zones[i].label || id; }
    }
    return id;
  }

  function currentViewLabel() { return viewLabel(app.state.viewId); }

  /* 当前**实际所在**的会话（按帧里的 bucket_index 落点），与所选视图无关。 */
  function activeSessionLabel(bucketIndex) {
    for (var i = 0; i < app.state.zones.length; i++) {
      var z = app.state.zones[i];
      if (bucketIndex >= z.first && bucketIndex <= z.last) {
        return z.is_session ? (z.label || z.id) : "空档";
      }
    }
    return "--";
  }

  function renderSessionButtons() {
    if (!sessionBar) { return; }
    sessionBar.innerHTML = "";
    sessionIds().forEach(function (id) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = viewLabel(id);
      btn.className = id === app.state.viewId ? "on" : "";
      btn.addEventListener("click", function () { setView(id); });
      sessionBar.appendChild(btn);
    });
  }

  function setView(id) {
    if (id === app.state.viewId) { return; }
    app.state.viewId = id;
    /* 时段切换后列数骤变，旧窗口必然越界 —— 复位热力图自己的横轴缩放。
       窗口归**面板**持有（`heatmap.js::_xWin`），所以复位要问面板。 */
    app.heatmapPanel.resetXZoom();
    /* 同上：Skew 的时间窗也是列下标，换时段后必须复位。两者各自复位，
       不是联动 —— 谁都不去改对方的窗口。 */
    app.skewPanel.resetZoom();
    renderSessionButtons();
    if (app.state.lastFrame) {
      global.renderSkew(app.state.lastFrame, global.renderHeatmap(app.state.lastFrame));
    }
  }

  function syncSessions(session) {
    var zones = (session && session.zones) || [];
    var key = zoneKeyOf(zones);
    if (key === app.state.zoneKey) { return; }
    app.state.zoneKey = key;
    app.state.zones = zones;

    var available = app.state.viewId === CFG.sessions.allId;
    for (var i = 0; i < zones.length; i++) {
      if (zones[i].is_session && zones[i].id === app.state.viewId) { available = true; }
    }
    if (!available) { app.state.viewId = CFG.sessions.allId; }
    renderSessionButtons();
  }

  /*
   * 所选时段覆盖的区段 id。
   */
  function keepIds() {
    var out = [];
    for (var i = 0; i < app.state.zones.length; i++) {
      var z = app.state.zones[i];
      if (!z.is_session) { continue; }
      if (app.state.viewId === CFG.sessions.allId || z.id === app.state.viewId) {
        out.push(z.id);
      }
    }
    return out;
  }

  /* 导出到 global，供 app.js / app_render.js 调用 */
  global.syncSessions = syncSessions;
  global.setView = setView;
  global.activeSessionLabel = activeSessionLabel;
  global.currentViewLabel = currentViewLabel;
  global.keepIds = keepIds;
})(window);
