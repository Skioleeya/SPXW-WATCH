/* 热力图横轴「自动滚动」(auto roll) —— 策略层
 * ------------------------------------------------------------------
 * 职责单一：决定**窗口右缘要不要跟着最新列走、走到哪**。
 * 不碰 ECharts，不碰 DOM，不读帧 —— 只吃 (窗口, 列数)，吐一个新窗口。
 *
 * 要解决的问题
 * ------------
 * 横轴窗口存的是**列下标** `{from, to}`，不是"距尾部多远"。列每帧往尾部追加，
 * 下标窗口**原地不动** ⇒ 缩进去看细节之后，图会越看越旧、最后停在历史里。
 * 全宽没这个问题（全宽天然含最新列），所以自动滚动只在**有窗口**时才有意义。
 *
 * 触发条件 / 方向 / 速度（三个量都在这里定死）
 * ------------------------------------------
 * **触发**（三条同时成立才滚）：
 *   ① `heatmap.xRoll.enabled` 为真；
 *   ② 存在横轴窗口（即已缩放；全宽不需要滚）；
 *   ③ 处于「跟随」态（见下）。
 * **方向**：**只有时间正方向**（列下标增大，朝更新的列）。永不自动往回走 ——
 *   往回走会让"我没动它，它自己退回去了"变成常态，比不滚更难理解。
 * **速度**：**数据驱动，不插值**。每帧把右缘移到 `cols - 1 - lagCols`，
 *   即"前进量 = 该帧新增的列数"；帧节拍由后端推送（400ms）决定。
 *   为什么不插值成平滑动画：一次 `setOption` 实测 p50 27.4ms / max 44.6ms
 *   （见 heatmap.js 文件头那组数），插到 60fps 需要 16.7ms 一次 —— 做不到，
 *   硬做会把单核打满并让帧积压。所以滚动是**每帧一步**，不是连续滑动。
 *
 * 「跟随」态为什么必须**存**、不能现算
 * ----------------------------------
 * 直觉上可以现算"右缘是否贴着最新列"，但列一追加，**任何**窗口的右缘都不再
 * 贴着最新列 ⇒ "用户往回拖了 5 列"与"过了 5 列"完全无法区分（两者 `to` 都
 * 差 5）。所以跟随态是一个**显式布尔位**，只由四件事改写：
 *   - 用户**按下拖动** ⇒ 立刻接管（停滚）；松手时若又拖回右缘 ⇒ 恢复跟随；
 *   - 一段拖动结束 / 复位（双击 / 按钮 / 切周期 / 换时段）⇒ 按右缘位置结算；
 *   - 全宽（窗口为 `null`）⇒ 跟随（全宽天然跟着最新列）；
 *   - 列数不够（跨度已覆盖全部列）⇒ 退化为全宽，也就等于跟随。
 * **滚轮缩放不改这一位**：缩放改的是跨度，不是"想不想跟"的意图。
 *
 * 不跟随时也要挡越界
 * ----------------
 * 列数会缩（切周期 / 换时段 / 尾部截断），停滚中的窗口会整体落到帧外。
 * 那时复位为全宽并**说出来**：静默复位会让人以为"缩放自己跳没了"，
 * 不复位则会让 option 构建器把窗口夹到帧尾、看起来像卡住。
 * ------------------------------------------------------------------ */
(function (global) {
  "use strict";

  function create(cfg) {
    if (!cfg) {
      throw new Error("SWATCH_CONFIG.heatmap.xRoll 缺失 —— 自动滚动无配置来源，拒绝静默兜底");
    }
    if (typeof cfg.enabled !== "boolean") {
      throw new Error("heatmap.xRoll.enabled 必须是布尔（拿到 " + cfg.enabled + "）");
    }
    var lag = Math.floor(Number(cfg.lagCols));
    if (!(lag >= 0)) {
      throw new Error("heatmap.xRoll.lagCols 必须是非负整数（拿到 " + cfg.lagCols + "）");
    }
    return new Roll(cfg.enabled, lag);
  }

  function Roll(enabled, lag) {
    this._enabled = enabled;
    this._lag = lag;
    /* 默认跟随。理由：全宽天然跟随，而"用户第一次缩进去看"通常是想盯住
       正在发生的那一段 —— 默认停滚会让"缩一下就再也不动了"成为第一印象。 */
    this._auto = true;
  }

  /* 右缘到最新列还差几列（0 = 正贴着）。窗口为空 ⇒ 0（全宽贴着最新）。 */
  Roll.prototype.lagOf = function (win, cols) {
    if (!win) { return 0; }
    return Math.max(0, (cols - 1) - win.to);
  };

  /* 右缘是否已经落在允许的滞后范围内。 */
  Roll.prototype.atTail = function (win, cols) {
    if (!win) { return true; }
    return this.lagOf(win, cols) <= this._lag;
  };

  /* 用户按下拖动 = 立刻接管，避免拖动与自动滚动**互相拉扯**
     （拉扯的症状是"拖到一半自己被拽回右边"，且只在 400ms 边界上偶发）。 */
  Roll.prototype.takeOver = function () { this._auto = false; };

  Roll.prototype.reengage = function () { this._auto = true; };

  /*
   * 一段拖动结束后结算：拖回右缘 ⇒ 恢复跟随；停在历史里 ⇒ 保持停滚。
   * 窗口为 `null`（全宽）⇒ 跟随 —— 这条很关键：全宽时横向拖是空操作，
   * 若因此把跟随关掉，用户下一次滚轮缩进去就会得到一张不动的图。
   */
  Roll.prototype.settle = function (win, cols) {
    this._auto = this.atTail(win, cols);
    return this._auto;
  };

  /* 把右缘钉到 `cols - 1 - lagCols`，**跨度不变**。列数不够长（`lagCols`
     比富余列数还大）时退到最左 —— 缩水的窗口是静默错值（少露的列不报错）。 */
  Roll.prototype._pinned = function (win, cols) {
    var span = win.to - win.from + 1;
    var to = cols - 1 - this._lag;
    if (to < span - 1) { to = span - 1; }
    return { from: to - span + 1, to: to };
  };

  /*
   * 每帧调用：把窗口推到它该在的位置。返回新窗口（`null` = 全宽）。
   */
  Roll.prototype.advance = function (win, cols) {
    if (!win) { return null; }
    if (!(cols > 1)) { return null; }

    var span = win.to - win.from + 1;
    if (!(span > 0)) { return null; }
    /* 跨度已覆盖全部列 ⇒ 与全宽等价，归一化成 `null`（"有没有窗口"只有一个状态）。 */
    if (span >= cols) { return null; }

    if (!this._enabled || !this._auto) {
      if (win.from < 0 || win.to >= cols) {
        if (global.console && console.warn) {
          console.warn("[heatmap] 横轴窗口 " + win.from + "–" + win.to +
            " 已越界（当前 " + cols + " 列）—— 复位为全宽");
        }
        return null;
      }
      return win;
    }

    return this._pinned(win, cols);
  };

  /*
   * 用户**显式**要"看最新"（点面板头按钮）—— 不看 `enabled` / 跟随态。
   *
   * 为什么不受 `enabled` 管：那个开关回答的是"要不要**自动**跟着最新列走"，
   * 而这是一个用户指令。让用户指令被自动化开关锁住，症状是按钮亮着、点了没反应
   * —— 又一条静默无操作。
   */
  Roll.prototype.snap = function (win, cols) {
    if (!win || !(cols > 1)) { return win; }
    var span = win.to - win.from + 1;
    if (!(span > 0) || span >= cols) { return win; }
    return this._pinned(win, cols);
  };

  /* 给 UI 层读的状态快照。`following` 只在**功能开着且有窗口**时才有意义；
     `atTail` 与功能开关无关 —— 「回到最新」按钮的判据是它。 */
  Roll.prototype.state = function (win, cols) {
    return {
      enabled: this._enabled,
      windowed: !!win,
      following: !win ? true : (this._enabled && this._auto),
      atTail: this.atTail(win, cols),
      lag: this.lagOf(win, cols),
      lagCols: this._lag
    };
  };

  global.SWATCH_HEATMAP_ROLL = { create: create, Roll: Roll };
})(window);
