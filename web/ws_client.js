/* WebSocket 客户端
 * ------------------------------------------------------------------
 * 职责单一：维持与后端的连接，把收到的帧交给回调，断线自动重连。
 *
 * 三个刻意的设计：
 *  1. WS 路径由 /health 发现，不硬编码 —— 避免与后端 config/transport.json 分叉。
 *  2. 指数退避 + 抖动：后端重启时多个标签页不会同时砸上来。
 *  3. 只保留"最新一帧"：前端渲染速度追不上推送时，丢掉中间帧而不是排队，
 *     否则画面会越来越滞后于真实行情（这正是后端 fail-closed 的对偶面）。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  function SwatchSocket(options) {
    this.onFrame = options.onFrame || function () {};
    this.onState = options.onState || function () {};
    this.onError = options.onError || function () {};

    this._path = options.path || "/ws";
    this._attempt = 0;
    this._ws = null;
    this._timer = null;
    this._closedByUser = false;

    /* 背压：只留最新帧 */
    this._pending = null;
    this._scheduled = false;
    this._self = this;

    this.stats = {
      frames: 0,
      dropped: 0,
      lastSeq: -1,
      gapCount: 0,
      lastFrameAt: 0,
      connectedAt: 0,
      forces: 0
    };
  }

  SwatchSocket.prototype.setPath = function (path) {
    if (path && path !== this._path) {
      this._path = path;
    }
  };

  SwatchSocket.prototype.connect = function () {
    this._closedByUser = false;
    this._open();
  };

  SwatchSocket.prototype.close = function () {
    this._closedByUser = true;
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    if (this._ws) {
      try { this._ws.close(); } catch (e) { /* 忽略 */ }
      this._ws = null;
    }
  };

  SwatchSocket.prototype._url = function () {
    var proto = global.location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + global.location.host + this._path;
  };

  /* 强制换一条连接。
   *
   * 为什么需要它：本 socket 的重连入口只有 `onclose`（与构造抛错），而对端
   * "不再投递、但也不断开"时 onclose 永不触发 —— 页面就永远停在旧数据上。
   * 2026-09-17 实盘事故正是这种形状：后端那条连接 100% 丢帧、挂了 4 小时，
   * 前端只是把状态文字改成"数据中断 Ns"，自己不会好，只能人工刷新。
   *
   * 做法是**先摘掉旧 socket 再重开**，不依赖旧连接的 onclose：
   *   · 四个回调先清空 —— 旧 socket 稍后自己关掉时不会触发第二次重连，
   *     否则会开出两条连接，而且 `_ws` 只指向后一条，前一条永久泄漏。
   *   · `_attempt` 复位 —— 这是一次手动介入，不该继承上一次退避的档位。
   * 只在真的持有连接时动手：`_ws` 为空说明重连本来就在进行中，
   * 再插一脚只会打断退避节奏。
   *
   * 返回是否真的换过连接（探针据此做非空转判定）。 */
  SwatchSocket.prototype.forceReconnect = function (reason) {
    if (!this._ws) { return false; }

    var old = this._ws;
    this._ws = null;
    old.onopen = null;
    old.onmessage = null;
    old.onerror = null;
    old.onclose = null;
    try { old.close(); } catch (e) { /* 忽略 */ }

    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    this._attempt = 0;
    this.stats.forces += 1;
    this.onError("连接已强制重建：" + (reason || "数据中断"));
    this._open();
    return true;
  };

  SwatchSocket.prototype._open = function () {
    var self = this;
    var url = this._url();
    var ws;

    try {
      ws = new WebSocket(url);
    } catch (e) {
      this._scheduleReconnect();
      return;
    }
    this._ws = ws;
    this.onState("connecting", url);

    ws.onopen = function () {
      self._attempt = 0;
      self.stats.connectedAt = Date.now();
      self.onState("open", url);
    };

    ws.onmessage = function (event) {
      var frame;
      try {
        frame = JSON.parse(event.data);
      } catch (e) {
        self.onError("帧解析失败: " + e.message);
        return;
      }
      self._accept(frame);
    };

    ws.onerror = function () {
      self.onError("连接异常");
    };

    ws.onclose = function () {
      self._ws = null;
      if (self._closedByUser) {
        self.onState("closed", url);
        return;
      }
      self._scheduleReconnect();
    };
  };

  SwatchSocket.prototype._accept = function (frame) {
    this.stats.frames += 1;
    this.stats.lastFrameAt = Date.now();

    /* 序号跳跃说明中间丢过帧（后端背压或网络），统计出来供健康面板显示 */
    var seq = frame.seq;
    if (typeof seq === "number") {
      if (this.stats.lastSeq >= 0 && seq > this.stats.lastSeq + 1) {
        this.stats.gapCount += 1;
      }
      this.stats.lastSeq = seq;
    }

    this._pending = frame;
    if (this._scheduled) {
      this.stats.dropped += 1;
      return;
    }
    this._scheduled = true;
    this._flushSoon();
  };

  SwatchSocket.prototype._flushSoon = function () {
    var self = this;
    var minInterval = 1000 / Math.max(CFG.render.maxFps, 1);
    var elapsed = Date.now() - (this._lastFlushAt || 0);
    var delay = Math.max(minInterval - elapsed, 0);

    setTimeout(function () {
      self._scheduled = false;
      var frame = self._pending;
      self._pending = null;
      self._lastFlushAt = Date.now();
      if (frame) {
        try {
          self.onFrame(frame);
        } catch (e) {
          self.onError("渲染回调异常: " + e.message);
          if (global.console && console.error) { console.error(e); }
        }
      }
    }, delay);
  };

  SwatchSocket.prototype._scheduleReconnect = function () {
    var self = this;
    var rc = CFG.reconnect;
    var backoff = Math.min(
      rc.initialMs * Math.pow(rc.factor, this._attempt),
      rc.maxMs
    );
    var jitter = (Math.random() * 2 - 1) * rc.jitterMs;
    var delay = Math.max(backoff + jitter, 100);

    this._attempt += 1;
    this.onState("retrying", "第 " + this._attempt + " 次重连，等待 " + Math.round(delay) + "ms");

    if (this._timer) { clearTimeout(this._timer); }
    this._timer = setTimeout(function () {
      self._timer = null;
      self._open();
    }, delay);
  };

  global.SwatchSocket = SwatchSocket;
})(window);
