"""
L4 — 推送帧编码器。
===================
唯一职责：把 ``Frame``（L0 契约对象）编码成可以直接 ``json.dumps`` 的字典，
以及最终的 JSON 文本。

分工
----
``Frame`` 是**语义**结构（用不可变对象表达"这一帧是什么"）；
本模块负责**表示**结构（用字典/文本表达"怎么发出去"）。两者分开的好处是：
传输层拿到的是成品字符串，不需要知道任何字段名。

``allow_nan=False``
-------------------
刻意关闭 NaN 输出。Python 默认会把 NaN 写成裸 ``NaN``，那是**非法 JSON**，
浏览器 ``JSON.parse`` 会直接抛错、整条推送链路静默死掉。关掉之后，一旦有
漏网的 NaN 会在服务端立刻炸出来，而不是在前端变成一片空白。

依赖：L0、L4（各编码器 / numeric）。
"""

from __future__ import annotations

import json
from typing import Any

from config import loader
from contracts.enums import ConnectionState, FeedMode
from contracts.frame import Frame, HealthBlock, SessionBlock

from serialization.cell_encoder import CellSerializer
from serialization.heatmap_matrix import HeatmapSerializer
from serialization.numeric import round_opt
from serialization.skew_series import SkewSerializer

_CFG = "serialization"


class FrameEncoder:
    """Frame → dict / JSON 文本。"""

    __slots__ = ("_heatmap", "_skew", "_cells", "_price_decimals")

    def __init__(self, serial_cfg: dict, clock) -> None:
        self._heatmap = HeatmapSerializer(serial_cfg)
        self._skew = SkewSerializer(serial_cfg, clock)
        self._cells = CellSerializer(serial_cfg)
        self._price_decimals = loader.as_int(serial_cfg, "price_decimals", module=_CFG)

    # ------------------------------------------------------------------ #
    # 编码
    # ------------------------------------------------------------------ #

    def encode(self, frame: Frame) -> dict[str, Any]:
        return {
            "type": "frame",
            "seq": int(frame.seq),
            "ts": round(float(frame.ts), 3),
            "spot": round(float(frame.spot), self._price_decimals),
            "session": self._session(frame.session),
            "health": self._health(frame.health),
            "atm": self._skew.encode_atm(frame.atm),
            "heatmap": self._heatmap.encode(frame.heatmap),
            "skew": {
                "series": self._skew.encode_series(frame.skew_series),
                "latest": self._skew.encode_latest(
                    frame.skew_series[-1] if frame.skew_series else None
                ),
            },
            "cells": self._cells.encode(frame.cells),
        }

    def dumps(self, frame: Frame) -> str:
        return json.dumps(
            self.encode(frame),
            separators=(",", ":"),
            allow_nan=False,
        )

    # ------------------------------------------------------------------ #
    # 子块
    # ------------------------------------------------------------------ #

    @staticmethod
    def _session(block: SessionBlock) -> dict[str, Any]:
        return {
            "date": block.date,
            "expiry": block.expiry,
            "open": block.open,
            "close": block.close,
            "is_open": bool(block.is_open),
            "elapsed_s": round(float(block.elapsed_s), 1),
            "seconds_to_close": round(float(block.seconds_to_close), 1),
            "bucket_index": int(block.bucket_index),
            "bucket_count": int(block.bucket_count),
        }

    @staticmethod
    def _health(block: HealthBlock) -> dict[str, Any]:
        mode = block.mode if isinstance(block.mode, FeedMode) else FeedMode(str(block.mode))
        connection = (
            block.connection
            if isinstance(block.connection, ConnectionState)
            else ConnectionState(str(block.connection))
        )
        return {
            "mode": str(mode),
            "connection": str(connection),
            "subscribed": int(block.subscribed),
            "subscription_cap": int(block.subscription_cap),
            "ticks_received": int(block.ticks_received),
            "ticks_dropped": int(block.ticks_dropped),
            "store_cells": int(block.store_cells),
            "last_tick_age_s": round_opt(block.last_tick_age_s, 1),
            "throttled": bool(block.throttled),
            "messages": list(block.messages),
        }
