"""
L3 — 日内动能热力图引擎。
==========================
唯一职责：把"每个网格点的时间序列"折叠成一张 2D 矩阵——
纵轴行权价、横轴会话时间桶、颜色值 ΔIV（波动率点）。

为什么不是直接画 IV
-------------------
IV 的绝对水平在 0DTE 上几乎不变，画出来是一片均匀的色块，什么信息都看不出来。
真正有意义的是**变化**：哪个行权价在哪个时刻突然被重新定价。所以矩阵里存的是
相邻时间桶之间的 IV 差。

前向填充（forward fill）
------------------------
并非每个行权价每分钟都有成交。若某桶没有新 tick 就直接留空，矩阵会碎成一片
噪点。这里用"沿用上一个已知 IV"的方式填充，于是没有成交的桶自然得到 0 变化，
语义正确且视觉连续。

为什么时间桶只按行权价分键，不带方向
------------------------------------
热力图每档只取虚值一侧，而**现价一旦穿越某档，这一行的取边就会从 Put 翻成
Call**。如果历史按 ``(行权价, 方向)`` 分键，翻转之后这一行就看不到翻转之前的
任何数据——前半段明明采到了，却躺在另一个键下。表现出来就是图上"现价附近
凭空出现一块黑色空洞"，而且空洞的位置会随现价漂移。

方向不是这一行的身份，只是"当前读哪张合约"的展示属性。所以键只认行权价，
序列跨取边翻转保持连续。翻转瞬间 Put 与 Call 的 IV 本来就几乎相等（都在平值
附近），合并不会引入跳变。

依赖：L0。
"""

from __future__ import annotations

from config import loader
from contracts.enums import TRUSTWORTHY_QUALITIES, OptionRight
from contracts.feature import HeatmapMatrix, ImpulseCell
from contracts.tick import OptionRef

_SERIAL = "serialization"

#: 时间桶的键：只认行权价。见模块 docstring「为什么时间桶只按行权价分键」。
_CellKey = float


class HeatmapEngine:
    """按时间桶累积 IV，并产出 ΔIV 矩阵。"""

    __slots__ = ("_clock", "_max_buckets", "_min_buckets", "_buckets")

    def __init__(self, clock, serial_cfg: dict) -> None:
        self._clock = clock
        self._max_buckets = loader.as_int(
            serial_cfg, "heatmap_max_buckets", module=_SERIAL
        )
        self._min_buckets = loader.as_int(
            serial_cfg, "heatmap_min_buckets", module=_SERIAL
        )
        # {行权价: {bucket_index: iv}}
        self._buckets: dict[_CellKey, dict[int, float]] = {}

    # ------------------------------------------------------------------ #
    # 累积
    # ------------------------------------------------------------------ #

    def observe(self, cells: tuple[ImpulseCell, ...], now: float) -> int:
        """
        把本轮的 IV 写进各自的时间桶。返回写入的网格点数。

        同一桶内重复写入只保留最后一次——这样每个桶代表"该分钟的收盘 IV"。

        只有 ``TRUSTWORTHY_QUALITIES`` 的点才写入：被毛刺过滤判定为 ``GLITCH``
        的分母效应尖峰**绝不能进矩阵**，否则一次尖峰就会在热力图上制造一个
        完全虚假的信号（实测可达 32 个波动率点）。

        同一行权价的 Put 与 Call 共用一条时间序列（见模块 docstring），因此取边
        翻转不会把这一行的历史劈断。
        """
        index = self._clock.bucket_index_of_ts(now)
        written = 0
        for cell in cells:
            if cell.quality not in TRUSTWORTHY_QUALITIES:
                continue
            key: _CellKey = float(cell.strike)
            bucket = self._buckets.setdefault(key, {})
            bucket[index] = float(cell.iv)
            written += 1

        self._prune(index)
        return written

    def _prune(self, current_index: int) -> None:
        cutoff = current_index - self._max_buckets
        if cutoff <= 0:
            return
        for bucket in self._buckets.values():
            for stale in [b for b in bucket if b < cutoff]:
                del bucket[stale]

    # ------------------------------------------------------------------ #
    # 产出矩阵
    # ------------------------------------------------------------------ #

    def build(
        self,
        rows: tuple[OptionRef, ...],
        spot: float,
        now: float,
    ) -> HeatmapMatrix | None:
        """构造当前时刻的矩阵。行数或列数不足时返回 ``None``。"""
        if not rows:
            return None

        current = self._clock.bucket_index_of_ts(now)
        if current + 1 < self._min_buckets:
            return None

        labels = tuple(self._clock.bucket_labels()[: current + 1])

        strikes: list[float] = []
        rights: list[OptionRight] = []
        values: list[tuple[float | None, ...]] = []

        for ref in rows:
            bucket = self._buckets.get(float(ref.strike))
            row = self._row_values(bucket, current) if bucket else None
            if row is None:
                continue
            strikes.append(ref.strike)
            rights.append(ref.right)
            values.append(row)

        if not strikes:
            return None

        return HeatmapMatrix(
            strikes=tuple(strikes),
            rights=tuple(rights),
            bucket_labels=labels,
            values=tuple(values),
            bucket_index=current,
            spot=float(spot),
        )

    @staticmethod
    def _row_values(
        bucket: dict[int, float] | None, current: int
    ) -> tuple[float | None, ...] | None:
        """
        把稀疏的桶字典展开成定长行，并前向填充后取差分。

        返回 ``None`` 仅表示"该行一个桶都没写过"（整行丢弃）。只有第 0 桶时，
        差分天然全为空——此时仍然返回定长行，让前端能立刻画出带正确坐标轴的
        空网格，而不是整块面板空白。``null`` 与 ``0`` 语义不同，前端会跳过空值。
        """
        if not bucket:
            return None

        first = min(bucket)
        if first > current:
            return None

        out: list[float | None] = []
        carried: float | None = None
        previous: float | None = None

        for index in range(current + 1):
            value = bucket.get(index, carried)
            if value is None:
                out.append(None)
            else:
                out.append(
                    None if previous is None else (value - previous) * 100.0
                )
            carried = value
            previous = value

        return tuple(out)

    # ------------------------------------------------------------------ #
    # 维护
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        self._buckets.clear()

    def tracked_rows(self) -> int:
        return len(self._buckets)

    def bucket_depth(self, ref: OptionRef) -> int:
        bucket = self._buckets.get(float(ref.strike))
        return len(bucket) if bucket else 0
