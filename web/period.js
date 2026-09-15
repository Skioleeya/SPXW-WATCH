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
   * **只输出已走满的周期（2026-09-15 修）**
   * ---------------------------------------
   * 末组不满时**不再输出**。旧版把它当成"正在成形的那一列"照画，类比 K 线
   * 最后一根未收盘的柱子 —— 那个类比是错的，两者语义根本不同：
   *
   *   - K 线未收盘柱画的是**当前价**，它本来就该随行情跳动；
   *   - 这里每一列画的是**一个周期内的 IV 变化量**（ΔIV 之和，望远镜相消后
   *     = IV[b] − IV[a−1]）。右端点 b 是**还没走完的当前桶**，而同一个桶内的
   *     IV 每 400ms 就被后来的 tick 覆盖一次（`heatmap_engine.observe` 同桶
   *     只保留最后一次）。于是一个"周期变化量"在周期还没结束时就一直变 ——
   *     它根本不是周期变化量，只是**相邻两个基线桶的差**。
   *
   * 实盘症状（2026-09-15 探针，3 分钟周期）：
   *   - 跨周期那一刻组内只有 1 个桶 ⇒ 聚合值 = IV[新桶] − IV[上一桶] ≈ **+0**；
   *   - 同一周期内该值持续变化（实测 0.000 → −0.072）。
   *
   * 语义定稿（KAI 2026-09-15）：**周期走满才出列，出列即定稿**。
   * 3 分钟周期下，T→T+3 这段期间该列在图上**不存在**；到 T+3 走满时一次性
   * 落图，值恒为 IV(T+3) − IV(T)，此后再不变化。
   *
   * 代价是最新一列会滞后最多一个周期（15 分钟周期下就是 15 分钟）。这是
   * **刻意的**：滞后一列是"看得见的等待"，而拿未定稿的数当定稿数展示是
   * "看不见的错值" —— 后者正是本项目的头号禁忌（见 QUICKREF 静默错值型）。
   *
   * 为什么"按桶数分组"就等于"按挂钟整点分分组"（2026-09-15 KAI 质问后核准）
   * -----------------------------------------------------------------------
   * KAI 的裁定是"时间周期第一，必须按挂钟整点分对齐"。查证结论：**本项目的
   * 桶分组已经满足该裁定，两者数值等价，不是两种方案。** 依据有两级：
   *
   *   1. 网格起点是 `20:15:00`，即相对当日 00:00 偏移 **72900 秒**；
   *      而 `72900 % 30/60/180/300/900` **全部为 0** ⇒ 第 c 个组的起点必然落在
   *      挂钟整点上（20:15、20:18、20:21 … 21:00、21:03）。这是
   *      `core/session_grid.py::build_zones` 的既有前提：它**强校验**每个区段
   *      边界落在桶边界上（`begin_s % bucket_seconds` 不为 0 直接抛错），
   *      而会话时刻又必须落在整分钟（`parse_hm` 只接受 `HH:MM`）。
   *   2. 因此 `floor(cols / g)` 与 `floor((t − 20:15) / period秒)` 给出同一个组号。
   *
   * **反过来说：想"改成按时间分组"在这里是恒等变换，改了也不会动一个像素。**
   * 真要动的是别的东西（例如把周期档位改成不整除 300s 的值、或让会话起点不再是
   * 整分钟），那时这条等价性才会破，**届时必须改的是本注释而不是这段代码** ——
   * 代码按桶分组是对的，因为桶序号的唯一真相在后端 `SessionClock`。
   */
  function aggregate(block, group) {
    if (!block || !block.values) { return block; }

    var g = Math.floor(Number(group));
    if (!(g > 1)) { return block; }

    var cols = block.labels.length;
    var rows = block.values.length;
    if (!cols || !rows) { return block; }

    var baseSeconds = Number(block.bucket_seconds);
    if (!(baseSeconds > 0)) {
      error("帧里没有 heatmap.bucket_seconds，已按基线原样返回（不聚合）");
      return block;
    }

    /* 只保留**完整**组：末尾凑不满 g 个基线桶的那一组整组丢弃。
       cols 不是 g 的整数倍时，outCols 比 ceil 少 1 —— 这一列正是未定稿的那列。 */
    var outCols = Math.floor(cols / g);
    if (outCols < 1) {
      /* 连一个完整周期都还没走满（极端：周期比整个交易日网格还长）。
         返回**空**矩阵，让前端画出带正确坐标轴的空网格。

         元字段必须与正常分支同口径，否则同一个函数两条路径给出两套语义：
         `bucket_index` 一律除以 g（周期编号），`vmax` 一律由聚合后的数值重算。
         代价是此刻没有可算的量程，退到 floor —— 空矩阵本就不画任何颜色，
         量程取什么都不影响显示。 */
      var emptyPolicy = block.scale_policy || {};
      var emptyVmax = Number(emptyPolicy.floor);
      return {
        labels: [],
        values: block.values.map(function () { return []; }),
        volumes: block.volumes ? block.volumes.map(function () { return []; }) : undefined,
        vmax: isFinite(emptyVmax) && emptyVmax > 0 ? emptyVmax : 0,
        strikes: block.strikes,
        rights: block.rights,
        rows: rows,
        cols: 0,
        bucket_index: Math.floor(block.bucket_index / g),
        bucket_seconds: baseSeconds * g,
        scale_policy: block.scale_policy,
        spot: block.spot
      };
    }

    var values = [];
    var flat = [];
    for (var r = 0; r < rows; r++) {
      var src = block.values[r];
      var dst = new Array(outCols);
      for (var c = 0; c < outCols; c++) {
        var start = c * g;
        var end = start + g;          /* 完整组 ⇒ 不必再夹到 cols */
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
