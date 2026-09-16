"""
L5 — 热力图桶的快照编解码。
============================
唯一职责：在"引擎内部的稀疏桶字典"与"可落盘的 ``columns`` 列表"之间来回翻译。

从 ``heatmap_engine.py`` 原样拆出（拆出原因：单文件 <400 行的机械门禁，
且"引擎状态与出矩阵"与"冷数据快照编解码"是两件事）。逻辑、注释均未改动。

两侧的形状
----------
::

    内部：{strike: {bucket_index: iv}}   +   breaks: set[bucket_index]
    落盘：[{bucket_index: int, ivs: {strike: iv}, break: bool}, ...]

本模块**不持有状态**：两个函数都只吃参数、吐结果。

依赖：无（纯标准库）。
"""

from __future__ import annotations

from typing import Any


def dump_bucket(buckets: dict[float, dict[int, float]], bucket_index: int) -> dict[float, float]:
    """
    提取某一桶的原始 IV 字典 ``{strike: iv}``，**键按行权价降序**。

    只返回该桶有值的档位；空桶返回空字典。供 ``AsyncPersistenceWriter``
    序列化写入 SQLite。

    为什么要在这里排序
    ------------------
    ``buckets`` 的键序是**首次出现顺序**，不是排序结果：现价先上移、再
    回落到会话初低点之下时，更低的档位会被追加到字典末尾（实测 ±12 档下
    一次 7700→7820→7600 的往返即可复现）。JSON 对象的键序会被原样写进
    ``ivs_json``，而 ``recover()`` / ``load_snapshot()`` 都不重排 —— 乱序
    会落盘并被继承下去。直接读 ``data/sessions/<到期日>.db`` 的人（或脚本）
    若默认"键序即降序"，就会静默错配行号。

    排一次序，把这条不变量收回到快照的产出点，让落盘产物与内部字典的
    历史无关。由 ``tools/check_persistence.py`` 的键序用例守住。

    为什么是**降序**（2026-09-13 统一）
    ----------------------------------
    对外帧的 ``strikes`` 与屏幕自上而下都是降序（见 ``HeatmapEngine.build()``
    与 ``web/heatmap.js`` 的 ``yAxis.inverse``）。冷数据一度是升序，与帧方向
    相反 —— 同一个系统里两处行序相反，读代码的人迟早串味。现在两边同向：
    **高行权价在前**。冷数据仍是内部恢复产物（键序不影响 ``buckets`` 的
    查找，``build()`` 自己会显式排序），统一只为消除这层反向语义。
    """
    out: dict[float, float] = {}
    for strike in sorted(buckets, reverse=True):
        iv = buckets[strike].get(bucket_index)
        if iv is not None:
            out[float(strike)] = float(iv)
    return out


def load_snapshot(
    buckets: dict[float, dict[int, float]],
    breaks: set[int],
    columns: list[dict[str, Any]],
) -> None:
    """
    从持久化存储恢复原始 IV 桶（**原地写入**传入的两个容器）。

    ``columns`` 格式：
    ``[{bucket_index: int, ivs: {float(strike): float}, break: bool}, ...]``

    恢复后 ``breaks`` 同时重建，但**不恢复任何差分产物**（ΔIV 在
    ``build()`` 时按当前上下文重新计算）。

    为什么原地改而不是返回新字典
    ----------------------------
    调用方（``HeatmapEngine.load_snapshot``）必须先 ``clear()`` 再灌入，
    两个容器要同时被替换。返回一个新字典会逼调用方自己赋值，多一次
    "忘了赋值"的机会。
    """
    buckets.clear()
    breaks.clear()
    for col in columns:
        idx = int(col["bucket_index"])
        if col.get("break"):
            breaks.add(idx)
        for strike_str, iv in col.get("ivs", {}).items():
            key = float(strike_str)
            bucket = buckets.setdefault(key, {})
            bucket[idx] = float(iv)
