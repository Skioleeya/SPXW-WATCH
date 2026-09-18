TASK-ID: live-start-blocked
DATE: 2026-09-18
TIER: T2
STATUS: blocked（等 KAI 决定是否修）
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
STARTUP-PROOF: 见下「开工基线」。**未改任何产品代码**（本轮只读 + 探针）。

# Handoff — 实盘启动失败：GTH 段前月到期日「算成已到期」⇒ 无现货 ⇒ 服务起不来

## 一句话

**不是 IBKR 的问题，是产品缺陷。** 独立探针证明 IBKR 侧一切正常（ES 前/次/次次月
**实时**报价都到了、农场 `usfarm.nj`/`hfarm`/`usfuture` 全 OK）；`run.py` 起不来是因为
`SpotSynthesis._years_to` 把到期时刻算成「到期日 **00:00 UTC**」—— 而 ES 前月的真实到期
时刻是**当天 08:30 中部时间（= 09:30 ET = 13:30 UTC）**。于是从 00:00 UTC 起
`T1 = -0.000970` 为负 ⇒ `t1 <= 0` ⇒ `spot()` **永远返回 None** ⇒ `_await_spot()` 20s
超时 ⇒ `SpotUnavailableError`。

## 触发条件（本轮实测命中）

**ES 季月到期日**（第三个周五：3/6/9/12 月）= **今天 2026-09-18**。
会话区段 `gth` = 20:15（前一日）→ 09:25；`synthesised_zones: ["gth"]`
⇒ GTH 段现货**必须由 ES 期货合成**（SPX 指数在 GTH 是冻结值，selector 主动丢弃）。
⇒ **ES 到期日的整个 GTH 窗口（≈13 小时）没有任何现货 ⇒ 服务起不来。**

## 取证链（全部可复跑）

### 1. IBKR 侧正常（`tmp/probe_ibkr_spot.py`，新建，只读 client_id=99）

```
managedAccounts = ['DUQ898780']
ES 月份：返回 22 条，带 conId 22 条 ⇒ 合约服务正常
  conId=649180671 月=20260918 realExpiry=20260918   ← 前月**今天到期**
  conId=515416632 月=20261218 / conId=649180684 月=20270319
ES 20260918 md=1 bid=7661.00 ask=7661.25 last=7660.75   <= 实时
ES 20261218 md=1 bid=7728.75 ask=7729.00 last=7729.00   <= 实时
ES 20270319 md=1 bid=7808.50 ask=7809.50 last=7810.50   <= 实时
2104 OK：usfarm.nj / hfarm / usfuture（apachmds 2107 不影响美股）
结果: 有行情到达 （3/3）  RC=0
```

### 2. `run.py` 两次同样失败（不反复重启，只跑两次定性）

```
04:25:34 INFO pipeline 启动 delayed | 到期 20260918 | 会话 {... 'is_open': True ...}
04:25:36 INFO ibkr.rate_limit 出站限速桶显式设为 45 条 / 1s
core.errors.SpotUnavailableError: 20s 内未收到标的现价。
  acquisition/feed_service.py:207 _resolve_and_subscribe → :314 _await_spot
第二次 04:28:39 起，同样 20s 后同样异常；`:8060` 从未真正服务（`/health` 空）
```

⚠️ 注意：`is_open: True`、会话 20:15→16:00 ⇒ **这不是"盘前 fail-closed"**，
是现价拿不到。且**日志里一条 feed 告警都没有** —— 因为 `_note()` 不写 logging
（本 skill 已记的坑），所以只查日志会得出"什么都没发生"的错误结论。

### 3. 用**产品自己的代码**验证（同一批真实报价，三个反证）

```
T(20260918) = -0.000970 年   ← 负数
T(20261218) = +0.248345 年
T(20270319) = +0.497660 年

A) 现状（三个月全喂进去）        → spot = None（永远）  samples=0
B) 只喂「次月 + 次次月」         → spot = 7650.12598 ✅  carry=0.0413
C) 同一批报价、moment 往前 12h   → spot = 7661.01154 ✅  T1(past)=+0.000400
⇒ 同一份代码、同一批报价，唯一变量是 T1 的符号 ⇒ 判据就是 `t1 <= 0`
```

### 4. 到期**时刻**在 IBKR 数据里就有（不需要推算）

```
conId=649180671 ESU6
realExpirationDate = '20260918'
lastTradeTime      = '08:30:00'
timeZoneId         = 'US/Central'                     ← IBKR 明确给了时区
tradingHours 末段  = 20260917:1700-20260918:0830      ← 该合约最后交易时段止于 08:30 CT
liquidHours        = 20260918:CLOSED
⇒ 权威到期时刻 = 2026-09-18 08:30 US/Central = 13:30 UTC = 09:30 ET
   两处独立来源（lastTradeTime+timeZoneId / tradingHours 末段）一致
```

## 两个缺陷（分层，都要修才完整）

**① `_years_to` 的到期时刻是"发明"出来的**（`acquisition/spot_synthesis.py`）
```python
target = datetime(year, month, day, tzinfo=timezone.utc).timestamp()   # ← 00:00 UTC
```
它只用了 `realExpirationDate`（精度到日），把到期时刻当成**当日 00:00 UTC**。
真实时刻早于它 **13.5 小时** ⇒ 前月被提前 13.5 小时判死。
⚠️ 该函数 docstring 为"精度到日"辩护的理由是"**ĉ 只依赖两个到期日的差，误差在相减时
抵消**"—— 这对 carry 成立，但 `t1 <= 0` 这个**闸门**和 `e^(−ĉ·t1)` 用的都是**绝对 T1**，
误差不抵消。
⇒ 正确层级：**用 IBKR 给的 `lastTradeTime` + `timeZoneId`（或 `tradingHours` 末段）**，
  与项目既有原则"到期日一律取 IBKR 给的、代码不推算任何日期"一致。

**② `spot()` 的"换月"只写在文档里，代码没实现**
`_subscribe_futures` 的 docstring 明确承诺：「前月到期消失后，需要 (次月, 次次月) 顶上，
所以第三个是**换月余量** —— 缺了它，换月当天会只剩一个月份，合成直接 fail-closed
一整个交易日」。
但 `spot()` 里：
```python
fresh = sorted(expiry for expiry, (_, ts) in self._quotes.items() if 新鲜)
front, second = fresh[0], fresh[1]          # ← 不跳过 T1 <= 0 的月份
...
if t1 <= 0 or t2 <= t1: return None         # ← 于是永远在这里返回
```
⇒ 第三个月份**订了但从没被当作前月用过**；文档承诺的换月行为不存在。
反证 B 就是"若按文档换月会怎样"：**7650.13**（与前月现价 7661.12 差 **10.99 点**）。

## 影响面

* **每年 4 天**（ES 季月到期 = 第三个周五：3/6/9/12 月）的 **GTH 窗口**
  （前一日 20:15 → 当日 09:25，≈13 小时）**没有任何现货 ⇒ 服务起不来**。
* 这 4 天恰好是**季月 0DTE**（链最长、关注度最高）。
* RTH（09:30 起）现货走 SPX 指数直读 ⇒ **不受影响**。
  ⇒ **今天不用修也能在 09:30 EDT 起来**；修是为了那 4 天 × 13 小时。

## 建议的修法（**待 KAI 拍板**，未动代码）

1. `_years_to` 改为吃**到期时刻**：由 `ContractDetails.realExpirationDate` +
   `lastTradeTime` + `timeZoneId` 合成（两处独立来源可交叉校验，见取证链 4）。
   `feed_service._subscribe_futures` 现在只把 `expiry`（日期字符串）塞进
   `set_future_contracts` 映射 ⇒ 需要把到期时刻一起带下去。
2. `spot()` 的 `fresh` 选择改为**跳过 `t1 <= 0` 的月份**，取最近两个 **T1 > 0** 的
   —— 即把文档承诺的换月真正实现掉。
   ⚠️ 换月那一刻 S 会跳 ≈11 点（Sep 锚 → Dec/Mar 合成）；`max_carry_jump` 会拒收第一拍
   （carry 0.0354 → 0.0413，Δ=0.0059 > 0.005），第二拍起正常 ⇒ 自愈一拍。
   `recenter_trigger_strikes` = 3 档（15 点）> 11 点 ⇒ 不会触发窗口重建。
3. ~~验证：`tools/check_spot_synthesis.py`（16 项）必须全绿 + **非空转**（造一个
   "前月 T1 ≤ 0" 的用例，旧代码 FAIL / 新代码 PASS）+ 用真实 ES 三月份报价复跑反证 A/B。~~
   ⚠️ **更正（同日，`live-start-fix` 会话）**：**`tools/check_spot_synthesis.py` 不存在**
   —— `tools/` 下只剩 1 个 `check_*.py`（`check_web_contract.py`），35 个旧检查器全被删过。
   实际验证 = `tmp/probe_spot_rollover.py`（非空转 A/B，旧代码从 git 现场取）+ 
   `run.py --check` 16/16。详见 `notes/sessions/2026-09-18/live-start-fix/handoff.md`。

## 开工基线

```
HEAD = 7058a15（已推送，本地=远端=跟踪引用，工作区干净）
:8060 未监听、0 个 python 进程（开工时）
:4002 LISTENING PID 15172 + ESTABLISHED 198.18.1.25:4001；ibgateway.exe 计数 = 1
本机 date = Fri Sep 18 04:25 EDT 2026（= 08:25 UTC）
IBKR：DUQ898780；ES 前月 20260918 今天到期
```

## CHANGED-PATHS

- `tmp/probe_ibkr_spot.py`（**新建**，gitignored，只读）—— 定性 IBKR 侧的独立探针。
  ⚠️ 探针自身踩了一个坑：`ib_async 2.1.0` 的 `Client` **没有** `twsConnectionTime()`
  （硬调会让探针第一步就崩），已改 `getattr` 兜底。
- **未改**任何产品代码、任何配置。

## OPEN-RISKS

- **修复方案未实施**（等 KAI 拍板）。今天 09:30 EDT 起服务可正常启动，**不受影响**。
- **`_years_to` 的"精度到日"误差对 `S` 的影响**：docstring 说 ≈0.36 点。改成真时刻后
  该误差消失，但**未量化过新误差**（时区解析错了会更糟）⇒ 改的时候必须用
  `tradingHours` 末段做交叉校验。
- 未验证"RTH 段真的不受影响"（今天 09:30 后才有机会实测）。
- `run.py` 在沙箱里长跑会让 Windows 回收站爆炸（本 skill 已记）⇒ 常驻请 KAI 在普通
  终端里起。
