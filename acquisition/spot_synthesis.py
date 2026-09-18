"""
L2 — GTH 现货基准合成（B2b）。
==============================
唯一职责：由前后月指数期货价反解隐含 carry，再折回现货。

为什么需要它
------------
SPX 指数在 GTH（Globex）时段**不被计算、不被播发**（Cboe Rule 9.20 强制披露；
S&P DJI 的实时指数依赖成分股 Consolidated Tape，美股不交易就没有指数）。IBKR
在 GTH 给的 SPX 指数是**上一交易日收盘的冻结值** —— 2026-09-14 实测：恒定
7656.98，而 ``ticker.marketDataType`` 仍报 1（"实时"），``max_underlying_age_s``
那条闸门结构上拦不住它。

实测危害：冻结指数与 ES 推算出的公允现货相差 **40+ 点 ≈ 8 档**（SPXW 档距
5 点）⇒ ATM 窗口会整体订偏 8 档，且不报任何错。

口径（KAI 2026-09-14 拍板 = B2b）
--------------------------------
::

    ĉ = (ln F2 − ln F1) / (T2 − T1)      前后月联立反解，单位 1/年
    S = F1 · e^(−ĉ · T1)

**不需要任何外部输入** —— r 与 q 都由两个市场价内蕴。这正是不用 B2a（外部
r−q）的理由：实测外部口径与市场内蕴值差 26.6bp，T=0.25 时值 5.04 点，而且它
是**静默**错的。也不用 B1（冻结 RTH 观测基差）：换月日会静默错值数十点。

``T`` 是**到期时刻**，不是到期日
--------------------------------
``T`` 由调用方通过 :meth:`SpotSynthesis.set_expiries` 注入，值来自 IBKR 的
``ContractDetails``（``lastTradeTime`` + ``timeZoneId``，见
``acquisition.future_expiry``）。本模块**不解析日期字符串、更不发明时刻**。

曾经这里把到期时刻当成"到期日 **00:00 UTC**"，比 ES 的真实到期时刻
（08:30 US/Central = 13:30 UTC）早 **13.5 小时**。误差在 ``T2 − T1`` 里会抵消
（所以 carry 一直是准的），但在**绝对 T1** 上不会 —— 2026-09-18（ES 季月到期日）
实测：从 00:00 UTC 起 ``T1 = -0.000970`` 为负 ⇒ ``spot()`` 命中 ``t1 <= 0``
⇒ GTH 段**一点现货都合成不出来、服务起不来**，且不报任何错。

**换月**（前月到期 ⇒ 由 (次月, 次次月) 顶上）是 :meth:`spot` 里一条显式规则，
不是"文档承诺"：候选月份必须先滤掉 ``T ≤ 0``，否则前月一到期就整天出不了值。

两层闸门
--------
1. ``max_abs_carry``：|ĉ| 越界 ⇒ fail-closed，拦"合约选错 / 数值算崩"。
2. ``max_carry_jump``：相邻两次反解的 |Δĉ| 越界 ⇒ **拒收该桶**，拦瞬时毛刺。

两层都只做"本次不出值"，**绝不回落到上一次的旧值** —— 静默回落等于把"没有
现货"伪装成"有现货"，正是本项目要禁的形态。

依赖：L0（config / contracts）与 L1（core）。
"""

from __future__ import annotations

import math

from config import loader

_CFG = "spot"


class SpotSynthesis:
    """前后月期货价 → 现货。无 IO、无时钟依赖（"现在"由调用方传入）。"""

    __slots__ = (
        "_max_abs", "_max_jump", "_quotes", "_expiries",
        "_last_carry", "_rejections", "_samples",
    )

    def __init__(self, spot_cfg: dict) -> None:
        months = loader.as_int(spot_cfg, "future_months", module=_CFG)
        if months < 2:
            # B2b 是两个方程解一个未知数（ĉ），少于两个到期月无解。
            # 这是配置错误，启动即炸 —— 不要留到运行时静默退化。
            raise loader.ConfigError(
                f"config/spot.json 的 'future_months' 必须 ≥ 2（B2b 需要前后月联立），"
                f"收到 {months}"
            )
        self._max_abs = loader.as_float(spot_cfg, "max_abs_carry", module=_CFG)
        self._max_jump = loader.as_float(spot_cfg, "max_carry_jump", module=_CFG)
        self._quotes: dict[str, tuple[float, float]] = {}
        self._expiries: dict[str, float] = {}
        self._last_carry: float | None = None
        self._rejections = 0
        self._samples = 0

    # ------------------------------------------------------------------ #
    # 只读状态
    # ------------------------------------------------------------------ #

    @property
    def carry(self) -> float | None:
        """最近一次成功反解出的隐含 carry（年化）。"""
        return self._last_carry

    @property
    def rejections(self) -> int:
        """被闸门拦下的次数（可观测：不为 0 说明输入或合约有问题）。"""
        return self._rejections

    @property
    def samples(self) -> int:
        """成功产出合成现货的次数。"""
        return self._samples

    def months(self) -> tuple[str, ...]:
        """当前已登记的到期月，升序。"""
        return tuple(sorted(self._quotes))

    # ------------------------------------------------------------------ #
    # 输入
    # ------------------------------------------------------------------ #

    def set_expiries(self, mapping: dict[str, float]) -> None:
        """
        登记 ``到期日 → 到期时刻（epoch 秒）``。**必须在 ``update()`` 之前调用。**

        到期时刻是**合约的属性**，不是每笔报价的属性，所以在这里设一次，而不是
        随每笔 tick 传下来 —— 与 ``TickRouter.set_future_contracts`` 同源同批
        （两张表都由 ``acquisition.future_expiry.build_map`` 生成）。

        没登记的月份一律 fail-closed（``_years_to`` 返回 0.0 ⇒ 被 :meth:`spot`
        滤掉），不猜一个时刻出来。
        """
        self._expiries = {
            str(key).strip(): float(value)
            for key, value in mapping.items()
            if str(key).strip()
        }

    def update(self, expiry: str, price: float, ts: float) -> None:
        """
        登记一条期货报价。

        价格非法（None / NaN / inf / ≤ 0）时**删除**该到期月，而不是留着上一次
        的值 —— 留着旧值会让"这个月没有报价"伪装成"这个月有报价"，是同一类
        静默错值。删掉之后 ``spot()`` 会自动改用后面两个月份（carry 与具体合约
        月无关，因此这是**自愈**的）；若剩余不足两个，则 fail-closed。
        """
        key = str(expiry or "").strip()
        if not key:
            return
        try:
            value = float(price)
        except (TypeError, ValueError):
            self._quotes.pop(key, None)
            return
        if math.isnan(value) or math.isinf(value) or value <= 0:
            self._quotes.pop(key, None)
            return
        self._quotes[key] = (value, float(ts))

    # ------------------------------------------------------------------ #
    # 合成
    # ------------------------------------------------------------------ #

    def spot(self, moment: float, max_age_s: float) -> float | None:
        """
        合成现货价；任一 fail-closed 条件不满足就返回 ``None``。

        候选月份 = **报价还新鲜** 且 **尚未到期**（``T > 0``），按到期时刻升序取最近
        两个。滤掉已到期月份就是**换月**：前月到期那一刻起，由 (次月, 次次月) 顶上
        —— 这正是 ``config/spot.json`` 里"订第 3 个月是换月余量"那句承诺的实现。
        （旧写法取 ``sorted(...)[:2]`` 从不跳过已到期月 ⇒ 换月日整天出不了值。）

        这里**不缓存、不回落到旧值**：拿不到就是拿不到，由调用方按"没有现货"
        处理（暂停窗口跟随并报 WARN），而不是拿一个看起来正常的旧数字顶上。
        """
        now = float(moment)
        candidates: list[tuple[float, str]] = []
        for expiry, (_, ts) in self._quotes.items():
            if (now - float(ts)) > max_age_s:
                continue
            years = self._years_to(expiry, now)
            if years <= 0:
                continue
            candidates.append((years, expiry))
        if len(candidates) < 2:
            return None
        candidates.sort()

        t1, front = candidates[0]
        t2, second = candidates[1]
        if t2 <= t1:
            # 两个不同的键指向同一个到期时刻 —— T 分母无意义，不能算。
            return None
        f1 = self._quotes[front][0]
        f2 = self._quotes[second][0]

        carry = (math.log(f2) - math.log(f1)) / (t2 - t1)

        if abs(carry) > self._max_abs:
            self._rejections += 1
            return None

        # 跳变闸门：**基准照常跟上**，只拒收这一桶。若基准不更新，一次真实跳变
        # 会让后续每一桶都被拒收 —— 那是死锁，不是保护。
        # 换月那一刻 S 会跳（Sep 锚 → Dec 锚，实测 ≈11 点）⇒ 第一拍被这里拒收、
        # 第二拍起正常 —— 自愈一拍，不是故障。
        jumped = (
            self._last_carry is not None
            and abs(carry - self._last_carry) > self._max_jump
        )
        self._last_carry = carry
        if jumped:
            self._rejections += 1
            return None

        price = f1 * math.exp(-carry * t1)
        if not (price > 0):
            return None
        self._samples += 1
        return price

    def diagnosis(self, moment: float) -> str:
        """
        一行"为什么合成不出来" —— 起不来时**唯一**能带进日志的东西。

        为什么要有它：``_note()`` 不写 logging，所以合成静默返回 ``None`` 时，
        日志里干净得像什么都没发生（2026-09-18 实测）。而 ``_await_spot`` 超时抛的
        异常**是**会进日志的，把这段状态拼进异常消息，下一次就不用再查两小时。
        """
        if not self._quotes:
            return "尚无任何期货报价登记"
        now = float(moment)
        items: list[str] = []
        for expiry in sorted(self._quotes):
            _, ts = self._quotes[expiry]
            years = self._years_to(expiry, now)
            flags = []
            if expiry not in self._expiries:
                flags.append("无到期时刻")
            elif years <= 0:
                flags.append("已到期")
            flags.append(f"报价{now - float(ts):.0f}s前")
            items.append(f"{expiry}={years:+.6f}({','.join(flags)})")
        return (
            f"期货 {len(items)} 个月 T: " + " ".join(items)
            + f"；合成成功 {self._samples} 次 / 闸门拒收 {self._rejections} 次"
        )

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #

    def _years_to(self, expiry: str, moment: float) -> float:
        """
        ``expiry``（"YYYYMMDD"）的**到期时刻**到 ``moment`` 的年数。

        到期时刻由 :meth:`set_expiries` 注入（来自 IBKR 的 ``lastTradeTime`` +
        ``timeZoneId``）。本模块不解析日期字符串、更不发明时刻：曾经这里用
        "到期日 00:00 UTC"，比真实时刻早 13.5 小时 ⇒ 前月被提前判死。

        未登记的 ``expiry`` 返回 0.0，由调用方按"T 非法"fail-closed 掉。
        """
        instant = self._expiries.get(str(expiry or "").strip())
        if instant is None:
            return 0.0
        return (instant - float(moment)) / (365.0 * 86400.0)
