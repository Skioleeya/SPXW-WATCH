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

  /* Skew 的 meta 行要跟着缩放立刻收窄，而缩放不经过 `update()` —— 面板在视口
     变化后回调 `writeSkewMeta`（声明在下面，函数声明会提升）。 */
  skewPanel.setViewportHook(writeSkewMeta);

  /* 最近一帧的 `skew.latest`。缩放回调发生在两帧之间，那时帧对象早已出栈，
     所以把"当前值"这一段缓存下来供 `writeSkewMeta` 复用。 */
  var lastSkewLatest = null;

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
    periodSeconds: 0,
    /* 时段切换的状态。zones 是后端随帧下发的网格区段表（会话 + 空档），
       zoneKey 用来判断"区段表变了没" —— 变了才重建按钮，避免每帧都重建。 */
    zones: [],
    zoneKey: "",
    viewId: CFG.sessions.allId
  };

  /* ------------------------------------------------------------------ */
  /* 时段切换（GTH / RTH / 全时段）                                      */
  /* ------------------------------------------------------------------ */

  /*
   * 按钮**不写死** GTH / RTH：时段真相在后端的 config/app.json，随帧下发到
   * session.zones。前端只挑出 is_session 的那些、照 label 显示，再补一个合成的
   * "全时段"。写死一份就等于把会话定义抄了第二遍 —— 后端加一个时段（例如
   * 未来的盘后），前端不会跟着变，只会静默少一个按钮。
   *
   * 为什么要看 zoneKey：区段表在一天之内是常量，每帧重建 DOM 纯属浪费；
   * 但它确实会随会话定义变化（重启后端换了配置），所以不能只建一次。
   */
  var sessionBar = el("heatmap-sessions");

  function zoneKeyOf(zones) {
    var parts = [];
    for (var i = 0; i < zones.length; i++) {
      parts.push(zones[i].id + ":" + zones[i].first + "-" + zones[i].last);
    }
    return parts.join("|");
  }

  function sessionIds() {
    var ids = [CFG.sessions.allId];
    for (var i = 0; i < state.zones.length; i++) {
      if (state.zones[i].is_session) { ids.push(state.zones[i].id); }
    }
    return ids;
  }

  function viewLabel(id) {
    if (id === CFG.sessions.allId) { return CFG.sessions.allLabel; }
    for (var i = 0; i < state.zones.length; i++) {
      if (state.zones[i].id === id) { return state.zones[i].label || id; }
    }
    return id;
  }

  function currentViewLabel() { return viewLabel(state.viewId); }

  /* 当前**实际所在**的会话（按帧里的 bucket_index 落点），与所选视图无关。 */
  function activeSessionLabel(bucketIndex) {
    for (var i = 0; i < state.zones.length; i++) {
      var z = state.zones[i];
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
      btn.className = id === state.viewId ? "on" : "";
      btn.addEventListener("click", function () { setView(id); });
      sessionBar.appendChild(btn);
    });
  }

  function setView(id) {
    if (id === state.viewId) { return; }
    state.viewId = id;
    renderSessionButtons();
    /* 换时段同样只影响呈现：拿缓存的最新一帧立刻重画，两块图一起 ——
       时段是两块图共用的横轴范围，只重画热力图会让 skew 停在旧范围上。 */
    if (state.lastFrame) {
      renderSkew(state.lastFrame, renderHeatmap(state.lastFrame));
    }
  }

  function syncSessions(session) {
    var zones = (session && session.zones) || [];
    var key = zoneKeyOf(zones);
    if (key === state.zoneKey) { return; }
    state.zoneKey = key;
    state.zones = zones;

    var available = state.viewId === CFG.sessions.allId;
    for (var i = 0; i < zones.length; i++) {
      if (zones[i].is_session && zones[i].id === state.viewId) { available = true; }
    }
    if (!available) { state.viewId = CFG.sessions.allId; }
    renderSessionButtons();
  }

  /*
   * 所选时段覆盖的区段 id。
   *
   * "全时段" = 所有**真实会话**，空档不选 —— 于是 GTH 收盘 09:25 到 RTH 开盘
   * 09:30 那几列被整段切掉（见 period.js::sliceZones），两块图的横轴上 GTH 段
   * 与 RTH 段直接相邻。这就是"把 5 分钟空档隐藏"的落点：不是把列涂白，是
   * 那几列根本不存在。
   */
  function keepIds() {
    var out = [];
    for (var i = 0; i < state.zones.length; i++) {
      var z = state.zones[i];
      if (!z.is_session) { continue; }
      if (state.viewId === CFG.sessions.allId || z.id === state.viewId) {
        out.push(z.id);
      }
    }
    return out;
  }

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
   * 基线矩阵 → 实际要画的矩阵。三步都是纯呈现变换，本体在 web/period.js：
   *   1. sliceZones —— 只留所选时段覆盖的列（空档整段切掉）；
   *   2. aggregate  —— 按选中周期把基线桶并组（ΔIV 相加）；
   *   3. clipTail   —— 从尾部截到 maxColumns 列。
   *
   * **顺序是契约**：必须先切列再并组。反过来的话，一个组会横跨 09:25–09:30
   * 那段空档，把两个会话的桶并进同一列，还会让组边界与区段边界错开。
   *
   * 返回 ``{view, index}``：index 是"基线列 → 切后列"的映射，Skew 折线要用
   * 同一份（见 period.js::alignSkew）。两块图各推一遍就是两份网格几何。
   */
  function displayView(block, session) {
    if (!block) { return null; }
    var sliced = global.SWATCH_PERIOD.sliceZones(
      block, (session && session.zones) || [], keepIds()
    );
    if (!sliced) { return null; }
    return {
      view: global.SWATCH_PERIOD.clipTail(
        global.SWATCH_PERIOD.aggregate(sliced.block, groupOf(state.periodSeconds)),
        CFG.heatmap.maxColumns
      ),
      index: sliced.index
    };
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
       那是基线桶的**个数**（30 秒粒度下是整个交易日网格的 2370），当分钟数用
       会显示成 "1185/2370 分"。同理，下面进度条用 bucket_index/bucket_count
       是对的（那是个比例）。elapsed 是**整个网格**（GTH 开盘起算）的进度，
       不是某一个会话的进度 —— 当前落在哪个会话由 bucket_index 落点判出来。 */
    var totalMin = Math.round(
      ((session.elapsed_s || 0) + (session.seconds_to_close || 0)) / 60
    );
    setText("st-session", (session.expiry || "--") + " · " +
      activeSessionLabel(session.bucket_index || 0) + " · " +
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
   * 返回 ``{view, index}``，供 Skew 折线复用它的列网格（`labels` 与 `clipped`）
   * 与"基线列 → 列号"映射。两块图必须画在同一条时间轴上，列网格只能有一份
   * 来源 —— 让热力图算完传给 skew，而不是两边各算一次（各算一次就等于把
   * 分组与切列规则抄了两遍）。无矩阵可画时返回 null，调用方据此保留上一帧。
   */
  function renderHeatmap(frame) {
    syncPeriods(frame.heatmap);
    syncSessions(frame.session);

    var display = displayView(frame.heatmap, frame.session);
    if (!display) {
      /* 所选时段一列都还没有（例如 GTH 时段里切到 RTH）。这里刻意不画一张
         空网格：帧里只带"到今天此刻为止"的标签，未来时段的时刻标签前端根本
         没有 —— 自己推一份就是把网格几何抄第二遍。说清楚比画一张假的强。 */
      setText("heatmap-meta", currentViewLabel() + " · 该时段尚未开始");
      return null;
    }

    var info = heatmapPanel.update(display.view, frame.spot);
    if (info) {
      setText("heatmap-meta", info.rows + " 档 × " + info.cols + " 桶 · " +
        info.cells.toLocaleString() + " 格 · 色标 ±" + info.vmax.toFixed(2) +
        " · " + currentViewLabel() + " · " + currentPeriodLabel());
    }
    setText("heatmap-foot", movers(display.view));
    return display;
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
   * 对齐必须用**热力图这一帧实际显示的那套列**（含时段切列与尾部截断），
   * 否则两块图的横坐标指向不同时刻。热力图本帧没有矩阵时没有可用网格，
   * 此时整体不更新 —— 拿上一帧的网格去配这一帧的数据，会画出时间错位而
   * 不报任何错。
   */
  function renderSkew(frame, display) {
    var block = frame.skew;
    if (!block || !block.series) { return; }
    if (!display || !display.view || !display.view.labels) { return; }

    var aligned = global.SWATCH_PERIOD.alignSkew(
      block.series,
      groupOf(state.periodSeconds),
      {
        labels: display.view.labels,
        drop: display.view.clipped || 0,
        index: display.index
      }
    );
    if (!aligned) { return; }

    /* 缩放回调发生在两帧之间，那时 `block` 早已出栈 —— 缓存"当前值"供它复用。 */
    lastSkewLatest = block.latest || null;
    writeSkewMeta(skewPanel.update(aligned));
  }

  /*
   * 写 Skew 的 meta 行。放在这里而不是面板里，是因为它要拼接"当前值 / 时段 /
   * 周期"这些面板之外的状态。
   *
   * `info.points` / `info.cols` 都按**当前可见列**算（面板口径），所以缩放后
   * 这两个数跟着收窄；`info.view.cols` 是**总列数**（"缩放 a–b/N 列"的分母）。
   *
   * 两条路径都调它：每帧的 `renderSkew`，以及缩放时面板的回调 —— 缩放不经过
   * `update()`，少了回调读数就会停在上一帧的全量数字。
   */
  function writeSkewMeta(info) {
    if (!info || !lastSkewLatest) { return; }
    /* 没缩放时不写"缩放 1–N/N"这一段，免得标题里常驻一个没有信息量的读数。 */
    var zoom = info.view
      ? " · 缩放 " + info.view.from + "–" + info.view.to + "/" + info.view.cols + " 列"
      : "";
    setText("skew-meta", info.points + "/" + info.cols + " 点 · 当前 " +
      signed(lastSkewLatest.skew, CFG.decimals.skew) + " · ATM " +
      num(lastSkewLatest.atm, CFG.decimals.iv) + " · " + currentViewLabel() +
      " · " + currentPeriodLabel() + zoom);
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
