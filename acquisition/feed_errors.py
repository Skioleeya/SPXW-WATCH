"""
L1 — IBKR 错误码翻译器。
========================
把网关层抛来的原始 (reqId, code, message) 翻译成项目内部的状态动作
（退避、重建订阅、记录日志等）。

本模块是纯逻辑，不持有任何网络连接或异步状态。

依赖：L0。
"""
from __future__ import annotations

from typing import Any, Callable

from contracts.enums import StatusLevel
from core.clock import now_ts

_CODE_SUBSCRIPTION_LIMIT = 300
_CODE_DATA_LOST = 1101
_CODE_NO_SECURITY = 200
_IGNORED_CODES = frozenset(
    {1100, 1102, 2103, 2104, 2105, 2106, 2108, 2110, 2119, 2158,
     10089, 10090, 10091, 10167}
)


class FeedErrorHandler:
    """处理 IBKR 推送的错误码，转化为内部动作。"""

    __slots__ = (
        "_manager", "_note", "_last_error", "_recover_at",
        "_trigger_resubscribe",
    )

    def __init__(
        self,
        manager: Any,
        note_callback: Callable[..., None],
        trigger_resubscribe: Callable[[], None],
    ) -> None:
        self._manager = manager
        self._note = note_callback
        self._last_error = ""
        self._recover_at = 0.0
        self._trigger_resubscribe = trigger_resubscribe

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def recover_at(self) -> float:
        return self._recover_at

    def set_recover_at(self, value: float) -> None:
        self._recover_at = value

    def handle(self, req_id: int, code: int, message: str, contract: Any) -> None:
        """翻译单个 IBKR 错误码并执行对应动作。"""
        if code == _CODE_SUBSCRIPTION_LIMIT:
            backoff = self._manager.note_limit_hit()
            self._recover_at = now_ts() + backoff
            self._note(
                f"触发 IBKR Error 300（行情行数超限），退避 {backoff:.0f}s",
                StatusLevel.ERROR, code,
            )
            return

        if code == _CODE_DATA_LOST:
            self._note(
                "IBKR 1101：行情订阅状态丢失，准备重建",
                StatusLevel.WARN, code,
            )
            self._trigger_resubscribe()
            return

        if code == _CODE_NO_SECURITY:
            self._note(
                f"合约无定义 (reqId={req_id}): {message}",
                StatusLevel.WARN, code,
            )
            return

        if code in _IGNORED_CODES:
            return

        self._last_error = f"{code}: {message}"
        self._note(f"IBKR 错误 {code}: {message}", StatusLevel.WARN, code)
