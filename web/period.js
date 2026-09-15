/* 时间周期聚合
 * ------------------------------------------------------------------
 * 唯一职责：把后端的**基线序列 / 矩阵**变换成前端要画的那张图。
 * 热力图与 Skew 折线共用同一条横轴，两者必须由同一个周期档位驱动 ——
 * 选了 1 分钟，两块图都必须是 1 分钟一格，否则同一屏幕横坐标在两块图里
 * 指向不同时刻，上下没法对着看。
 *
 * 四件事，都是纯粹的呈现变换，不含任何业务判断：
 *
 *   1. options()   —— 按基线桶宽筛掉凑不出整组的周期；
 *   2. aggregate() —— 把若干基线桶并成一列（ΔIV 相加）；
 *   3. clipTail()  —— 列数超上限时只保留最近的一段；
 *   4. bound()     —— 色标量程（robust_bound 的 JS 镜像）。
 *
 * sliceZones() / alignSkew() 已拆分到 period_align.js。
 *
 * 为什么聚合放在前端而不是后端
 * ----------------------------
 * 热力图存的是相邻基线桶之间的 IV 差：ΔIV[k] = IV[k] − IV[k−1]。把一组连续
 * 基线桶并成一个更粗的桶，其 ΔIV 就是组内求和 —— 望远镜式相消之后
 *
 *     Σ(k=a..b) ΔIV[k] = IV[b] − IV[a−1]
 *
 * 正好等于该跨度的 IV 变化量。**这是恒等式，不是近似**，所以前端聚合不会
 * 引入任何信息损失，后端不必为每个可选周期各算一遍、各编码一遍。
 * Skew 折线同理：它每个基线桶一个读数，并组后取**末值**即可，无需后端重算。
 *
 * 代价是色标量程必须在前端按同样的规则重算（聚合后数值量级会变），于是这里
 * 有一份 `bound()` —— 它是 `serialization/numeric.py::robust_bound` 的镜像。
 * 为了不让两份实现悄悄漂移：**参数由后端随帧下发**（`heatmap.scale_policy`），
 * 且 `tools/check_period_aggregation.py` 会把两版逐值对拍，漂移即 FAIL。
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

  /* ------------------------------------------------------------------ */
  /* 可用周期                                                            */
  /* ------------------------------------------------------------------ */

  /*
   * 把 config.js 里声明的周期列表按基线桶宽过滤，只保留整数倍的项。
   *
   * 基线桶宽只有后端知道（随帧下发），前端**不复制**这个值 —— 复制一份就是
   * 两份真相，后端改一次桶宽，前端就会把 30 秒的基线当成 60 秒来分组，画出一
   * 张数值全错、但看起来完全正常的图。
   *
   * 非整数倍的周期会被丢掉并告警：那意味着最后一组凑不满，柱子长度悄悄短
   * 一截。宁可少一个按钮，也不要画一条长度不对的柱子。
   */
  function options(bucketSeconds) {
    var base = Math.floor(Number(bucketSeconds));
    if (!(base > 0)) {
      error("帧里没有可用的 heatmap.bucket_seconds，周期切换已停用" +
        "（拒绝猜一个基线桶宽 —— 猜错会让整张矩阵的数值全错）");
      return [];
    }

    var declared = CFG.heatmap.periods || [];
    var out = [];
    for (var i = 0; i < declared.length; i++) {
      var item = declared[i];
      var seconds = Math.floor(item.seconds);
      if (!(seconds > 0)) { continue; }
      if (seconds % base !== 0) {
        warn("周期 " + seconds + "s 不是基线桶宽 " + base + "s 的整数倍，已跳过");
        continue;
      }
      out.push({
        seconds: seconds,
        label: item.label || (seconds + "s"),
        group: seconds / base
      });
    }
    if (!out.length) {
      error("没有任何周期是基线桶宽 " + base + "s 的整数倍，周期切换不可用");
    }
    return out;
  }

  /* ------------------------------------------------------------------ */
  /* 聚合                                                                */
  /* ------------------------------------------------------------------ */

  /*
   * 组起点的标签。
   *
   * 基线桶宽不是整分钟时（例如 30 秒），后端下发的标签带秒（"09:30:30"）。
   * 聚合到整分钟及更粗的周期后，组起点必然落在 :00 上，这时把秒去掉，
   * 免得 1 分钟视图显示成 "09:30:00" 这种比原来更啰嗦的写法。
   * 30 秒粒度下组宽不是整分钟，秒必须留着 —— 否则相邻两列同名。
   */
  function groupLabel(label, groupSeconds) {
    if (typeof label !== "string") { return label; }
    if (groupSeconds % 60 !== 0) { return label; }
    if (label.length === 8 && label.slice(5) === ":00") { return label.slice(0, 5); }
    return label;
  }

  /*
   * 把基线矩阵按 group 个基线桶并成一列。
   *
   * 组内只要有一格是 null（该行那一段还没有数据），整组就是 null：少加了一段
   * 却仍报一个数，等于拿一个偏小的值冒充完整值 —— 那正是这张图最不该做的事。
   *
   * 末组不满时照样输出。它是"正在成形"的那一列，和 K 线最后一根未收盘的柱子
   * 是同一件事；丢掉它会让最新一列永远滞后整整一个周期（15 分钟周期下就是
   * 滞后 15 分钟，对盯盘等于没有这一列）。
   */
  function aggregate(block, group) {
    if (!block || !block.values) { return block; }

    var g = Math.floor(Number(group));
    if (!(g > 1)) { return block; }

    var cols = block.labels.length;
    var rows = block.values.length;
    if (!cols || !rows) { return block; }

    var outCols = Math.ceil(cols / g);
    var baseSeconds = Number(block.bucket_seconds);
    if (!(baseSeconds > 0)) {
      error("帧里没有 heatmap.bucket_seconds，已按基线原样返回（不聚合）");
      return block;
    }

    var values = [];
    var flat = [];
    for (var r = 0; r < rows; r++) {
      var src = block.values[r];
      var dst = new Array(outCols);
      for (var c = 0; c < outCols; c++) {
        var start = c * g;
        var end = Math.min(start + g, cols);
        var sum = 0;
        var known = true;
        for (var k = start; k < end; k++) {
          var v = src[k];
          if (v === null || v === undefined) { known = false; break; }
          sum += v;
        }
        dst[c] = known ? sum : null;
        if (known) { flat.push(sum); }
      }
      values.push(dst);
    }

    var labels = [];
    for (var i = 0; i < outCols; i++) {
      labels.push(groupLabel(block.labels[i * g], g * baseSeconds));
    }

    /* volume 跟着一起聚合：组内 tick 计数**求和**。
       30 秒桶是唯一数据源，更粗的周期只是把若干个 30 秒桶并起来。
       与 values 的"组内任一 null 则整组 null"刻意不同 —— ΔIV 少加一段会得到一个
       偏小却看着正常的数（静默错值）；而 tick 计数少一个桶就是少几个 tick，
       求和依然正确。整组一个 tick 都没有时才给 null（= 该格无边框）。 */
    var volumes = null;
    if (block.volumes) {
      volumes = [];
      for (var rv = 0; rv < rows; rv++) {
        var vsrc = block.volumes[rv] || [];
        var vdst = new Array(outCols);
        for (var cv = 0; cv < outCols; cv++) {
          var vstart = cv * g;
          var vend = Math.min(vstart + g, cols);
          var vsum = 0;
          var vany = false;
          for (var kv = vstart; kv < vend; kv++) {
            var vv = vsrc[kv];
            if (vv === null || vv === undefined) { continue; }
            vsum += vv;
            vany = true;
          }
          vdst[cv] = vany ? vsum : null;
        }
        volumes.push(vdst);
      }
    }

    var policy = block.scale_policy || {};
    var quantile = Number(policy.quantile);
    var floor = Number(policy.floor);
    if (!isFinite(quantile) || !isFinite(floor)) {
      /* 帧里缺色标规则（契约违规，check_web_contract 会先报出来）。
         这里退到 quantile=1（取最大绝对值）：量程只可能偏宽、不可能偏窄，
         偏宽只是对比度低，偏窄会让整张图糊成饱和色 —— 失败方向必须选前者。 */
      error("帧里缺 heatmap.scale_policy，色标退到最大绝对值（对比度会偏低）");
      quantile = 1;
      floor = 0;
    }

    return {
      labels: labels,
      strikes: block.strikes,
      rights: block.rights,
      values: values,
      volumes: volumes,
      vmax: Math.round(bound(flat, quantile, floor) * 1000) / 1000,
      rows: rows,
      cols: outCols,
      bucket_index: Math.floor(block.bucket_index / g),
      bucket_seconds: baseSeconds * g,
      scale_policy: block.scale_policy,
      spot: block.spot
    };
  }

  /* ------------------------------------------------------------------ */
  /* 显示窗口                                                            */
  /* ------------------------------------------------------------------ */

  /*
   * 列数超过上限时只保留**最近**的 maxColumns 列。
   *
   * 会话 6.5 小时在 30 秒粒度下是 780 列，铺在约 1450px 上每列不到 2px，
   * 只会糊成一条深色条纹 —— 那不是热力图，是噪点。盯盘关心的是当下，
   * 所以从尾部截取。
   *
   * 上限取 400 是刻意的：1 分钟粒度整个会话只有 390 列，所以这个截断
   * **只对 30 秒粒度生效**，更粗的周期一个像素都不变。
   */
  function clipTail(block, maxColumns) {
    var limit = Math.floor(Number(maxColumns));
    if (!block || !block.values || !(limit > 0)) { return block; }

    var cols = block.labels.length;
    if (cols <= limit) { return block; }

    var drop = cols - limit;
    var values = [];
    for (var r = 0; r < block.values.length; r++) {
      values.push(block.values[r].slice(drop));
    }

    /* volume 必须与 values 用**同一个 drop** 裁掉同样多的左端列，
       否则边框粗细会整体右移（错位后依然"看着像"一张正常的图）。 */
    var volumes = null;
    if (block.volumes) {
      volumes = [];
      for (var rv = 0; rv < block.volumes.length; rv++) {
        volumes.push(block.volumes[rv].slice(drop));
      }
    }

    return {
      labels: block.labels.slice(drop),
      strikes: block.strikes,
      rights: block.rights,
      values: values,
      volumes: volumes,
      vmax: block.vmax,
      rows: block.rows,
      cols: limit,
      bucket_index: block.bucket_index - drop,
      bucket_seconds: block.bucket_seconds,
      scale_policy: block.scale_policy,
      spot: block.spot,
      clipped: drop
    };
  }

  /* ------------------------------------------------------------------ */
  /* 色标量程                                                            */
  /* ------------------------------------------------------------------ */

  /*
   * `serialization/numeric.py::robust_bound` 的镜像。
   *
   * 为什么不直接用最大值：0DTE 尾盘只要有一个毛刺点就能把最大值顶到几十个
   * 波动率点，色标被拉满之后整张热力图会变成一片灰。改用分位数后，少数极端
   * 值被截断在色标之外，主图对比度得以保留。
   *
   * **规则本体在 Python 那一份**，这里只是同一算法的 JS 表达；参数由后端
   * 随帧下发，两版的一致性由 tools/check_period_aggregation.py 逐值对拍。
   */
  function bound(values, quantile, floor) {
    var clean = [];
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (v === null || v === undefined) { continue; }
      v = Math.abs(Number(v));
      if (!isFinite(v)) { continue; }
      clean.push(v);
    }
    if (!clean.length) { return floor; }

    clean.sort(function (a, b) { return a - b; });

    var picked;
    if (quantile <= 0) {
      picked = clean[0];
    } else if (quantile >= 1) {
      picked = clean[clean.length - 1];
    } else {
      var position = quantile * (clean.length - 1);
      var lower = Math.floor(position);
      var upper = Math.min(lower + 1, clean.length - 1);
      var weight = position - lower;
      picked = clean[lower] * (1 - weight) + clean[upper] * weight;
    }

    return Math.max(picked, floor);
  }

  var existing = global.SWATCH_PERIOD || {};
  global.SWATCH_PERIOD = {
    options: options,
    sliceZones: existing.sliceZones,
    aggregate: aggregate,
    clipTail: clipTail,
    alignSkew: existing.alignSkew,
    bound: bound
  };
})(window);
