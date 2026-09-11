"""回归：订阅前必须先向 IBKR 确认合约（qualify）。

为什么需要这条检查
------------------
``ib_async`` 用 ``hash(contract)`` 索引 ticker，而 ``Contract.__hash__`` 在
``conId == 0`` 时**直接抛 ValueError**：

    Contract Option(...) can't be hashed because no 'conId' value exists.
    Qualify contract to populate 'conId'.

``reqMktData`` 的第一件事就是 ``wrapper.startTicker`` → ``hash(contract)``，
所以**未确认的合约根本订阅不了**。

这个缺陷曾经真实存在：期权合约走 ``option_from_ref()`` 生成，从未 qualify，
而订阅处的 ``except Exception: return`` 又把异常静默吞掉。结果是实盘会
"启动成功、报告就绪、然后整场收不到任何期权数据，且没有任何报错"。

本脚本用假网关**忠实模拟** ib_async 的哈希约束，断言协调器在订阅前完成了
确认。它不联网、不需要 TWS。

用法::

    python tools/check_subscription_qualify.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import loader  # noqa: E402
from contracts.enums import OptionRight  # noqa: E402
from contracts.tick import OptionRef  # noqa: E402
from core.errors import ContractResolveError  # noqa: E402
from acquisition.subscription_manager import SubscriptionManager  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

STRIKES = (6490.0, 6495.0, 6500.0, 6505.0, 6510.0)
EXPIRY = "20260911"


class FakeContract:
    """模拟 ib_async.Contract 的哈希约束。"""

    __slots__ = ("symbol", "strike", "right", "expiry", "conId")

    def __init__(self, strike: float, right: OptionRight, expiry: str) -> None:
        self.symbol = "SPX"
        self.strike = strike
        self.right = right
        self.expiry = expiry
        self.conId = 0

    def __hash__(self) -> int:
        # 与 ib_async 一致：没有 conId 就不能被哈希。
        if not self.conId:
            raise ValueError(
                f"Contract {self!r} can't be hashed because no 'conId' value "
                "exists. Qualify contract to populate 'conId'."
            )
        return hash((self.symbol, self.strike, str(self.right), self.expiry, self.conId))

    def __repr__(self) -> str:
        return (f"FakeContract(strike={self.strike}, right={self.right}, "
                f"conId={self.conId})")

    def label(self) -> str:
        return f"{self.strike:.0f}{self.right}"


class FakeFactory:
    """模拟 ContractFactory：生成未确认合约 + 判定是否已确认。"""

    def option_from_ref(self, ref: OptionRef) -> FakeContract:
        return FakeContract(ref.strike, ref.right, ref.expiry)

    @staticmethod
    def assert_qualified(contract: FakeContract) -> FakeContract:
        if contract is None or not contract.conId:
            raise ContractResolveError("合约未被 IBKR 确认（缺少 conId）")
        return contract


class FakeGateway:
    """模拟 IbkrGateway：qualify_many 回填 conId，subscribe 依赖哈希。"""

    def __init__(self, *, qualify_works: bool = True) -> None:
        self.qualify_works = qualify_works
        self.subscribed: dict[int, FakeContract] = {}
        self.cancelled: list[FakeContract] = []
        self.qualify_calls = 0

    async def qualify_many(self, contracts):
        self.qualify_calls += 1
        results = []
        for index, contract in enumerate(contracts):
            if self.qualify_works:
                contract.conId = 1000 + index   # 模拟 IBKR 回填 conId
                results.append(contract)
            else:
                results.append(None)            # 模拟确认失败
        return results

    def subscribe_option(self, contract: FakeContract) -> None:
        # 这一行就是 ib_async 的真实行为：未确认的合约在这里炸掉。
        key = hash(contract)
        self.subscribed[key] = contract

    def cancel_option(self, contract: FakeContract) -> None:
        self.cancelled.append(contract)
        self.subscribed.pop(hash(contract), None)


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


async def main() -> int:
    sub_cfg = loader.load("subscription")
    passed = True

    # ------------------------------------------------------------------ #
    # 0. 先验证假网关确实忠实：未确认的合约连 hash 都过不了
    # ------------------------------------------------------------------ #
    print("=" * 72)
    print("订阅前合约确认回归")
    print("=" * 72)
    print("\n[0] 假网关是否忠实模拟 ib_async 的哈希约束")
    probe = FakeContract(6500.0, OptionRight.CALL, EXPIRY)
    try:
        hash(probe)
        passed &= check("未确认合约的 hash 应当抛错", False, "竟然没抛")
    except ValueError:
        passed &= check("未确认合约的 hash 抛 ValueError（与 ib_async 一致）", True)

    raw = FakeGateway()
    try:
        raw.subscribe_option(probe)
        passed &= check("未确认合约直接订阅应当失败", False, "竟然成功了")
    except ValueError:
        passed &= check("未确认合约直接订阅会失败（说明假网关忠实）", True)

    # ------------------------------------------------------------------ #
    # 1. 正常路径：协调器必须先确认再订阅
    # ------------------------------------------------------------------ #
    print("\n[1] 正常路径：协调器订阅前先确认")
    gateway = FakeGateway()
    manager = SubscriptionManager(gateway, FakeFactory(), sub_cfg)
    plan = await manager.reconcile(EXPIRY, STRIKES)

    expected = len(STRIKES) * 2
    passed &= check("确实调用了批量确认", gateway.qualify_calls == 1,
                    f"调用 {gateway.qualify_calls} 次")
    passed &= check("全部合约订阅成功", manager.count == expected,
                    f"{manager.count}/{expected} 条")
    passed &= check("无失败项", not plan.failed, f"failed={len(plan.failed)}")

    # ------------------------------------------------------------------ #
    # 2. 确认失败时：必须暴露而不是静默
    # ------------------------------------------------------------------ #
    print("\n[2] 确认失败时必须暴露")
    broken = FakeGateway(qualify_works=False)
    broken_manager = SubscriptionManager(broken, FakeFactory(), sub_cfg)
    broken_plan = await broken_manager.reconcile(EXPIRY, STRIKES)

    passed &= check("确认失败时一条都没订上", broken_manager.count == 0,
                    f"{broken_manager.count} 条")
    passed &= check("失败项被记入 plan.failed（不静默）",
                    len(broken_plan.failed) == expected,
                    f"failed={len(broken_plan.failed)}/{expected}")

    # ------------------------------------------------------------------ #
    # 3. 退订仍能匹配上（哈希一致）
    # ------------------------------------------------------------------ #
    print("\n[3] 退订能匹配到已订阅的合约")
    shrunk = await manager.reconcile(EXPIRY, STRIKES[:3])
    passed &= check("滑出窗口的合约被取消", len(gateway.cancelled) > 0,
                    f"取消 {len(gateway.cancelled)} 条")
    passed &= check("活跃订阅数收敛到新窗口", manager.count == 3 * 2,
                    f"{manager.count}/{3 * 2}")

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过{RESET}" if passed
          else f"{RED}结果: 存在失败项{RESET}")
    print("=" * 72)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
