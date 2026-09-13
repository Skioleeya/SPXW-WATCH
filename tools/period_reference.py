"""
L6 — 周期聚合回归的对照夹具。
==============================
唯一职责：为 ``tools/check_period_aggregation.py`` 提供三样东西 —— 确定性的
合成矩阵、独立的 Python 参考实现、以及取回 JS 结果的 node 驱动。

为什么单独一个文件：``check_*`` 脚本的正文应该是"怎么对照"，造数与参考实现是
夹具。混在一起会同时撑破 400 行上限与单一职能 —— 两条都是项目硬约束。

为什么参考实现另写一份，而不是直接调 ``web/period.js``
------------------------------------------------------
对拍的意义就在两侧**独立**。这里刻意用最直白的写法（朴素双重循环 + 显式 null
传播），不图效率，只图"读一遍就能确认它对"。

唯一的例外是色标那一环：它直接 import 生产代码
``serialization.numeric.robust_bound``。前端那份 ``bound()`` 是它的镜像，要钉住的
正是这个镜像有没有漂移 —— 抄一份参考实现来对拍等于两边一起错，没有意义。
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

#: node 侧驱动：求值 config.js + period.js，把结果原样吐成 JSON。
#: 数据由 Python 生成后经临时文件传入 —— 两侧各自造数的话，"对拍对象其实不是
#: 同一个矩阵"这件事会悄无声息地让整组对照失效。
NODE_DRIVER = r"""
const fs = require("fs");
const periodPath = process.argv[1];
const configPath = process.argv[2];
const casesPath = process.argv[3];

const window = { console: console };
eval(fs.readFileSync(configPath, "utf8"));
eval(fs.readFileSync(periodPath, "utf8"));

const P = window.SWATCH_PERIOD;
const cfg = window.SWATCH_CONFIG;
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));

const out = {
  declared: (cfg.heatmap && cfg.heatmap.periods) || [],
  maxColumns: cfg.heatmap ? cfg.heatmap.maxColumns : null,
  options: {}, bound: {}, aggregate: {}, clip: null
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
    """
    造一格 ΔIV。

    ``null`` 只出现在**每行开头**（``col < row * 3``），模拟真实情形：某一档在
    它被第一次观测之前没有任何时间桶。于是既会产生"整组全空"的组（该行第一
    组），也会产生"组内部分为空"的组（第二组）—— 后者正是"少加了一段却报一个
    数"最容易发生的地方。
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
    """四组对照的全部输入。"""
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


# --------------------------------------------------------------------------- #
# node 驱动
# --------------------------------------------------------------------------- #

def run_node(period_path: Path, config_path: Path, payload: dict) -> dict:
    """把 cases 交给 node，取回 period.js 的实际输出。"""
    with tempfile.TemporaryDirectory(prefix="swatch-period-") as tmp:
        cases_file = Path(tmp) / "cases.json"
        cases_file.write_text(json.dumps(payload), encoding="utf-8")
        proc = subprocess.run(
            ["node", "-e", NODE_DRIVER, str(period_path), str(config_path),
             str(cases_file)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"node 驱动失败: {proc.stderr.strip()}")
    return json.loads(proc.stdout)
