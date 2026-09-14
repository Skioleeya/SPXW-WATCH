"""
现货来源选择回归（区段切源 + 09:25 交班）。
==========================================
验证 ``acquisition.spot_source.SpotSourceSelector``：

1. **GTH 段**：冻结指数被丢弃（不放行），合成值由**期货 tick 驱动**产出。
2. **09:25 交班**：立刻下线合成、切回指数直读；期货 tick 不再产出合成值。
3. **窗口重建**：交班瞬间锚跳 8 档 > ``recenter_trigger_strikes``（3 档）
   ⇒ 必然触发期权订阅窗口重建 —— 这是 KAI 2026-09-14「必须下线 GTH 的锚定、
   订阅 SPX」那条指令的**可验证落点**。

合成器本身的数值与闸门见 ``tools/check_spot_synthesis.py``。本文件只测"选谁"，
不重复测"算得对不对"—— 锚点常量与输出原语从那一个文件复用，避免第二份真相。

运行::

    python tools/check_spot_source.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acquisition.chain_resolver import ChainResolver  # noqa: E402
from acquisition.spot_source import SpotSourceSelector  # noqa: E402
from acquisition.spot_synthesis import SpotSynthesis  # noqa: E402
from config import loader  # noqa: E402
from contracts.tick import FutureTick, SpotTick  # noqa: E402
from tools.check_spot_synthesis import (  # noqa: E402
    FROZEN_INDEX,
    SAMPLE_F1,
    SAMPLE_F2,
    SAMPLE_FRONT,
    SAMPLE_MOMENT,
    SAMPLE_SECOND,
    STRIKE_STEP,
    Case,
    report,
)
from tools.fixtures import make_session_clock  # noqa: E402

# 网格起点（GTH 20:15）到 09:25 交班点的秒数。
HANDOVER_S = 13 * 3600 + 10 * 60


class _Recorder:
    """记录下游收到的现货 tick 与状态事件。"""

    __slots__ = ("spots", "notes")

    def __init__(self) -> None:
        self.spots: list[SpotTick] = []
        self.notes: list[str] = []

    def on_option_tick(self, tick) -> None:
        pass

    def on_quote_tick(self, tick) -> None:
        pass

    def on_spot_tick(self, tick: SpotTick) -> None:
        self.spots.append(tick)

    def on_status(self, event) -> None:
        pass

    def note(self, message: str, level=None, code: int = 0) -> None:
        self.notes.append(message)


def _selector(spot_cfg: dict, ibkr_cfg: dict, app_cfg: dict, serial_cfg: dict):
    clock, fake = make_session_clock(app_cfg, serial_cfg)
    rec = _Recorder()
    sel = SpotSourceSelector(
        rec,
        SpotSynthesis(spot_cfg),
        clock,
        spot_cfg,
        float(ibkr_cfg["max_underlying_age_s"]),
        rec.note,
    )
    return sel, rec, fake, clock


def case_zones(spot_cfg: dict, ibkr_cfg: dict, app_cfg: dict,
               serial_cfg: dict) -> list[Case]:
    sel, rec, fake, clock = _selector(spot_cfg, ibkr_cfg, app_cfg, serial_cfg)
    out: list[Case] = []

    # 推进到 GTH 段中部（网格起点 20:15 + 5h → 01:15 ET）
    fake.advance(5 * 3600)
    out.append((
        "GTH 段：判定为需要合成",
        sel.synthesising() is True,
        f"zone={clock.current_zone_id()!r}",
    ))

    sel.on_spot_tick(SpotTick(price=FROZEN_INDEX, ts=fake.now()))
    out.append((
        "GTH 段：冻结指数被丢弃（不放行）",
        sel.dropped == 1 and len(rec.spots) == 0,
        f"dropped={sel.dropped} forwarded={sel.forwarded} spots={len(rec.spots)}",
    ))

    sel.on_future_tick(FutureTick(SAMPLE_FRONT, SAMPLE_F1, fake.now()))
    sel.on_future_tick(FutureTick(SAMPLE_SECOND, SAMPLE_F2, fake.now()))
    out.append((
        "GTH 段：期货驱动产出合成现货",
        sel.synthesised >= 1 and len(rec.spots) >= 1,
        f"synthesised={sel.synthesised} spots={len(rec.spots)}",
    ))
    out.append((
        "GTH 段：产出的是合成值，不是冻结指数",
        bool(rec.spots) and abs(rec.spots[-1].price - FROZEN_INDEX) > 20.0,
        f"price={rec.spots[-1].price if rec.spots else None!r}",
    ))

    fake.advance(HANDOVER_S - 5 * 3600)
    out.append((
        "09:25 交班：立刻下线合成、切回指数",
        sel.synthesising() is False,
        f"zone={clock.current_zone_id()!r}",
    ))

    before = len(rec.spots)
    sel.on_spot_tick(SpotTick(price=FROZEN_INDEX, ts=fake.now()))
    out.append((
        "09:25 之后：指数直读被转发",
        sel.forwarded == 1 and len(rec.spots) == before + 1,
        f"forwarded={sel.forwarded}",
    ))

    sel.on_future_tick(FutureTick(SAMPLE_FRONT, SAMPLE_F1, fake.now()))
    out.append((
        "09:25 之后：期货 tick 不再产出合成值",
        len(rec.spots) == before + 1,
        f"spots={len(rec.spots)}",
    ))

    out.append((
        "切源有状态事件可观测（不静默）",
        any("现货源切换" in n for n in rec.notes),
        f"notes={rec.notes}",
    ))
    return out


def case_recentre(spot_cfg: dict, app_cfg: dict,
                  sub_cfg: dict) -> list[Case]:
    syn = SpotSynthesis(spot_cfg)
    syn.update(SAMPLE_FRONT, SAMPLE_F1, SAMPLE_MOMENT)
    syn.update(SAMPLE_SECOND, SAMPLE_F2, SAMPLE_MOMENT)
    synth_price = syn.spot(SAMPLE_MOMENT, 60.0)
    if synth_price is None:
        return [("前置：合成值可得", False, "got=None")]

    resolver = ChainResolver(app_cfg, sub_cfg)
    # 以 7615 为中心、间距 5 点的一段档位
    strikes = tuple(7615.0 + STRIKE_STEP * k for k in range(-20, 21))
    prev_centre = resolver.centre_strike(strikes, synth_price)
    trigger = float(sub_cfg["recenter_trigger_strikes"])

    moved = resolver.centre_moved(prev_centre, strikes, FROZEN_INDEX, trigger)
    shift = abs(FROZEN_INDEX - synth_price) / STRIKE_STEP

    return [
        (
            "交班前锚 = 合成值，中心档位可定位",
            prev_centre is not None,
            f"centre={prev_centre!r}",
        ),
        (
            f"交班锚跳 {shift:.2f} 档 > trigger {trigger:g} 档",
            shift > trigger,
            f"shift={shift:.2f}",
        ),
        (
            "⇒ 交班瞬间触发窗口重建（WindowFollower 会自动重建）",
            moved is True,
            f"moved={moved!r}",
        ),
    ]


def main() -> int:
    app_cfg = loader.load("app")
    ibkr_cfg = loader.load("ibkr")
    spot_cfg = loader.load("spot")
    serial_cfg = loader.load("serialization")
    sub_cfg = loader.load("subscription")

    return report("现货来源选择回归（区段切源 + 09:25 交班）", [
        ("[1] 区段切源（GTH 合成 / 09:25 交班切指数）",
         case_zones(spot_cfg, ibkr_cfg, app_cfg, serial_cfg)),
        ("[2] 09:25 交班 → 期权订阅窗口重建",
         case_recentre(spot_cfg, app_cfg, sub_cfg)),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
