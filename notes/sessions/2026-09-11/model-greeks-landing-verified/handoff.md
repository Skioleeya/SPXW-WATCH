# Handoff — model-greeks-landing-verified

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: 动手前探环境 —— `netstat -ano | grep -E ":8060|:4002"` →
**4002 LISTENING（IB Gateway 模拟盘，PID 15028）**；`8060` 无监听；
`(echo > /dev/tcp/127.0.0.1/4002)` 连接成功。故直接连 IBKR 观测，探针用
`clientId=97`（项目用 71），与项目互不干扰。收尾复跑 `python run.py --check`
→ **11/11 全部通过**（归档的 `.py.txt` 未触发自检 [10] 误报）。

## 结论

KAI 第 2 问「实盘 tick 回流后 106 模型 Greeks 落地（paper 无实时 OPRA 权限）
什么意思？」——**不靠复述记录回答，直接跑探针当场验证**。结果推翻了记录里的
"未验证"结论。

**`config/ibkr.json` 的 `generic_tick_list: "106"` 确实让 IBKR 推送
`tickOptionComputation`，`ticker.modelGreeks` 非空，第 5 秒就出现。**

```
marketDataType = 1 (1=实时 2=冻结 3=延迟 4=延迟冻结)
modelGreeks = iv=0.12483 delta=0.43913 gamma=0.01883 vega=0.66205 theta=-6.83688
bidGreeks   = iv=0.12329 delta=0.46919 ...
askGreeks   = iv=0.12629 delta=0.46995 ...
lastGreeks  = iv=0.11728 delta=0.46756 ...
VERDICT: modelGreeks 在第 5s 出现 —— 106 → tickOptionComputation → MODEL_OPTION 确实回流
```

**两个关键判读：**

1. **四档 greeks 并存且值互不相同** ⇒ MODEL_OPTION 是独立的 tick 通道，
   不是同一份数据的别名。项目 `use_model_greeks: true` 时
   `TickRouter._pick_computation()`（`acquisition/tick_router.py:204-214`）
   只接受 modelGreeks，其余 `return None`，所以项目吃到的就是第一行那组值。

2. **`marketDataType = 1`（实时）** —— 标的现价那条 ticker 报 3（延迟，符合
   `reqMarketDataType(3)`），而**期权合约的 ticker 报 1**。且 Error 10090 原文是
   "**Part of** requested market data is not subscribed"（**部分**未订阅），
   并非"无权限"。⇒ "paper 账户无实时 OPRA 权限，只返回延迟数据"这一假设
   **与观测不符**，已在记录中修正。

同时落地 KAI 的决策 1：**IV 热力图 ΔIV ≈ 0 不退回中性色**（维持 Turbo）。

CHANGED-PATHS: 0 个生产代码文件（0 新增 + 0 改）
**仅改记录（2 个活文档）：**
- `notes/context/open_tasks.md`（改）—— ① 把「IV 热力图 0 值是否退回中性色」
  从 `## Active` **移入** `## 已决策（KAI，2026-09-11）` 节，写明"不再作为待办
  重提"；② 重写 `## Stale / Needs Verification` 里的「106 模型 Greeks 落地」
  条目 —— 由"未验证"改为"**已由直接探针证实**"，并附观测值。
- `notes/context/project_state.md`（改）—— 同步：`NEXT` 第 2 项（106 Greeks
  落地）标注已证实；新增一句说明 `marketDataType=1` 推翻了 paper 无实时权限的
  旧假设。
- `.workbuddy-ai/memory/MEMORY.md`（改）—— 记录「106 模型 Greeks 已实测落地」
  与"paper 有实时权限"这两个新事实。
**新增证据（1 个会话根 + 2 个 artifact）：**
- `notes/sessions/2026-09-11/model-greeks-landing-verified/{startup,project_state,open_tasks,handoff}.md` + `meta.yaml`
- `.../artifacts/probe_model_greeks.py.txt`（探针源码，5,651 字节）
- `.../artifacts/probe_output_20260911_1147.txt`（原始输出 + 判读要点）

VALIDATION-SUMMARY: 全部通过。本次无生产代码改动，验证目标是"106 是否真的
回流"，用一支直接探针拿到直接证据；收尾复跑 `run.py --check` **11/11** 确认
记录改动与归档未影响任何机械检查。

COMMAND-EVIDENCE: 明细见下
- 环境探测：
  - `netstat -ano | grep -E ":8060|:4002"` → `TCP 0.0.0.0:4002 LISTENING 15028`
    （8060 无输出 = 未监听）
  - `(echo > /dev/tcp/127.0.0.1/4002)` → 成功（4002 OPEN）
- **探针（决定性证据）**：
  `NO_PROXY=127.0.0.1,localhost <VENV>/python.exe -u
  C:/Users/Lenovo/.workbuddy-ai/tmp/probe_model_greeks.py` → exit 0
  - `[1] connected=True clientId=97`
  - `[3] 标的 SPX conId=416904 secType=IND`
  - `[4] 链参数 6 片` / `[5] 命中 SPXW 20260911 exchange=CBOE strikes=744`
  - `[6] 标的现价 ≈ 7673.27 marketDataType=3`
  - `[7] 取 ATM 行权价 7675.0`
  - `[8] 期权 SPXW  260911C07675000 conId=904013316`
  - `[9] 已订阅 genericTickList="106"`
  - `marketDataType = 1`；`modelGreeks` 第 5s 出现（iv=0.12483 / delta=0.43913）
  - `bidGreeks` 0.12329 / 0.46919；`askGreeks` 0.12629 / 0.46995；
    `lastGreeks` 0.11728 / 0.46756 —— 四者并存且不同
  - `Error 10090 ... Part of requested market data is not subscribed ...`
    （**部分**未订阅，非无权限）
- `python run.py --check` → `结果: 全部通过`（**11/11**）

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 两条
1. **"未验证"这条结论本该更早被推翻 —— 靠的是推理，不是新观测。**
   第七轮实盘已读出 ATM IV 15.70/16.83、25Δ Skew、热力图 36 格；而
   `use_model_greeks=true` 时 `_pick_computation()` 只接受 `modelGreeks`，
   `OptionTick.iv` 又是热力图 IV 的唯一来源（`feature_engine.py:205`）——
   **"落地"当时就已被间接证明**，只是没人把这条链条串起来。
   教训：记录里的"未验证"要标注**未验证的是哪一环**，否则它会一直挂着，
   哪怕证据早已在手。本次已在 `open_tasks.md` 里把该条改写为"已证实"，
   并新增一条低优先级项记录残留的**真**未验证点（tickType 13 vs 83）。
2. **探针能力应沉淀。** 本探针（独立 clientId + 与项目逐字相同的订阅参数 +
   观测 `modelGreeks`）是可复用的"IBKR 期权计算数据链路"体检工具，
   与既有 `tools/ws_probe.py`（查项目端到端）互补。当前仍是手工脚本，
   未收进 `tools/`（同 `open_tasks.md` 里"联通与限速无常驻回归"那条）。

NOTES-PATHS: 8 个文件（会话根 5 件 + artifacts 2 件 + 上下文索引 3 件，含重叠）
- `notes/sessions/2026-09-11/model-greeks-landing-verified/startup.md`
- `notes/sessions/2026-09-11/model-greeks-landing-verified/project_state.md`
- `notes/sessions/2026-09-11/model-greeks-landing-verified/open_tasks.md`
- `notes/sessions/2026-09-11/model-greeks-landing-verified/handoff.md`
- `notes/sessions/2026-09-11/model-greeks-landing-verified/meta.yaml`
- `notes/sessions/2026-09-11/model-greeks-landing-verified/artifacts/probe_model_greeks.py.txt`
- `notes/sessions/2026-09-11/model-greeks-landing-verified/artifacts/probe_output_20260911_1147.txt`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 3 条，明细见下
1. **`source_tick_type` 是名义值（低）** —— `TickRouter` 把 `modelGreeks` 一律
   记为 `tick_type=13`，而 ib_async 的 `GREEKS_TICK_MAP` 把 13（实时模型）与
   83（延迟模型）合并到同一个属性，**属性层无法区分**。若将来需要区分，
   得改从 `ticker.marketDataType` 取（本次观测到它有值）。
2. **单次观测（低）** —— 一张合约、一个时点（2026-09-11 11:47 EDT）。
   未做多合约/多时点的稳定性统计。结论"确实回流"证据充分；
   "走的是实时而非延迟"是单次观测 + 间接推断。
3. **"paper 有实时权限"这个新结论需要更大样本（中）** —— 它推翻了沿用多轮的
   旧假设，但目前只有一张 SPXW 期权的 `marketDataType=1` 支撑。
   建议下次跑 `run.py --live` 时统计**全部 72 条订阅**的 `marketDataType` 分布，
   再下结论。

FAST-FAIL-CHECK: N/A:本次为观测与记录改动，未触碰任何背压 / 失败路径
NO-COMPAT-BRANCH: 通过 —— 未引入任何条件分支或新旧双路
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径
NO-PATCH-BANDAGE: 通过 —— 未在记录里补一句"以最新为准"来掩盖过期结论，
  而是直接改写过期结论本身
NO-FALLBACK-BEHAVIOR: 通过 —— 未新增静默降级；残留不确定（tickType 13 vs 83、
  单次观测）**明确写在** `project_state.md` 与 `OPEN-RISKS` 里，没有含糊过去

TRIGGER-PATHS: N/A:本项目为 Python/JS，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check`（11/11），已在上方
  COMMAND-EVIDENCE 记录
