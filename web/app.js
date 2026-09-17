/* 应用引导与主循环
 * ------------------------------------------------------------------
 * 职责：创建面板、维护状态、连接 WebSocket、调度渲染。
 * 具体渲染逻辑已拆分到 app_sessions.js / app_periods.js / app_render.js。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;
  var RT = global.SWATCH_RUNTIME || { wsPath: "/ws", pushIntervalMs: 400 };

  function el(id) { return document.getElementById(id); }

  function setText(id, value) {
    var node = el(id);
    if (node && node.textContent !== value) { node.textContent = value; }
  }

  function setClass(id, cls) {
    var node = el(id);
    if (node && node.className !== cls) { node.className = cls; }
  }

  function num(value, digits) {
    if (value === null || value === undefined) { return "--"; }
    return Number(value).toFixed(digits);
  }

  function signed(value, digits) {
    if (value === null || value === undefined) { return "--"; }
    var n = Number(value);
    return (n > 0 ? "+" : "") + n.toFixed(digits);
  }

  /* ------------------------------------------------------------------ */
  /* 面板                                                                */
  /* ------------------------------------------------------------------ */

  var heatmapPanel = new global.HeatmapPanel(el("heatmap"));
  var skewPanel = new global.SkewPanel(el("skew"));

  /* ------------------------------------------------------------------ */
  /* 状态（导出供拆分模块复用）                                           */
  /* ------------------------------------------------------------------ */

  var state = {
    frames: 0,
    lastFrame: null,
    lastFrameAt: 0,
    lastHealth: "",
    startedAt: Date.now(),
    periodBase: 0,
    periods: [],
    periodSeconds: 0,
    zones: [],
    zoneKey: "",
    viewId: CFG.sessions.allId
  };

  var lastSkewLatest = null;

  /* 导出共享上下文供 app_sessions.js / app_periods.js / app_render.js */
  global.SWATCH_APP = {
    CFG: CFG,
    state: state,
    heatmapPanel: heatmapPanel,
    skewPanel: skewPanel,
    lastSkewLatest: lastSkewLatest,
    el: el,
    setText: setText,
    setClass: setClass,
    num: num,
    signed: signed,
    socket: null
  };

  /* Skew 的 meta 行要跟着缩放立刻收窄。
     ⚠️ 这里**只**管 Skew 自己的读数。2026-09-17 之前还有一个
     `setViewportChangeHook`，把 Skew 的缩放窗口写进 `state.viewport`、
     反过来裁剪热力图的列 —— KAI 裁定取消两图联动，那一整条已删除。
     现在热力图的横轴缩放是它自己的（`web/heatmap.js`），与 Skew 无关。 */
  skewPanel.setZoomHook(function(info) {
    if (global.writeSkewMeta) { global.writeSkewMeta(info); }
  });

  /* 空操作提示：全宽时横向拖是**设计上的空操作**（凭空长窗会让横轴静默停止
     跟随最新列），但屏幕上毫无反应 —— 用户只会归因为"图坏了"。
     静默无操作比报错更难查，所以它必须**响**。 */
  heatmapPanel.setNoopHook(function () {
    global.ViewChips.flash("heatmap-mode", "全宽 · 横拖无效，先用滚轮缩出时间窗");
  });
  skewPanel.setNoopHook(function () {
    global.ViewChips.flash("skew-mode", "全宽 · 横拖无效，先在底部时间轴区拖出时间窗");
  });

  /* ------------------------------------------------------------------ */
  /* 复位入口（按钮 + 快捷键）                                            */
  /* ------------------------------------------------------------------ */

  /* 复位路径此前只有"双击"，而且只写在 10.5px 的灰色提示里 ——
     误操作之后要么恰好记得双击，要么刷新页面。现在三条路并存：
     双击（原有）/ 面板头按钮 / 键盘。 */

  var RESET_KEYS = CFG.ui && CFG.ui.resetKeys;
  if (!RESET_KEYS || !RESET_KEYS.length) {
    throw new Error("SWATCH_CONFIG.ui.resetKeys 缺失 —— 复位快捷键无配置来源，拒绝静默兜底");
  }

  function syncChips() {
    if (global.syncViewChips) { global.syncViewChips(); }
  }

  /* 面板头按钮的统一接法：点一下执行动作，然后立刻刷新徽标 ——
     不依赖"下一帧到达时顺带刷新"（没有数据时下一帧可能很久不来）。 */
  function bindButton(id, fn) {
    var node = el(id);
    if (!node) { return; }
    node.addEventListener("click", function () { fn(); syncChips(); });
  }

  bindButton("heatmap-reset", function () { heatmapPanel.resetXZoom(); });
  bindButton("heatmap-latest", function () { heatmapPanel.rollToLatest(); });
  bindButton("skew-reset", function () { skewPanel.resetZoom(); });

  /* 键盘 = 两个面板一起复位。每个面板仍各自持有自己的视图状态，
     这里只是"一次清干净"，不是把两图重新联动起来（联动 2026-09-17 已取消）。 */
  global.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    if (RESET_KEYS.indexOf(e.key) < 0) { return; }
    heatmapPanel.resetXZoom();
    skewPanel.resetZoom();
    syncChips();
    e.preventDefault();
  });

  /* ------------------------------------------------------------------ */
  /* 主循环                                                              */
  /* ------------------------------------------------------------------ */

  function render(frame) {
    if (!global.renderHeader) { return; } /* 拆分模块尚未加载，静默丢弃 */
    frame = global.SWATCH_MATRIX.decodeFrame(frame);

    state.frames += 1;
    state.lastFrame = frame;
    state.lastFrameAt = Date.now();

    global.renderHeader(frame);
    global.renderStatus(frame);
    global.renderSkew(frame, global.renderHeatmap(frame));

    setClass("st-dot", "dot on");
  }

  /* ------------------------------------------------------------------ */
  /* 陈旧数据看门狗                                                      */
  /* ------------------------------------------------------------------ */

  function watchdog() {
    if (!state.lastFrameAt) { return; }
    var age = Date.now() - state.lastFrameAt;

    if (age > CFG.render.staleErrorMs) {
      setClass("st-dot", "dot err");
      setText("st-conn", "数据中断 " + Math.round(age / 1000) + "s");
    } else if (age > CFG.render.staleWarnMs) {
      setClass("st-dot", "dot warn");
      setText("st-conn", "数据陈旧 " + Math.round(age / 1000) + "s");
    }
  }

  /* ------------------------------------------------------------------ */
  /* 连接                                                                */
  /* ------------------------------------------------------------------ */

  var socket = new global.SwatchSocket({
    path: RT.wsPath,
    onFrame: render,
    onState: function (kind, detail) {
      if (kind === "open") {
        setClass("st-dot", "dot on");
        setText("st-conn", "已连接 · " + detail);
      } else if (kind === "connecting") {
        setClass("st-dot", "dot warn");
        setText("st-conn", "连接中…");
      } else if (kind === "retrying") {
        setClass("st-dot", "dot err");
        setText("st-conn", "重连中");
        setText("sb-msg", "行情通道断开：" + detail);
      } else if (kind === "closed") {
        setClass("st-dot", "dot off");
        setText("st-conn", "已关闭");
      }
    },
    onError: function (message) {
      setText("sb-msg", message);
    }
  });

  global.SWATCH_APP.socket = socket;

  global.addEventListener("resize", function () {
    heatmapPanel.resize();
    skewPanel.resize();
  });

  setInterval(watchdog, 1000);

  /* 延迟连接：等所有拆分模块加载完毕后再启动 socket，
     避免首帧到达时 render 函数尚未定义。 */
  if (document.readyState === "complete") {
    socket.connect();
  } else {
    global.addEventListener("load", function () { socket.connect(); });
  }
})(window);
