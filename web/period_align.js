/* 时段切列 + Skew 折线对齐
 * ------------------------------------------------------------------
 * 从 period.js 拆分：单一职责 —— 把基线列按时段过滤，以及把 Skew 序列
 * 对齐到热力图的列网格。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var CFG = global.SWATCH_CONFIG;

  function warn(message) {
    if (global.console && console.warn) { console.warn("[period] " + message); }
  }

  function error(message) {
    if (global.console && console.error) { console.error("[period] " + message); }
  }

  /* 恒等映射：不切列时也返回一个映射，调用方不必分两种情况处理。 */
  function identityIndex(cols) {
    var out = new Array(cols);
    for (var i = 0; i < cols; i++) { out[i] = i; }
    return out;
  }

  /*
   * 只保留所选时段覆盖的列，其余整列**切掉**。
   *
   * 返回 ``{block, index}``；``index[基线列]`` 是切完之后的列号，-1 表示已切掉。
   * 所选时段一列都还没有时返回 ``null``。
   */
  function sliceZones(block, zones, keepIds) {
    if (!block || !block.values || !block.labels) { return null; }

    var cols = block.labels.length;
    var keep = {};
    var wanted = 0;
    for (var i = 0; keepIds && i < keepIds.length; i++) {
      keep[keepIds[i]] = true;
      wanted += 1;
    }
    if (!wanted) {
      warn("没有可用的时段列表（帧里缺 session.zones），时段切换已停用 —— " +
        "不猜网格几何，原样显示整块矩阵");
      return { block: block, index: identityIndex(cols) };
    }

    var order = [];
    for (var z = 0; zones && z < zones.length; z++) {
      if (keep[zones[z].id]) { order.push(zones[z]); }
    }
    if (!order.length) {
      error("所选时段在帧的 session.zones 里一个都对不上，拒绝猜一个网格");
      return null;
    }

    var index = new Array(cols);
    for (var c = 0; c < cols; c++) { index[c] = -1; }

    var labels = [];
    var picked = [];
    for (var k = 0; k < order.length; k++) {
      var first = Math.floor(Number(order[k].first));
      var last = Math.floor(Number(order[k].last));
      if (!isFinite(first) || !isFinite(last)) {
        error("区段 " + order[k].id + " 的 first/last 不是数字，该时段已跳过");
        continue;
      }
      if (first < 0) { first = 0; }
      if (last > cols - 1) { last = cols - 1; }
      for (var c2 = first; c2 <= last; c2++) {
        index[c2] = labels.length;
        labels.push(block.labels[c2]);
        picked.push(c2);
      }
    }
    if (!labels.length) { return null; }

    var values = [];
    for (var r = 0; r < block.values.length; r++) {
      var src = block.values[r];
      var dst = new Array(labels.length);
      for (var n = 0; n < picked.length; n++) { dst[n] = src[picked[n]]; }
      values.push(dst);
    }

    /* volume 与 values 同形、同列序 —— 用**同一个 picked** 取列，
       否则边框粗细会与格子错位（错位了看不出来：只是粗细对不上成交量）。 */
    var volumes = null;
    if (block.volumes) {
      volumes = [];
      for (var rv = 0; rv < block.volumes.length; rv++) {
        var vsrc = block.volumes[rv];
        var vdst = new Array(labels.length);
        for (var nv = 0; nv < picked.length; nv++) { vdst[nv] = vsrc[picked[nv]]; }
        volumes.push(vdst);
      }
    }

    var here = index[Math.floor(Number(block.bucket_index))];
    if (typeof here !== "number" || here < 0) { here = labels.length - 1; }

    return {
      block: {
        labels: labels,
        strikes: block.strikes,
        rights: block.rights,
        values: values,
        volumes: volumes,
        vmax: block.vmax,
        rows: block.rows,
        cols: labels.length,
        bucket_index: here,
        bucket_seconds: block.bucket_seconds,
        scale_policy: block.scale_policy,
        spot: block.spot
      },
      index: index
    };
  }

  function nullArray(n) {
    var out = new Array(n);
    for (var i = 0; i < n; i++) { out[i] = null; }
    return out;
  }

  /*
   * 把 Skew 序列铺到热力图那套列网格上，返回与 `grid.labels` **等长**的序列。
   *
   * 取组内**末值**而不是求和：skew 是水平量，加和没有金融含义。
   */
  function alignSkew(series, group, grid) {
    if (!series || !series.bucket || !series.ts) { return null; }
    if (!grid || !grid.labels || !grid.labels.length) { return null; }

    var g = Math.floor(Number(group));
    if (!(g > 0)) { return null; }

    var cols = grid.labels.length;
    var drop = Math.floor(Number(grid.drop));
    if (!(drop > 0)) { drop = 0; }

    var index = grid.index && grid.index.length ? grid.index : null;

    var bucket = series.bucket;
    var out = {
      ts: nullArray(cols),
      label: grid.labels.slice(),
      skew: nullArray(cols),
      atm: nullArray(cols),
      put25: nullArray(cols),
      call25: nullArray(cols),
      spot: nullArray(cols),
      count: cols
    };

    var stray = 0;
    for (var i = 0; i < bucket.length; i++) {
      var b = bucket[i];
      if (typeof b !== "number" || !isFinite(b) || b < 0) { stray += 1; continue; }
      var pos = b;
      if (index) {
        if (b >= index.length) { stray += 1; continue; }
        pos = index[b];
        if (pos < 0) { continue; }
      }
      var col = Math.floor(pos / g) - drop;
      if (col < 0) { continue; }
      if (col >= cols) { stray += 1; continue; }
      out.ts[col] = series.ts[i];
      out.skew[col] = series.skew[i];
      out.atm[col] = series.atm[i];
      out.put25[col] = series.put25[i];
      out.call25[col] = series.call25[i];
      out.spot[col] = series.spot[i];
    }
    if (stray) {
      warn(stray + " 个 Skew 点的桶索引非法或超出列网格右端，已丢弃" +
        "（两块图的桶口径应当同源，出现这个说明帧里的 bucket 与热力图对不上）");
    }
    return out;
  }

  /* 合并到 SWATCH_PERIOD（period.js 可能已先加载，也可能后加载） */
  var existing = global.SWATCH_PERIOD || {};
  global.SWATCH_PERIOD = {
    options: existing.options,
    sliceZones: sliceZones,
    aggregate: existing.aggregate,
    clipTail: existing.clipTail,
    alignSkew: alignSkew,
    bound: existing.bound
  };
})(window);
