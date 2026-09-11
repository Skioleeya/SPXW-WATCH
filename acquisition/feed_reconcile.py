"""
L1 — 窗口跟随现价维护循环。
============================
定期检查标的价格是否显著移动，并据此重建 ATM 附近的期权订阅窗口。

本模块只依赖 L0，通过构造器注入的 callable 与宿主 ``IbkrFeed`` 交互，
避免对宿主的硬引用。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from config import loader
from contracts.enums import StatusLevel
from core.clock import now_ts


class WindowFollower:
    """
    维护「以现价为中心的 ATM 窗口」的订阅。

    逻辑
    ----
    每隔 ``reconcile_interval_s`` 检查一次：
    1. 订阅配额是否已从退避中恢复；
    2. 现价是否断流（超过 ``max_underlying_age_s`` 未更新）；
    3. 现价是否移动了足够多（超过 ``recenter_trigger_strikes``），
       需要以新的 ATM 档为中心重建窗口。
    """

    __slots__ = (
        "_manager", "_resolver", "_tap", "_note",
        "_interval", "_trigger", "_spot_max_age",
        "_spot_stale_noted", "_recover_at_ref", "_set_recover_at",
        "_window", "_centre",
    )

    def __init__(
        self,
        manager: Any,
        resolver: Any,
        tap: Any,
        sub_cfg: dict,
        note_callback: Callable[..., None],
        spot_max_age: float,
        recover_at_ref: Callable[[], float],
        set_recover_at: Callable[[float], None],
    ) -> None:
        self._manager = manager
        self._resolver = resolver
        self._tap = tap
        self._note = note_callback
        self._interval = loader.as_float(
            sub_cfg, "reconcile_interval_s", module="subscription",
        )
        self._trigger = loader.as_float(
            sub_cfg, "recenter_trigger_strikes", module="subscription",
        )
        self._spot_max_age = spot_max_age
        self._spot_stale_noted = False
        self._recover_at_ref = recover_at_ref
        self._set_recover_at = set_recover_at
        self._window: tuple[float, ...] = ()
        self._centre: float | None = None

    def initialize(self, window: tuple[float, ...], centre: float | None) -> None:
        self._window = window
        self._centre = centre

    @property
    def window(self) -> tuple[float, ...]:
        return self._window

    @property
    def centre(self) -> float | None:
        return self._centre

    async def run(
        self,
        running_flag: Callable[[], bool],
        slice_provider: Callable[[], Any],
    ) -> None:
        """主循环。running_flag 返回 False 时优雅退出。"""
        while running_flag():
            await asyncio.sleep(self._interval)
            if not running_flag():
                break

            slice_obj = slice_provider()
            if slice_obj is None or self._tap is None:
                continue

            if self._manager.in_backoff:
                continue

            recover_at = self._recover_at_ref()
            if recover_at and now_ts() >= recover_at:
                self._manager.note_recovered()
                self._set_recover_at(0.0)
                self._note("订阅配额已恢复", StatusLevel.INFO)

            spot = self._tap.last_spot
            if spot <= 0:
                continue

            if self._spot_stale():
                if not self._spot_stale_noted:
                    self._spot_stale_noted = True
                    self._note(
                        f"现价已超过 {self._spot_max_age:.0f}s 未更新，暂停窗口跟随"
                        "（避免用陈旧现价订错档位）",
                        StatusLevel.WARN,
                    )
                continue

            if self._spot_stale_noted:
                self._spot_stale_noted = False
                self._note("现价恢复更新，窗口跟随继续", StatusLevel.INFO)

            if not self._resolver.centre_moved(
                self._centre, slice_obj.strikes, spot, self._trigger,
            ):
                continue

            window = self._resolver.window(slice_obj.strikes, spot)
            if window == self._window:
                continue

            self._window = window
            self._centre = self._resolver.centre_strike(window, spot)
            try:
                plan = await self._manager.reconcile(slice_obj.expiry, window)
            except Exception as exc:
                self._note(f"窗口重建失败: {exc}", StatusLevel.ERROR)
                continue

            if plan.changed:
                self._note(
                    f"窗口跟随现价重建 ±{len(window) // 2} 档 "
                    f"(+{len(plan.add)} / -{len(plan.drop)}, 共 {plan.projected_total})"
                )
            if plan.failed:
                self._note(
                    f"窗口重建时 {len(plan.failed)} 条合约订阅失败",
                    StatusLevel.WARN,
                )

    def _spot_stale(self) -> bool:
        """
        现价是否已超过 ``max_underlying_age_s`` 没有更新。

        时间戳由 ``tick_router`` 用 ``core.clock.now_ts()``（墙钟 epoch 秒）写入，
        与本函数用的 ``now_ts()`` 同源，可直接相减。
        """
        tap = self._tap
        if tap is None or tap.last_spot_ts <= 0:
            return True
        return (now_ts() - tap.last_spot_ts) > self._spot_max_age
