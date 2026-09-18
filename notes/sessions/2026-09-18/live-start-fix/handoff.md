TASK-ID: live-start-fix
DATE: 2026-09-18
TIER: T2
STATUS: done（代码已改 + 非空转验证 + 实盘已启动并出数据）
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
STARTUP-PROOF: 见「开工基线」；本轮开工时 `:8060` 未监听、0 个 python 进程，
`HEAD = b3d1e9d`（已推送，三值一致）。

# Handoff — 修掉 GTH 段「前月被提前 13.5h 判死」的两处缺陷，实盘起起来了

## 一句话

KAI 令「现在就修，然后起系统」。**两处缺陷都修了**（到期时刻改从 IBKR 取 +
`spot()` 真正实现换月），**非空转 A/B 证明旧代码在换月前/后都出不了值、新代码两处
都出值**，`run.py` 一次起成功：`:8060` 在服务、现货 **7661.1**（合成值）、订阅
**80/92**、SVI 拟合成功、skew 出值。

## 改了什么

| 文件 | 行数 | 说明 |
|---|---|---|
| `acquisition/future_expiry.py` | **新建 149** | 到期**时刻**解析 + 交叉校验 + 两张登记表 |
| `acquisition/spot_synthesis.py` | 195 → **260** | `T` 改为注入的到期时刻；`spot()` 真正实现换月；新增 `diagnosis()` |
| `acquisition/feed_service.py` | 391 → **394** | 接 `future_expiry`；起不来时把合成器状态拼进异常 |

`git diff --stat`（不含新文件）= `feed_service.py` 27 行改动 / `spot_synthesis.py`
121 行改动（+108 −40）。**未改任何配置**（`config/*.json` 一字未动）。

### 缺陷① 到期时刻不再"发明"（`future_expiry.py` + `set_expiries`）

- 旧：`_years_to` 用 `datetime(y, m, d, tzinfo=utc)` ⇒ 到期时刻 = **当日 00:00 UTC**，
  比 ES 真实的 **08:30 US/Central（13:30 UTC）** 早 **13.5 小时**。
- 新：到期时刻 = IBKR 的 `lastTradeTime` + `timeZoneId` 合成（`ZoneInfo`，夏令时由
  时区库处理，**不写死偏移**）。
- **交叉校验**：`tradingHours` 里"止于到期日"那一段的结束时刻必须等于 `lastTradeTime`，
  不一致 ⇒ 抛 `SpotUnavailableError`（不知道该信谁时不猜 T）。
  ⚠️ `tradingHours` 是**有限窗口**（实测 ESZ6/ESH7 只列 6 天），窗口不覆盖到期日时
  无从校验 ⇒ 只用主来源。**"缺少校验"与"校验失败"被显式分开**。
- 到期日与到期时刻**一起返回**（`instant_of` → `(day, instant)`），两者同源不会错配。
- 时刻是**合约的属性**，所以 `set_expiries()` 设一次，不随每笔 tick 传。
- 没登记的月份 ⇒ `_years_to` 返回 0.0 ⇒ 被 `spot()` 滤掉（fail-closed，不猜时刻）。

### 缺陷② 换月真正实现（`spot()`）

```python
# 旧：sorted(新鲜月份)[:2] —— 从不跳过已到期月 ⇒ 换月日整天出不了值
# 新：候选 = 新鲜 且 T > 0，按到期时刻升序取最近两个
for expiry, (_, ts) in self._quotes.items():
    if (now - float(ts)) > max_age_s: continue
    years = self._years_to(expiry, now)
    if years <= 0: continue                      # ← 换月就发生在这里
    candidates.append((years, expiry))
```

### 顺带补的观测（不是"顺手重构"，是这次的直接教训）

`_await_spot()` 超时抛的异常里**拼进合成器状态**（`SpotSynthesis.diagnosis()`）：
每个月的 `T` 值、是否"已到期/无到期时刻"、报价多久前、成功/拒收次数。
理由：`_note()` **不写 logging**，合成静默返回 `None` 时日志干净得像什么都没发生 ——
2026-09-18 就为这个查了两小时。异常**是**会进日志的，所以诊断放这里。

## 非空转验证（`tmp/probe_spot_rollover.py`，新建，只读 client_id=99）

同一批**真实** ES 报价，旧代码现场从 git 取（`git show HEAD:acquisition/spot_synthesis.py`，
195 行），新代码走工作区。**9/9 成立，RC=0**：

```
真实报价（IBKR 实时）与到期时刻：
  20260918  F=7659.25  到期时刻=2026-09-18 13:30:00Z
  20261218  F=7727.00  到期时刻=2026-12-18 14:30:00Z   ← CST，与上面差 1 小时 = 夏令时
  20270319  F=7807.12  到期时刻=2027-03-19 13:30:00Z

[场景 1] 换月前（现在）
  [ok] 旧代码 T(前月) 为负（判死）   T=-0.000996 年
  [ok] 新代码 T(前月) 为正           T=+0.000545 年
  [ok] 旧代码 spot() = None          None            ← 这正是服务起不来的原因
  [ok] 新代码 spot() 出值            7659.102698851836
  [ok] 新代码用的是 (前月, 次月)      实得 7659.10270 / 手算 7659.10270

[场景 2] 换月后（moment = 前月到期 + 1h）
  [ok] 旧代码仍 = None               None            ← 文档承诺的换月没实现
  [ok] 新代码出值                    7647.661187522193
  [ok] 新代码用的是 (次月, 次次月)    实得 7647.66119 / 手算 7647.66119
       ⇒ 换月那一刻 S 从 7659.10 跳到 7647.66（差 11.44 点）

[场景 3] 负对照：只喂一个月 ⇒ 新旧都 None（不是"总是出值"）
```

**判据为什么可信**：不只看"有没有值"，还**手算**了 (前月,次月) 与 (次月,次次月)
两对的反解结果，证明新代码**真的换了那一对**、而不是碰巧出个数。
`14:30Z vs 13:30Z` 那一小时差是**夏令时被正确处理**的旁证（写死偏移会两处都 13:30）。

**fail-closed 也单独验了**：坏时区 `Mars/Olympus` ⇒ `SpotUnavailableError`；
空 `realExpirationDate` ⇒ `SpotUnavailableError`。**没有静默回落。**

## 项目门禁（最终字节上）

- `run.py --check` ⇒ **16/16 RC=0**（`feed_service.py` 394 行、`spot_synthesis.py`
  260、`future_expiry.py` 149 ⇒ 均未触发"余量 < 5 行"警告）
- `tools/check_web_contract.py` ⇒ 全部通过 RC=0
- `[13]` 活链路（`:8060` 起来后自动跑）⇒ 全绿：
  `活帧顶层字段齐全 / 会话到期日 20260918 / 连接 connected / 订阅 80/92 /
  热力图 39 档 × 1021 桶`

## 实盘启动证据（04:44 EDT 起，一次成功）

```
04:44:08 INFO pipeline  启动 delayed | 到期 20260918 | 会话 {… 'is_open': True …}
04:44:21 INFO pipeline  流水线已就绪
[SVI] fitted 1/1 expiries | avg RMSE=0.023217
```
日志里 `error|traceback|warn` 计数 = **0**。

帧实测（`tmp/peek_frame.py`，新建，只读）：

```
spot = 7661.1
health.connection=connected   last_tick_age_s=0.1   mode=delayed
health.subscribed=80 / cap=92   ticks_received=14751   ticks_dropped=1082
health.messages = ['期货 3 个月已订阅: 20260918, 20261218, 20270319',
                   '现货源切换：区段 gth → 合成（B2b 期货反解）',
                   '标的现价 7659.60',
                   '0DTE 切片 20260918 SPXW (744 个行权价, SMART)',
                   '初始订阅 80 条 (上限 92, 目标 80)',
                   '行情服务已就绪']
atm = {atm_strike 7660.0, atm_iv 16.181, straddle 35.57,
       put25_iv 17.848, call25_iv 15.174, skew_25d 2.674}
skew.latest = {label '04:45:30', skew 2.674, quality 'ok'}
静态：GET / → 200 (4452 B, index.html) / GET /style.css → 200
```
⚠️ 现货 **7661.1** 是**合成值**（`health.messages` 里"现货源切换 → 合成（B2b 期货反解）"
是直接证据），不是指数直读 —— GTH 段本来就该如此。

## 修正：上一份 handoff 里有一条**假声明**

`notes/sessions/2026-09-18/live-start-blocked/handoff.md` 的「建议的修法 3」写了
「验证：`tools/check_spot_synthesis.py`（16 项）必须全绿」—— **该文件不存在**。
`tools/` 下**只剩 1 个** `check_*.py`（`check_web_contract.py`），35 个旧检查器全被删过。
已在原文件里就地标注更正。**本轮实际的验证 = 上面那条非空转探针 + `run.py --check`。**

## CHANGED-PATHS

- `acquisition/future_expiry.py`（新建）
- `acquisition/spot_synthesis.py`（改）
- `acquisition/feed_service.py`（改）
- `tmp/probe_spot_rollover.py` / `tmp/peek_frame.py` / `tmp/inspect_es_details.py`
  （新建，gitignored，只读）
- `notes/sessions/2026-09-18/live-start-blocked/handoff.md`（就地更正那条假声明）

## OPEN-RISKS

- **换月那一刻 `max_carry_jump` 会拒收第一拍**（carry 0.0354 → 0.0413，Δ=0.0059 > 0.005）：
  预测"自愈一拍"，**今天 09:30 EDT 才有机会实测**。`recenter_trigger_strikes` = 3 档
  （15 点）> 跳变 11.44 点 ⇒ 预测不会触发窗口重建，同样待实测。
- **`future_expiry` 只在 ES 上实测过**（前 3 个月）。换到别的品种（`future_symbol`
  可配）时，`lastTradeTime` / `timeZoneId` / `tradingHours` 的形态**未验证**。
- **交叉校验只在窗口覆盖到期日时生效** —— 也就是只有**前月**能被独立校验，
  次月/次次月只有主来源。窗口不覆盖时**静默降级为"不校验"**（已在 docstring 写明，
  但这是本轮唯一的"少校验"路径）。
- **非空转探针在 `tmp/`，无回归保护**（与既有的四个探针同）。项目里**没有** spot
  合成的常驻检查器 ⇒ 这条不变量目前只靠"下次有人记得跑探针"。
- `ticks_dropped = 1082 / 14751`（≈7.3%）—— 属既有行为（TickRouter 的 IV 值域/降级
  闸门），本轮未动，**未定性**。
- 前端页面本轮**未在浏览器里目视确认**（只验了静态资源 200 与帧内容）。
- `run.py` 在沙箱里长跑会让 Windows 回收站爆炸 ⇒ 常驻请 KAI 在普通终端里起。
