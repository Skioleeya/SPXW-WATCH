"""
L3 — 特征编排器。
==================
唯一职责：按固定顺序跑完一轮特征计算，产出一个自洽的 ``FeatureBundle``。

流水线顺序（顺序本身是契约，不能随意调换）
------------------------------------------
::

    1. 取现价
    2. 选行权价窗口 → 每档取 OTM 一侧
    3. 逐点毛刺过滤 → Quality
    4. 逐点算 IV 冲量 → ImpulseCell
    5. 把 IV 写进时间桶 → 累积
    6. 折叠出 ΔIV 矩阵 → HeatmapMatrix
    7. 插值定位 25Δ → SkewPoint（并写入折线序列）
    8. 汇总 ATM 读数 → AtmSnapshot

先过滤再算动能，是因为一个毛刺点会同时污染它自己的冲量和整个时间桶的差分；
反过来"先算再过滤"就必须在矩阵层再做一次清洗，逻辑会重复。

依赖：L0、L2（TickStore）、L3 内部。
"""

from __future__ import annotations

from config import loader
from contracts.enums import TRUSTWORTHY_QUALITIES, OptionRight, Quality
from contracts.feature import (
    AtmSnapshot,
    FeatureBundle,
    ImpulseCell,
)
from contracts.tick import OptionRef, OptionTick
from core.ring_buffer import RingBuffer

from features.glitch_filter import GlitchFilter
from features.heatmap_engine import HeatmapEngine
from features.impulse_engine import ImpulseEngine
from features.skew_engine import SkewEngine
from features.strike_window import StrikeWindow

_FEAT = "features"
_SERIAL = "serialization"


class FeatureEngine:
    """L3 的统一入口。"""

    __slots__ = (
        "_store", "_clock", "_window", "_glitch",
        "_impulse", "_heatmap", "_skew", "_each_side", "_session_key",
        "_feed_gap_s", "_feed_gap_open", "_writer",
    )

    def __init__(
        self,
        store,
        clock,
        feat_cfg: dict,
        serial_cfg: dict,
        writer: Any | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._window = StrikeWindow(feat_cfg)
        self._glitch = GlitchFilter(feat_cfg)
        self._impulse = ImpulseEngine(feat_cfg)
        self._heatmap = HeatmapEngine(clock, serial_cfg)
        self._skew = SkewEngine(feat_cfg, serial_cfg, clock)
        self._each_side = loader.as_int(
            feat_cfg, "heatmap_rows_each_side", module=_FEAT
        )
        # 断流判定阈值。它是热力图的形状参数（与 heatmap_max_buckets 同族），
        # 消费方 HeatmapEngine 也读 serialization.json，所以放那里而不是这里。
        self._feed_gap_s = loader.as_float(
            serial_cfg, "heatmap_feed_gap_s", module=_SERIAL
        )
        self._feed_gap_open = False
        # 当前累积数据归属的会话。首次 compute 时落定，之后只在翻篇时变。
        self._session_key: str | None = None
        # 旁路持久化写入器（可选）。不为 None 时每 compute 一轮后把当前桶入队。
        self._writer = writer

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #

    def compute(self, now: float | None = None) -> FeatureBundle:
        # 时间源必须取自注入的会话时钟，不能用墙钟：模拟模式下会话时间被加速，
        # 墙钟会落在开盘之前，分桶全部钳到第 0 桶，热力图就永远差不出第一列。
        moment = now if now is not None else self._clock.now_ts()
        self._sync_session()
        # 断流恢复的那一刻必须留白，否则整段断线的变化会被压进单个桶 ——
        # 画出一堵与真冲量无法区分的假墙（见 HeatmapEngine 模块 docstring）。
        feed_gap_break = self._note_feed_gap(moment)
        spot = self._store.spot()

        if spot <= 0:
            return FeatureBundle(ts=moment, spot=0.0)

        rows = self._window.rows(self._session_refs(), spot, self._each_side)
        if not rows:
            return FeatureBundle(ts=moment, spot=spot)

        cells = self._build_cells(rows, moment)
        if not cells:
            return FeatureBundle(ts=moment, spot=spot)

        self._heatmap.observe(cells, moment, break_now=feed_gap_break)
        self._persist_current_bucket(moment)
        matrix = self._heatmap.build(rows, spot, moment)

        skew_point = self._skew.compute(cells, spot, moment)
        atm = self._build_atm(cells, spot, skew_point, moment)

        ok = sum(1 for c in cells if c.quality in TRUSTWORTHY_QUALITIES)

        return FeatureBundle(
            ts=moment,
            spot=spot,
            cells=cells,
            heatmap=matrix,
            skew=skew_point,
            skew_series=self._skew.series(),
            atm=atm,
            quality_ok=ok,
            quality_flagged=len(cells) - ok,
        )

    # ------------------------------------------------------------------ #
    # 各步骤
    # ------------------------------------------------------------------ #

    def _note_feed_gap(self, moment: float) -> bool:
        """
        检测"行情断流后又恢复"的那一刻，返回本桶是否要打断代标记。

        为什么用**全局** tick 年龄而不是逐档年龄
        ----------------------------------------
        断流是喂价层的事件，所有行权价同时停。而单个远虚值档本来就可能几分钟
        没有成交 —— 用逐档年龄判会把它误判成断流，热力图上凭空多出一堆空白。
        全局年龄只在整个喂价停摆时才变大，不误伤安静的档位。

        为什么不能只靠毛刺过滤器
        ------------------------
        断线期间最后一笔 tick 会一直是 ``STALE``，而 ``STALE`` 属于
        ``TRUSTWORTHY_QUALITIES``（会话内前向填充语义）⇒ 它仍被逐桶写进矩阵，
        断线看起来只是"IV 没动"。重连后第一笔新 IV 一进来就与断线前的值做差，
        整段变化被压进单个桶。而毛刺过滤器的两道幅度闸门
        （``glitch_max_jump_vol_points``、MAD）是为**逐笔错价**标定的，且断线
        超过 tick 缓冲时间窗（``state.option_buffer_seconds``）后旧 tick 被裁光、
        两道闸门都会因"样本不足"返回 False —— 拦不住这件事。

        返回值只在**跨越阈值的那一次恢复**时为真，不会持续为真。
        """
        age = self._store.last_tick_age_s(moment)
        if age is not None and age > self._feed_gap_s:
            self._feed_gap_open = True
            return False
        if self._feed_gap_open:
            self._feed_gap_open = False
            return True
        return False

    def _session_refs(self) -> tuple[OptionRef, ...]:
        """
        只取属于当前会话的合约。

        为什么必须过滤
        --------------
        上一个会话的 tick **不会**被毛刺过滤器拦下：过滤器只按"距现在多久"判
        陈旧，而 ``STALE`` 属于 ``TRUSTWORTHY_QUALITIES`` —— 这是会话内的前向
        填充语义，本身是对的（某档几分钟没成交，沿用它上一个 IV 让行保持连续）。
        于是跨会话之后，旧会话的 IV 会被原样写进新会话的时间桶。

        这里按 ``ref.expiry`` 过滤，而不是"翻篇时清空 tick 存储"：清空依赖调用
        顺序，模拟模式下时钟连续推进，翻篇那一刻新会话的 tick 可能已经到了，
        清空会把刚到的数据一起清掉。过滤与顺序无关。

        用到期日当会话身份不是将就：0DTE 的到期日**就是**这张合约的身份，而
        实盘侧的 ref 正是用 ``ChainSlice.expiry = clock.expiry_str()`` 构造的，
        两边同源。
        """
        return tuple(
            ref for ref in self._store.refs() if ref.expiry == self._session_key
        )

    def _build_cells(
        self, rows: tuple[OptionRef, ...], now: float
    ) -> tuple[ImpulseCell, ...]:
        entries: list[tuple[OptionRef, RingBuffer[OptionTick] | None, Quality]] = []
        for ref in rows:
            buffer = self._store.option_buffer(ref)
            quote = self._store.quote(ref)
            quality = self._glitch.evaluate(buffer, quote, now)
            if quality is Quality.MISSING:
                continue
            entries.append((ref, buffer, quality))
        return self._impulse.cells_for(entries, now)

    def _build_atm(
        self,
        cells: tuple[ImpulseCell, ...],
        spot: float,
        skew_point,
        now: float,
    ) -> AtmSnapshot:
        atm_strike = StrikeWindow.nearest_strike(
            (c.strike for c in cells), spot
        )

        atm_delta = None
        if atm_strike is not None:
            for cell in cells:
                if cell.strike == atm_strike and cell.delta is not None:
                    atm_delta = cell.delta
                    break

        return AtmSnapshot(
            spot=spot,
            atm_strike=atm_strike,
            atm_iv=self._atm_iv(cells, atm_strike, skew_point),
            atm_delta=atm_delta,
            straddle_price=self._straddle(cells, atm_strike),
            put25_iv=skew_point.put25_iv if skew_point else None,
            call25_iv=skew_point.call25_iv if skew_point else None,
            skew_25d_vol_points=(
                skew_point.skew_25d_vol_points if skew_point else None
            ),
            butterfly_vol_points=(
                skew_point.butterfly_vol_points if skew_point else None
            ),
            ts=now,
        )

    def _atm_iv(
        self,
        cells: tuple[ImpulseCell, ...],
        atm_strike: float | None,
        skew_point,
    ) -> float | None:
        """
        平值 IV。

        优先取平值档 Put 与 Call 的均值——热力图每档只保留虚值一侧，直接用它
        会得到"平值档恰好是 Call 时只能看到 Call IV"的偏差，在偏斜较陡时这个
        偏差可以到 1 个波动率点以上。两侧都拿不到时才退回微笑插值。
        """
        if atm_strike is not None and cells:
            expiry = cells[0].ref.expiry
            sides: list[float] = []
            for right in (OptionRight.PUT, OptionRight.CALL):
                ref = OptionRef(strike=float(atm_strike), right=right, expiry=expiry)
                tick = self._store.latest_option(ref)
                if tick is not None:
                    sides.append(float(tick.iv))
            if len(sides) == 2:
                return sum(sides) / 2.0
            if len(sides) == 1:
                return sides[0]

        return skew_point.atm_iv if skew_point else None

    def _straddle(
        self, cells: tuple[ImpulseCell, ...], atm_strike: float | None
    ) -> float | None:
        """
        平值跨式价格 = 同档 Put + Call 的期权价之和。

        热力图每档只保留 OTM 一侧，所以这里必须回到存储里把另一侧也取出来。
        """
        if atm_strike is None or not cells:
            return None
        expiry = cells[0].ref.expiry

        total = 0.0
        for right in (OptionRight.PUT, OptionRight.CALL):
            ref = OptionRef(strike=float(atm_strike), right=right, expiry=expiry)
            tick = self._store.latest_option(ref)
            if tick is None or tick.opt_price is None:
                return None
            total += float(tick.opt_price)
        return total

    def _persist_current_bucket(self, now: float) -> None:
        """
        把当前桶的原始 IV 丢进旁路持久化队列。

        每次 ``compute()`` 后调用；同一桶被多次覆盖写入是安全的
        （SQLite ``INSERT OR REPLACE`` 保证幂等）。
        """
        writer = self._writer
        if writer is None:
            return
        idx = self._clock.bucket_index_of_ts(now)
        ivs = self._heatmap.dump_bucket(idx)
        if ivs:
            writer.enqueue(idx, ivs, self._heatmap.is_break(idx))

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def _sync_session(self) -> None:
        """
        会话翻篇就清空按会话累积的状态。

        跨会话有两条独立的泄漏路径，都要堵
        ----------------------------------
        1. **桶序号被复用。** 热力图与 Skew 序列的键都是会话内桶序号
           （``0..389``），只在一天之内唯一。新一天第 1 桶的 IV 会去减上一天
           第 1 桶的 IV，差出一个毫无根据的冲量 —— 那不是"数据缺失"，而是
           **凭空造出来的信号**。这里靠 ``reset()`` 清掉。
        2. **旧会话的 tick 被当成本会话的输入。** 它们不会被毛刺过滤器拦下，
           因为 ``STALE`` 属于 ``TRUSTWORTHY_QUALITIES``（会话内的前向填充语义，
           本身是对的）。这条靠 ``_session_refs()`` 按到期日过滤堵住。

        会话身份取自时钟的当日到期日：0DTE 的到期日**就是**会话的身份，两个会话
        必然是两张合约，不存在"同一张合约、两个会话"的情形。

        在 ``compute()`` 最前面调用（早于现价检查），这样即使新会话还没有任何
        tick，上一天的残留也会被立刻清掉，而不是挂在那里冒充当天数据。

        这个钩子（``reset()``）一直存在，但之前**没有任何地方调用它** —— 于是
        跨过会话边界后，热力图会从"36 档 × 304 桶"塌成"36 档 × 1 桶 · 0 格"，
        看起来像渲染坏了，实际是旧数据被新会话的桶序号重新解释了一遍。
        """
        key = self._clock.expiry_str()
        if self._session_key is None:
            self._session_key = key
            return
        if key != self._session_key:
            self._session_key = key
            self.reset()

    def reset(self) -> None:
        """清空所有按会话累积的状态。由 ``_sync_session()`` 在翻篇时触发。"""
        self._heatmap.reset()
        self._skew.reset()

    def restore_heatmap(self, columns: list[dict]) -> None:
        """从持久化存储恢复热力图原始 IV 桶。供 L6 组装层在启动时调用。"""
        self._heatmap.load_snapshot(columns)

    def windows(self) -> tuple[int, ...]:
        return self._impulse.windows

    @property
    def glitch_filter(self) -> GlitchFilter:
        return self._glitch
