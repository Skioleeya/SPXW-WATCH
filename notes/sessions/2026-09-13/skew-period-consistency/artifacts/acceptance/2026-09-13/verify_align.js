/* skew × 热力图 周期一致性验证（工程外临时脚本）
 * ------------------------------------------------------------------
 * 直接在 Node 里加载**工程真实的** web/*.js，复现 app.js::render() 的调用顺序：
 *   decodeFrame → aggregate → clipTail → alignSkew → SkewPanel.update
 *
 * 判据设计原则：每一条都必须**可失败**。
 * 上一版用了"aligned.label 与 view.labels 逐列相同"，但 alignSkew 里
 * `out.label = grid.labels.slice()` 是直接复制的 —— 这条断言永远为真，是空转。
 * 现在改成跨函数/跨域的对拍：
 *   C1 聚合真的发生了（bucket_seconds 与列数）
 *   C2 时间轴一致：用 ts 时间域判断，不用 bucket 字段（与 alignSkew 内部算法无关）
 *   C3 ts 严格单调
 *   C4 末值语义（且至少一列首值≠末值，证明这条判据不是空转）
 *   C5 drop 生效
 *   C6 量程窗口生效（窗口内 vs 全序列，含尖峰对照）
 *   C7 有值列数
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const PROJECT_WEB = "E:/US.market/SPXW SWATCH/spxw_swatch/web";
const SITE = "C:/Users/Lenovo/.workbuddy-ai/tmp/skew-layout-probe/site";
const TMP = "C:/Users/Lenovo/.workbuddy-ai/tmp/skew-layout-probe";
const NODE = process.execPath;

function load(webDir) {
  const sandbox = {
    console: console,
    atob: atob,
    window: null,
    echarts: {
      init: function () {
        return { setOption: function () {}, resize: function () {}, clear: function () {} };
      }
    },
    addEventListener: function () {},
    document: { getElementById: function () { return {}; } }
  };
  sandbox.window = sandbox;
  const ctx = vm.createContext(sandbox);
  for (const f of ["config.js", "matrix_codec.js", "period.js", "skew.js"]) {
    vm.runInContext(fs.readFileSync(path.join(webDir, f), "utf8"), ctx, { filename: f });
  }
  vm.runInContext(fs.readFileSync(path.join(SITE, "probe_frame.js"), "utf8"), ctx,
    { filename: "probe_frame.js" });
  return sandbox;
}

function check(webDir) {
  const S = load(webDir);
  const P = S.SWATCH_PERIOD;
  const CFG = S.SWATCH_CONFIG;
  const F = S.PROBE_FRAME;
  const MAX_COLS = CFG.heatmap.maxColumns;

  /* 复现 app.js::render() 第一步 */
  F.heatmap = S.SWATCH_MATRIX.decodeFrame(F).heatmap;
  if (!F.heatmap.values) { throw new Error("decodeFrame 没产出 values"); }

  const HEAT_COLS = F.heatmap.cols;
  const BASE = F.heatmap.bucket_seconds;
  const SER = F.skew.series;
  const OPEN_TS = SER.ts[0];
  const SPIKE_BUCKET = 100, SPIKE_VALUE = 9.0;

  const fails = [];
  const lines = [];
  const metrics = {};

  lines.push("解码后热力图 rows=" + F.heatmap.rows + " cols=" + HEAT_COLS +
    " bucket_seconds=" + BASE + " maxColumns=" + MAX_COLS);
  lines.push("skew n=" + SER.count + "  ts[0]=" + OPEN_TS + "  scale_policy=" +
    JSON.stringify(F.skew.scale_policy));
  lines.push("");

  function need(cond, msg) { if (!cond) { fails.push(msg); } }

  const periods = P.options(BASE).map(function (o) { return o.seconds; });
  const rows = [];

  for (const seconds of periods) {
    const group = Math.round(seconds / BASE);
    const view = P.clipTail(P.aggregate(F.heatmap, group), MAX_COLS);
    const drop = view.clipped || 0;
    const aligned = P.alignSkew(SER, group, { labels: view.labels, drop: drop });
    const panel = new S.SkewPanel({});
    const info = panel.update(aligned, F.skew.scale_policy);

    const tag = seconds + "s(group=" + group + ")";
    const r = [];
    r.push("=== " + tag + " ===");
    r.push("  热力图 cols=" + view.labels.length + " 列宽=" + view.bucket_seconds +
      "s clipped=" + drop + "  skew cols=" + aligned.label.length);

    /* C1 聚合真的发生了（注意 clipTail 会把列数再截到 maxColumns） */
    const expCols = Math.min(Math.ceil(HEAT_COLS / group), MAX_COLS);
    need(view.bucket_seconds === BASE * group, tag + " C1 列宽应为 " + (BASE * group) + "，实得 " + view.bucket_seconds);
    need(view.labels.length === expCols, tag + " C1 列数应为 " + expCols + "，实得 " + view.labels.length);
    if (group > 1) { need(view.labels.length < HEAT_COLS, tag + " C1 聚合后列数应少于基线"); }
    r.push("  C1 聚合: 列宽=" + view.bucket_seconds + "s 列数=" + view.labels.length +
      " (期望 " + expCols + " 列) " + (view.bucket_seconds === BASE * group && view.labels.length === expCols ? "PASS" : "FAIL"));

    /* C2 时间轴一致：纯时间域，不看 bucket 字段 */
    let c2bad = -1, c2detail = "";
    for (let c = 0; c < aligned.skew.length && c2bad < 0; c++) {
      if (aligned.skew[c] === null) { continue; }
      const t = aligned.ts[c];
      if (typeof t !== "number") { c2bad = c; c2detail = "ts 非数值"; break; }
      const lo = OPEN_TS + (c + drop) * group * BASE;
      const hi = lo + group * BASE;
      /* 末列可能只填了一半（正在成形的那一组），区间右端放宽到会话末尾 */
      const isLast = (c + drop) === Math.ceil(HEAT_COLS / group) - 1;
      if (t < lo || (t >= hi && !isLast)) {
        c2bad = c;
        c2detail = "列" + c + " ts=" + t + " 不在 [" + lo + "," + hi + ")";
      }
    }
    need(c2bad < 0, tag + " C2 时间轴错位: " + c2detail);
    r.push("  C2 时间轴一致（ts 时间域）: " + (c2bad < 0 ? "PASS 全部 " +
      aligned.skew.filter(function (v) { return v !== null; }).length + " 列落在本列时间区间内" : "FAIL " + c2detail));

    /* C3 ts 严格单调 */
    let prev = -Infinity, c3ok = true;
    for (let c = 0; c < aligned.ts.length; c++) {
      const t = aligned.ts[c];
      if (t === null) { continue; }
      if (!(t > prev)) { c3ok = false; break; }
      prev = t;
    }
    need(c3ok, tag + " C3 ts 非严格单调");
    r.push("  C3 ts 严格单调: " + (c3ok ? "PASS" : "FAIL"));

    /* C4 末值语义 + 至少一列首值≠末值 */
    let c4bad = -1, diffCols = 0;
    for (let c = 0; c < aligned.skew.length; c++) {
      const lo = (c + drop) * group, hi = lo + group;
      let first = null, last = null;
      for (let m = 0; m < SER.bucket.length; m++) {
        const b = SER.bucket[m];
        if (b >= lo && b < hi) { if (first === null) { first = SER.skew[m]; } last = SER.skew[m]; }
      }
      if (aligned.skew[c] !== last) { c4bad = c; break; }
      if (first !== null && last !== null && first !== last) { diffCols += 1; }
    }
    need(c4bad < 0, tag + " C4 末值语义不符，列 " + c4bad);
    /* 非空转断言只在 group>1 时有意义：group=1 时组内只有一个点，首值恒等于末值。 */
    if (group > 1) { need(diffCols > 0, tag + " C4 判据空转：没有任何一列的首值≠末值"); }
    r.push("  C4 取组内末值: " + (c4bad < 0 ? "PASS" : "FAIL 列" + c4bad) +
      "  （首值≠末值的列有 " + diffCols + " 个" +
      (group > 1 ? "，证明该判据非空转）" : "；group=1 时该计数恒为 0，不作非空转断言）"));

    /* C5 首列 ts 应等于该列所覆盖桶区间内的**最后**一个点的 ts */
    let expFirstTs = null;
    {
      const lo = drop * group, hi = lo + group;
      for (let m = 0; m < SER.bucket.length; m++) {
        const b = SER.bucket[m];
        if (b >= lo && b < hi) { expFirstTs = SER.ts[m]; }
      }
    }
    need(aligned.ts[0] === expFirstTs, tag + " C5 首列 ts 应为 " + expFirstTs + "，实得 " + aligned.ts[0]);
    r.push("  C5 drop=" + drop + " 首列 ts: " + aligned.ts[0] + " 期望 " + expFirstTs +
      " (桶区间 [" + (drop * group) + "," + (drop * group + group) + ") 内最后一点) → " +
      (aligned.ts[0] === expFirstTs ? "PASS" : "FAIL"));

    /* C7 有值列数 */
    const filled = aligned.skew.filter(function (v) { return v !== null; }).length;
    const expFilled = Math.ceil(HEAT_COLS / group) - drop;
    need(filled === expFilled, tag + " C7 有值列应为 " + expFilled + "，实得 " + filled);
    r.push("  C7 有值列 " + filled + "/" + aligned.label.length + " (期望 " + expFilled + ") → " +
      (filled === expFilled ? "PASS" : "FAIL"));

    /* 面板读数（顺带证明 SkewPanel 能跑通） */
    r.push("  面板 update → points/cols=" + info.points + "/" + info.cols +
      "  纵轴量程=[" + info.range[0].toFixed(3) + ", " + info.range[1].toFixed(3) + "]");

    metrics[seconds] = {
      cols: view.labels.length, drop: drop, filled: filled,
      range: info.range, bucket_seconds: view.bucket_seconds
    };
    rows.push(r.join("\n"));
  }

  /* C6 量程窗口：窗口开 vs 关。
     必须用**不裁剪**的全序列网格 —— 30 秒视图会把尖峰（桶 100）裁掉，
     那样窗口开/关都看不到它，判据就退化成空转。 */
  const full = P.aggregate(F.heatmap, 1);
  const aFull = P.alignSkew(SER, 1, { labels: full.labels, drop: 0 });
  const spikeCol = aFull.skew.indexOf(SPIKE_VALUE);
  need(spikeCol >= 0, "C6 判据空转：不裁剪的序列里找不到尖峰 " + SPIKE_VALUE);
  const win = new S.SkewPanel({}).update(aFull, { window_s: 3600 });
  const all = new S.SkewPanel({}).update(aFull, { window_s: 0 });
  const maxWin = win.range[1], maxAll = all.range[1];
  need(maxWin < SPIKE_VALUE / 2, "C6 窗口开着仍把尖峰算进量程：max=" + maxWin);
  need(maxAll > SPIKE_VALUE * 0.8, "C6 窗口关掉却没算进尖峰：max=" + maxAll);
  need(maxAll > maxWin * 2, "C6 窗口开/关的量程没有显著差异");
  rows.push("=== C6 量程窗口（尖峰在基线桶 " + SPIKE_BUCKET + "，值 " + SPIKE_VALUE +
    "，位于不裁剪序列的第 " + spikeCol + " 列）===");
  rows.push("  序列共 " + aFull.label.length + " 列，窗口 3600s 覆盖最近 " +
    Math.round(3600 / BASE) + " 列");
  rows.push("  window_s=3600 → 上界 " + maxWin.toFixed(3) + "（尖峰已退出窗口）");
  rows.push("  window_s=0    → 上界 " + maxAll.toFixed(3) + "（等于旧的全序列极值，被尖峰撑大）");
  rows.push("  比值 " + (maxAll / maxWin).toFixed(1) + "× → " +
    (maxWin < SPIKE_VALUE / 2 && maxAll > SPIKE_VALUE * 0.8 ? "PASS" : "FAIL"));
  metrics.window = { on: win.range, off: all.range, spikeCol: spikeCol };

  lines.push(rows.join("\n"));
  return { lines: lines.join("\n"), fails: fails, metrics: metrics };
}

/* ------------------------------------------------------------------ */
/* 变异测试：把修复摘掉，必须报 FAIL                                     */
/* ------------------------------------------------------------------ */

const MUTANTS = [
  {
    name: "M1 取组内首值（而非末值）",
    file: "period.js",
    from: "      out.ts[col] = series.ts[i];\n      out.skew[col] = series.skew[i];\n      out.atm[col] = series.atm[i];\n      out.put25[col] = series.put25[i];\n      out.call25[col] = series.call25[i];\n      out.spot[col] = series.spot[i];",
    to: "      if (out.skew[col] === null) {\n      out.ts[col] = series.ts[i];\n      out.skew[col] = series.skew[i];\n      out.atm[col] = series.atm[i];\n      out.put25[col] = series.put25[i];\n      out.call25[col] = series.call25[i];\n      out.spot[col] = series.spot[i];\n      }",
    expect: "C4"
  },
  {
    name: "M2 aggregate 空转（不聚合）",
    file: "period.js",
    from: "    if (!(g > 1)) { return block; }",
    to: "    if (true) { return block; }",
    expect: "C1"
  },
  {
    name: "M3 去掉 drop 偏移",
    file: "period.js",
    from: "      var col = Math.floor(b / g) - drop;",
    to: "      var col = Math.floor(b / g);",
    expect: "C2"
  },
  {
    name: "M4 量程窗口失效（退回全序列极值）",
    file: "skew.js",
    from: "      if (windowS > 0 && latest !== null) {",
    to: "      if (false) {",
    expect: "C6"
  }
];

function main() {
  console.log("################ 基线：工程真实 web/ ################");
  const base = check(PROJECT_WEB);
  console.log(base.lines);
  console.log("");
  console.log("基线结论: " + (base.fails.length ? "FAIL" : "PASS") +
    (base.fails.length ? "\n  - " + base.fails.join("\n  - ") : ""));

  console.log("");
  console.log("################ 变异测试（摘掉修复必须报 FAIL）################");
  let mutantOk = true;
  const dir = path.join(TMP, "mutant_web");
  for (const m of MUTANTS) {
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    for (const f of ["config.js", "matrix_codec.js", "period.js", "skew.js"]) {
      fs.copyFileSync(path.join(PROJECT_WEB, f), path.join(dir, f));
    }
    const p = path.join(dir, m.file);
    const src = fs.readFileSync(p, "utf8");
    if (src.indexOf(m.from) < 0) {
      console.log("  " + m.name + " → 变异注入失败（源串未找到），检查脚本已过期");
      mutantOk = false;
      continue;
    }
    fs.writeFileSync(p, src.replace(m.from, m.to), "utf8");

    let res;
    try {
      res = check(dir);
    } catch (e) {
      console.log("  " + m.name + " → 加载即失败: " + e.message);
      continue;
    }
    const hit = res.fails.some(function (f) { return f.indexOf(m.expect) >= 0; });
    if (hit) {
      console.log("  " + m.name + " → 抓住 " + m.expect + "  FAIL  (" +
        res.fails.length + " 条失败)");
    } else {
      console.log("  " + m.name + " → 没抓住！期望 " + m.expect + " 报错，实得 " +
        (res.fails.length ? res.fails.join(" | ") : "全绿"));
      mutantOk = false;
    }
  }
  fs.rmSync(dir, { recursive: true, force: true });

  console.log("");
  const allOk = base.fails.length === 0 && mutantOk;
  console.log("总体: " + (allOk ? "PASS" : "FAIL"));
  process.exit(allOk ? 0 : 1);
}

main();
