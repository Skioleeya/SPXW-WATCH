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
    viewId: CFG.sessions.allId,
    viewport: null,
    lastDisplay: null
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

  /* Skew 的 meta 行要跟着缩放立刻收窄 */
  skewPanel.setViewportHook(function(info) {
    if (global.writeSkewMeta) { global.writeSkewMeta(info); }
  });

  /* P2: Skew 缩放时同步到共享 viewportState，驱动热力图裁剪。 */
  skewPanel.setViewportChangeHook(function(zoom) {
    state.viewport = zoom || null;
    if (state.lastDisplay && state.lastDisplay.view && global.renderHeatmap) {
      global.renderHeatmap(state.lastFrame || {});
    }
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
