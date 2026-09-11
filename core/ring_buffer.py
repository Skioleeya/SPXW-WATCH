"""
L0 — 环形缓冲区。
==================
唯一职责：按时间戳有序地保存最近 N 个采样点，并支持按时间点回溯查询。

这是"日内动能"能算出来的基础设施：IV 冲量需要拿到"1 分钟前那个行权价的 IV"，
所以每个数据分片都要有历史，而不是只存最新值。

特性
----
* 双限容量：``maxlen`` 限制点数，``max_age_s`` 限制时间跨度，先到者生效。
* ``at_or_before`` 用于回看：找不到足够接近的基准点时返回 ``None``
  （调用方据此判定"历史不足"，而不是拿一个很远的点硬算）。
* 纯内存、无 I/O、无第三方依赖。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Generic, Iterator, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Sample(Generic[T]):
    """一个带时间戳的采样点。"""

    ts: float
    value: T


class RingBuffer(Generic[T]):
    """按 ``ts`` 单调递增写入的定长时间窗缓冲。"""

    __slots__ = ("_samples", "_maxlen", "_max_age_s", "_last_ts")

    def __init__(self, maxlen: int, max_age_s: float) -> None:
        if maxlen <= 0:
            raise ValueError(f"maxlen 必须为正整数，收到 {maxlen}")
        if max_age_s <= 0:
            raise ValueError(f"max_age_s 必须为正数，收到 {max_age_s}")
        self._samples: Deque[Sample[T]] = deque(maxlen=maxlen)
        self._maxlen = maxlen
        self._max_age_s = float(max_age_s)
        self._last_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #

    def append(self, ts: float, value: T) -> None:
        """追加一个采样点，并顺带按时间窗裁剪尾部。"""
        if self._samples and ts < self._last_ts:
            # 时间戳回退（IBKR 偶尔会补发），丢弃该点以保证有序性。
            return
        self._samples.append(Sample(ts=ts, value=value))
        self._last_ts = ts
        self._trim(ts)

    def prune(self, now: float) -> int:
        """按当前时间裁剪过期样本，返回被丢弃的条数。"""
        return self._trim(now)

    def _trim(self, now: float) -> int:
        cutoff = now - self._max_age_s
        dropped = 0
        while self._samples and self._samples[0].ts < cutoff:
            self._samples.popleft()
            dropped += 1
        return dropped

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #

    def latest(self) -> Sample[T] | None:
        return self._samples[-1] if self._samples else None

    def latest_value(self) -> T | None:
        return self._samples[-1].value if self._samples else None

    def oldest(self) -> Sample[T] | None:
        return self._samples[0] if self._samples else None

    def at_or_before(self, ts: float, tolerance_s: float) -> Sample[T] | None:
        """
        找出 ``ts`` 之前（含）最近的一个采样点。

        ``tolerance_s`` 是允许的最大时间偏差：如果找到的点比
        ``ts - tolerance_s`` 还旧，就认为"历史不足"，返回 ``None``。
        这样调用方不会拿一个 10 分钟前的点冒充"1 分钟前"。
        """
        best: Sample[T] | None = None
        for sample in reversed(self._samples):
            if sample.ts <= ts:
                best = sample
                break
        if best is None:
            return None
        if ts - best.ts > tolerance_s:
            return None
        return best

    def value_at_or_before(self, ts: float, tolerance_s: float) -> T | None:
        sample = self.at_or_before(ts, tolerance_s)
        return sample.value if sample is not None else None

    def between(self, t0: float, t1: float) -> list[Sample[T]]:
        """返回 ``[t0, t1]`` 闭区间内的样本。"""
        return [s for s in self._samples if t0 <= s.ts <= t1]

    def median_value(self, last_n: int) -> float | None:
        """
        最近 ``last_n`` 个样本的数值中位数。仅当 value 可转 float 时可用，
        供毛刺过滤器做鲁棒基准。
        """
        if last_n <= 0 or not self._samples:
            return None
        window = list(self._samples)[-last_n:]
        vals: list[float] = []
        for sample in window:
            try:
                vals.append(float(sample.value))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
        if not vals:
            return None
        vals.sort()
        mid = len(vals) // 2
        if len(vals) % 2 == 1:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    def values(self) -> list[T]:
        return [s.value for s in self._samples]

    def samples(self) -> Iterator[Sample[T]]:
        return iter(self._samples)

    # ------------------------------------------------------------------ #
    # 元信息
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        return len(self._samples)

    def __bool__(self) -> bool:
        return bool(self._samples)

    @property
    def max_age_s(self) -> float:
        return self._max_age_s

    @property
    def capacity(self) -> int:
        return self._maxlen

    def span_s(self) -> float:
        """当前缓冲覆盖的时间跨度（秒）。"""
        if len(self._samples) < 2:
            return 0.0
        return self._samples[-1].ts - self._samples[0].ts
