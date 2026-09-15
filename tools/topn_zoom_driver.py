"""
L6 — 热力图 Top-N 与 Skew Y 轴缩放的 **node 驱动**。
=====================================================
从 ``tools/check_heatmap_topn_skew_zoom.py`` 拆出（2026-09-15）：那里管"判据"，这里管
"把前端脚本跑起来、取回结果"—— 前者是断言，后者要起子进程、建临时目录，属 IO。
混在一个文件里会撑破 400 行上限（项目硬约束 #1：文件 < 400 行）。

驱动本体是 ``DRIVER_BODY``：拼在 ``skew_reference.SANDBOX_JS`` 之后，做两件事 ——

① 用**成交量已知**的合成块走 ``HeatmapPanel.update``，从收到的 option 上读每格的
   ``itemStyle.borderWidth``。不用真帧是因为真帧的成交量排序每帧都在变，断言只能
   写成"有 3 格被描边"这种弱条件 —— 而对拍的价值恰恰在"**哪** 3 格"。
② 直接调 ``SKEW`` 的纯函数验缩放数学（无限制缩放、锚点、边界夹取、退化输入、
   随机扫），外加锁定量程不被数据覆盖、``dataZoom`` 不碰 Y 轴。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from tools import skew_reference as ref  # noqa: E402

#: 合成矩阵的形状。成交量取 ``vol = r * cols + c`` ⇒ 最大的 N 格位置完全可预测
#: （右下角起倒数），于是判据能断言"**哪** 3 格"而不只是"有 3 格"。
TOPN_ROWS = 6
TOPN_COLS = 8

DRIVER_BODY = r"""
const ROWS = __ROWS__, COLS = __COLS__;
const vt = CFG.heatmap.volumeTop;

const values = [], volumes = [], labels = [];
for (let c = 0; c < COLS; c++) { labels.push("t" + c); }
for (let r = 0; r < ROWS; r++) {
  const vr = [], vv = [];
  for (let c = 0; c < COLS; c++) { vr.push(0.5); vv.push(r * COLS + c); }
  values.push(vr); volumes.push(vv);
}

/* ---- ① Top-N 高亮：走 HeatmapPanel.update 真路径 ---- */
let lastOption = null;
const heatEl = { getBoundingClientRect: function () {
  return { width: 1200, height: 600 };
} };
const panel = new S.HeatmapPanel(heatEl);
panel._chart.setOption = function (opt) { lastOption = opt; };
panel.update({
  strikes: [100, 101, 102, 103, 104, 105],
  rights: ["C", "C", "C", "C", "C", "C"],
  labels: labels, values: values, volumes: volumes, vmax: 1
}, 103);

const cells = [];
for (const item of lastOption.series[0].data) {
  const bare = Array.isArray(item);
  const styled = !bare && !!(item.itemStyle && item.itemStyle.borderWidth > 0);
  const c = bare ? item[0] : item.value[0];
  const r = bare ? item[1] : item.value[1];
  cells.push({ c: c, r: r, w: styled ? item.itemStyle.borderWidth : 0,
               styled: styled, bare: bare });
}

out.topn = {
  cfg: { topN: vt.topN, enabled: vt.enabled !== false, color: vt.color,
         maxRatio: vt.maxRatio, minRatio: vt.minRatio },
  total: cells.length,
  styledCount: cells.filter(function (x) { return x.styled; }).length,
  styled: cells.filter(function (x) { return x.styled; })
    .map(function (x) { return { c: x.c, r: x.r, w: x.w, vol: x.r * COLS + x.c }; }),
  bareNonStyled: cells.filter(function (x) { return !x.styled && x.bare; }).length,
  nonStyledCount: cells.filter(function (x) { return !x.styled; }).length,
  /* 格短边 —— 判据用它换算宽度是否落在 maxRatio/minRatio 区间里 */
  cellShort: Math.min((1200 - 66 - 84) / COLS, (600 - 10 - 28) / ROWS)
};

/* ---- ② Y 轴缩放纯函数 ---- */
const Z = CFG.skew.yZoom;
const H = S.SKEW;
function span(r) { return r[1] - r[0]; }

const base = [-1, 3];
const zin = H.zoomRange(base, 1 / Z.step, 1);
let rIn = base.slice();
for (let i = 0; i < 60; i++) { rIn = H.zoomRange(rIn, 1 / Z.step, (rIn[0] + rIn[1]) / 2); }
let rOut = base.slice();
for (let i = 0; i < 60; i++) { rOut = H.zoomRange(rOut, Z.step, (rOut[0] + rOut[1]) / 2); }

/* 退化输入：从窄于下限的量程继续放大；锚点压在两端边界上；锚点落到量程外 */
const degNarrow = H.zoomRange([0, 0.01], 0.1, 0);
const edgeLo = H.zoomRange([2.50, 2.53], 1 / Z.step, 2.50);
const edgeHi = H.zoomRange([2.50, 2.53], 1 / Z.step, 2.53);
const outside = H.zoomRange([2.50, 2.53], 1 / Z.step, 99);

/* 随机扫：任何输入都不得产出 span<=0 / NaN / 超上限 */
let bad = 0, n4k = 4000;
for (let i = 0; i < n4k; i++) {
  const a = (Math.random() - 0.5) * 200;
  const s = Math.random() * 20;
  const f = Math.pow(10, (Math.random() - 0.5) * 4);
  const anc = Math.random() < 0.3 ? null : (a - s) + Math.random() * s * 2;
  const o = H.zoomRange([a, a + s], f, anc);
  const sp = o[1] - o[0];
  if (!(sp > 0) || !isFinite(sp) || sp > Z.maxSpan + 1e-6) { bad += 1; }
}

/* 锁定量程：用真帧的 Skew 序列 */
const full = P.aggregate(F.heatmap, 1);
const aFull = P.alignSkew(F.skew.series, 1, { labels: full.labels, drop: 0 });
const series = { skew: aFull.skew };

out.yzoom = {
  cfg: { step: Z.step, minSpan: Z.minSpan, maxSpan: Z.maxSpan },
  baseSpan: span(base),
  inSpan: span(zin),
  outSpan: span(H.zoomRange(base, Z.step, 1)),
  anchorBase: (1 - base[0]) / span(base),
  anchorIn: (1 - zin[0]) / span(zin),
  tinySpan: span(rIn),
  hugeSpan: span(rOut),
  degNarrowSpan: span(degNarrow),
  edgeLoSpan: span(edgeLo),
  edgeHiSpan: span(edgeHi),
  outsideCenter: (outside[0] + outside[1]) / 2,
  outsideIsCenter: Math.abs((outside[0] + outside[1]) / 2 - 2.515) < 1e-9,
  randomBad: bad, randomTrials: n4k,
  autoRange: H.effectiveRange(series, null, null),
  lockedRange: H.effectiveRange(series, null, [0, 5]),
  lockedStable: H.effectiveRange(series, null, [0, 5])[1] === 5,
  decimalsWide: H.axisDecimalsFor([-1, 3]),
  decimalsNarrow: H.axisDecimalsFor([2.50, 2.55]),
  decimalsCapped: H.axisDecimalsFor([2.5, 2.5000001])
};

/* ---- ③ X 轴：dataZoom 不得碰 Y ---- */
const opt = S.buildSkewFullOption([], labels, null, COLS, [-1, 3]);
out.axes = {
  xAxisIndex: opt.dataZoom[0].xAxisIndex,
  hasYAxisIndex: opt.dataZoom[0].yAxisIndex !== undefined,
  y0min: opt.yAxis[0].min,
  y0max: opt.yAxis[0].max
};

process.stdout.write(JSON.stringify(out));
"""


def driver_js() -> str:
    """沙箱 + 驱动体，形状参数已代入。"""
    return (ref.SANDBOX_JS + DRIVER_BODY
            .replace("__ROWS__", str(TOPN_ROWS))
            .replace("__COLS__", str(TOPN_COLS)))


def run_node(payload: dict, web_dir: Path | None = None) -> dict:
    """在沙箱里跑前端脚本，取回 Top-N 选中结果与 Y 缩放数学结果。

    ``web_dir`` 缺省用仓库的 ``web/``；变异自证会传一个临时目录进来，
    里面是被改坏的前端脚本副本。
    """
    with tempfile.TemporaryDirectory(prefix="swatch-topn-zoom-") as tmp:
        frame_file = Path(tmp) / "frame.json"
        frame_file.write_text(json.dumps(payload), encoding="utf-8")
        proc = subprocess.run(
            ["node", "-e", driver_js(), str(web_dir or (ROOT / "web")),
             str(frame_file), str(ref.CLIP_COLUMNS)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"node 驱动失败: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


#: 供检查器与变异自证共用的前端脚本清单（含 heatmap.js）。
WEB_FILES: tuple[str, ...] = tuple(ref.WEB_SCRIPTS) + ("heatmap.js",)
