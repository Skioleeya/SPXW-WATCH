# GTH 时段 SPXW ATM 现货基准 —— 业界做法调研

调研日期：2026-09-14 ｜ 状态：**调研完成，未改任何代码**

---

## 一、结论

**1. 官方口径：GTH 期间 SPX 指数不计算、不播发。**
这不是"IBKR 不给"，而是指数本身不存在 —— S&P DJI 的实时 SPX 由成分股 **Consolidated Tape**
（成交带）计算，成分股不交易就无法计算。Cboe 甚至把它列为 GTH 的**强制风险披露**。
⇒ 任何来源在 GTH 给的 SPX 指数值都必然是陈旧值。

**2. 业界做法确实是"用 ES 期货换算出隐含现金指数"（implied cash / fair value）。**
方向与 KAI 的判断一致。但**主流变体不是"冻结 RTH 观测基差"**，而是三条并列：

| 变体 | 基差怎么来 | 谁在用 | 风险 |
|---|---|---|---|
| **B1 冻结 RTH 观测基差** | RTH 记 `ES − SPX`，GTH 用 `ES − basis` | 简单盯盘脚本 | 跨日漂移小（<1 点/日）；**换月日静默错值**（basis 跳变数十点） |
| **B2 成本携带模型** | `basis = S·(e^{(r−q)T} − 1)`，r/q/T 为模型输入 | **公开发布口径**（impliedopen.com、CNBC"fair value"） | 依赖 r、q、T 的准确性与合约选择 |
| **B3 同到期日期权链平价** | `F = K + e^{rT}(C − P)`，对 0DTE 而言 T≈0 ⇒ F≈现货 | 波动率台标准做法 | 需要 GTH 有可用的 Call/Put 报价 |

**3. 对本项目的建议：方向选 ES（B2 为主口径），B1 可作单日简化，B3 作交叉校验锚。**
单日盯盘 B1 的误差 <1 点，够用；但 B1 在**换月日**会静默错值数十点，必须有一条
不依赖历史观测的通道（B2 或 B3）做闸门。三条通道两两应在 ±2 点内一致。

---

## 二、证据

### E1 官方：GTH 期间指数不更新

**Morgan Stanley《Cboe Options Global Trading Hours and Curb Trading Hours Disclosure》(2024-08)**
（转述 Cboe Options Rule 9.20 的强制披露）逐字：

> "Trading during GTH and Curb Trading Hours involves material trading risks, including the possibility of
> lower liquidity, high volatility, changing prices, an exaggerated effect from news announcements,
> wider spreads, **the absence of an updated underlying index or portfolio value or intraday indicative
> value** and lack of regular trading in the securities underlying the index or portfolio ..."

> "**Risk of Lack of Calculation or Dissemination of Underlying Index Value or Intraday Indicative
> Value ("IIV")** ... For certain products, an updated underlying index or portfolio value or IIV
> **will not be calculated or publicly disseminated** during Global Trading Hours or Curb Trading Hours.
> ... an investor who is unable to calculate **implied values** for certain products during Global
> Trading Hours and Curb Trading Hours **may be at a disadvantage to market professionals**."

关键三点：① 指数在 GTH 不被计算/播发；② 措辞里明确出现了 **"implied values"** 与
**"market professionals"** —— 即官方承认"专业方自己算隐含值"是常规操作；③ 这是**披露义务**，
说明监管层知道投资者会拿陈旧指数当现价。

**SEC 批准令（2026-06-02，Release 34-104227 系列；91 FR 33005）** 对 Cboe Rule 9.20 的修订描述：

> "The Exchange proposes to update the rule to: (1) specify that existing references to the absence of an
> updated underlying index or portfolio value or intraday indicative value, and lack of regular trading in
> the securities underlying the index or portfolio **apply to index options during GTH and Curb** ..."

**S&P DJI 方法论（SEC 424B2 系列招股书披露）** —— 指数为何算不出来：

> "Prices used for the calculation of real time SPX levels are based on the 'Consolidated Tape.'
> The Consolidated Tape is an aggregation of trades for each constituent over all regional exchanges
> and trading venues and includes the primary exchange."

⇒ 实时 SPX = 成分股成交的加权 → 美股不交易 = 无输入 = 指数冻结。

**Cboe 官方 GTH 时段**（芝加哥时间）：RTH 8:30–15:15 ｜ Curb 15:15–16:00 ｜ **GTH 19:15–08:25 CT**
（= 20:15–09:25 ET，周一至周五）。

### E2 业界发布口径 = ES 换算隐含现金（可复算）

**impliedopen.com**（实时页面，2026-09-14 抓取）：

```
S&P 500 implied open 2026-09-14   7,556.08   −100.90  −1.32%
  ES=F  7,620.75      IDX 7,656.98
页面明示的模型输入：RISK-FREE 4.01% (3M T-BILL · MODEL INPUT)
                   S&P 500 股息率 0.75% (US DIVIDEND YIELDS)
```

**我的复算**（`tmp` 一次性脚本，`r=4.01%`、`q=0.75%`、T = 2026-09-14 → ES 2026-12 到期日）：

```
S = 7620.75 × e^{−(0.0401−0.0075)×0.2603} = 7556.36     （页面显示 7556.08，差 0.3 点 = 日算约定）
basis = F − S = 64.39
```

⇒ **公式得证**：页面的"implied open"就是 `ES − basis`，basis 由成本携带模型给出，
不是冻结的历史观测。

**weekendindex.com**（同类商用服务）逐字：

> "The official index is only calculated while the New York Stock Exchange and Nasdaq are open: weekdays
> from 9:30 AM to 4:00 PM Eastern, minus holidays. **Outside those hours the published value freezes.**
> WeekendIndex instead shows a live, continuously-updating S&P 500 price 24 hours a day ...
> **This is an implied market price, not the official index value.**"

**flashalpha《ES Fair Value & Basis Explained》(2026-06-16)** —— 给出台面工作流：

> "Fair value is the theoretical price of the future implied by the cash index plus the cost of holding
> the position to expiry. Formally it is the cost-of-carry relationship: `F = S * e^((r - q) * T)`
> ... The **basis** is simply the difference: `basis = F - S`"
>
> "**implied cash gap = (ES now - basis) - SPX prior close**"

并明确两条对本项目直接相关的警告：

> "Because the basis is driven by `r - q` and `T`, it **widens with rates and time-to-expiry** ..."
> "In the days before expiry ... the **roll** ... the newly-front contract has a longer `T` and therefore
> a *larger* basis, so the headline 'ES premium' appears to **jump on roll day** even though nothing about
> the market changed. If you track the basis across a roll without accounting for the contract switch,
> you will misread a **calendar artifact** as a regime shift."
> "**do not compare ES strikes to SPX 1:1** ... Dealer levels ... live on the **futures price scale**,
> and the SPX equivalents live on the **cash scale**. They are separated by the basis."

⇒ 这正是 B1 变体的致命处：**冻结基差在换月日会静默错值**。

### E3 学术

- **MacKinlay & Ramaswamy (1988)**, *Index-Futures Arbitrage and the Behavior of Stock Index Futures Prices*,
  **Review of Financial Studies 1(2): 137–158**（DOI 10.1093/rfs/1.2.137）——
  期现差（basis）由其理论成本携带值决定；套利受阻时偏离扩大。
  ⇒ 现金市场关闭时套利腿不可执行，basis 的"可执行性"下降（但**水平**仍由 carry 主导）。
- **Perreten (2026-02)**, *Price Discovery Overnight: Evidence from Pre- and After-Market Trading*
  （University of Fribourg，v2026-02-28）—— 引言引 **Bondarenko & Muravyev (2023)**：
  美国现金市场关闭时的价格发现发生在 **"near-24-hour E-mini S&P 500 futures"** 上。
  ⇒ 学术侧同样把 ES 当作美股休市时段的唯一价格发现载体。

### E4 IBKR tick 162 的正确定义（修正上一轮的说法）

官方 TWS API tick 表：

| Tick ID | 名称 | 描述（逐字） | 请求用的 generic tick |
|---|---|---|---|
| **31** | **Index Future Premium** | "The number of points that the index is over the cash index." | **162** |

⇒ **162 是"请求码"，返回的是 tick 31**。上一轮把 162 当成 tick 本身，属命名混淆（结论方向没错）。

⚠️ 语义澄清：它给的是"期货高于现金的**点数**"= **基差本身**，仍需要一个基准价才能落成 SPX 价格；
且 IBKR 未公开说明它用哪个合约、GTH 是否有值 —— **必须实测，不能据文档推断**。
当前项目 `config/ibkr.json::generic_tick_list = "106"`（Option IV），**未请求 162**。

---

## 三、对本项目的一处结论修正

上一轮记录（`.workbuddy-ai/memory/2026-09-14.md`）：

> "ES202612 期货报价 7687，但系统 ATM spot 显示 7590"
> "期权反推价 7620 与期货价 7687 仍有 **67 点偏差**"
> "→ 说明算法或数据源有问题"

**复算**（同一 r/q，T = 2026-09-11 → ES 2026-12 到期）：

```
S = 7687 × e^{−(0.0401−0.0075)×0.2685} = 7620.01
```

**与记录的"期权反推价 7620"相差 0.01 点。**

⇒ 那个 67 点 **就是 Dec-2026 合约 3 个月的携带（计算值 66.99 点）**，
是 **"远期 vs 现货"的量纲错配**，不是算法错、也不是数据源错。
上一轮"反推价"的**数值其实是对的**（它给的是现金等价值），被否的理由（67 点偏差）不成立。

但**方向仍应以 ES 为基准**（E1/E2/E3 一致指向 ES 是 GTH 唯一可信的连续价格），
平价反推降级为**交叉校验通道**。真正该吸取的教训是：**先把合约与量纲（远期/现货）写清楚再动手**。

---

## 四、动手前必须探针的问题

> ⚠️ **本节第 1 条已撤回**（2026-09-14 同日更正）。原文推断"IBKR 在 GTH 给的现货与官方收盘差 64 点"，
> 依据是日志里的 `现货 7591.70`。**KAI 更正**：7591.70 是上一轮被驳回算法自己算出来的产物，
> **不是** IBKR 给的值。随后探针实测证实：**IBKR 在 GTH 给的 SPX 指数 = 7656.98 = 周五官方收盘，
> 全程恒定，且 `marketDataType = 1`（报"实时"）**。⇒ 原文的"前提不成立"判断是错的，
> "IBKR 给的是冻结的 RTH 收盘价"这个说法**成立**。完整实测见 `verify_b2_vs_b3.md`。

1. ~~`现货 7591.70` 与 SPX 官方周五收盘不符~~ —— **已关闭**（见上）。
   取而代之的真问题：**`marketDataType` 判不出新鲜度**（实测 md=1 但值是冻结的），
   `ibkr.max_underlying_age_s` 结构上拦不住这类值。
2. ~~残留进程~~ —— **已中断**（KAI 指令，`taskkill /F /PID 15612`）。教训保留：
   实盘验证前必须先确认 8060 上没有别的进程，否则看到的是别的代码的行为。
3. **陈旧闸没拦住恒定值**（**保留**，且已由实测坐实）—— `config/ibkr.json::max_underlying_age_s = 10.0`
   已接线（`acquisition/feed_reconcile.py::_spot_stale`），但 GTH 期间指数恒定 7656.98 仍被持续使用
   ⇒ 与 README 里"防用陈旧现价重建窗口 —— 会订错档位且不报任何错"的意图不符。
   实测危害量级：该指数比 ES 推算现货高 **40.4–42.0 点 ≈ 8.1–8.4 档**。
   需确认：闸门只挡"重建窗口"还是也应挡"渲染/计算"，以及改判什么（例如"指数在 N 分钟内是否变动过"）。

---

## 五、建议的最小探针（未执行，待 KAI 批准）

落点 `<项目根>/tmp/`（已登记 `.gitignore` + `NON_SOURCE_DIRS`），一次性，跑 10 分钟：

同时订阅并逐行落盘：

| 通道 | 合约 | 取的字段 |
|---|---|---|
| ① 指数 | `SPX` IND, conId 416904 | `last / close / marketPrice`、**tick 31（`genericTickList="162"`）**、`ticker.time`（IBKR 侧时间戳）+ 到达时间 |
| ② 期货 | `ES` FUT 前月 + 次月，SMART | `last / bid / ask / close` + 合约到期日 |
| ③ 期权 | 当日 SPXW ATM ±5 档 Call/Put | `bid / ask / undPrice / modelGreeks` |

输出：三路各自的 **SPX 等价值 + 时间戳** 并排，每 10s 一行。

**判据（非空转）**：
- 若 ① 的时间戳陈旧（≠ 到达时间）而 ② 新鲜 ⇒ "指数冻结"结论锁定，方案方向确认。
- ② 的 `ES − basis(B2)` 与 ③ 的平价反推应在 **±2 点**内一致；若不一致，说明数据源或合约选择有问题。
- ① 的 tick 31 若在 GTH 有值 ⇒ 可考虑直接采用（省掉自己算 carry）；若无值或为 0 ⇒ 排除该通道。
