"""
L6 — 周期聚合回归的 node 驱动。
================================
唯一职责：把 Python 侧造好的 cases 交给 node，取回 ``web/period.js`` 的**实际输出**。

从 ``tools/period_reference.py`` 拆出（2026-09-15）：那里是"造数 + 参考实现"，
这里是"跑 JS 拿结果"—— 前者是纯计算，后者要起子进程、建临时目录，属 IO。
混在一个文件里会撑破 400 行上限（拆分前 441 行，项目硬约束是 < 400）。

驱动本体是 ``NODE_DRIVER`` 字符串：求值 ``config.js`` + ``period.js`` +
``period_align.js``，把 cases.json 喂进去，结果原样吐成 JSON。
数据经**临时文件**传入而不是拼进命令行 —— 两侧各自造数的话，"对拍对象其实不是
同一个矩阵"这件事会悄无声息地让整组对照失效。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NODE_DRIVER = r"""
const fs = require("fs");
const periodPath = process.argv[1];
const configPath = process.argv[2];
const casesPath = process.argv[3], alignPath = process.argv[4];

const window = { console: console };
eval(fs.readFileSync(configPath, "utf8"));
eval(fs.readFileSync(periodPath, "utf8"));
/* period_align.js 必须排在 period.js 之后：它读 SWATCH_PERIOD 再合并回去。 */
eval(fs.readFileSync(alignPath, "utf8"));

const P = window.SWATCH_PERIOD;
const cfg = window.SWATCH_CONFIG;
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));

const out = {
  declared: (cfg.heatmap && cfg.heatmap.periods) || [],
  maxColumns: cfg.heatmap ? cfg.heatmap.maxColumns : null,
  options: {}, bound: {}, aggregate: {}, clip: null, slice: {}, index: null
};

for (const key of Object.keys(cases.options)) {
  out.options[key] = P.options(Number(key)).map(function (p) {
    return [p.seconds, p.group, p.label];
  });
}

for (const c of cases.bound) {
  out.bound[c.name] = P.bound(c.values, c.quantile, c.floor);
}

for (const c of cases.aggregate) {
  const r = P.aggregate(c.block, c.group);
  out.aggregate[c.name] = {
    cols: r.cols, rows: r.rows, labels: r.labels, values: r.values,
    volumes: r.volumes === undefined ? null : r.volumes,
    vmax: r.vmax, bucket_seconds: r.bucket_seconds, bucket_index: r.bucket_index
  };
}

const cl = P.clipTail(cases.clip.block, cases.clip.maxColumns);
out.clip = {
  cols: cl.cols, labels: cl.labels, values: cl.values,
  volumes: cl.volumes === undefined ? null : cl.volumes,
  bucket_index: cl.bucket_index,
  clipped: cl.clipped === undefined ? null : cl.clipped
};

for (const c of cases.slice.cases) {
  const r = P.sliceZones(c.block, cases.slice.zones, c.keep);
  out.slice[c.name] = r === null ? null : {
    cols: r.block.cols, labels: r.block.labels, values: r.block.values,
    volumes: r.block.volumes === undefined ? null : r.block.volumes,
    bucket_index: r.block.bucket_index, index: r.index
  };
}

/* 时段切列对 Skew 的影响：带 index 的路径必须与"先把桶号预映射一遍再走普通
   路径"逐值相同；而**不带** index（用原始桶号）必须不同 —— 后者是非空转判据，
   少了它，"index 被忽略"这个缺陷会静默通过。 */
const idx = cases.index;
function runSkew(series, index) {
  const a = P.alignSkew(series, idx.group,
    { labels: idx.labels, drop: idx.drop, index: index });
  return a === null ? null : a.skew;
}
out.index = {
  withIndex: runSkew(idx.series, idx.index),
  premapped: runSkew(idx.premapped, null),
  unsliced: runSkew(idx.raw, null)
};

process.stdout.write(JSON.stringify(out));
"""


def run_node(period_path: Path, config_path: Path, payload: dict,
             align_path: Path = ROOT / "web" / "period_align.js") -> dict:
    """把 cases 交给 node，取回 period.js 的实际输出。

    ``align_path`` 缺省用仓库的 ``web/period_align.js``；变异自证
    （``tools/period_selftest.py``）会把两个前端脚本都换成临时目录里的副本传进来。
    """
    with tempfile.TemporaryDirectory(prefix="swatch-period-") as tmp:
        cases_file = Path(tmp) / "cases.json"
        cases_file.write_text(json.dumps(payload), encoding="utf-8")
        proc = subprocess.run(
            ["node", "-e", NODE_DRIVER, str(period_path), str(config_path),
             str(cases_file), str(align_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"node 驱动失败: {proc.stderr.strip()}")
    return json.loads(proc.stdout)
