"""
L2 — Tick 存储。
================
唯一职责：把采集层推来的 tick 按"数据分片"保存成可回溯的时间序列，并对外
提供**只读**查询。

数据分片（分片键 = 行权价 × 方向）
----------------------------------
日内动能要回答的是"这个行权价的 IV 在过去 1 分钟里变了多少"，所以每个分片
都必须保留历史，只存最新值是不够的。这里每个分片一个 ``RingBuffer``。

并发模型
--------
``on_*`` 回调由 ib_async 的事件循环线程调用，特征计算与序列化跑在同一个
asyncio 事件循环上。理论上同线程无竞争，但 IBKR 客户端库在不同版本里可能
把回调放到独立线程，因此这里仍然用 ``RLock`` 保护——一把锁的代价远小于
偶发的数据结构撕裂。

依赖：L0。
"""

from __future__ import annotations

import threading
from typing import Any

from config import loader
from contracts.ports import TickSink
from contracts.tick import (
    OptionRef,
    OptionTick,
    QuoteTick,
    SpotTick,
    StatusEvent,
)
from core.clock import WallClock
from core.ring_buffer import RingBuffer

_CFG = "state"


class TickStore(TickSink):
    """按分片保存 tick 历史的内存存储。"""

    __slots__ = (
        "_lock", "_clock", "_option_age", "_option_maxlen",
        "_spot_age", "_spot_maxlen", "_prune_interval_s",
        "_options", "_quotes", "_spot", "_status",
        "_counts", "_last_tick_ts", "_last_option_ts", "_last_spot_ts",
    )

    def __init__(self, state_cfg: dict, clock: Any = None) -> None:
        self._lock = threading.RLock()
        # 时间源必须可注入：模拟模式下会话时间被加速，用墙钟算 tick 年龄会得到
        # 负值（tick 时间戳在"未来"），健康块就永远显示不出陈旧。
        self._clock = clock if clock is not None else WallClock()

        self._option_age = loader.as_float(state_cfg, "option_buffer_seconds", module=_CFG)
        self._option_maxlen = loader.as_int(state_cfg, "option_buffer_max_points", module=_CFG)
        self._spot_age = loader.as_float(state_cfg, "spot_buffer_seconds", module=_CFG)
        self._spot_maxlen = loader.as_int(state_cfg, "spot_buffer_max_points", module=_CFG)
        # 裁剪节奏属于本层的配置：L6 只负责按这个节奏驱动循环，不决定"多久裁一次"。
        # 这个值曾经只写在 config/pipeline.json 里，导致 state.json 的同名键是死的
        # （改了没有任何效果）——由自检项 [7] 兜住这类"未接线键"。
        self._prune_interval_s = loader.as_float(state_cfg, "prune_interval_s", module=_CFG)

        self._options: dict[OptionRef, RingBuffer[OptionTick]] = {}
        self._quotes: dict[OptionRef, QuoteTick] = {}
        self._spot: RingBuffer[SpotTick] = RingBuffer(self._spot_maxlen, self._spot_age)
        self._status: list[StatusEvent] = []

        self._counts: dict[str, int] = {
            "option_ticks": 0,
            "quote_ticks": 0,
            "spot_ticks": 0,
            "status_events": 0,
        }
        self._last_tick_ts: float = 0.0
        self._last_option_ts: float = 0.0
        self._last_spot_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # TickSink 实现（写路径）
    # ------------------------------------------------------------------ #

    def on_option_tick(self, tick: OptionTick) -> None:
        with self._lock:
            buffer = self._options.get(tick.ref)
            if buffer is None:
                buffer = RingBuffer(self._option_maxlen, self._option_age)
                self._options[tick.ref] = buffer
            buffer.append(tick.ts, tick)
            self._counts["option_ticks"] += 1
            self._last_option_ts = tick.ts
            self._last_tick_ts = max(self._last_tick_ts, tick.ts)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        with self._lock:
            self._quotes[tick.ref] = tick
            self._counts["quote_ticks"] += 1
            self._last_tick_ts = max(self._last_tick_ts, tick.ts)

    def on_spot_tick(self, tick: SpotTick) -> None:
        with self._lock:
            self._spot.append(tick.ts, tick)
            self._counts["spot_ticks"] += 1
            self._last_spot_ts = tick.ts
            self._last_tick_ts = max(self._last_tick_ts, tick.ts)

    def on_status(self, event: StatusEvent) -> None:
        with self._lock:
            self._status.append(event)
            self._counts["status_events"] += 1
            if len(self._status) > 128:
                del self._status[:-128]

    # ------------------------------------------------------------------ #
    # 读路径
    # ------------------------------------------------------------------ #

    def option_buffer(self, ref: OptionRef) -> RingBuffer[OptionTick] | None:
        with self._lock:
            return self._options.get(ref)

    def latest_option(self, ref: OptionRef) -> OptionTick | None:
        buffer = self.option_buffer(ref)
        return buffer.latest_value() if buffer is not None else None

    def quote(self, ref: OptionRef) -> QuoteTick | None:
        with self._lock:
            return self._quotes.get(ref)

    def refs(self) -> tuple[OptionRef, ...]:
        with self._lock:
            return tuple(self._options.keys())

    def refs_with_history(self, min_points: int = 1) -> tuple[OptionRef, ...]:
        """只返回历史点数达标的分片，避免特征层反复做空判断。"""
        with self._lock:
            return tuple(
                ref for ref, buf in self._options.items() if len(buf) >= min_points
            )

    def spot(self) -> float:
        with self._lock:
            sample = self._spot.latest_value()
        return float(sample.price) if sample is not None else 0.0

    def spot_series(self) -> RingBuffer[SpotTick]:
        return self._spot

    def spot_at_or_before(self, ts: float, tolerance_s: float) -> float | None:
        sample = self._spot.value_at_or_before(ts, tolerance_s)
        return float(sample.price) if sample is not None else None

    def status_events(self, limit: int = 8) -> tuple[StatusEvent, ...]:
        with self._lock:
            return tuple(self._status[-limit:])

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def cell_count(self) -> int:
        with self._lock:
            return len(self._options)

    def last_tick_age_s(self, now: float | None = None) -> float | None:
        with self._lock:
            last = self._last_tick_ts
        if last <= 0:
            return None
        return max((now if now is not None else self._clock.now()) - last, 0.0)

    def last_option_age_s(self, now: float | None = None) -> float | None:
        with self._lock:
            last = self._last_option_ts
        if last <= 0:
            return None
        return max((now if now is not None else self._clock.now()) - last, 0.0)

    def last_spot_age_s(self, now: float | None = None) -> float | None:
        with self._lock:
            last = self._last_spot_ts
        if last <= 0:
            return None
        return max((now if now is not None else self._clock.now()) - last, 0.0)

    # ------------------------------------------------------------------ #
    # 维护
    # ------------------------------------------------------------------ #

    @property
    def prune_interval_s(self) -> float:
        """
        本层期望的裁剪节奏（秒）。

        L6 的维护循环按它驱动 ``prune()``。节奏由本层配置决定，
        组装层只负责"照着跑"，不替本层选参数。
        """
        return self._prune_interval_s

    def prune(self, now: float | None = None) -> int:
        """
        按时间窗裁剪所有分片，返回被丢弃的样本总数。

        由 L6 的维护循环驱动——L2 不自己起线程，保持"谁组装谁负责生命周期"；
        但**多久裁一次**由本层的 ``prune_interval_s`` 决定（见同名属性）。
        """
        moment = now if now is not None else self._clock.now()
        dropped = 0
        with self._lock:
            dropped += self._spot.prune(moment)
            for buffer in self._options.values():
                dropped += buffer.prune(moment)
        return dropped

    def clear(self) -> None:
        with self._lock:
            self._options.clear()
            self._quotes.clear()
            self._spot = RingBuffer(self._spot_maxlen, self._spot_age)
            self._status.clear()

    def snapshot_meta(self) -> dict[str, Any]:
        """供健康面板使用的一行摘要。"""
        with self._lock:
            cells = len(self._options)
            points = sum(len(b) for b in self._options.values())
            quotes = len(self._quotes)
            spot_points = len(self._spot)
        return {
            "cells": cells,
            "option_points": points,
            "quotes": quotes,
            "spot_points": spot_points,
            "counts": self.counts(),
        }
