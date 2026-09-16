"""
L5 — 毛刺过滤。
===============
唯一职责：判断一个网格点的当前 IV 是否可信，输出 ``Quality`` 标签。

要解决的真实问题
----------------
0DTE 到了下午盘，离现价很远的极度虚值期权价格会跌到 0.05 以下。此时 IV 的
计算本质上是"一个极小的时间价值 ÷ 一个极小的价格"，分母效应会让 IV 在没有
任何真实信息的情况下飙到 200% 以上。这类点如果进热力图，会在收盘前把整张图
的颜色标度彻底毁掉。

五道闸门（任一不通过即判定为毛刺）
----------------------------------
1. IV 绝对值越界
2. 期权绝对价格过低（分母效应的根因）
3. 与上一笔 tick 的跳变过大（瞬时错价/胖手指）
4. 偏离近期中位数超过 ``mad_multiplier`` 倍 MAD（鲁棒离群，用 MAD 而非标准差
   是因为标准差本身会被离群点污染）
5. tick 过旧

依赖：L0（config / contracts）与 L1（core）。
"""

from __future__ import annotations

from statistics import median

from config import loader
from contracts.enums import Quality
from contracts.tick import OptionTick, QuoteTick
from core.ring_buffer import RingBuffer

_CFG = "features"


def _mad(values: list[float], centre: float) -> float:
    """中位数绝对偏差。"""
    if not values:
        return 0.0
    return median([abs(v - centre) for v in values])


class GlitchFilter:
    """对单个网格点做可信度判定。"""

    __slots__ = (
        "_min_price", "_min_iv", "_max_iv", "_max_age",
        "_mad_window", "_mad_mult", "_max_jump_vol_points",
    )

    def __init__(self, feat_cfg: dict) -> None:
        self._min_price = loader.as_float(
            feat_cfg, "glitch_min_abs_option_price", module=_CFG
        )
        self._min_iv = loader.as_float(feat_cfg, "glitch_min_iv", module=_CFG)
        self._max_iv = loader.as_float(feat_cfg, "glitch_max_iv", module=_CFG)
        self._max_age = loader.as_float(
            feat_cfg, "glitch_max_tick_age_s", module=_CFG
        )
        self._mad_window = loader.as_int(feat_cfg, "glitch_mad_window", module=_CFG)
        self._mad_mult = loader.as_float(
            feat_cfg, "glitch_mad_multiplier", module=_CFG
        )
        self._max_jump_vol_points = loader.as_float(
            feat_cfg, "glitch_max_jump_vol_points", module=_CFG
        )

    # ------------------------------------------------------------------ #
    # 主判定
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        buffer: RingBuffer[OptionTick] | None,
        quote: QuoteTick | None,
        now: float,
    ) -> Quality:
        """返回该分片当前时刻的可信度标签。"""
        if buffer is None or not buffer:
            return Quality.MISSING

        latest = buffer.latest()
        if latest is None:
            return Quality.MISSING

        tick = latest.value
        if now - tick.ts > self._max_age:
            return Quality.STALE

        if not (self._min_iv <= tick.iv <= self._max_iv):
            return Quality.GLITCH

        if not self._price_ok(tick, quote):
            return Quality.GLITCH

        if self._jumped(buffer, tick):
            return Quality.GLITCH

        if self._off_baseline(buffer, tick):
            return Quality.GLITCH

        return Quality.OK

    # ------------------------------------------------------------------ #
    # 各道闸门
    # ------------------------------------------------------------------ #

    def _price_ok(self, tick: OptionTick, quote: QuoteTick | None) -> bool:
        """期权价格必须高于阈值；价格缺失时用盘口中间价兜底。"""
        price = tick.opt_price
        if price is None and quote is not None:
            price = quote.mid
        if price is None:
            # 拿不到价格就不做这一道判断，避免把正常点全部误杀。
            return True
        return price >= self._min_price

    def _jumped(self, buffer: RingBuffer[OptionTick], tick: OptionTick) -> bool:
        """与上一笔 tick 的跳变是否超过阈值（单位：波动率点）。"""
        samples = list(buffer.samples())
        if len(samples) < 2:
            return False
        previous = samples[-2].value
        return abs(tick.iv - previous.iv) * 100.0 > self._max_jump_vol_points

    def _off_baseline(self, buffer: RingBuffer[OptionTick], tick: OptionTick) -> bool:
        """相对近期中位数的 MAD 离群检测（不含当前点本身）。"""
        if self._mad_window < 3:
            return False
        samples = list(buffer.samples())
        history = [s.value.iv for s in samples[:-1]][-self._mad_window:]
        if len(history) < 3:
            return False

        centre = median(history)
        spread = _mad(history, centre)
        if spread <= 0:
            return False
        return abs(tick.iv - centre) > self._mad_mult * spread

    # ------------------------------------------------------------------ #
    # 供上游复用的阈值
    # ------------------------------------------------------------------ #

    @property
    def max_tick_age_s(self) -> float:
        return self._max_age

    @property
    def min_option_price(self) -> float:
        return self._min_price
