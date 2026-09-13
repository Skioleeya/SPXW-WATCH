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
    startedAt: Date.now(),
    /* 时间周期切换的状态。periodBase 是后端随帧下发的**基线桶宽**（秒）；
       它一变就说明后端换了粒度，已选周期可能已不合法，需要重建按钮并复检。 */
    periodBase: 0,
    periods: [],
    periodSeconds: 0
  };

  /* ------------------------------------------------------------------ */
  /* 时间周期切换                                                        */
  /* ------------------------------------------------------------------ */

  var periodBar = el("heatmap-periods");

  function currentPeriodLabel() {
    for (var i = 0; i < state.periods.length; i++) {
      if (state.periods[i].seconds === state.periodSeconds) {
        return state.periods[i].label;
      }
    }
    return "--";
  }

  function renderPeriodButtons() {
    if (!periodBar) { return; }
    periodBar.innerHTML = "";
    state.periods.forEach(function (p) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = p.label;
      btn.className = p.seconds === state.periodSeconds ? "on" : "";
      btn.addEventListener("click", function () { setPeriod(p.seconds); });
      periodBar.appendChild(btn);
    });
  }

  function setPeriod(seconds) {
    if (seconds === state.periodSeconds) { return; }
    state.periodSeconds = seconds;
    renderPeriodButtons();
    /* 换周期只影响呈现，不必向后端要数据：拿缓存的最新一帧立刻重画。
       否则要干等到下一次推送（最多 400ms）画面才变，点按钮像是没反应。
       **两块图都要重画** —— 周期是两块图共用的时间尺度，只重画热力图会让
       skew 停在旧粒度上，正是这次要消灭的不一致。 */
    if (state.lastFrame) {
      renderSkew(state.lastFrame, renderHeatmap(state.lastFrame));
    }
  }

  function pickDefaultPeriod() {
    var wanted = CFG.heatmap.defaultPeriodSeconds;
    for (var i = 0; i < state.periods.length; i++) {
      if (state.periods[i].seconds === wanted) { return wanted; }
    }
    return state.periods.length ? state.periods[0].seconds : 0;
  }

  /*
   * 基线桶宽一变就重建按钮，并复检当前选中周期是否还在可用列表里 ——
   * 不在就回退到默认档，而不是留着一个分组算不对的选中态。
   */
  function syncPeriods(block) {
    var base = block ? Number(block.bucket_seconds) : 0;
    if (!(base > 0) || base === state.periodBase) { return; }

    state.periodBase = base;
    state.periods = global.SWATCH_PERIOD.options(base);

    var available = false;
    for (var i = 0; i < state.periods.length; i++) {
      if (state.periods[i].seconds === state.periodSeconds) { available = true; }
    }
    if (!available) { state.periodSeconds = pickDefaultPeriod(); }
    renderPeriodButtons();
  }

  function groupOf(seconds) {
    if (!(state.periodBase > 0) || !(seconds > 0)) { return 1; }
    var g = Math.round(seconds / state.periodBase);
    return g > 0 ? g : 1;
  }

  /*
   * 基线矩阵 → 实际要画的矩阵。两步都是纯呈现变换，本体在 web/period.js：
   * 先按选中周期把基线桶并组（ΔIV 相加），再从尾部截到 maxColumns 列。
   */
  function displayBlock(block) {
    if (!block) { return block; }
    return global.SWATCH_PERIOD.clipTail(
      global.SWATCH_PERIOD.aggregate(block, groupOf(state.periodSeconds)),
      CFG.heatmap.maxColumns
    );
  }

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

    /* 会话长度必须由 elapsed + 剩余推算，**不能**用 session.bucket_count ——
       那是基线桶的**个数**（30 秒粒度下是 780），当分钟数用会显示成 "390/780 分"。
       同理，下面进度条用 bucket_index/bucket_count 是对的（那是个比例）。 */
    var totalMin = Math.round(
      ((session.elapsed_s || 0) + (session.seconds_to_close || 0)) / 60
    );
    setText("st-session", (session.expiry || "--") + " · " +
      Math.round((session.elapsed_s || 0) / 60) + "/" + totalMin + " 分");

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

  /*
   * 返回**显示矩阵**，供 Skew 折线复用它的列网格（`labels` 与 `clipped`）。
   * 两块图必须画在同一条时间轴上，列网格只能有一份来源 —— 让热力图算完
   * 传给 skew，而不是两边各算一次（各算一次就等于把分组规则抄了两遍）。
   * 无矩阵时返回 null，调用方据此保留上一帧画面。
   */
  function renderHeatmap(frame) {
    syncPeriods(frame.heatmap);

    var view = displayBlock(frame.heatmap);
    var info = heatmapPanel.update(view, frame.spot);
    if (info) {
      setText("heatmap-meta", info.rows + " 档 × " + info.cols + " 桶 · " +
        info.cells.toLocaleString() + " 格 · 色标 ±" + info.vmax.toFixed(2) +
        " · " + currentPeriodLabel());
    }
    setText("heatmap-foot", movers(view));
    return view;
  }

  /* 取最新一列里绝对变动最大的几档，作为"雷达"读数。
     传入的是**显示矩阵**，所以"本桶"就是用户当前选中周期的那一桶 ——
     换周期时这个读数会跟着变，因此把周期写进标题，免得两行读数对不上。 */
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
      return r.strike + r.right + " " + signed(r.value, CFG.decimals.impulse);
    });
    return "本桶(" + currentPeriodLabel() + ")冲量 Top: " + parts.join("   ");
  }

  /*
   * Skew 折线：先按当前周期对齐到热力图的列网格，再交给面板画。
   *
   * 对齐必须用**热力图这一帧实际显示的那套列**（含尾部截断），否则两块图的
   * 横坐标指向不同时刻。热力图本帧没有矩阵时没有可用网格，此时整体不更新 ——
   * 拿上一帧的网格去配这一帧的数据，会画出时间错位而不报任何错。
   */
  function renderSkew(frame, view) {
    var block = frame.skew;
    if (!block || !block.series) { return; }
    if (!view || !view.labels) { return; }

    var aligned = global.SWATCH_PERIOD.alignSkew(
      block.series,
      groupOf(state.periodSeconds),
      { labels: view.labels, drop: view.clipped || 0 }
    );
    if (!aligned) { return; }

    var info = skewPanel.update(aligned, block.scale_policy);
    if (info && block.latest) {
      setText("skew-meta", info.points + "/" + info.cols + " 点 · 当前 " +
        signed(block.latest.skew, CFG.decimals.skew) + " · ATM " +
        num(block.latest.atm, CFG.decimals.iv) + " · " + currentPeriodLabel());
    }
  }

  function render(frame) {
    /* 热力图数值块在线上是「位图 + 定标整数」，先还原成 block.values 再往下走。
       放在这里而不是 ws_client 里，是因为上面已经做过"只留最新一帧"的背压，
       被丢掉的帧不必白解一遍。解包是幂等的，换周期重画时不会重复劳动。 */
    frame = global.SWATCH_MATRIX.decodeFrame(frame);

    state.frames += 1;
    state.lastFrame = frame;
    state.lastFrameAt = Date.now();

    renderHeader(frame);
    renderStatus(frame);
    /* 热力图先算：它产出两块图共用的列网格，skew 需要它。 */
    renderSkew(frame, renderHeatmap(frame));

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
