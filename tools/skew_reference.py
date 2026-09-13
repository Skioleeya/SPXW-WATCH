"""
L6 — Skew 周期对齐回归的对照夹具。
==================================
唯一职责：为 ``tools/check_skew_alignment.py`` 提供三样东西 —— 确定性的合成帧
（**走生产编码器**，与真实线上帧同形状）、独立的 Python 参考实现、以及取回 JS
结果的 node 驱动。

为什么需要这个回归
------------------
周期切换要求"IV 热力图与 Skew 折线按同一个周期标签显示同一段时间"。两块图的列
网格由热力图产出（``period.js::aggregate`` + ``clipTail``），Skew 再对齐过去
（``period.js::alignSkew``）。这条链上任何一环错位都**不会报错**，只会让上下两块
图的横坐标指向不同时刻 —— 正是本项目最怕的"静默出错值"。

为什么帧要走生产编码器
----------------------
热力图数值块在线上是「位图 + 定标整数」，前端先 ``decodeFrame`` 还原成
``block.values`` 再聚合。夹具若直接造一个带 ``values`` 的块，就绕开了这条真实
路径：``aggregate`` 在 ``!block.values`` 时会**原样返回整块**（30 秒视图列数
780、列宽 30s），聚合悄悄不发生，而所有对齐断言仍会通过。夹具因此必须编码。

为什么要参考实现而不是直接调 ``alignSkew``
------------------------------------------
对拍的意义在两侧独立。这里用最直白的写法（朴素双重循环、显式越界判断），不图
效率，只图"读一遍就能确认它对"。
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts.enums import OptionRight, Quality  # noqa: E402
from contracts.feature import HeatmapMatrix, SkewPoint  # noqa: E402
from core.clock import SessionClock  # noqa: E402
from serialization.heatmap_matrix import HeatmapSerializer  # noqa: E402
from serialization.skew_series import SkewSerializer  # noqa: E402

#: 整会话 30 秒粒度 = 780 列。夹具刻意**不**用整张交易日网格（2370 列）：这里
#: 要钉的是"周期对齐 + 尾部截断"这条链，网格越小越容易把别的东西混进来。
#: 时段切列（GTH/空档/RTH）由 tools/check_period_aggregation.py 单独覆盖。
BUCKETS = 780
BASE_SECONDS = 30
ROWS = 24

#: 夹具自己指定的列数上限。**不读** web/config.js 的 maxColumns —— 那个值现在
#: 大到"一个交易日内永不生效"，拿它做上限会让 clipTail 这条路径彻底空转，
#: 于是"漏掉截断偏移"这类缺陷再也抓不到。上限只对"截断这件事"有意义，
#: 取多少由夹具决定；真实值够不够大由 check_period_aggregation 的跨文件
#: 不变量单独核对。
CLIP_COLUMNS = 400

#: 尖峰所在基线桶。刻意放得很早：这样它会**退出** ``skew.scale_policy.window_s``
#: 定义的量程窗口，量程窗口开着与关掉才会有可观测差异（否则该判据是空转）。
SPIKE_AT = 100
SPIKE_VALUE = 9.0

#: node 侧驱动：按 ``app.js::render()`` 的真实顺序求值
#: ``decodeFrame → aggregate → clipTail → alignSkew → SkewPanel.update``。
NODE_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const webDir = process.argv[1];
const framePath = process.argv[2];

const sandbox = {
  console: console,
  atob: atob,
  echarts: { init: function () {
    return { setOption: function () {}, resize: function () {}, clear: function () {} };
  } },
  addEventListener: function () {},
  document: { getElementById: function () { return {}; } }
};
sandbox.window = sandbox;
const ctx = vm.createContext(sandbox);

for (const f of ["config.js", "matrix_codec.js", "period.js", "skew.js"]) {
  vm.runInContext(fs.readFileSync(webDir + "/" + f, "utf8"), ctx, { filename: f });
}

const S = sandbox;
const P = S.SWATCH_PERIOD;
const CFG = S.SWATCH_CONFIG;
const F = S.SWATCH_MATRIX.decodeFrame(JSON.parse(fs.readFileSync(framePath, "utf8")));
/* 列数上限由夹具给（见 skew_reference.CLIP_COLUMNS），缺省才退回配置值 */
const MAX_COLS = Number(process.argv[3]) || CFG.heatmap.maxColumns;

const out = {
  base: F.heatmap.bucket_seconds,
  maxColumns: MAX_COLS,
  heatCols: F.heatmap.cols,
  decoded: !!F.heatmap.values,
  periods: {}, window: null
};

for (const opt of P.options(out.base)) {
  const group = opt.group;
  const view = P.clipTail(P.aggregate(F.heatmap, group), MAX_COLS);
  const drop = view.clipped || 0;
  const a = P.alignSkew(F.skew.series, group, { labels: view.labels, drop: drop });
  const info = new S.SkewPanel({}).update(a, F.skew.scale_policy);
  out.periods[String(opt.seconds)] = {
    group: group,
    cols: view.labels.length,
    bucket_seconds: view.bucket_seconds,
    drop: drop,
    labels: view.labels,
    ts: a.ts,
    skew: a.skew,
    filled: a.skew.filter(function (v) { return v !== null; }).length,
    points: info.points,
    panelCols: info.cols,
    range: info.range
  };
}

/* 量程窗口：用**不裁剪**的全序列网格，否则尖峰会被 clipTail 裁掉、判据空转 */
const full = P.aggregate(F.heatmap, 1);
const aFull = P.alignSkew(F.skew.series, 1, { labels: full.labels, drop: 0 });
out.window = {
  cols: aFull.label.length,
  spikeCol: aFull.skew.indexOf(9),
  on: new S.SkewPanel({}).update(aFull, { window_s: 3600 }).range,
  off: new S.SkewPanel({}).update(aFull, { window_s: 0 }).range
};

process.stdout.write(JSON.stringify(out));
"""


# --------------------------------------------------------------------------- #
# 合成帧
# --------------------------------------------------------------------------- #

def _app_config() -> dict:
    return json.loads((ROOT / "config" / "app.json").read_text("utf-8"))


def _serial_config() -> dict:
    """序列化配置 —— 两个序列化器的构造参数（``HeatmapSerializer`` 单参、
    ``SkewSerializer`` 双参）。与 ``app.json`` 分开读：会话定义与推送帧形状
    是两个不同层级的真相，不从一个文件里取两样东西。"""
    return json.loads((ROOT / "config" / "serialization.json").read_text("utf-8"))


def build() -> tuple[dict, dict]:
    """造一整个帧（热力图**经生产编码器**编码）+ 供参考实现用的源序列。"""
    cfg = _serial_config()
    app = _app_config()
    # 会话定义取自 config/app.json（时段真相的唯一归属），网格起点由产品时钟
    # 算出来 —— 夹具不自己推"网格从哪一刻开始"，那是把几何抄第二份。
    clock = SessionClock(
        str(app["timezone"]), list(app["sessions"]), BASE_SECONDS
    )
    open_dt = clock.grid_start_dt()

    labels = clock.bucket_labels()[:BUCKETS]
    #: strikes 降序 —— 与真实帧一致（帧与屏幕同向，见项目 MEMORY）
    strikes = tuple(6500.0 + 5 * i for i in range(ROWS // 2 - 1, -ROWS // 2 - 1, -1))
    values = tuple(
        tuple(
            # 尾部故意留空洞：验证 null 传播
            None if (c > 600 and r % 3 == 0)
            else round(math.sin(c / 9.0 + r) * 1.8, 3)
            for c in range(BUCKETS)
        )
        for r in range(ROWS)
    )

    matrix = HeatmapMatrix(
        strikes=strikes,
        rights=tuple(OptionRight.PUT if s < 6500 else OptionRight.CALL for s in strikes),
        bucket_labels=tuple(labels),
        values=values,
        bucket_index=BUCKETS - 1,
        spot=6500.0,
    )

    ts: list[float] = []
    skew: list[float] = []
    points: list[SkewPoint] = []
    for i in range(BUCKETS):
        v = SPIKE_VALUE if i == SPIKE_AT else round(0.4 + 0.35 * math.sin(i / 30.0), 3)
        stamp = (open_dt + timedelta(seconds=BASE_SECONDS * i)).timestamp()
        ts.append(stamp)
        skew.append(v)
        points.append(SkewPoint(
            ts=stamp,
            spot=6500.0 + 3 * math.sin(i / 50.0),
            atm_iv=0.12,
            put25_iv=0.12 + v / 200.0,
            call25_iv=0.12 - v / 200.0,
            skew_25d_vol_points=v,
            butterfly_vol_points=round(v / 4.0, 3),
            quality=Quality.OK,
        ))

    heat_ser = HeatmapSerializer(cfg)
    skew_ser = SkewSerializer(cfg, clock)
    frame = {
        "heatmap": heat_ser.encode(matrix),
        "skew": {
            "series": skew_ser.encode_series(points),
            "latest": skew_ser.encode_latest(points[-1]),
            "scale_policy": skew_ser.scale_policy,
        },
    }
    source = {
        "bucket": list(frame["skew"]["series"]["bucket"]),
        "ts": ts,
        "skew": skew,
        "open_ts": ts[0],
        "bucket_seconds": BASE_SECONDS,
        "cols": BUCKETS,
    }
    return frame, source


# --------------------------------------------------------------------------- #
# 参考实现
# --------------------------------------------------------------------------- #

def ref_align(source: dict, group: int, cols: int, drop: int) -> dict[str, Any]:
    """
    把 Skew 序列铺到 ``cols`` 列网格上：桶 ``b`` 落到第 ``b // group - drop`` 列，
    组内**末值**胜出（后写的覆盖先写的）。

    与 ``web/period.js::alignSkew`` 的差别只在于写法：这里用最直白的循环，
    越界判断写全，方便人读。
    """
    ts: list[Any] = [None] * cols
    skew: list[Any] = [None] * cols
    for i, b in enumerate(source["bucket"]):
        if b is None or b < 0:
            continue
        col = b // group - drop
        if col < 0 or col >= cols:
            continue
        ts[col] = source["ts"][i]
        skew[col] = source["skew"][i]
    return {
        "ts": ts,
        "skew": skew,
        "filled": sum(1 for v in skew if v is not None),
    }


def ref_column_span(col: int, group: int, drop: int) -> tuple[int, int]:
    """第 ``col`` 列覆盖的基线桶区间 ``[lo, hi)`` —— 取自 ``aggregate`` 的取数口径。"""
    lo = (col + drop) * group
    return lo, lo + group


# --------------------------------------------------------------------------- #
# node 驱动
# --------------------------------------------------------------------------- #

def run_node(frame: dict) -> dict:
    """把合成帧交给 node，取回真实前端在各周期下的对齐结果。"""
    return run_node_in(frame, ROOT / "web", CLIP_COLUMNS)


def run_node_in(frame: dict, web_dir: Path, max_columns: int = CLIP_COLUMNS) -> dict:
    """
    同上，但前端目录与列数上限可指定 —— ``--selftest`` 用前者加载被注入缺陷的
    副本，免得为了跑一次变异去改动工程里的真实文件；后者让"截断"这条路径在
    夹具里可控（真实的 maxColumns 大到永不生效，见 CLIP_COLUMNS 的说明）。
    """
    with tempfile.TemporaryDirectory(prefix="swatch-skew-") as tmp:
        frame_file = Path(tmp) / "frame.json"
        frame_file.write_text(json.dumps(frame), encoding="utf-8")
        proc = subprocess.run(
            ["node", "-e", NODE_DRIVER, str(web_dir), str(frame_file),
             str(int(max_columns))],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"node 驱动失败: {proc.stderr.strip()}")
    return json.loads(proc.stdout)
