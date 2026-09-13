"""
L0 — 层间接口（Protocol）。
===========================
整个系统"单向依赖"能成立的关键：**调用方依赖抽象，实现方也依赖抽象，双方都
只认识 L0**。

举例：L5（传输）需要拿到最新帧，如果它 import L4，就变成 L5→L4 的硬依赖；
一旦 L4 内部结构调整，传输层就得跟着改。这里定义 ``FrameSource``，L4 去实现它、
L5 去消费它，两边互不认识。

注意：这里只放**结构契约**，不放任何实现。协议里的方法签名就是层与层之间的
正式接口，改动它等于改动架构，需要同步所有实现方。
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

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
# 数据下沉（L1 → L2）
# --------------------------------------------------------------------------- #


@runtime_checkable
class TickSink(Protocol):
    """
    采集层把归一化后的 tick 推给状态层的出口。

    L1 只知道这个协议，不知道对端是内存存储还是别的东西。
    实现方必须**非阻塞**：本方法在 IBKR 回调线程里被调用，任何阻塞都会
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
# 数据源（L1 实现）
# --------------------------------------------------------------------------- #


@runtime_checkable
class FeedPort(Protocol):
    """
    行情源。目前唯一的生产实现是 ``IbkrFeed``（IBKR）。

    之所以仍然定义为协议、而不是让组装层直接依赖 ``IbkrFeed``：L6 只认识本
    协议，于是"换一个数据源"（接入别的经纪商、或另写一个实现）不必改动任何
    下游代码，也不会让组装层反向依赖 L1 的具体模块。
    """

    def set_sink(self, sink: TickSink) -> None:
        """注入下游接收者。必须在 ``start()`` 之前调用。"""
        ...

    def set_reconnect_hook(self, hook: Callable[[], None]) -> None:
        """
        注册"连接重建成功"之后要执行的回调，由行情源在自动重连成功时触发。

        为什么这条钩子必须进端口
        ------------------------
        它是 L1 → L6 的**上行**信号（下层告诉组装层"我刚重连了"）。组装层只
        认识 ``FeedPort``，如果这条钩子只长在 ``IbkrFeed`` 上，那么任何一次
        "换数据源"或"新写一个实现"都会静默漏掉它。

        本项目已经在这类"接口没写、实现漏了、调用方碰运气"的模式上栽过一次：
        ``SessionClock`` 没有实现 ``ClockPort.now()``，于是 ``TickStore.prune()``
        每 10 秒抛一次被吞掉的异常，时间窗裁剪长期形同虚设。所以这里选择把
        钩子写进协议 —— 让 ``runtime_checkable`` 能静态地要求两个实现都有它。

        "要不要据此清空特征状态"不属于本层：L1 只负责报告事件，决策由组装层
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
# 帧流转（L4 → L5）
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
    里面有哪些字段。这样 L5 只依赖 L0，不会 import L4 的编码器。
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
