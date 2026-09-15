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

#: 跑 JS 取结果的驱动已拆到 tools/period_node.py（IO 与造数分离，
#: 原文件因此超 400 行上限）。re-export 以免改动调用点。
from tools.period_node import run_node  # noqa: F401

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


def _vol(row: int, col: int) -> int | None:
    """造一格成交量（tick 计数）。

    ``null`` 的位置**刻意与** ``_cell`` **不同**（这里落在 ``col % 7 == 3``），
    因为两者聚合规则不同，必须能被区分开：

    * ``values``：组内**任一** null ⇒ 整组 null（ΔIV 少加一段会得到偏小的假数）
    * ``volumes``：组内 null 当缺席，**求和其余**；整组全 null 才给 null

    若两者用同一套 null 布局，上面对拍就分不出"规则被写成了同一条"。
    """
    if col % 7 == 3:
        return None
    return (row * 13 + col * 7) % 50


def block(cols: int = COLS) -> dict[str, Any]:
    """造一个与后端帧同形状的基线矩阵（``strikes`` 降序，与真实帧一致）。"""
    return {
        "labels": [_label(c) for c in range(cols)],
        "strikes": [6400 + 5 * r for r in range(ROWS - 1, -1, -1)],
        "rights": ["P" if r % 2 else "C" for r in range(ROWS)],
        "values": [[_cell(r, c) for c in range(cols)] for r in range(ROWS)],
        "volumes": [[_vol(r, c) for c in range(cols)] for r in range(ROWS)],
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
    """按 group 个基线桶并成一列：组内 ΔIV 相加；组内有一格为 null 则整组 null。

    **只输出已走满的组（2026-09-15 修）** —— 末尾凑不满 group 个基线桶的那一组
    整组丢弃。旧版用 ``ceil`` 把它也输出，于是"周期变化量"在周期还没结束时就
    随每个 tick 变化（右端点是未走完的当前桶），跨周期那一刻还会先渲染 +0。
    语义定稿：周期走满才出列，出列即定稿 ``IV(T+period) − IV(T)``。

    与 ``web/period.js::aggregate`` 逐值对拍 —— 两处必须同步改，漂移即 FAIL。
    """
    labels, values = base["labels"], base["values"]
    cols, rows = len(labels), len(values)
    span = base["bucket_seconds"]
    out_cols = cols // group                 # 整除，丢掉不完整的末组

    # 连一个完整周期都没走满（周期比整个交易日网格还长）：给空矩阵。
    # 元字段与正常分支同口径 —— bucket_index 一律除以 group，vmax 由聚合后的
    # 数值重算；此刻无量程可算，退到 scale_policy.floor。与前端逐字段对齐。
    if out_cols < 1:
        policy = base.get("scale_policy") or {}
        floor = policy.get("floor")
        return {
            "labels": [],
            "values": [[] for _ in range(rows)],
            "volumes": ([[] for _ in range(rows)]
                        if base.get("volumes") else None),
            "vmax": float(floor) if isinstance(floor, (int, float)) and floor > 0 else 0.0,
            "cols": 0,
            "rows": rows,
            "bucket_seconds": span * group,
            "bucket_index": base["bucket_index"] // group,
        }

    out_values: list[list[float | None]] = []
    flat: list[float] = []
    for r in range(rows):
        row: list[float | None] = []
        for c in range(out_cols):
            chunk = values[r][c * group:(c + 1) * group]
            if any(v is None for v in chunk):
                row.append(None)
                continue
            total = 0.0
            for v in chunk:
                total += v
            row.append(total)
            flat.append(total)
        out_values.append(row)

    # volumes 与 values 的规则**不同**：null 当缺席，求和其余；全 null 才给 null。
    # 与前端 web/period.js::aggregate 的对应分支逐值对拍。
    src_volumes = base.get("volumes")
    out_volumes: list[list[int | None]] | None = None
    if src_volumes:
        out_volumes = []
        for r in range(rows):
            src = src_volumes[r] if r < len(src_volumes) else []
            row_v: list[int | None] = []
            for c in range(out_cols):
                chunk = src[c * group:(c + 1) * group]
                known = [v for v in chunk if v is not None]
                row_v.append(sum(known) if known else None)
            out_volumes.append(row_v)

    return {
        "labels": [ref_group_label(labels[c * group], group * span)
                   for c in range(out_cols)],
        "values": out_values,
        "volumes": out_volumes,
        "cols": out_cols,
        "rows": rows,
        "bucket_seconds": span * group,
        "bucket_index": base["bucket_index"] // group,
    }


def ref_clip(base: dict, limit: int) -> dict[str, Any]:
    """列数超上限时保留**最近**的 limit 列。"""
    cols = len(base["labels"])
    src_volumes = base.get("volumes")
    if cols <= limit:
        return {"cols": cols, "labels": base["labels"], "values": base["values"],
                "volumes": [list(row) for row in src_volumes] if src_volumes else None,
                "bucket_index": base["bucket_index"], "clipped": None}
    drop = cols - limit
    return {
        "cols": limit,
        "labels": base["labels"][drop:],
        "values": [row[drop:] for row in base["values"]],
        "volumes": [row[drop:] for row in src_volumes] if src_volumes else None,
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
    src_volumes = base.get("volumes")
    if not keep_ids:
        return {"cols": cols, "labels": list(base["labels"]),
                "values": [list(row) for row in base["values"]],
                "volumes": [list(row) for row in src_volumes] if src_volumes else None,
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
        "volumes": ([[row[c] for c in picked] for row in src_volumes]
                    if src_volumes else None),
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
