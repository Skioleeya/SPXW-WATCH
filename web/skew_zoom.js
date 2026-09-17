/* Skew 面板 —— 手势交互层与视图状态的唯一出口
 * ==================================================================
 * 职责单一：把「鼠标按下 + 拖动」翻译成**视图状态**（两条纵轴量程 + 时间窗），并作为
 * 该状态的唯一出口交给宿主重绘。不构建 option、不碰 series、不读帧数据、**不写图表**：
 * 量程与时间窗经 `yAxisPatch()` / `view()` 交给宿主，由宿主在自己的 setOption 里贴上去
 * —— 这样"锁没锁、窗口在哪"只有一个出口，不会出现"屏上已缩、下一帧又被自动量程冲掉"。
 *
 * 技术栈
 * ------
 *   纯浏览器端 ES5 脚本（`var` / 原型方法，与 `web/` 其余文件同风格），无构建步骤、
 *   无模块系统 —— 通过 `<script>` 顺序加载，只挂 `window`。唯一依赖：`echarts`
 *   （已内置 `web/vendor/echarts.min.js`）+ `global.SKEW`（纯函数与配置访问器，
 *   见 `skew_helpers.js`；本文件**不直接读配置**）。
 *   事件来自 **zrender**（`chart.getZr()`），不是原生 DOM 冒泡。
 *
 * 手势（2026-09-17 KAI 改版；**滚轮缩放整条删除**）
 * --------------------------------------------------
 *   · 左 / 右 Y 轴区上下拖 → 缩**那一侧**的纵轴（左 = 25Δ Skew，右 = IV）
 *   · 底部 X 轴区左右拖   → 缩 / 放**时间窗**
 *   · 网格内按住拖        → 自由平移（左右 = 时间窗，上下 = 两条纵轴量程一起移）
 *   · 双击                → 三条轴全部复位
 *   方向统一为「**往轴的正方向拖 = 放大**」：Y 轴区向上 = 放大，X 轴区向右 = 放大。
 *   锚点固定为**按下那一刻**指针所在的数值 / 列（锚随指针走会让内容反向跑）。
 *   步长 / 上下限 / 节流全在 `SWATCH_CONFIG.skew`（`drag` / `zoom` / `pan`）。
 *
 * 一个手势一个主人
 * ----------------
 * 归属在**按下那一刻**按位置定（`SKEW.regionOf()`，三个区域互不重叠），整段拖动
 * 不再改判。中途改判会让同一次拖动一半在缩、一半在移（用户看到"图在抖"），
 * 而且两条纵轴会只锁一半。
 * 三种收尾都会清掉拖动态：`mouseup`、指针移出图表（`globalout`）、以及**移动时
 * 左键已不在按下状态** —— 最后一条是自愈用的，少了它，一次漏掉的 mouseup
 * 会让图此后一直跟着指针乱动。
 *
 * 谁被锁：轴区拖动只锁**那一侧**；网格内上下平移锁**两条**
 * --------------------------------------------------------
 * 2026-09-17 KAI 裁定：左轴区拖只缩 25Δ Skew、右轴区拖只缩 IV。此前是"一次缩放
 * 两条轴同时进锁定态"（为了让同一屏幕高度在左右两边的含义保持一致）；改成各缩
 * 各的之后，这条一致性不再由手势保证，而是由**读数**报出来（`_readout()` 两条都报）。
 * 反之，网格内上下平移**两条一起锁**：两条轴共用同一段屏幕高度，只锁一条的话，
 * 另一条下一帧按新数据自己重算，两条曲线就会"各走各的"（同一屏高当场分家）。
 * 为什么绑在 `chart.getZr()` 上，而不是图表容器上
 * ------------------------------------------------
 * 实测（2026-09-17，Playwright + 真机 + 真帧）：把监听器挂在容器 `#skew` 上
 * **永远不触发**。zrender 在容器内部另建了一个 viewport root `<div>`，事件只到达它；
 * zrender 自己的处理会调 `stopPropagation()`（vendor 里即
 * `de = function(t){ t.preventDefault(); t.stopPropagation(); t.cancelBubble = true; }`），
 * 所以事件**根本冒泡不到容器**。证据：同一格滚轮下 `zr.on("mousewheel")` 计数 **1**、
 * 容器监听计数 **0**、document **0**。⇒ 2026-09-15 那版"绑在容器上"的纵轴缩放是
 * **从未执行过的死代码**：静态看每行都对，只有把真实事件打进去才看得见。
 * 这条是本文件存在的第一个理由。
 *
 * 时间窗为什么存**列下标**、为什么必须每帧重贴
 * ----------------------------------------------
 * 横轴每帧往尾部追加新列，**百分比**窗口会随列数漂移 —— 用户盯着的那段时间会
 * 自己跑掉。窗口因此按列下标存（`_xWin`，全宽一律归一化成 null），由宿主每帧
 * 经 `view()` 换算成百分比贴回 `dataZoom`（`web/skew_option.js::buildSkewDataZoom`）。
 * 与热力图 `web/heatmap.js::_xWin` 同一套约定 —— 两图的时间窗语义必须一致。
 * ⚠️ 列数**只减不增**地掉下去 = 别处把窗口列数当成了总列数（`skew.js::_count`）。
 * 越界处理"先夹后复位"，见 `view()`。
 *
 * 纯水平拖动**不动纵轴**
 * ----------------------
 * 网格内拖动只有在指针真的发生了**纵向位移**（`y !== y0`）时才碰纵轴。少了这条，
 * 任何一次"只想左右挪时间窗"的拖动都会顺手把两条纵轴锁死在当时的量程上 ——
 * 此后新数据不再改纵轴，看起来像"图死了"，而用户根本没做过纵向操作。
 *
 * 全宽时**水平方向拖不动**（与热力图一致）
 * ----------------------------------------
 * 全宽 = "自动跟随最新列"。若在网格内横向拖一下就能凭空长出时间窗，横轴会
 * **静默**停止跟随 —— 图上完全看不出来，用户只会觉得"图卡住了"。
 * 所以横向平移的前提是**已经有窗口**；要窗口请用底部时间轴区那个显式手势。
 * 纵向平移不受此限（全宽下也能上下挪量程）。
 * ================================================================== */

(function (global) {
  "use strict";

  var H = global.SKEW;

  /* 两条纵轴的编号。0 = 25Δ Skew（左轴），1 = IV（右轴），顺序即绘制顺序。 */
  var AXES = [0, 1];

  /* 手势配置的访问器（`dragCfg` / `zoomCfg` / `panCfg` / `zoomLimits`）、
     只认左键的判定、四个手势区的矩形 —— 都是无 this 的纯函数，
     统一放 `skew_helpers.js`（本文件只留"状态与手势"）。 */

  function SkewZoom(chart, host) {
    this._chart = chart;
    this._host = host || {};
    /* 每条轴各自锁定的量程；null = 走自动量程。下标即轴号。 */
    this._yLocked = [null, null];
    /* 时间窗（列下标、含两端）；null = 全宽。 */
    this._xWin = null;
    /* 当前列数，由宿主每帧 `setCols()` 告知 —— 不自己去问 ECharts，
       否则 `clear()` 之后两边会各说各话。 */
    this._cols = 0;
    this._drag = null;
    this._dirty = false;
    this._paintAt = 0;
    this._bound = false;
  }

  /* ------------------------------------------------------------------ */
  /* 绑定                                                                */
  /* ------------------------------------------------------------------ */

  SkewZoom.prototype.bind = function () {
    if (this._bound) { return; }
    var self = this;
    var zr = this._chart.getZr();

    /* zr 级监听：这是**唯一**能收到指针事件的位置（理由见文件头）。 */
    zr.on("mousedown", function (e) { self._down(e); });
    zr.on("mousemove", function (e) { self._move(e); });
    zr.on("mouseup", function () { self._up(); });
    zr.on("globalout", function () { self._up(); });
    zr.on("dblclick", function () { self.reset(); });

    this._bound = true;
  };

  /* 绘图网格矩形 / 区域判定 / 锚点取值 / 各轴当前量程 —— 都是无 this 的纯函数，
     统一放 `skew_helpers.js`（本文件只留"状态与手势"）。 */

  SkewZoom.prototype.setCols = function (cols) {
    var n = Math.round(Number(cols));
    this._cols = (isFinite(n) && n > 0) ? n : 0;
  };

  /* ------------------------------------------------------------------ */
  /* 拖动的三段：按下 / 移动 / 松手                                      */
  /* ------------------------------------------------------------------ */

  SkewZoom.prototype._down = function (e) {
    if (!H.leftHeld(e)) { return; }
    var x = Number(e.offsetX);
    var y = Number(e.offsetY);
    if (!isFinite(x) || !isFinite(y)) { return; }

    var region = H.regionOf(this._chart, x, y);
    if (!region) { return; }
    if (region === "pan" ? (H.panCfg().enabled === false) : (H.zoomCfg().enabled === false)) {
      return;
    }

    /* 基准量程 / 基准窗口**在按下这一刻取一次**，之后整段拖动都相对它算 ——
       逐次累加会让浮点误差一路攒起来，指针拖回原位也回不到原来的量程。 */
    this._drag = {
      mode: region,
      x0: x,
      y0: y,
      baseWin: this._xWin ? { from: this._xWin.from, to: this._xWin.to } : null,
      baseRange: H.axisExtents(this._chart, AXES)
    };
    this._dirty = false;
  };

  SkewZoom.prototype._move = function (e) {
    var d = this._drag;
    if (!d) { return; }
    if (!H.leftHeld(e)) { this._drag = null; return; }
    var x = Number(e.offsetX);
    var y = Number(e.offsetY);
    if (!isFinite(x) || !isFinite(y)) { return; }
    if (e.event && e.event.preventDefault) { e.event.preventDefault(); }

    if (d.mode === "pan") { this._pan(d, x, y); return; }
    if (d.mode === "x") { this._zoomX(d, x); return; }
    this._zoomY(d, y);
  };

  SkewZoom.prototype._up = function () {
    if (!this._drag) { return; }
    this._drag = null;
    /* 节流窗口内最后一次移动可能没落地 ⇒ 松手时补一次，保证落点精确。 */
    if (this._dirty) { this._paint(true); }
  };

  /* ------------------------------------------------------------------ */
  /* 三种手势各自要改什么                                                */
  /* ------------------------------------------------------------------ */

  /* 网格内拖动 = 自由平移：左右挪时间窗、上下挪两条纵轴的量程。 */
  SkewZoom.prototype._pan = function (d, x, y) {
    var rect = H.gridRect(this._chart);
    if (!rect || !(rect.width > 0) || !(rect.height > 0)) { return; }
    var moved = false;

    /* 全宽时**不建窗**（`d.baseWin` 为 null ⇒ 整段跳过）：与热力图同一条约定 ——
       全宽表示"自动跟随最新列"，若拖一下凭空长出窗口，横轴会**静默**停止跟随，
       而图上一丁点都看不出来。想要窗口就先在底部时间轴区拖一下（那里是显式的
       "缩时间窗"手势），之后网格内拖动才有东西可挪。 */
    if (this._cols > 1 && d.baseWin) {
      var win = d.baseWin;
      var span = win.to - win.from + 1;
      /* 内容跟着指针走：拖一个网格宽 = 挪一个窗口宽。与热力图同一口径。 */
      var dx = Math.round((d.x0 - x) * span / rect.width);
      var nextWin = H.clampWindow(win.from + dx, win.to + dx, this._cols - 1);
      if (!H.nearWindow(nextWin, this._xWin)) { this._xWin = nextWin; moved = true; }
    }

    /* 纯水平拖动**不动纵轴**。少了这一条，任何一次网格内拖动（哪怕只是左右挪时间窗）
       都会把两条纵轴顺手锁死在当时的量程上 —— 之后新数据不再改纵轴，
       看起来像"图死了"，而用户根本没做过纵向操作。 */
    if (y !== d.y0) {
      for (var i = 0; i < AXES.length; i++) {
        var axis = AXES[i];
        var base = d.baseRange[axis];
        if (!base) { continue; }
        var delta = (y - d.y0) * (base[1] - base[0]) / rect.height;
        var next = H.shiftRange(base, delta);
        if (!H.nearRange(this._yLocked[axis], next)) {
          /* 上下平移必然同时动两条轴（它们共用同一段屏幕高度）⇒ 两条一起进锁定态，
             否则未锁的那条下一帧按新数据自己重算，两条曲线就会"各走各的"。 */
          this._yLocked[axis] = next;
          moved = true;
        }
      }
    }

    if (!moved) { return; }
    this._dirty = true;
    this._paint(false);
  };

  /* 轴区上下拖动 = 缩**那一侧**的纵轴（另一侧一律不碰）。 */
  SkewZoom.prototype._zoomY = function (d, y) {
    var c = H.zoomCfg();
    var rect = H.gridRect(this._chart);
    var axis = d.mode === "y1" ? 1 : 0;
    var base = d.baseRange[axis];
    if (!base || !rect || !(rect.height > 0)) { return; }

    /* 方向：轴区**向上**拖 = 放大（往值轴正方向）。stepPx 是"每级缩放所需像素"。
       锚点取**按下那一刻**指针所在的数值（不是当前位置）—— 锚随指针走的话，
       内容会与指针反向跑（往上拖、图往下走），手感是反的。 */
    var factor = Math.pow(c.step, (y - d.y0) / c.stepPx);
    var anchor = c.anchorAtPointer === false ? null : H.valueAt(base, d.y0, rect);
    var next = H.zoomRange(base, factor, anchor, H.zoomLimits());
    if (H.nearRange(this._yLocked[axis], next)) { return; }
    this._yLocked[axis] = next;
    this._dirty = true;
    this._paint(false);
  };

  /* 横轴区左右拖动 = 缩 / 放时间窗。 */
  SkewZoom.prototype._zoomX = function (d, x) {
    var c = H.zoomCfg();
    var rect = H.gridRect(this._chart);
    if (!rect || !(rect.width > 0) || !(this._cols > 1)) { return; }

    var win = d.baseWin || { from: 0, to: this._cols - 1 };
    /* 方向：**向右**拖 = 放大（往时间轴正方向）。锚点取按下那一列，理由同 _zoomY。
       ⚠️ 锚要按**当前窗口**换算成列号，不能用全宽口径 —— 底部轴区显示的是窗口内
       那几列的标签，拿全宽口径算出来的列号可能根本不在窗口里，锚点会被 zoomWindow
       判为越界而退到中心（症状：贴着左边缘拖，图却从中间缩）。 */
    var factor = Math.pow(c.step, (d.x0 - x) / c.stepPx);
    var t = (d.x0 - rect.x) / rect.width;
    var anchor = win.from + t * (win.to - win.from);
    var next = H.zoomWindow(win, factor, anchor, c.minCols, this._cols - 1);
    if (H.nearWindow(next, this._xWin)) { return; }
    this._xWin = next;
    this._dirty = true;
    this._paint(false);
  };

  /* 拖动过程中的重绘节流：每像素都重绘会把主线程占满，页面其它面板一起卡。 */
  SkewZoom.prototype._paint = function (force) {
    var wait = H.dragCfg().throttleMs;
    var now = (global.performance && global.performance.now)
      ? global.performance.now() : Date.now();
    if (!force && wait > 0 && (now - this._paintAt) < wait) { return; }
    this._paintAt = now;
    this._dirty = false;
    this._notify();
  };

  /* ------------------------------------------------------------------ */
  /* 施加 / 状态                                                         */
  /* ------------------------------------------------------------------ */

  /*
   * 两条纵轴的 `{min,max}` 补丁 —— **锁定与否的唯一出口**。
   * `skew.js` 每次 setOption 都必须走它，否则会出现"屏上已缩、下一帧又被
   * 自动量程冲掉"（拖了但图没动，最难查的一类）。
   *
   * 左轴（0）：**永远显式给值** —— 它的自动量程由 `H.axisRange()` 按可见窗口算，
   *            本就不依赖 ECharts 的自动伸缩。
   * 右轴（1）：锁定则显式给值；未锁定给 `min:null, max:null` 交回 ECharts
   *            自动量程。`null` 能真的清掉先前的显式值 —— **这一条是实测过的**
   *            （2026-09-17 探针：pin 到 [9,24] 后置 null，extent 回到 [14,19]）。
   *
   * `locked` 是给宿主的**状态标记**，不是 ECharts 的字段：宿主照它把那一侧的
   * 轴刻度换成警示色（两条轴各缩各的之后，图上必须能看出"哪条被锁过"）。
   * 锁定态**跟着量程一起走**，不在两处各判一次 —— 两份判断迟早分家。
   */
  SkewZoom.prototype.yAxisPatch = function (range0) {
    var patch = [
      { min: Number(range0[0]), max: Number(range0[1]), locked: !!this._yLocked[0] },
      { min: null, max: null, locked: !!this._yLocked[1] }
    ];
    var l1 = this._yLocked[1];
    if (l1) { patch[1] = { min: Number(l1[0]), max: Number(l1[1]), locked: true }; }
    return patch;
  };

  /*
   * 这一帧的时间窗：一次算清「窗口下标 + 给 option 的百分比补丁 + 窗口有没有
   * 被挤动」。三件事必须同源 —— 拆开各判一次，迟早有一处漏判
   * （症状是窗口贴着旧列数画，图上右边永远少一截）。
   *
   * 列数变少时**先夹、后复位**，不是一律复位：列数**确实**会变小
   * （切周期 / 换时段 / 尾部截断），而一律复位会把用户刚拖出来的窗口
   * **静默抹掉**（表现是"图自己跳回全宽"，屏幕上找不出原因）。
   * 能夹回范围就夹（窗口活着、只是被裁到边界），夹完真没宽度了才复位；
   * 两条路都**回报**给宿主告警，都不是静默的。列数的**语义**变化
   * （切周期 / 换时段）由调用方显式 `resetZoom()`，不靠这条兜底。
   */
  SkewZoom.prototype.view = function () {
    var last = this._cols - 1;
    var win = this._xWin;
    var reset = false;
    var clamped = false;

    if (!(last > 0)) {
      this._xWin = null;
      win = null;
    } else if (win) {
      /* `clampWindow` 已含"夹完全宽 ⇒ null"这条归一化，直接复用，
         免得这里再写一份口径（两份口径迟早对不上）。 */
      var next = H.clampWindow(win.from, win.to, last);
      if (!next) {
        this._xWin = null;
        win = null;
        reset = true;
      } else if (next.from !== win.from || next.to !== win.to) {
        this._xWin = next;
        win = next;
        clamped = true;
      }
    }

    var from = win ? win.from : 0;
    var to = win ? win.to : Math.max(last, 0);
    var denom = Math.max(last, 1);
    return {
      patch: { start: from / denom * 100, end: to / denom * 100 },
      from: from,
      to: to,
      count: to - from + 1,
      windowed: !!win,
      reset: reset,
      clamped: clamped
    };
  };

  SkewZoom.prototype.locked = function (axis) {
    var r = this._yLocked[axis];
    return r ? [Number(r[0]), Number(r[1])] : null;
  };

  SkewZoom.prototype.anyLocked = function () {
    return !!(this._yLocked[0] || this._yLocked[1]);
  };

  SkewZoom.prototype.xWindow = function () {
    return this._xWin ? { from: this._xWin.from, to: this._xWin.to } : null;
  };

  /* 双击 = 三条轴全部复位（两条纵轴量程 + 时间窗）。 */
  SkewZoom.prototype.reset = function () {
    this._yLocked = [null, null];
    this._xWin = null;
    this._drag = null;
    this._notify();
  };

  /*
   * 数据被清空（切周期 / 换时段）⇒ 锁定量程与时间窗都失去参照，一并复位。
   * 只清状态、不做别的 —— 此刻图表正要被重建，多一次 setOption 是白费。
   */
  SkewZoom.prototype.clear = function () {
    this._yLocked = [null, null];
    this._xWin = null;
    this._drag = null;
  };

  SkewZoom.prototype._notify = function () {
    if (this._host.onZoom) { this._host.onZoom(); }
  };

  global.SkewZoom = SkewZoom;
})(window);
