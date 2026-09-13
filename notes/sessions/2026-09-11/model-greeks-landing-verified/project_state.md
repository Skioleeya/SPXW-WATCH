# Project State — model-greeks-landing-verified

## 本会话性质

**直接观测 + 决策落地。零生产代码改动。**
不修任何 bug、不加任何功能；产出是"一条被证实的结论"与"一条被落地的决策"。

## 结论一：106 模型 Greeks **确实落地**（此前记录说"未验证"，已证伪）

直接证据（`artifacts/probe_output_20260911_1147.txt`，2026-09-11 11:47 EDT 开盘后）：

```
[5] 命中 SPXW 20260911 exchange=CBOE strikes=744
[8] 期权 SPXW  260911C07675000 conId=904013316
[9] 已订阅 genericTickList="106"，最多等 30s ...

marketDataType = 1 (1=实时 2=冻结 3=延迟 4=延迟冻结)
modelGreeks = iv=0.12483 delta=0.43913 gamma=0.01883 vega=0.66205 theta=-6.83688
bidGreeks   = iv=0.12329 delta=0.46919 ...
askGreeks   = iv=0.12629 delta=0.46995 ...
lastGreeks  = iv=0.11728 delta=0.46756 ...

VERDICT: modelGreeks 在第 5s 出现 —— "106" → tickOptionComputation →
         MODEL_OPTION 数据确实回流。
```

**两个关键判读：**

1. **modelGreeks 与 bid/ask/last 四者并存且值互不相同** ⇒ MODEL_OPTION 是一条
   独立的 tick 通道，不是同一份数据的别名。项目 `use_model_greeks: true` 时
   `TickRouter._pick_computation()` 只接受 modelGreeks，所以项目吃到的就是
   `iv=0.12483 / delta=0.43913` 这一组。

2. **`marketDataType = 1`（实时）**，而标的现价那条 ticker 报 3（延迟，符合
   `reqMarketDataType(3)`）。同时 Error 10090 原文是 "**Part of** requested
   market data is not subscribed" —— 是**部分**未订阅的警告，不是"没有权限"。
   ⇒ 此前"paper 账户无实时 OPRA 权限，只返回延迟数据"的假设**与本次观测不符**。

## 结论二：IV 热力图 ΔIV ≈ 0 **不退回中性色**（KAI 决策，已落地）

`Turbo` 顺序色阶维持现状（0 = 亮黄绿 `#a4fc3b`）。理由：忠实于参考项目截图 +
原指令就是"只改色调"；换发散色阶超出该指令授权。已写入
`notes/context/open_tasks.md` 的「已决策」节，**不再作为待办重提**。

## 仍未验证的残留（诚实标注）

- **无法从 ib_async 属性层区分 tickType 是 13（实时模型）还是 83（延迟模型）**：
  库的 `GREEKS_TICK_MAP` 把两者合并到同一个 `modelGreeks` 属性。
  `TickRouter` 因此把 `source_tick_type` 一律记为 13 —— 这是**名义值**，
  不是观测值。本次 `marketDataType=1` 倾向于是 13，但属间接推断。
- 单次观测（一张合约、一个时点）。未做多次/多合约的稳定性统计。

## 交叉证据（项目自身路径，非本探针）

2026-09-11 实盘读数（`notes/context/project_state.md`）：ATM IV 15.70/16.83、
25Δ Skew +3.30、热力图 36 格有效数值。在 `use_model_greeks=true` 下这些 IV/Δ
**只能**来自 modelGreeks —— 与本探针结论一致。
