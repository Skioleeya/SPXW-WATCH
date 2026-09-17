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
    /* 连接自称的状态：connecting / open / retrying / closed。
       看门狗靠它区分"连接真的断了（socket 自己在退避重连）"与
       "连接自称开着、其实早收不到数据（必须主动换掉）"—— 后者是本项目
       2026-09-17 那次 4 小时静默中断的形状。 */
    conn: "",
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
    /* 两个活体信号必须分开 —— **换连接只能修传输，修不了解码/渲染的错**。
       · 传输活体：`socket.stats.lastFrameAt`（`ws_client._accept` 里、任何解析
         之前打点）= "socket 收到了帧"。
       · 渲染活体：`state.lastFrameAt`（`render` 里、`decodeFrame` 之后打点）
         = "页面真的画出来过一帧"。
       两者都取 **`max(最后一帧, 连接建立时刻)`**：
       · 用 `||` 会让"刚换上的新连接"继承上一条连接的老时间戳 ⇒ 新连接一开就
         判定超时；若它又恰好收不到帧，就会变成重连风暴。
       · 一帧都没有时 `max` 自动退回"连接建立时刻"，否则"连上了却一直没数据"
         会被 `!since` 直接跳过 —— 那正是本项目最怕的静默故障形状。 */
    var rxAt = Math.max(socket.stats.lastFrameAt, socket.stats.connectedAt);
    /* 两个时间戳都还是 0 ⇒ 一次都没连上过，没有可用的基准，什么都别判。
       （少了这一句，"连接中"那一拍会把 `Date.now() - 0` 当成天文数字的
       超时值，于是连接中就把状态点刷成错误色。） */
    if (!rxAt) { return; }
    var rxAge = Date.now() - rxAt;

    if (rxAge > CFG.render.staleErrorMs) {
      setClass("st-dot", "dot err");
      if (state.conn === "open") {
        /* 连接自称开着、却一个帧都收不到 ⇒ 这条连接是假的，换掉它。
           只在 "open" 时动手，天然限流：动手后状态变成 connecting/retrying，
           下一秒 watchdog 不会再插一脚；换完还是静默，45 秒后才再换一次。
           ⚠️ 状态文字交给 onState，这里只负责"动手" —— 否则每秒都会把
           "重连中"改回"数据中断 Ns"。 */
        if (CFG.render.reconnectOnStale) {
          socket.forceReconnect("数据中断 " + Math.round(rxAge / 1000) + "s");
        } else {
          setText("st-conn", "数据中断 " + Math.round(rxAge / 1000) + "s");
        }
      } else if (state.conn === "closed") {
        setText("st-conn", "数据中断 " + Math.round(rxAge / 1000) + "s");
      }
      return;
    }

    /* 帧在来（传输没问题），但页面很久没画出一帧 ⇒ 渲染层坏了。
       换连接不可能修好，只能**报** —— 报出来才不会变成
       "状态写着已连接、图却冻住"的假象（`render()` 在拆分模块缺失时是
       **静默丢弃**每一帧的，原本没有任何出口）。 */
    var drawAge = Date.now() - Math.max(state.lastFrameAt,
      socket.stats.connectedAt);
    if (drawAge > CFG.render.staleErrorMs) {
      setClass("st-dot", "dot err");
      setText("st-conn", "渲染停滞 " + Math.round(drawAge / 1000) + "s");
      return;
    }

    if (rxAge > CFG.render.staleWarnMs) {
      setClass("st-dot", "dot warn");
      setText("st-conn", "数据陈旧 " + Math.round(rxAge / 1000) + "s");
    }
  }

  /* ------------------------------------------------------------------ */
  /* 连接                                                                */
  /* ------------------------------------------------------------------ */

  var socket = new global.SwatchSocket({
    path: RT.wsPath,
    onFrame: render,
    onState: function (kind, detail) {
      state.conn = kind;
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
