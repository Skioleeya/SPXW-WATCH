# Startup: model-greeks-landing-verified

STARTUP-PROOF: 动手前先探环境 —— `netstat -ano | grep -E ":8060|:4002"` →
**4002 LISTENING（IB Gateway 模拟盘在听，PID 15028）**；`8060` 无监听
（上一轮占用 8060 的 `run.py --sim` 已退出）。`(echo > /dev/tcp/127.0.0.1/4002)`
→ 连接成功。故本次可以**真连 IBKR 做直接观测**，不需要起项目服务。
探针用 `clientId=97`（项目用 71），与项目互不干扰。

## Session

- 任务 id：`model-greeks-landing-verified`
- 日期：2026-09-11
- 触发：KAI 回复「1. IV 热力图 ΔIV ≈ 0 不退回中性色；2. 实盘 tick 回流后
  106 模型 Greeks 落地（paper 无实时 OPRA 权限）什么意思？」——
  第 1 项是决策（落地即可），第 2 项是**提问**（要解释）。
  为了让解释有实据而不是复述记录，选择**跑一支直接探针**当场验证。

## Scope Understanding

- In scope：
  - 用与项目**逐字相同**的订阅参数（`SPX` / `IND` / `CBOE` / `SPXW` / `SMART` /
    `genericTickList="106"` / `reqMarketDataType(3)`）直接订阅一张 SPXW 0DTE
    期权，观测 `ticker.modelGreeks` 是否非空。
  - 把 KAI 的决策 1 写进 `notes/context/open_tasks.md` 的「已决策」节。
  - 用观测结果修正记录里"未验证"的过时结论。
- Out of scope：
  - **零生产代码改动。** 探针在工程目录之外，不 import 项目模块。
  - 不起 `run.py --live`（会占 8060 且与探针重复；项目路径的 IV 落地已有
    第七轮的实盘读数作证）。
  - 不区分 tickType 13 vs 83（ib_async 属性层做不到，见 `meta.yaml` 的 notes）。

## Prior Context Read

- 本会话前序：`notes/sessions/2026-09-11/record-reconciliation/`（记录校正）。
- 代码侧（确认"唯一来源"链条）：
  - `acquisition/tick_router.py:32-42` `_COMPUTATION_SOURCES` ——
    `("modelGreeks", 13), ("lastGreeks", 12), ("bidGreeks", 10), ("askGreeks", 11)`。
  - `acquisition/tick_router.py:204-214` `_pick_computation()` ——
    `use_model=True` 时**只接受** modelGreeks，其余 `return None`。
  - `acquisition/ibkr_gateway.py:339-352` —— `reqMktData(contract, generic_ticks, False, False)`。
  - `contracts/tick.py:86-106` `OptionTick` —— 来源限定为 generic tick `106` 的
    `tickOptionComputation`，`source_tick_type` 默认 13。
  - `features/feature_engine.py:205` `sides.append(float(tick.iv))` ——
    热力图的 IV 唯一来自 `OptionTick.iv`。
  - `config/ibkr.json`：`generic_tick_list: "106"`、`market_data_type: 3`、
    `use_model_greeks: true`；`config/app.json`：`SPX`/`IND`/`CBOE`/`SPXW`/`SMART`。

## Recent Git Context

- Key commits reviewed：`N/A:仓库仍只有 755b221 Initial commit，工作树改动未提交。`

## Worker Readiness

- Risks noticed：
  1. **"未验证"这条结论是推理层面的，不是观测层面的。** 第七轮实盘已读出
     ATM IV 15.70/16.83、25Δ Skew、热力图 36 格 —— 在 `use_model_greeks=true`
     下这些值**只能**来自 modelGreeks，即"落地"其实已被间接证明。但记录一直
     写"未验证"，属于"结论没跟上实测"。本会话用直接探针把它变成直接证据。
  2. **`ib.sleep()` 在 async 上下文里不可用**（同步方法，内部 `util.run`）——
     第一版探针在 [6] 步抛 `RuntimeError: This event loop is already running`。
     改用 `await asyncio.sleep()`。
  3. 探针若放进工程目录会让自检 [10] 误报 —— 已放工程外，归档改 `.py.txt`。
- Blockers noticed：无。
