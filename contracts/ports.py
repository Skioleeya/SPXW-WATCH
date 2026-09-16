"""
L0 — 层间接口（Protocol）。
===========================
整个系统"单向依赖"能成立的关键：**调用方依赖抽象，实现方也依赖抽象，双方都
只认识 L0**。

举例：L7（传输）需要拿到最新帧，如果它 import L6，就变成 L7→L6 的硬依赖；
一旦 L6 内部结构调整，传输层就得跟着改。这里定义 ``PayloadSource``，L6 去实现它、
L7 去消费它，两边互不认识。

注意：这里只放**结构契约**，不放任何实现。协议里的方法签名就是层与层之间的
正式接口，改动它等于改动架构，需要同步所有实现方。
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from contracts.feature import SurfaceSummary
from contracts.frame import Frame
from contracts.tick import (
    FeedStatus,
    OptionTick,
    QuoteTick,
    SpotTick,
    StatusEvent,
)

# --------------------------------------------------------------------------- #
# 时间源
# --------------------------------------------------------------------------- #


@runtime_checkable
class ClockPort(Protocol):
    """时间源。生产实现是墙上时钟（``core.clock.WallClock``）。"""

    def now(self) -> float:
        """返回当前时间（epoch 秒）。"""
        ...


# --------------------------------------------------------------------------- #
# 数据下沉（L2 → L3）
# --------------------------------------------------------------------------- #


@runtime_checkable
class TickSink(Protocol):
    """
    采集层把归一化后的 tick 推给状态层的出口。

    L2 只知道这个协议，不知道对端是内存存储还是别的东西。
    实现方必须**非阻塞**：本方法在 IBKR 回调路径里被调用，任何阻塞都会
    拖垮行情通道。
    """

    def on_option_tick(self, tick: OptionTick) -> None:
        ...

    def on_quote_tick(self, tick: QuoteTick) -> None:
        ...

    def on_spot_tick(self, tick: SpotTick) -> None:
        ...

    def on_status(self, event: StatusEvent) -> None:
        ...


# --------------------------------------------------------------------------- #
# 数据源（L2 实现）
# --------------------------------------------------------------------------- #


@runtime_checkable
class FeedPort(Protocol):
    """
    行情源。目前唯一的生产实现是 IBKR（``ib_async``）。

    之所以仍然定义为协议、而不是让组装层直接依赖具体实现：L8 只认识本
    协议，于是"换一个数据源"不必改动任何下游代码，也不会让组装层反向依赖
    L2 的具体模块。
    """

    def set_sink(self, sink: TickSink) -> None:
        """注入下游接收者。必须在 ``start()`` 之前调用。"""
        ...

    def set_reconnect_hook(self, hook: Callable[[], None]) -> None:
        """
        注册"连接重建成功"之后要执行的回调，由行情源在自动重连成功时触发。

        为什么这条钩子必须进端口
        ------------------------
        它是 L2 → L8 的**上行**信号（下层告诉组装层"我刚重连了"）。组装层只
        认识 ``FeedPort``，如果这条钩子只长在具体实现上，那么任何一次
        "换数据源"或"新写一个实现"都会静默漏掉它。

        本项目已经在这类"接口没写、实现漏了、调用方碰运气"的模式上栽过一次：
        ``SessionClock`` 没有实现 ``ClockPort.now()``，于是 ``TickStore.prune()``
        每 10 秒抛一次被吞掉的异常，时间窗裁剪长期形同虚设。所以这里选择把
        钩子写进协议 —— 让 ``runtime_checkable`` 能静态地要求实现方有它。

        "要不要据此清空特征状态"不属于本层：L2 只负责报告事件，决策由组装层
        按 ``pipeline.reset_feature_state_on_reconnect`` 做。
        """
        ...

    async def start(self) -> None:
        """建立连接、解析合约链、开始订阅并进入运行态。"""
        ...

    async def stop(self) -> None:
        """取消订阅、断开连接、释放资源。必须可重入。"""
        ...

    def status(self) -> FeedStatus:
        """返回当前健康快照（非阻塞，供健康面板调用）。"""
        ...

    @property
    def mode(self) -> str:
        """数据模式标识，用于前端标注。"""
        ...


# --------------------------------------------------------------------------- #
# 帧流转（L6 → L7）
# --------------------------------------------------------------------------- #


@runtime_checkable
class FrameSource(Protocol):
    """
    最新帧的提供方。实现方必须是**无锁读**：传输层每秒调用多次，
    不能因为读一个快照而阻塞特征计算。
    """

    def latest(self) -> Frame | None:
        ...


@runtime_checkable
class PayloadSource(Protocol):
    """
    已序列化载荷的提供方。

    传输层只需要"一段可以直接发出去的文本"，不需要知道 JSON 是怎么拼的、
    里面有哪些字段。这样 L7 只依赖 L0，不会 import L6 的编码器。
    """

    def latest_payload(self) -> tuple[str, int] | None:
        """返回 ``(JSON 文本, 帧序号)``；尚无可用帧时返回 ``None``。"""
        ...

    def frame_count(self) -> int:
        """累计产出的帧数，用于健康面板与丢帧检测。"""
        ...


@runtime_checkable
class FrameSink(Protocol):
    """
    帧的消费方。实现方必须容忍高频调用并自行做背压处理
    （慢客户端丢帧，而不是让生产者等待）。
    """

    def publish(self, frame: Frame) -> None:
        ...


# --------------------------------------------------------------------------- #
# 曲面模型（L4 实现，L5 消费）
# --------------------------------------------------------------------------- #


@runtime_checkable
class SurfaceInputPort(Protocol):
    """
    曲面模型读取原始行情的入口。

    ⚠️ **这 5 个属性就是全部耦合面**，是从原版 `models/` 逐字核出来的
    （`grep -ohE "app\\.[a-z_]+" models/*.py` 只有这 5 个）。刻意保持这么窄：
    适配器只要暴露这 5 个属性，模型层就能原样工作，不必认识本项目的
    ``TickStore`` / ``SessionClock`` 等任何类型。

    实现方（``features/surface_engine.py``）负责把状态层翻译成这个形状。

    ⚠️ **形状以消费方代码为准，不以本 docstring 为准。**
    唯一读这些属性的地方是 ``models/raw_cleaning.py::build_clean_surface()``
    （L59–L105），下面每个字段都标了对应行号。**改契约前先读那 30 行** ——
    本 docstring 早先写成 ``{expiry: {strike: iv}}`` 形状，与代码不符：
    真形状是 **按 reqId 索引的三张平行表**。照错形状写适配器，后果是
    ``if rid not in app.id_map: continue`` 把每一行都跳过 ⇒ ``fresh_count == 0``
    ⇒ 曲面恒为空，**且不抛任何异常**（静默错值，不是崩溃）。
    """

    @property
    def iv_dict(self) -> dict:
        """
        ``{req_id: point}``。``point`` 是 ``dict``（含 ``iv`` / ``time`` /
        ``optPrice`` / ``undPrice`` / ``tickType``），也允许是裸 ``float``
        （此时年龄按 0 算，见 L65–L77）。

        ``req_id`` 只要求**可哈希且在本快照内唯一** —— 模型层不解释它的含义，
        只拿它去 ``id_map`` / ``quote_dict`` 里对齐。本项目的实现方用
        ``(expiry, strike, right)`` 元组，比裸整数更抗错位。
        """
        ...

    @property
    def id_map(self) -> dict:
        """
        ``{req_id: (expiry_str, strike_float)}`` —— 把 reqId 翻译成曲面坐标（L60–L63）。

        ⚠️ **本项目的实现方返回三元组** ``(expiry, strike, right)``，
        比上面的两元多一个方向。为什么要有第三个：

        残差是**逐 reqId** 的 —— 同一档的 Put / Call 各出一条，真实行情下常常
        一正一负。方向若在 ``id_map`` 就丢掉，它就再也回不来（``clean_df`` →
        ``residuals()`` → ``SurfaceResidual`` 整条链都无从补），前端残差图上
        同 strike 的两个点会重叠/抵消。见 ``contracts/feature.py::SurfaceResidual``。

        **对模型层无影响**：``raw_cleaning.py`` 只解前两元做曲面坐标（用切片而不是
        三元组解包，故两元实现同样可用），第三元仅用于给 ``clean_df`` 打标记。
        所以这里写的是**允许的形状**，不是强制三元组。
        """
        ...

    @property
    def quote_dict(self) -> dict:
        """
        ``{req_id: {bid, ask, last, close, bidSize, askSize, lastSize, quote_time}}``
        （L85–L104）。键缺失一律按 ``None`` 处理，模型层会把它计入
        ``missing_quote`` 并在 ``require_bid_ask_for_filter`` 为真时剔除该点。
        """
        ...

    @property
    def spot_price(self) -> float:
        """标的现价。``<= 0`` 会让模型层直接放弃本轮拟合（``svi_surface_model.py:147``）。"""
        ...

    @property
    def is_delayed(self) -> bool:
        """
        当前是否为延迟行情。

        唯一作用：选择 IV 的**最大允许年龄**（``CleaningParams.max_iv_age``，
        延迟行情给更宽的窗口）。缺失时模型层按 ``True`` 处理（``raw_cleaning.py:50``）。
        """
        ...


@runtime_checkable
class SurfaceModelPort(Protocol):
    """
    曲面模型。L5 只认识这个协议，不认识具体是 Raw / SVI / SSVI。

    ⚠️ **``summary()`` 必须返回 L0 的 ``SurfaceSummary``，不得返回 DataFrame。**
    这是把 numpy/pandas 关在 L4 里的**机械手段**：L5 拿到的是普通 dataclass，
    就算想用 pandas 也没有对象可用。由 ``tools/selfcheck_duty.py`` 守住。
    """

    @property
    def name(self) -> str:
        """模型名（用于帧内标注）。"""
        ...

    def fit(self, source: SurfaceInputPort) -> None:
        """按当前行情重新拟合。实现方必须自己处理坏切片（退回 Raw）。"""
        ...

    def summary(self) -> SurfaceSummary:
        """拟合诊断 + 逐点残差，已翻译成 L0 类型。"""
        ...

    def iv(self, expiry: str, strike: float) -> float | None:
        """查询某个 (到期日, 行权价) 的模型 IV（小数）。"""
        ...
