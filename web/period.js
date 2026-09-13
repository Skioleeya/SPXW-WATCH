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
 *   2. sliceZones()—— 只留所选时段（GTH / RTH / 全时段）覆盖的列；
 *   3. aggregate() —— 把若干基线桶并成一列（ΔIV 相加）；
 *   4. clipTail()  —— 列数超上限时只保留最近的一段；
 *   5. alignSkew() —— 把 Skew 折线对齐到上面那套列网格（取组内末值，
 *                     并消费 sliceZones 产出的"桶号 → 列号"映射）。
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

    return {
      labels: block.labels.slice(drop),
      strikes: block.strikes,
      rights: block.rights,
      values: values,
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
  /* 时段切列                                                            */
  /* ------------------------------------------------------------------ */

  /* 恒等映射：不切列时也返回一个映射，调用方不必分两种情况处理。 */
  function identityIndex(cols) {
    var out = new Array(cols);
    for (var i = 0; i < cols; i++) { out[i] = i; }
    return out;
  }

  /*
   * 只保留所选时段覆盖的列，其余整列**切掉**。
   *
   * 为什么必须切掉，而不是把那几列填 null
   * ------------------------------------
   * 横轴是**类别轴**：填 null 只是不画颜色，那几列照样占着宽度，屏幕上留一条
   * 空洞。而 GTH 收盘 09:25 到 RTH 开盘 09:30 这段空档里根本没有任何行情 ——
   * 一条空洞等于告诉人"这里本该有数据"。切掉之后 GTH 段与 RTH 段直接相邻，
   * 与"这段时间没交易"的读法一致（KAI 2026-09-13 要求）。
   *
   * 为什么同时返回 index 映射
   * -------------------------
   * Skew 折线按**基线桶号**落列（见 alignSkew）。一旦切掉中间的列，"桶号 →
   * 列号"就不再是"整除 + 平移"能表达的了。让 skew 自己再推一遍，就是把网格
   * 几何抄了第二份 —— 切错一列不会有任何报错，只会让两块图的横坐标指向不同
   * 时刻。所以映射在这里产出一次，两块图共用。
   *
   * 区段表来自帧里的 session.zones（后端算的），这里只按 first/last 切，
   * **不自己推算时刻**：自己算就是把网格几何抄第二份。
   *
   * 返回 ``{block, index}``；``index[基线列]`` 是切完之后的列号，-1 表示已切掉。
   * 所选时段一列都还没有（例如 GTH 时段里切到 RTH）时返回 ``null``。
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

    /* 当前列：桶号平移过来。当前桶正好落在被切掉的空档里（09:25–09:30）时
       取保留列里的最后一列 —— 它紧邻空档左侧，是"最后一个有行情的时刻"。 */
    var here = index[Math.floor(Number(block.bucket_index))];
    if (typeof here !== "number" || here < 0) { here = labels.length - 1; }

    return {
      block: {
        labels: labels,
        strikes: block.strikes,
        rights: block.rights,
        values: values,
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

  /* ------------------------------------------------------------------ */
  /* Skew 折线对齐                                                       */
  /* ------------------------------------------------------------------ */

  function nullArray(n) {
    var out = new Array(n);
    for (var i = 0; i < n; i++) { out[i] = null; }
    return out;
  }

  /*
   * 把 Skew 序列铺到热力图那套列网格上，返回与 `grid.labels` **等长**的序列。
   *
   * 取组内**末值**而不是求和：热力图聚合的是 ΔIV（增量，可加），而 skew 是
   * 水平量（两点 IV 之差），把一组里的 skew 加起来没有任何金融含义，只会得到
   * 一个随周期变化的假数字。取末值等于"这一格画的是该周期结束时的读数"，
   * 与 K 线取收盘价同理。
   *
   * 为什么要 drop：热力图列数超上限时会从尾部截取，被截掉的列在两块图里都
   * 不该出现。前端不做二次裁剪，只把落在窗口外的点丢掉。
   *
   * 为什么要 index：`grid.labels` 那一套列网格可能已经过了 `sliceZones` ——
   * 空档（09:25–09:30）那几列被整段切掉，于是"桶号 → 列号"不再是"整除 +
   * 平移"能表达的了（RTH 段每一点都会左移 10 列）。`index` 就是那份映射，
   * 由 `sliceZones` 产出、两块图共用；自己再推一遍就是第二份网格几何，
   * 切错一列不会有任何报错，只会让上下两块图的横坐标指向不同时刻。
   *
   * `index` 为 null 表示**序列里的桶号已经是切后位置**（没有切列，或调用方
   * 已自行预映射过），此时退回 `pos = b`。这不是兜底分支，是契约的两条入口：
   * 有映射就查表，没有就按原样 —— 两者必须给出同一结果（见
   * `tools/check_period_aggregation.py` 的"时段映射路径 ≡ 预映射路径"）。
   *
   * 落在窗口**之前**的点（`col < 0`）是 `clipTail` 裁掉的历史段，属于正常
   * 情况，静默丢弃 —— 30 秒粒度下每帧有 380 个，若也告警会每帧刷满日志，
   * 把真正该响的"桶口径不符"淹掉。只有桶索引非法或落在网格**右端之外**
   * 才告警：那说明帧里的 bucket 与热力图对不上，静默画到别的列上更糟。
   */
  function alignSkew(series, group, grid) {
    if (!series || !series.bucket || !series.ts) { return null; }
    if (!grid || !grid.labels || !grid.labels.length) { return null; }

    var g = Math.floor(Number(group));
    if (!(g > 0)) { return null; }

    var cols = grid.labels.length;
    var drop = Math.floor(Number(grid.drop));
    if (!(drop > 0)) { drop = 0; }

    /* 时段切列的"基线桶号 → 切后列号"映射（见 sliceZones）。为 null 表示
       序列里的桶号已经是切后位置，不必再查表。 */
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
        /* 桶号超出映射表右端：帧里的 bucket 与热力图不同源，丢弃并告警。 */
        if (b >= index.length) { stray += 1; continue; }
        pos = index[b];
        /* 被时段切列丢掉的那几列（空档）：正常，静默丢弃（见上方说明）。 */
        if (pos < 0) { continue; }
      }
      var col = Math.floor(pos / g) - drop;
      /* 被 clipTail 裁掉的历史段：正常，静默丢弃（见上方说明）。 */
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

  global.SWATCH_PERIOD = {
    options: options,
    sliceZones: sliceZones,
    aggregate: aggregate,
    clipTail: clipTail,
    alignSkew: alignSkew,
    bound: bound
  };
})(window);
