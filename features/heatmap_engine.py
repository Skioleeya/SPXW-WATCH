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

前向填充（forward fill）—— **有上限**
------------------------------------
并非每个行权价每分钟都有成交。若某桶没有新 tick 就直接留空，矩阵会碎成一片
噪点。这里用"沿用上一个已知 IV"的方式填充，于是没有成交的桶自然得到 0 变化，
语义正确且视觉连续。

但该假定**只对短跨度成立**：跨度一长，"沿用"就变成"编造"。最典型的来源是
``load_snapshot()`` 恢复出来的**孤立旧桶** —— 上一次进程存活期在 20:15 只写了
一个桶就结束了，重启后该桶被恢复，若一路沿用到当前，图上就出现一条横跨
整段会话的 ΔIV=0「假 0 带」（亮黄绿，与真"IV 没变"肉眼无法区分）。
所以跨度超过 ``heatmap_max_ffill_buckets`` 的桶一律输出 ``None``（留白）。

断代（break）—— 前向填充唯一危险的地方
--------------------------------------
前向填充假定"没有新 IV ⇒ IV 没变"。**行情断流时这个假定是假的**：断线期间
最后一笔 tick 会一直是 ``STALE``，而 ``STALE`` 属于 ``TRUSTWORTHY_QUALITIES``
（会话内前向填充语义），于是它被逐桶写进矩阵，断线看起来只是"IV 没动"。
重连后第一笔新 IV 一进来，就与断线前的值做差 —— **整段断线的变化被压进单个
30 秒桶**，在图上画出一堵与真冲量无法区分的假墙。色标下限只有 ±0.5 波动率点，
几个点的跳变就直接打满，肉眼完全分不出来。

所以这里引入 ``break``：调用方（L3 编排器，它才知道全局 tick 年龄）在
"断流恢复"的那一刻传 ``break_now=True``，本桶的值**只作为新段的起点、不与
前一个值做差**，即该桶输出 ``None``（留白）。宁可留白，也不画假信号。

同一类留白的第二个来源：**会话之间的空档**（2026-09-13 起）
----------------------------------------------------------
网格覆盖整个交易日之后，GTH（20:15 → 09:25）与 RTH（09:30 → 16:00）之间
那 5 分钟不交易的时间也在横轴上占了桶位。跨过它做差，就是把整段空档的变化
压进一个 30 秒桶 —— 与断线恢复**机制上完全一样**，只是触发者从"网络断了"
换成"交易所中场"。所以区段起点桶同样留白，由时钟的 ``zone_start_indexes()``
给出（静态的网格几何，见 ``_zone_starts``）。前端在「全时段」视图里把那几列
整段切掉；切掉之后相邻的两列本来就不该有差分关系，两边语义自洽。

为什么断代标记是**全局**的而不是逐档的
--------------------------------------
断流是喂价层的事件，所有行权价同时停。而单个远虚值档本来就可能几分钟没有
成交 —— 用逐档年龄判会把它误判成断流，热力图上凭空多出一堆空白。全局标记
只在整个喂价停摆时才置位，不误伤安静的档位。

为什么时间桶只按行权价分键，不带方向
------------------------------------
热力图每档只取虚值一侧，而**现价一旦穿越某档，这一行的取边就会从 Put 翻成
Call**。如果历史按 ``(行权价, 方向)`` 分键，翻转之后这一行就看不到翻转之前的
任何数据——前半段明明采到了，却躺在另一个键下。表现出来就是图上"现价附近
凭空出现一块黑色空洞"，而且空洞的位置会随现价漂移。

方向不是这一行的身份，只是"当前读哪张合约"的展示属性。所以键只认行权价，
序列跨取边翻转保持连续。

⚠️ 合并**不引入跳变**的真正原因不是"翻转时都在平值附近所以两侧差不多"（那只是
估算，不足以承重），而是 ``config/ibkr.json::use_model_greeks = true`` 时 IBKR 的
``modelGreeks.impliedVol`` **一个行权价只给一个波动率 —— Put 与 Call 同值**。
2026-09-14 实测（SPXW 0DTE，4 档 × 双向，conId 与买卖价均不同）：model 口径两侧差
**0.000**、报价口径 ~0.16、最新成交口径 **5.5～6.3 波动率点**（色标量程只有 ±0.5
⇒ 足以打满；逐档读数见 ``notes/memory/TROUBLESHOOTING.md`` §10）。``tick_router``
在 ``use_model_greeks = false`` 时按 model → last → bid → ask 降级 ⇒ **关掉该开关，
每次现价穿越行权价都会在图上打出一个假的 ΔIV 跳变**。它是本节的**前提条件**。

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

    __slots__ = (
        "_clock", "_max_buckets", "_min_buckets", "_max_ffill", "_buckets",
        "_tick_counts", "_breaks", "_zone_starts",
    )

    def __init__(self, clock, serial_cfg: dict) -> None:
        self._clock = clock
        self._max_buckets = loader.as_int(
            serial_cfg, "heatmap_max_buckets", module=_SERIAL
        )
        self._min_buckets = loader.as_int(
            serial_cfg, "heatmap_min_buckets", module=_SERIAL
        )
        self._max_ffill = loader.as_int(
            serial_cfg, "heatmap_max_ffill_buckets", module=_SERIAL
        )
        # {行权价: {bucket_index: iv}}
        self._buckets: dict[_CellKey, dict[int, float]] = {}
        # {行权价: {bucket_index: tick_count}} —— 每格有多少笔 tick 写入。
        # 用于前端「成交量加权」视觉层（P1）。
        self._tick_counts: dict[_CellKey, dict[int, int]] = {}
        # 断代桶序号：这些桶的值是新段的起点，差分时必须留白。全局集合，
        # 因为断流是所有档位同时发生的事件（见模块 docstring）。
        self._breaks: set[int] = set()
        # 区段起点桶（会话之间的空档边界）：静态的网格几何，一天内不变，
        # 因此不进持久化、也不随裁剪淘汰（见模块 docstring）。
        self._zone_starts: frozenset[int] = frozenset(
            int(index) for index in clock.zone_start_indexes()
        )

    # ------------------------------------------------------------------ #
    # 累积
    # ------------------------------------------------------------------ #

    def observe(
        self, cells: tuple[ImpulseCell, ...], now: float, break_now: bool = False
    ) -> int:
        """
        把本轮的 IV 写进各自的时间桶。返回写入的网格点数。

        ``break_now`` 由调用方在"行情断流后恢复"的那一刻置位：本桶记入
        ``_breaks``，出矩阵时该桶留白，不与断线前的值做差。

        同一桶内重复写入只保留最后一次——这样每个桶代表"该分钟的收盘 IV"。

        只有 ``TRUSTWORTHY_QUALITIES`` 的点才写入：被毛刺过滤判定为 ``GLITCH``
        的分母效应尖峰**绝不能进矩阵**，否则一次尖峰就会在热力图上制造一个
        完全虚假的信号（实测可达 32 个波动率点）。

        同一行权价的 Put 与 Call 共用一条时间序列（见模块 docstring），因此取边
        翻转不会把这一行的历史劈断。
        """
        index = self._clock.bucket_index_of_ts(now)
        if break_now:
            self._breaks.add(index)

        written = 0
        for cell in cells:
            if cell.quality not in TRUSTWORTHY_QUALITIES:
                continue
            key: _CellKey = float(cell.strike)
            bucket = self._buckets.setdefault(key, {})
            bucket[index] = float(cell.iv)
            # 累加 tick 计数（P1：volume 视觉层）
            tick_bucket = self._tick_counts.setdefault(key, {})
            tick_bucket[index] = tick_bucket.get(index, 0) + 1
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
        for tick_bucket in self._tick_counts.values():
            for stale in [b for b in tick_bucket if b < cutoff]:
                del tick_bucket[stale]
        self._breaks = {b for b in self._breaks if b >= cutoff}

    # ------------------------------------------------------------------ #
    # 产出矩阵
    # ------------------------------------------------------------------ #

    def build(
        self,
        rows: tuple[OptionRef, ...],
        spot: float,
        now: float,
    ) -> HeatmapMatrix | None:
        """
        构造当前时刻的矩阵。行数或列数不足时返回 ``None``。

        产出行的顺序是**降序**（行权价高的在前）。``strikes`` / ``rights`` /
        ``values`` 由同一个循环产出，所以顺序只在这里定一次，三者必然对齐。

        为什么在这里显式排序，而不是沿用 ``rows`` 的顺序
        -------------------------------------------------
        ``StrikeWindow.rows()`` 恰好返回升序是它的实现细节，不是本模块可以
        依赖的契约 —— 依赖它，就等于把帧的行序建立在一个跨模块的巧合上。
        帧的顺序是**对外契约**（前端纵轴按它渲染），所以必须由产出点保证。
        降序的含义：与屏幕自上而下一致（见 ``web/heatmap.js`` 的 ``inverse``）。
        """
        if not rows:
            return None

        current = self._clock.bucket_index_of_ts(now)
        if current + 1 < self._min_buckets:
            return None

        labels = tuple(self._clock.bucket_labels()[: current + 1])

        strikes: list[float] = []
        rights: list[OptionRight] = []
        values: list[tuple[float | None, ...]] = []
        volumes: list[tuple[int | None, ...]] = []

        for ref in sorted(rows, key=lambda r: r.strike, reverse=True):
            key = float(ref.strike)
            bucket = self._buckets.get(key)
            row = self._row_values(bucket, current) if bucket else None
            if row is None:
                continue
            strikes.append(ref.strike)
            rights.append(ref.right)
            values.append(row)
            # 体积矩阵：与 values 同形，取 tick 计数
            tick_bucket = self._tick_counts.get(key, {})
            vol_row = self._row_volumes(tick_bucket, current)
            volumes.append(vol_row)

        if not strikes:
            return None

        return HeatmapMatrix(
            strikes=tuple(strikes),
            rights=tuple(rights),
            bucket_labels=labels,
            values=tuple(values),
            bucket_index=current,
            spot=float(spot),
            volumes=tuple(volumes),
        )

    def _row_values(
        self, bucket: dict[int, float] | None, current: int
    ) -> tuple[float | None, ...] | None:
        """
        把稀疏的桶字典展开成定长行，并前向填充后取差分。

        返回 ``None`` 仅表示"该行一个桶都没写过"（整行丢弃）。只有**一个**
        桶有值（不一定是第 0 桶——冷启动/重启时当前桶常非第 0 桶）时，
        差分天然全为空——此时仍然返回定长行，让前端能立刻画出带正确坐标轴的
        空网格，而不是整块面板空白。``null`` 与 ``0`` 语义不同，前端会跳过空值。

        四种情况输出 ``None``（留白），它们的含义不同但都"不该画颜色"：
        1. 该桶从未有过 IV（``previous is None``）—— 序列还没开始；
        2. 该桶是断代桶（``index in self._breaks``）—— 前一个值来自断线前，
           做差会造出假冲量；
        3. 该桶是区段起点（``index in self._zone_starts``）—— 前一个值来自
           上一个会话，中间隔着整段不交易的空档（GTH 收盘 09:25 → RTH 开盘
           09:30），做差就是把空档里的全部变化压进一个桶，与断线恢复是同一类
           假信号。**这是"5 分钟空档"在数据侧的落点**：前端把那几列整段切掉，
           而切掉之后相邻的两列本来就不该有差分关系；
        4. 该桶本身没有值（整行一个桶都没写过时由调用方提前返回 ``None``）。

        第五种（2026-09-14 补）：**距上一个真实观测超过 ``_max_ffill`` 桶**。
        前向填充的假定只对短跨度成立，跨小时沿用会把孤立旧桶（``load_snapshot()``
        从上一进程存活期恢复出来的）拉成一条横跨整段会话的 ΔIV=0「假 0 带」——
        亮黄绿，与真"IV 没变"肉眼无法区分。留白不画，见模块 docstring。
        """
        if not bucket:
            return None

        first = min(bucket)
        if first > current:
            return None

        blocked = self._breaks | self._zone_starts
        out: list[float | None] = []
        carried: float | None = None
        previous: float | None = None
        last_seen: int | None = None

        for index in range(current + 1):
            raw = bucket.get(index)
            if raw is not None:
                last_seen = index
                carried = raw
                value: float | None = raw
            elif last_seen is not None and index - last_seen <= self._max_ffill:
                # 短跨度：沿用上一个已知 IV（"没有新 IV ⇒ IV 没变"）。
                value = carried
            else:
                # 跨度超限，或该行还没开始：留白。见模块 docstring ——
                # 一路沿用会把孤立旧桶拉成横跨整段会话的「假 0 带」。
                value = None
            if value is None or previous is None or index in blocked:
                out.append(None)
            else:
                out.append((value - previous) * 100.0)
            previous = value

        return tuple(out)

    def _row_volumes(
        self, tick_bucket: dict[int, int] | None, current: int
    ) -> tuple[int | None, ...]:
        """
        把稀疏的 tick 计数字典展开成定长行。
        与 ``_row_values`` 同形：有值的位置给计数，无值给 None。
        """
        if not tick_bucket:
            return tuple([None] * (current + 1))

        out: list[int | None] = []
        for index in range(current + 1):
            count = tick_bucket.get(index)
            out.append(count if count is not None else None)
        return tuple(out)

    # ------------------------------------------------------------------ #
    # 维护
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        self._buckets.clear()
        self._tick_counts.clear()
        self._breaks.clear()

    def tracked_rows(self) -> int:
        return len(self._buckets)

    def bucket_depth(self, ref: OptionRef) -> int:
        bucket = self._buckets.get(float(ref.strike))
        return len(bucket) if bucket else 0

    def is_break(self, bucket_index: int) -> bool:
        """给定桶序号是否为断代桶。"""
        return bucket_index in self._breaks

    def break_count(self) -> int:
        """已记录的断代桶数，供探针与回归核对。"""
        return len(self._breaks)

    # ------------------------------------------------------------------ #
    # 持久化快照
    # ------------------------------------------------------------------ #

    def dump_bucket(self, bucket_index: int) -> dict[float, float]:
        """
        提取某一桶的原始 IV 字典 ``{strike: iv}``，**键按行权价降序**。

        只返回该桶有值的档位；空桶返回空字典。供 ``AsyncPersistenceWriter``
        序列化写入 SQLite。

        为什么要在这里排序
        ------------------
        ``_buckets`` 的键序是**首次出现顺序**，不是排序结果：现价先上移、再
        回落到会话初低点之下时，更低的档位会被追加到字典末尾（实测 ±12 档下
        一次 7700→7820→7600 的往返即可复现）。JSON 对象的键序会被原样写进
        ``ivs_json``，而 ``recover()`` / ``load_snapshot()`` 都不重排 —— 乱序
        会落盘并被继承下去。直接读 ``data/sessions/<到期日>.db`` 的人（或脚本）
        若默认"键序即降序"，就会静默错配行号。

        排一次序，把这条不变量收回到快照的产出点，让落盘产物与内部字典的
        历史无关。由 ``tools/check_persistence.py`` 的键序用例守住。

        为什么是**降序**（2026-09-13 统一）
        ----------------------------------
        对外帧的 ``strikes`` 与屏幕自上而下都是降序（见 ``build()`` 与
        ``web/heatmap.js`` 的 ``yAxis.inverse``）。冷数据一度是升序，与帧方向
        相反 —— 同一个系统里两处行序相反，读代码的人迟早串味。现在两边同向：
        **高行权价在前**。冷数据仍是内部恢复产物（键序不影响 ``_buckets`` 的
        查找，``build()`` 自己会显式排序），统一只为消除这层反向语义。
        """
        out: dict[float, float] = {}
        for strike in sorted(self._buckets, reverse=True):
            iv = self._buckets[strike].get(bucket_index)
            if iv is not None:
                out[float(strike)] = float(iv)
        return out

    def load_snapshot(self, columns: list[dict]) -> None:
        """
        从持久化存储恢复原始 IV 桶。

        ``columns`` 格式：
        ``[{bucket_index: int, ivs: {float(strike): float}, break: bool}, ...]``

        恢复后 ``_breaks`` 同时重建，但**不恢复任何差分产物**（ΔIV 在
        ``build()`` 时按当前上下文重新计算）。
        """
        self._buckets.clear()
        self._breaks.clear()
        for col in columns:
            idx = int(col["bucket_index"])
            if col.get("break"):
                self._breaks.add(idx)
            for strike_str, iv in col.get("ivs", {}).items():
                key = float(strike_str)
                bucket = self._buckets.setdefault(key, {})
                bucket[idx] = float(iv)
