/* 面板头的状态呈现（状态徽标 + 复位按钮可用态 + 瞬时提示）
 * ==================================================================
 * 职责单一：**唯一**负责把面板状态写进面板头那几个 DOM 节点。
 * 不读帧数据、不碰图表、不改任何视图状态 —— 状态一律从面板自己的查询接口取
 * （`heatmapPanel.xZoom()` / `skewPanel.viewState()`），本层不自己推。
 *
 * 为什么需要状态徽标
 * ------------------
 * 横轴"是否还在跟随最新"、两条纵轴"哪条被锁住"这两种状态，此前**只**出现在
 * meta 行的一段文字里，而且与提示文字（操作说明书）位置分离、字号 10.5px、
 * 颜色是 `--text-faint`。结果：用户离开一会儿回来，无法一眼判断图还是不是
 * 自己调过的样子；两条纵轴各缩各的之后，图上更是完全看不出哪条动过。
 * ⇒ 状态从 meta 行**移出来**，各自一个徽标（同一件事只有一个归属）。
 *
 * 为什么需要瞬时提示
 * ------------------
 * 全宽时横向拖动是**设计上的空操作**（凭空长窗会让横轴静默停止跟随最新列），
 * 但屏幕上一点反应都没有 —— 用户只会归因为"图坏了"。
 * 静默无操作比报错更难查，所以它必须**响**。
 * ================================================================== */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  var persistent = {};   /* id -> {text, cls}：持久态（瞬时提示结束后回到它） */
  var timers = {};       /* id -> 定时器句柄 */

  function flashMs() {
    var v = CFG.ui && CFG.ui.flashMs;
    if (!(v > 0)) {
      throw new Error("SWATCH_CONFIG.ui.flashMs 非法 —— 瞬时提示无时长来源，拒绝静默兜底");
    }
    return v;
  }

  function node(id) { return document.getElementById(id); }

  function paint(id) {
    var el = node(id);
    if (!el) { return; }
    var p = persistent[id] || { text: "", cls: "chip" };
    var cls = p.text ? p.cls : p.cls + " hidden";
    if (el.textContent !== p.text) { el.textContent = p.text; }
    if (el.className !== cls) { el.className = cls; }
  }

  /*
   * 写持久态。
   * ⚠️ 值没变就直接返回 —— 调用方每帧都会来一次（400ms），
   * 无条件重写会把正在显示的瞬时提示冲掉（症状：提示一闪而过）。
   */
  function set(id, text, cls) {
    var next = { text: text || "", cls: cls || "chip" };
    var prev = persistent[id];
    if (prev && prev.text === next.text && prev.cls === next.cls) { return; }
    persistent[id] = next;
    if (timers[id]) { global.clearTimeout(timers[id]); timers[id] = null; }
    paint(id);
  }

  /* 瞬时提示：显示 flashMs 之后自动回到持久态。 */
  function flash(id, text, cls) {
    var el = node(id);
    if (!el) { return; }
    el.textContent = text;
    el.className = (cls || "chip") + " flash";
    if (timers[id]) { global.clearTimeout(timers[id]); }
    timers[id] = global.setTimeout(function () {
      timers[id] = null;
      paint(id);
    }, flashMs());
  }

  /* 复位按钮的可用态：视图被改过就点亮 —— 让"这个面板现在不是默认样子"可见。 */
  function button(id, dirty) {
    var el = node(id);
    if (!el) { return; }
    var cls = "vbtn" + (dirty ? " dirty" : "");
    if (el.className !== cls) { el.className = cls; }
  }

  global.ViewChips = { set: set, flash: flash, button: button, flashMs: flashMs };
})(window);
