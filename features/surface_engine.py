"""
L5 — 曲面引擎。
================
唯一职责：把 L3 的 tick 存储翻译成 ``SurfaceInputPort`` 的形状，驱动 L4 的曲面模型
拟合，并缓存最近一次结果（``SurfaceSummary``）。

为什么需要这一层
----------------
``models/`` 只认识 5 个属性（``iv_dict`` / ``id_map`` / ``quote_dict`` /
``spot_price`` / ``is_delayed``），不认识本项目的 ``TickStore``。
本模块就是那条**唯一接缝** —— 除此之外 L4 与 L3 之间没有任何耦合。

⚠️ 形状以消费方代码为准
-----------------------
``models/raw_cleaning.py::build_clean_surface()``（L57–L105）按 **reqId 索引的
三张平行表** 读取，**不是** ``{expiry: {strike: iv}}`` 那种"看起来更自然"的形状。
写错形状的后果是静默的：``if rid not in app.id_map: continue`` 会跳过每一行
⇒ ``fresh_count == 0`` ⇒ 曲面恒为空，**且不抛任何异常**。
契约逐字段说明见 ``contracts/ports.py::SurfaceInputPort``。

为什么 reqId 用 ``(expiry, strike, right)`` 元组
-------------------------------------------------
模型层只要求它可哈希且在本快照内唯一。用元组而不是自增整数：
  * 同一个 ``(expiry, strike)`` 上 Put 与 Call 是**两张不同合约**，用序号容易错位；
  * 元组自解释，且天然不重复。
模型层按 ``id_map`` 把它翻回 ``(expiry, strike)`` —— 同档两侧会落到 pivot
的同一格，由 ``pivot_table`` 取均值。**这是原版语义，未改。**

⚠️ ``id_map`` 的值是**三元组** ``(expiry, strike, right)``，不是两元组。
``raw_cleaning.py`` 只解前两元（曲面坐标），第三元用于给 ``clean_df`` 打上
方向标记 —— 该标记最终到达 ``SurfaceResidual.right``。同 strike 的 Put / Call
各出一条残差，没有方向字段时前端无法区分（实测 50 条 / 25 档 = 2×）。

为什么要喂**两侧**、不能只喂虚值一侧
------------------------------------
``build_clean_surface()`` 有一道 ``clean_count >= min_points_to_plot``（默认 30）
的门槛。本项目 ``heatmap_rows_each_side = 12`` ⇒ ±12 档 = 24 个行权价，
**只喂虚值一侧只有 24 个点，永远过不了 30**；两侧都喂是 48 个点，才过。
热力图每档只留虚值一侧是**展示**选择，与曲面拟合的数据需求不是一回事。

⚠️ 拟合很贵 —— 绝不能每轮 compute 都跑
--------------------------------------
实测（2026-09-15，48 个点、5 个多起点，`venv/Scripts/python.exe`）：

| 模型 | 中位 | 最小 | 最大 |
|---|---|---|---|
| RawSurface | 35.8 ms | 28.7 | 49.5 |
| **SVI** | **618.2 ms** | **342.8** | **1439.3** |
| SSVI | 35.7 ms | 29.7 | 50.8 |

而推送节拍只有 400 ms ⇒ 每轮都拟合 SVI 会让帧率直接塌掉。因此：
  * 拟合按 ``config/features.json::surface_refit_interval_s`` 限流；
  * 限流由本模块自己判（``due()``），**不依赖调用方记得**；
  * 两次拟合之间复用缓存结果 ⇒ ``FeatureBundle.surface`` 是**阶梯状**的，
    这是设计而非缺陷（曲面残差是慢变量诊断量，不是逐 tick 指标）；
  * ⚠️ L8 调用 ``refit()`` 时**应当放到线程里**（``asyncio.to_thread``）：
    618 ms 的同步调用在事件循环上会吞掉约 1.5 个推送周期。

依赖：L0（config / contracts）、L1（core）、L3（存储，鸭子类型）、L4（``SurfaceModelPort``）。
"""

from __future__ import annotations

from config import loader
from contracts.feature import SurfaceSummary
from contracts.ports import SurfaceModelPort

_FEAT = "features"


class SurfaceSnapshot:
    """
    一次拟合用的行情快照，实现 ``SurfaceInputPort``。

    为什么是**快照**而不是活视图：拟合期间存储还在被行情线程写。把 5 张表在
    构造时拷平，拟合看到的就是一个自洽的时间点，且**可以在别的线程里跑**
    （L8 会这么干）而不必加锁。
    """

    __slots__ = ("_iv", "_ids", "_quotes", "_spot", "_delayed")

    def __init__(
        self,
        iv_dict: dict,
        id_map: dict,
        quote_dict: dict,
        spot_price: float,
        is_delayed: bool,
    ) -> None:
        self._iv = iv_dict
        self._ids = id_map
        self._quotes = quote_dict
        self._spot = spot_price
        self._delayed = is_delayed

    @property
    def iv_dict(self) -> dict:
        return self._iv

    @property
    def id_map(self) -> dict:
        return self._ids

    @property
    def quote_dict(self) -> dict:
        return self._quotes

    @property
    def spot_price(self) -> float:
        return self._spot

    @property
    def is_delayed(self) -> bool:
        return self._delayed


class SurfaceEngine:
    """L5 的曲面入口。持有模型、按间隔重拟合、缓存最近一次结果。"""

    __slots__ = (
        "_store", "_clock", "_model", "_is_delayed",
        "_interval_s", "_last_refit_ts", "_summary", "_refits",
    )

    def __init__(
        self,
        store,
        clock,
        model: SurfaceModelPort,
        feat_cfg: dict,
        is_delayed,
    ) -> None:
        """
        Parameters
        ----------
        store
            鸭子类型：只用 ``refs()`` / ``latest_option()`` / ``quote()`` / ``spot()``。
        clock
            只用 ``expiry_str()``（会话身份 = 当日到期日，与 ``FeatureEngine`` 同源）。
        model
            L4 的曲面模型（``SurfaceModelPort``）。**必填** —— 不做"没模型就跳过曲面"
            这种可关特性，那会让曲面静默消失。
        feat_cfg
            ``config/features.json``。
        is_delayed
            返回当前是否延迟行情的 **callable**（延迟行情用更宽的 IV 年龄门槛）。
            传函数而不是布尔，是因为它每轮都可能变，而本对象只构造一次。
        """
        self._store = store
        self._clock = clock
        self._model = model
        self._is_delayed = is_delayed
        self._interval_s = loader.as_float(
            feat_cfg, "surface_refit_interval_s", module=_FEAT
        )
        # 用 -inf 而不是 0：第一轮就应当拟合，不必等满一个间隔。
        self._last_refit_ts = float("-inf")
        self._summary: SurfaceSummary | None = None
        self._refits = 0

    # ------------------------------------------------------------------ #
    # 对外
    # ------------------------------------------------------------------ #

    def due(self, now: float) -> bool:
        """到重拟合时间了吗。首轮恒为真（``_last_refit_ts`` 初始为 ``-inf``）。"""
        return (now - self._last_refit_ts) >= self._interval_s

    def refit(self, now: float) -> SurfaceSummary:
        """
        立即重拟合一次并缓存结果。

        **CPU 密集**（SVI 实测中位 618 ms）—— 调用方在事件循环里跑之前先看模块
        docstring 的那张表。本方法不自己限流（``due()`` 是给调用方判的），
        因为"什么时候跑"是调度决策，属 L8。
        """
        snapshot = self._build_snapshot()
        self._model.fit(snapshot)
        self._summary = self._model.summary()
        self._last_refit_ts = now
        self._refits += 1
        return self._summary

    def summary(self) -> SurfaceSummary | None:
        """最近一次拟合结果。首次 ``refit()`` 之前为 ``None``。"""
        return self._summary

    def reset(self) -> None:
        """
        会话翻篇时调用。

        必须做两件事，缺一不可：
          1. 丢掉上一会话的摘要 —— 否则新会话第一帧会带着昨天的残差；
          2. 把 ``_last_refit_ts`` 推回 ``-inf`` —— 否则新会话开头这段时间
             会沿用旧时间戳，``due()`` 判否 ⇒ 新会话**迟迟不拟合**。
        """
        self._summary = None
        self._last_refit_ts = float("-inf")

    @property
    def model_name(self) -> str:
        return self._model.name

    @property
    def refits(self) -> int:
        """累计拟合次数（诊断用；``reset()`` 不清零，它是进程级计数）。"""
        return self._refits

    @property
    def refit_interval_s(self) -> float:
        return self._interval_s

    # ------------------------------------------------------------------ #
    # 快照
    # ------------------------------------------------------------------ #

    def _build_snapshot(self) -> SurfaceSnapshot:
        """
        把存储翻译成模型层要的 5 个属性。

        只取**属于当前会话**的合约（按 ``ref.expiry`` 过滤），与
        ``FeatureEngine._session_refs()`` 同源同理：``bucket_index`` 与 IV 的
        前向填充语义都只在会话内有意义，跨会话的旧 tick 会让曲面拟合出一个
        不存在的微笑。
        """
        session_key = self._clock.expiry_str()
        iv_dict: dict = {}
        id_map: dict = {}
        quote_dict: dict = {}

        for ref in self._store.refs():
            if ref.expiry != session_key:
                continue
            tick = self._store.latest_option(ref)
            if tick is None or tick.iv is None:
                continue

            # reqId：自解释的元组，保证同一档的 Put / Call 不互相覆盖。
            rid = (ref.expiry, float(ref.strike), ref.right.value)
            iv_dict[rid] = {
                "iv": float(tick.iv),
                "time": float(tick.ts),
                "optPrice": tick.opt_price,
                "undPrice": tick.und_price,
                "tickType": tick.source_tick_type,
            }
            # id_map 也带上方向（三元组，与 rid 同形）。模型层只解前面的
            # (expiry, strike) 两元，第三元被忽略 —— 曲面坐标不受影响；
            # 它的作用是让 raw_cleaning 能把方向写进 clean_df，最终到达
            # SurfaceResidual.right（否则同 strike 的 Put/Call 两条残差无法区分）。
            id_map[rid] = (ref.expiry, float(ref.strike), ref.right.value)
            quote_dict[rid] = self._quote_fields(ref)

        return SurfaceSnapshot(
            iv_dict=iv_dict,
            id_map=id_map,
            quote_dict=quote_dict,
            spot_price=float(self._store.spot()),
            is_delayed=bool(self._is_delayed()),
        )

    def _quote_fields(self, ref) -> dict:
        """
        盘口快照。键名必须与 ``raw_cleaning.py`` 读取的完全一致（L97–L104）。

        没有盘口的档返回**空 dict** 而不是填 ``None``：模型层对两种写法等价
        （都走 ``quote.get(...)`` → ``None``），但空 dict 更省内存 —— 远虚值档
        长期没有盘口，每个都塞 8 个 ``None`` 是无谓的。
        """
        quote = self._store.quote(ref)
        if quote is None:
            return {}
        return {
            "bid": quote.bid,
            "ask": quote.ask,
            "last": quote.last,
            "close": quote.close,
            "bidSize": quote.bid_size,
            "askSize": quote.ask_size,
            "lastSize": quote.last_size,
            "quote_time": float(quote.ts),
        }
