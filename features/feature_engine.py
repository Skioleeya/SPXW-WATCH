"""
L5 — 特征编排器。
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
    9. 按间隔重拟合曲面 → SurfaceSummary（**贵，按 surface_refit_interval_s 限流**）

第 9 步在代码里排在**最前面**执行（这样所有早退路径都能带上缓存的摘要），
但它与第 1–8 步之间没有数据依赖，顺序不影响结果。

先过滤再算动能，是因为一个毛刺点会同时污染它自己的冲量和整个时间桶的差分；
反过来"先算再过滤"就必须在矩阵层再做一次清洗，逻辑会重复。

依赖：L0（config / contracts）、L1（core）、L3（存储，鸭子类型）、L5 内部。
"""

from __future__ import annotations

from dataclasses import replace

from config import loader
from contracts.enums import TRUSTWORTHY_QUALITIES, Quality
from contracts.feature import (
    AtmSnapshot,
    FeatureBundle,
    ImpulseCell,
    SurfaceSummary,
)
from contracts.tick import OptionRef, OptionTick
from core.ring_buffer import RingBuffer

from features.atm_reader import build_atm
from features.glitch_filter import GlitchFilter
from features.heatmap_engine import HeatmapEngine
from features.impulse_engine import ImpulseEngine
from features.skew_engine import SkewEngine
from features.strike_window import StrikeWindow
from features.surface_engine import SurfaceEngine

_FEAT = "features"
_SERIAL = "serialization"


class FeatureEngine:
    """L5 的统一入口。"""

    __slots__ = (
        "_store", "_clock", "_window", "_glitch",
        "_impulse", "_heatmap", "_skew", "_surface", "_each_side",
        "_visible_each_side", "_session_key",
        "_feed_gap_s", "_feed_gap_open", "_writer",
    )

    def __init__(
        self,
        store,
        clock,
        feat_cfg: dict,
        serial_cfg: dict,
        surface_model,
        is_delayed,
        writer: Any | None = None,
    ) -> None:
        """
        ``surface_model`` / ``is_delayed`` **必填**，不给默认值。

        理由：曲面残差是本项目的产品指标之一（见 ``ARCHITECTURE.md §1``）。
        如果做成"没传模型就跳过曲面"，那么任何一处漏接线都会表现为
        "曲面一直空着"，而那是**静默**的 —— 与"没有曲面功能"无法区分。
        必填参数会让漏接线在启动时立刻 ``TypeError``。
        """
        self._store = store
        self._clock = clock
        self._window = StrikeWindow(feat_cfg)
        self._glitch = GlitchFilter(feat_cfg)
        self._impulse = ImpulseEngine(feat_cfg)
        self._heatmap = HeatmapEngine(clock, serial_cfg)
        self._skew = SkewEngine(feat_cfg, serial_cfg, clock)
        self._surface = SurfaceEngine(store, clock, surface_model, feat_cfg, is_delayed)
        self._each_side = loader.as_int(
            feat_cfg, "heatmap_draw_rows_each_side", module=_FEAT
        )
        # 可视窗口半径。本层**只用它填进矩阵契约**（随帧下发），不参与选档 ——
        # 选档由 _each_side 决定。放在这里是因为 features.json 的读取点必须在
        # 本层（[7] 的归属校验只认字面量 module=），而消费方在前端。
        # 为什么不是前端配置：它与订阅窗口有物理耦合，见
        # features/strike_window.py 模块注释与 [6] 的三条不变量。
        self._visible_each_side = loader.as_int(
            feat_cfg, "heatmap_visible_rows_each_side", module=_FEAT
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
        # 时间源必须取自注入的会话时钟，不能用墙钟：夹具注入的时间源可以把会话时间加速，
        # 墙钟会落在开盘之前，分桶全部钳到第 0 桶，热力图就永远差不出第一列。
        moment = now if now is not None else self._clock.now_ts()
        self._sync_session()
        # 断流恢复的那一刻必须留白，否则整段断线的变化会被压进单个桶 ——
        # 画出一堵与真冲量无法区分的假墙（见 HeatmapEngine 模块 docstring）。
        feed_gap_break = self._note_feed_gap(moment)
        # 曲面拟合放在最前面，这样**所有**早退路径都能带上缓存的摘要 ——
        # 否则"现价还没到"或"窗口还没数据"的那几帧会丢曲面字段，
        # 前端就得处理"这个字段有时在有时不在"（第二份真相）。
        surface = self._surface_summary(moment)
        spot = self._store.spot()

        if spot <= 0:
            return FeatureBundle(ts=moment, spot=0.0, surface=surface)

        rows = self._window.rows(self._session_refs(), spot, self._each_side)
        if not rows:
            return FeatureBundle(ts=moment, spot=spot, surface=surface)

        cells = self._build_cells(rows, moment)
        if not cells:
            return FeatureBundle(ts=moment, spot=spot, surface=surface)

        self._heatmap.observe(cells, moment, break_now=feed_gap_break)
        matrix = self._heatmap.build(rows, spot, moment)
        if matrix is not None:
            # 把**可视**窗口半径挂到矩阵上（随帧下发，前端照着裁可视区）。
            # 用 replace 而不是让 HeatmapEngine 去读这个键：可视半径是**呈现**
            # 参数，HeatmapEngine 不消费它，让它读等于把一个它用不上的配置
            # 塞进它的构造参数里（制造假的依赖关系）。
            matrix = replace(
                matrix, visible_rows_each_side=self._visible_each_side
            )

        skew_point = self._skew.compute(cells, spot, moment)
        self._persist_current_bucket(moment, skew_point)
        atm = self._build_atm(cells, spot, skew_point, moment)

        ok = sum(1 for c in cells if c.quality in TRUSTWORTHY_QUALITIES)

        return FeatureBundle(
            ts=moment,
            spot=spot,
            cells=cells,
            heatmap=matrix,
            skew=skew_point,
            skew_series=self._skew.series(moment),
            atm=atm,
            surface=surface,
            quality_ok=ok,
            quality_flagged=len(cells) - ok,
        )

    def _surface_summary(self, moment: float) -> SurfaceSummary | None:
        """
        到间隔就重拟合，否则复用缓存。

        ⚠️ 判据放在**本层**（``SurfaceEngine.due()``），调度权在 L8。
        这样"不许每轮都跑"这条约束不依赖调用方记得 —— 忘了限流的后果是
        帧率塌掉（SVI 单次拟合实测中位 618 ms，推送节拍 400 ms）。

        首轮必然拟合（``due()`` 的初值是 ``-inf``），之后每
        ``surface_refit_interval_s`` 一次。
        """
        if self._surface.due(moment):
            return self._surface.refit(moment)
        return self._surface.summary()

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
        顺序，夹具注入的时钟连续推进时，翻篇那一刻新会话的 tick 可能已经到了，
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
        """转调 ``atm_reader.build_atm()`` —— 汇总逻辑不在本模块（见该模块 docstring）。"""
        return build_atm(self._store, cells, spot, skew_point, now)

    def _persist_current_bucket(self, now: float, skew_point=None) -> None:
        """
        把当前桶的原始 IV 与 Skew 点丢进旁路持久化队列。

        每次 ``compute()`` 后调用；同一桶被多次覆盖写入是安全的
        （SQLite ``INSERT OR REPLACE`` 保证幂等）。

        **必须带会话身份**（``_session_key``，由 ``_sync_session()`` 在本函数
        之前落定）：``bucket_index`` 是日内坐标、每个交易日复用，不带身份的桶
        落盘后无法与别的交易日区分，恢复时就会把昨天当成今天。
        """
        writer = self._writer
        if writer is None:
            return
        session_key = self._session_key
        if not session_key:
            return  # _sync_session() 未跑过 ⇒ 身份未知，宁可不写
        idx = self._clock.bucket_index_of_ts(now)
        ivs = self._heatmap.dump_bucket(idx)
        if ivs:
            writer.enqueue(idx, ivs, self._heatmap.is_break(idx), session_key)
        if skew_point is not None:
            writer.enqueue_skew(idx, skew_point, session_key)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def _sync_session(self) -> None:
        """
        会话翻篇就清空按会话累积的状态。

        跨会话有两条独立的泄漏路径，都要堵
        ----------------------------------
        1. **桶序号被复用。** 热力图与 Skew 序列的键都是**网格内**桶序号，
           只在一天之内唯一（跨过午夜会绕回低位）。新一天第 1 桶的 IV 会去减
           上一天第 1 桶的 IV，差出一个毫无根据的冲量 —— 那不是"数据缺失"，
           而是**凭空造出来的信号**。这里靠 ``reset()`` 清掉。
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
        self._surface.reset()

    def restore_heatmap(self, columns: list[dict]) -> None:
        """从持久化存储恢复热力图原始 IV 桶。供 L8 组装层在启动时调用。"""
        self._heatmap.load_snapshot(columns)

    def restore_skew(self, points: list) -> None:
        """从持久化存储恢复 Skew 折线序列。供 L8 组装层在启动时调用。"""
        self._skew.load_series(points)

    def windows(self) -> tuple[int, ...]:
        return self._impulse.windows

    @property
    def glitch_filter(self) -> GlitchFilter:
        return self._glitch

    @property
    def surface_engine(self) -> SurfaceEngine:
        """给 L8 读诊断量（``model_name`` / ``refits`` / ``refit_interval_s``）。"""
        return self._surface
