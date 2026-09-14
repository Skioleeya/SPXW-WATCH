"""
L6 — 周期聚合回归的对照夹具。
==============================
唯一职责：为 ``tools/check_period_aggregation.py`` 提供三样东西 —— 确定性的
合成矩阵、独立的 Python 参考实现、以及取回 JS 结果的 node 驱动。

为什么单独一个文件：``check_*`` 脚本的正文应该是"怎么对照"，造数与参考实现是夹具。
混在一起会同时撑破 400 行上限与单一职能 —— 两条都是项目硬约束。

为什么参考实现另写一份，而不是直接调 ``web/period.js``：对拍的意义就在两侧**独立**。
这里刻意用最直白的写法（朴素双重循环 + 显式 null 传播），不图效率，只图"读一遍就能
确认它对"。唯一的例外是色标那一环 —— 它直接 import 生产代码
``serialization.numeric.robust_bound``：前端那份 ``bound()`` 是它的镜像，要钉住的正是
这个镜像有没有漂移，抄一份参考实现来对拍等于两边一起错，没有意义。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: 合成矩阵的形状。列数刻意取 125 —— 它能被 2/6/10/60 整除却不能被 30 整除，
#: 于是"末组不满"这条路径一定会被走到（125 = 4×30 + 5）。
ROWS = 6
COLS = 125
WIDE_COLS = 780
BASE_SECONDS = 30
OPEN_MINUTE = 9 * 60 + 30

#: 时段切列用例：一个 3 区段的小网格（GTH / 空档 / RTH），刻意与真实配置
#: 无关 —— 这里要钉的是"按 first/last 切列、空档整段消失"这条规则本身。
ZONE_COLS = 60
ZONE_TABLE: list[dict[str, Any]] = [
    {"id": "gth", "label": "GTH", "is_session": True,
     "first": 0, "last": 29, "open": "20:15", "close": "09:25"},
    {"id": "gap", "label": "空档", "is_session": False,
     "first": 30, "last": 33, "open": "09:25", "close": "09:30"},
    {"id": "rth", "label": "RTH", "is_session": True,
     "first": 34, "last": 59, "open": "09:30", "close": "16:00"},
]
ZONE_KEEPS: tuple[tuple[str, ...], ...] = (
    ("gth",),
    ("rth",),
    ("gth", "rth"),     # 全时段：空档不选，于是被整段切掉
    (),                 # 空列表 = 不切（恒等），前端要能容忍缺 zones
    ("nosuch",),        # 选了一个帧里没有的时段：必须返回空，前端保留上一帧
)

#: node 侧驱动：求值 config.js + period.js + period_align.js，把结果原样吐成 JSON。
#: 数据由 Python 生成后经临时文件传入 —— 两侧各自造数的话，"对拍对象其实不是
#: 同一个矩阵"这件事会悄无声息地让整组对照失效。
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
    vmax: r.vmax, bucket_seconds: r.bucket_seconds, bucket_index: r.bucket_index
  };
}

const cl = P.clipTail(cases.clip.block, cases.clip.maxColumns);
out.clip = {
  cols: cl.cols, labels: cl.labels, values: cl.values,
  bucket_index: cl.bucket_index,
  clipped: cl.clipped === undefined ? null : cl.clipped
};

for (const c of cases.slice.cases) {
  const r = P.sliceZones(c.block, cases.slice.zones, c.keep);
  out.slice[c.name] = r === null ? null : {
    cols: r.block.cols, labels: r.block.labels, values: r.block.values,
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


# --------------------------------------------------------------------------- #
# 合成数据
# --------------------------------------------------------------------------- #

def _label(index: int) -> str:
    total = OPEN_MINUTE * 60 + index * BASE_SECONDS
    hour, rest = divmod(total, 3600)
    minute, second = divmod(rest, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _cell(row: int, col: int) -> float | None:
    """造一格 ΔIV。

    ``null`` 只出现在**每行开头**（``col < row * 3``），模拟真实情形：某一档在它被
    第一次观测之前没有任何时间桶。于是既会产生"整组全空"的组（该行第一组），也会
    产生"组内部分为空"的组（第二组）—— 后者正是"少加了一段却报一个数"的易发处。
    """
    if col < row * 3:
        return None
    raw = ((row * 37 + col * 11) % 401) - 200      # 整数 [-200, 200]
    return round(raw / 100.0, 3)


def block(cols: int = COLS) -> dict[str, Any]:
    """造一个与后端帧同形状的基线矩阵（``strikes`` 降序，与真实帧一致）。"""
    return {
        "labels": [_label(c) for c in range(cols)],
        "strikes": [6400 + 5 * r for r in range(ROWS - 1, -1, -1)],
        "rights": ["P" if r % 2 else "C" for r in range(ROWS)],
        "values": [[_cell(r, c) for c in range(cols)] for r in range(ROWS)],
        "vmax": 3.25,
        "rows": ROWS,
        "cols": cols,
        "bucket_index": cols - 1,
        "bucket_seconds": BASE_SECONDS,
        "scale_policy": {"quantile": 0.95, "floor": 0.5},
        "spot": 6500.0,
    }


def cases() -> dict[str, Any]:
    """五组对照的全部输入。"""
    base = block()
    flat = [v for row in base["values"] for v in row if v is not None]

    bound_cases = [
        {"name": f"q{q}", "values": flat, "quantile": q, "floor": 0.5}
        for q in (0.0, 0.5, 0.9, 0.95, 1.0)
    ]
    bound_cases.append({"name": "empty", "values": [], "quantile": 0.95, "floor": 0.5})
    bound_cases.append(
        {"name": "floor", "values": [0.01, 0.02], "quantile": 1.0, "floor": 0.5}
    )

    return {
        # 0 是"非法基线桶宽"的探针：前端必须拒绝猜一个值，返回空列表
        "options": {"0": None, "20": None, "30": None, "60": None},
        "bound": bound_cases,
        "aggregate": [{"name": f"g{g}", "group": g, "block": base}
                      for g in (1, 2, 6, 10, 30, 60, 200)],
        "clip": {"block": block(WIDE_COLS), "maxColumns": 400},
        "slice": {
            "zones": ZONE_TABLE,
            "cases": [
                {"name": "keep=" + ("+".join(k) if k else "none"),
                 "block": block(ZONE_COLS), "keep": list(k)}
                for k in ZONE_KEEPS
            ],
        },
        "index": _index_case(),
    }


def _skew_series(buckets: list) -> dict[str, Any]:
    """造一条与帧同形状的 Skew 序列（只填 alignSkew 真正读的字段）。"""
    n = len(buckets)
    return {
        "bucket": list(buckets),
        "ts": [1000.0 + i for i in range(n)],
        "skew": [round(1.0 + i * 0.5, 3) for i in range(n)],
        "atm": [0.12] * n,
        "put25": [0.13] * n,
        "call25": [0.11] * n,
        "spot": [6500.0] * n,
    }


def _index_case() -> dict[str, Any]:
    """时段切列下 Skew 落列的对拍输入。

    ``series`` + ``index`` 是**真实路径**（帧里的原始桶号 + 切列映射）；``premapped``
    是"先把桶号换成切后位置、把被切掉的点丢掉"的等价序列；``raw`` 是**错误的做法**
    （拿原始桶号直接除，即忽略 index）—— 非空转判据。
    """
    base = block(ZONE_COLS)
    sliced = ref_slice_zones(base, ZONE_TABLE, ["gth", "rth"])
    if sliced is None:
        raise RuntimeError("切列夹具自坏：所选时段一列都没有")
    index = sliced["index"]

    # 每 7 个桶掺一个 null，覆盖"序列里有洞"的情形
    buckets = [None if i % 7 == 0 else i for i in range(ZONE_COLS)]
    raw = _skew_series(buckets)

    kept, values = [], []
    for i, b in enumerate(buckets):
        if b is None or index[b] < 0:
            continue
        kept.append(index[b])
        values.append(raw["skew"][i])
    premapped = _skew_series(kept)
    premapped["skew"] = values

    return {
        "series": raw,
        "raw": raw,
        "premapped": premapped,
        "index": index,
        "group": 3,
        "drop": 2,
        "labels": sliced["labels"],
    }


# --------------------------------------------------------------------------- #
# 参考实现
# --------------------------------------------------------------------------- #

def ref_group_label(label: str, group_seconds: int) -> str:
    if group_seconds % 60 == 0 and len(label) == 8 and label[5:] == ":00":
        return label[:5]
    return label


def ref_aggregate(base: dict, group: int) -> dict[str, Any]:
    """按 group 个基线桶并成一列：组内 ΔIV 相加；组内有一格为 null 则整组 null。"""
    labels, values = base["labels"], base["values"]
    cols, rows = len(labels), len(values)
    span = base["bucket_seconds"]
    out_cols = -(-cols // group)          # 整数向上取整

    out_values: list[list[float | None]] = []
    flat: list[float] = []
    for r in range(rows):
        row: list[float | None] = []
        for c in range(out_cols):
            chunk = values[r][c * group:min(c * group + group, cols)]
            if any(v is None for v in chunk):
                row.append(None)
                continue
            total = 0.0
            for v in chunk:
                total += v
            row.append(total)
            flat.append(total)
        out_values.append(row)

    return {
        "labels": [ref_group_label(labels[c * group], group * span)
                   for c in range(out_cols)],
        "values": out_values,
        "cols": out_cols,
        "rows": rows,
        "bucket_seconds": span * group,
        "bucket_index": base["bucket_index"] // group,
    }


def ref_clip(base: dict, limit: int) -> dict[str, Any]:
    """列数超上限时保留**最近**的 limit 列。"""
    cols = len(base["labels"])
    if cols <= limit:
        return {"cols": cols, "labels": base["labels"], "values": base["values"],
                "bucket_index": base["bucket_index"], "clipped": None}
    drop = cols - limit
    return {
        "cols": limit,
        "labels": base["labels"][drop:],
        "values": [row[drop:] for row in base["values"]],
        "bucket_index": base["bucket_index"] - drop,
        "clipped": drop,
    }


def ref_slice_zones(
    base: dict, zones: list, keep_ids: list
) -> dict[str, Any] | None:
    """只保留所选区段覆盖的列，其余整列切掉。

    ``keep_ids`` 为空 = 不切（恒等，前端在帧缺 ``session.zones`` 时走这条路）；
    所选区段一列都没有时返回 ``None``（前端据此保留上一帧）。
    """
    cols = len(base["labels"])
    if not keep_ids:
        return {"cols": cols, "labels": list(base["labels"]),
                "values": [list(row) for row in base["values"]],
                "bucket_index": base["bucket_index"],
                "index": list(range(cols))}

    keep = set(keep_ids)
    index = [-1] * cols
    labels: list = []
    picked: list[int] = []
    for zone in zones:
        if zone["id"] not in keep:
            continue
        first = max(0, int(zone["first"]))
        last = min(cols - 1, int(zone["last"]))
        for c in range(first, last + 1):
            index[c] = len(labels)
            labels.append(base["labels"][c])
            picked.append(c)
    if not labels:
        return None

    here = index[base["bucket_index"]]
    if here < 0:
        here = len(labels) - 1
    return {
        "cols": len(labels),
        "labels": labels,
        "values": [[row[c] for c in picked] for row in base["values"]],
        "bucket_index": here,
        "index": index,
    }


def ref_align_indexed(
    series: dict, group: int, cols: int, drop: int, index: list
) -> list:
    """带时段映射的 Skew 落列：桶号先经 ``index`` 换成切后位置（-1 = 已切掉），
    再走"整除 + 平移"。等价于"把序列预映射一遍再走普通公式"。
    """
    out: list = [None] * cols
    for i, b in enumerate(series["bucket"]):
        if b is None or b < 0:
            continue
        pos = index[b] if b < len(index) else -1
        if pos < 0:
            continue
        col = pos // group - drop
        if 0 <= col < cols:
            out[col] = series["skew"][i]
    return out


# --------------------------------------------------------------------------- #
# node 驱动
# --------------------------------------------------------------------------- #

def run_node(period_path: Path, config_path: Path, payload: dict,
             align_path: Path = ROOT / "web" / "period_align.js") -> dict:
    """把 cases 交给 node，取回 period.js 的实际输出。

    ``align_path`` 缺省用仓库的 ``web/period_align.js``（变异只复制 period.js）。
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
