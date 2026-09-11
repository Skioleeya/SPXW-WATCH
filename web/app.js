/* 应用引导与渲染
 * ------------------------------------------------------------------
 * 职责：把 WebSocket 收到的帧分发到顶栏读数、热力图、Skew 曲线，并维护
 * 连接状态指示与陈旧数据告警。
 *
 * 陈旧判定用【本地收帧时刻】而不是帧里的时间戳 —— 帧时间戳走的是市场时钟，
 * 离线模拟模式下它被加速了 60 倍，拿它和 Date.now() 比会立刻误报。
 * 用本地收帧间隔判断"后端还在不在推"，与数据源模式无关。
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

  var state = {
    frames: 0,
    lastFrame: null,
    lastFrameAt: 0,
    lastHealth: "",
    startedAt: Date.now()
  };

  /* ------------------------------------------------------------------ */
  /* 渲染                                                                */
  /* ------------------------------------------------------------------ */

  function renderHeader(frame) {
    setText("ro-spot", num(frame.spot, CFG.decimals.spot));

    var atm = frame.atm;
    if (atm) {
      setText("ro-atm", (atm.atm_strike === null ? "--" : atm.atm_strike) +
        " / " + num(atm.atm_iv, CFG.decimals.iv));
      setText("ro-straddle", num(atm.straddle, CFG.decimals.price));
      setText("ro-put25", num(atm.put25_iv, CFG.decimals.iv));
      setText("ro-call25", num(atm.call25_iv, CFG.decimals.iv));
      setText("ro-fly", signed(atm.butterfly, CFG.decimals.skew));

      var skewValue = atm.skew_25d;
      setText("ro-skew", signed(skewValue, CFG.decimals.skew));
      if (skewValue === null || skewValue === undefined) {
        setClass("ro-skew", "hero flat");
      } else {
        setClass("ro-skew", "hero " + (skewValue > 0 ? "hot" : "cool"));
      }
    }
  }

  function renderStatus(frame) {
    var session = frame.session || {};
    var health = frame.health || {};

    setText("st-session", (session.expiry || "--") + " · " +
      Math.round((session.elapsed_s || 0) / 60) + "/" +
      Math.round((session.bucket_count || 0)) + " 分");

    var sub = (health.subscribed || 0) + "/" + (health.subscription_cap || 0);
    var age = health.last_tick_age_s;
    setText("st-feed", sub + " 订阅 · 分片 " + (health.store_cells || 0) +
      " · " + (age === null || age === undefined ? "--" : age.toFixed(1) + "s"));

    setText("st-frames", "帧 #" + frame.seq + " · 丢 " + socket.stats.dropped +
      " · 缺口 " + socket.stats.gapCount);

    setText("st-conn", String(health.connection || "?") + " · " +
      String(health.mode || "?"));

    if (session.bucket_count) {
      var pct = Math.min((session.bucket_index + 1) / session.bucket_count, 1) * 100;
      el("sessionbar-fill").style.width = pct.toFixed(2) + "%";
    }

    if (health.messages && health.messages.length) {
      state.lastHealth = health.messages[health.messages.length - 1];
    }
    setText("sb-msg", state.lastHealth || "等待数据…");
    setText("sb-right", "本机 " + new Date().toLocaleTimeString() +
      " · 推送 " + RT.pushIntervalMs + "ms");
  }

  function renderHeatmap(frame) {
    var info = heatmapPanel.update(frame.heatmap, frame.spot);
    if (info) {
      setText("heatmap-meta", info.rows + " 档 × " + info.cols + " 桶 · " +
        info.cells.toLocaleString() + " 格 · 色标 ±" + info.vmax.toFixed(2));
    }
    setText("heatmap-foot", movers(frame));
  }

  /* 取最新一列里绝对变动最大的几档，作为"雷达"读数 */
  function movers(frame) {
    var block = frame.heatmap;
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
      return r.strike + r.right + " " + signed(r.value, CFG.decimals.impulse);
    });
    return "本桶冲量 Top: " + parts.join("   ");
  }

  function renderSkew(frame) {
    var block = frame.skew;
    var info = skewPanel.update(block);
    if (info && block.latest) {
      setText("skew-meta", info.points + " 点 · 当前 " +
        signed(block.latest.skew, CFG.decimals.skew) + " · ATM " +
        num(block.latest.atm, CFG.decimals.iv));
    }
  }

  function render(frame) {
    state.frames += 1;
    state.lastFrame = frame;
    state.lastFrameAt = Date.now();

    renderHeader(frame);
    renderStatus(frame);
    renderHeatmap(frame);
    renderSkew(frame);

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

  global.addEventListener("resize", function () {
    heatmapPanel.resize();
    skewPanel.resize();
  });

  setInterval(watchdog, 1000);
  socket.connect();
})(window);
