"""
L6 — 载荷组装器。
==================
唯一职责：把 L5 的 ``FeatureBundle`` 与 L3 的健康读数合成一帧，编码成 JSON 文本，
并对外暴露"最新一帧"。

它同时实现两个 L0 协议
----------------------
* ``FrameSource``：给健康面板/调试用的语义快照。
* ``PayloadSource``：给传输层用的成品文本。

这样 L7 只依赖 L0 就能拿到可发送内容，不必 import 本模块的任何编码器。

为什么在这里预编码
------------------
编码（尤其是热力图矩阵的逐格舍入）是整条链路里最贵的一步。把它放在特征循环
里做一次，传输层就只是搬运字符串——即使前端全部掉线、广播被跳过，也不会有
任何重复编码开销。

依赖：L0、L3（MarketState 的类型无关，通过鸭子类型调用）、L6 内部。
"""

from __future__ import annotations

from typing import Any

from contracts.feature import FeatureBundle
from contracts.frame import Frame
from contracts.tick import FeedStatus

from serialization.frame_encoder import FrameEncoder


class PayloadBuilder:
    """FeatureBundle + 健康信息 → 可发送的 JSON 文本。"""

    __slots__ = ("_state", "_encoder", "_seq", "_frame", "_payload", "_count")

    def __init__(self, market_state: Any, serial_cfg: dict, clock) -> None:
        self._state = market_state
        self._encoder = FrameEncoder(serial_cfg, clock)
        self._seq = 0
        self._frame: Frame | None = None
        self._payload: tuple[str, int] | None = None
        self._count = 0

    # ------------------------------------------------------------------ #
    # 产出
    # ------------------------------------------------------------------ #

    def build(self, bundle: FeatureBundle, feed_status: FeedStatus) -> Frame:
        """
        合成一帧并完成编码。返回的 ``Frame`` 同时被缓存。

        ⚠️ **每个字段都要显式搬运** —— ``Frame`` 的字段都有默认值，漏传一个不会
        报错，只会让那个字段恒为 ``None``/``()``，前端表现为"这个功能一直没有
        数据"（静默空值）。本模块因此刻意不用 ``dataclasses.replace`` 或
        ``**asdict`` 这类"自动搬运"：显式列表让漏传在 code review 时看得见。
        """
        self._seq += 1

        frame = Frame(
            seq=self._seq,
            ts=bundle.ts,
            spot=bundle.spot,
            session=self._state.session_block(),
            health=self._state.health(feed_status, bundle.ts),
            heatmap=bundle.heatmap,
            skew=bundle.skew,
            skew_series=bundle.skew_series,
            cells=bundle.cells,
            atm=bundle.atm,
            surface=bundle.surface,
        )

        self._frame = frame
        self._payload = (self._encoder.dumps(frame), frame.seq)
        self._count += 1
        return frame

    # ------------------------------------------------------------------ #
    # FrameSource / PayloadSource
    # ------------------------------------------------------------------ #

    def latest(self) -> Frame | None:
        return self._frame

    def latest_payload(self) -> tuple[str, int] | None:
        return self._payload

    def frame_count(self) -> int:
        return self._count

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #

    def encode_only(self, frame: Frame) -> str:
        """把一个已有帧重新编码（离线回放或测试用）。"""
        return self._encoder.dumps(frame)

    def reset(self) -> None:
        self._frame = None
        self._payload = None
