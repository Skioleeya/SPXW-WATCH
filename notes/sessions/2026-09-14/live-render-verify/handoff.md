TASK-ID: live-render-verify
DATE: 2026-09-14
TIER: T1
STATUS: complete
CHANGE-ID: N/A:未走 OpenSpec；纯验证，无源码改动

# Handoff — live-render-verify

**结论：四项全部 ✅。一处与任务书预期不符已如实纠正（SPX 指数实际 `marketDataType=1`，
不是预期的 3）。未强杀 KAI 常驻进程，故未停服务。**

STARTUP-PROOF: N/A:纯只读验证任务，本轮不修改任何源码/配置；首次落盘即本 handoff，
不存在"改动前基线"可捕获。基线改由 `COMMAND-EVIDENCE` 中的活进程读数承担。

## Session

- 触发：automation `e4ad7495`，在交易日盘中补跑「实盘首次出图」验证
  （open_tasks `[中] 实盘首次出图未验证`，2026-09-13 硬切删掉模拟盘后唯一未验环节）。
- 前置判据：**2026-09-14（周一）09:45 EDT，美股交易日，RTH 段**；
  帧内 `session.expiry = 20260914` ⇒ 当日到期 SPXW 存在。判据成立，进入验证。
- 端口 4001/4002/8060 全 OPEN。

## Scope Understanding

- In scope：四项逐条取证 —— (a) `health.mode` 与单合约权限；(b) 订阅条数；
  (c) 热力图出图（帧数 / 行数 / 真浏览器截图）；(d) `health.rate_limit` 四要素 + 非空转证伪。
- Out of scope：任何源码或配置改动；重跑离线回归全量；RTH 收盘后行为。

## Prior Context Read

| 来源 | 取到的约束 |
|---|---|
| skill `spxw-live-verify` + `references/live-link.md` | 单合约权限只能看 `ticker.marketDataType`；`MaxRequests`/`throttleStart` 挂 `ib.client`，`IB` 不转发；断言 45 是空转，必须传非默认值；`ib.sleep()` 在 async 上下文不可用 |
| `config/ibkr.json::_market_data_comment` | `health.mode` 是**由 `market_data_type` 推导**的，不是观测值 ⇒ 不能据它判单合约权限 |
| `notes/context/open_tasks.md` | 本条是硬切后唯一未验环节 |

## CHANGED-PATHS

- 新增 `notes/sessions/2026-09-14/live-render-verify/handoff.md`（本文件）
- 新增 `notes/sessions/2026-09-14/live-render-verify/artifacts/probe-outputs.txt`
- 新增 `notes/sessions/2026-09-14/live-render-verify/artifacts/live_render_094842.png`
- 新增 `tmp/dump_health.py`、`tmp/probe_mdt.py`、`tmp/probe_ratelimit.py`（一次性探针，落 `tmp/`）
- 无源码、无配置、无 `web/` 改动。

## COMMAND-EVIDENCE

前置：

- `date "+%Y-%m-%d %H:%M:%S %Z (%a)"` → `2026-09-14 09:45:47 EDT (Mon)`
- `for p in 4001 4002 8060; do (echo > /dev/tcp/127.0.0.1/$p) …` → 三者全 `OPEN`

(a) `health.mode` 与权限：

- 帧内 health 块 → `"mode": "delayed"`、`"connection": "connected"`
- `tmp/probe_mdt.py`（clientId=97 独立会话，`reqMarketDataType(3)`）→
  期权 `SPXW 20260914 C7610` `marketDataType=1`；SPX 指数 `conId=416904`
  **`marketDataType=1`**（任务书预期 3 —— 实测是 1，见 OPEN-RISKS）；
  `modelGreeks iv=0.14468` 与 bid/ask/last Greeks（0.14400 / 0.14524 / 0.15883）
  **并存且值不同**；指数 `last=7611.27` ≠ `close=7656.98`（周五收盘）⇒ RTH 段指数是活的

(b) 订阅条数：

- `grep "pipeline" logs/spxw_swatch.log | tail -3` → `订阅 48/92`（09:46/09:47/09:48 三行一致）
- `projected_subscriptions()` = `2*2*12 + 1` = **49**（48 option + 1 现价）
- ⚠️ 旧数字 72（±18 档）已过期，不作为判据

(c) 热力图出图：

- `tools/ws_probe.py` → `全部通过`；帧序号 `18059 → 18068`（`frames > 0`）；
  **热力图行数 24 档**；`24 档 × 1624 桶`；`位图置位数与 filled 一致 15420 格`；
  `25Δ Skew = 2.618`；末帧 `spot=7608.66`，载荷 145,502 字节
- HTTP 静态资源 11 条全 `200`
- 真 Chrome 截图 → `185973 bytes`（≫ 25 KB「等待数据…」签名）；顶栏 `connected`，
  两块面板均出图

(d) `health.rate_limit` 四要素 + 证伪：

- 帧内 `health.rate_limit` → `{capacity: 45, interval_s: 1.0, events: 0,
  throttling: false, throttled_total_s: 0.0}`（四要素齐全）
- 日志 `07:19:50 INFO ibkr.rate_limit 出站限速桶显式设为 45 条 / 1s`
- `tmp/probe_ratelimit.py` 证伪 1（非默认 12 / 0.5s）→ `MaxRequests=12`、
  `RequestsInterval=0.5`、`throttleStart/End 回调数各 1`、`hasattr(ib,"MaxRequests")=False`
- 证伪 2（突发 200 条 `reqMarketDataType`）→ `events 0→1`、`throttling True→False`、
  `throttled_total_s 0.502 → 4.004`（≈200/45）、`disconnect` 后仍 `False`

自查（探针未伤及常驻进程）：

- 探针后 `/health` → `frames 18287`、`dropped 0`；日志 `09:48:02 … 订阅 48/92`
  ⇒ 帧数继续增长、订阅未掉、现价持续更新

## VALIDATION-SUMMARY

- `tools/ws_probe.py`（需服务，盘中）→ `RC=0`，全部通过
- `tmp/probe_mdt.py` → `RC=0`，单合约权限观测成功
- `tmp/probe_ratelimit.py` → `RC=0`，两条证伪均通过
- HTTP 静态资源 11/11 → `200`
- 真 Chrome 截图 → 文件 185,973 字节，已核存在
- `run.py --check` / 离线回归全量 → `N/A`:本轮未改源码，且盘中不宜重启进程，故不重跑
- 服务停机 → `N/A`:KAI 常驻 `run.py` 正在盘中服务，任务书要求"不要强杀既有进程"，
  故**未停服务**（该项被前置指令覆盖）

## Closed in session

- open_tasks `[中]「实盘首次出图未验证」` —— **已闭合**：四项逐条取证通过（见上）。

## NOTES-PATHS

- `notes/sessions/2026-09-14/live-render-verify/handoff.md`
- `notes/sessions/2026-09-14/live-render-verify/artifacts/probe-outputs.txt`
- `notes/sessions/2026-09-14/live-render-verify/artifacts/live_render_094842.png`

## OPEN-RISKS

1. **任务书对 (a) 的预期与实测不符**：任务书写「SPX 指数 `=3`（延迟）」，
   实测 `marketDataType = 1`（实时）。`config/ibkr.json::_market_data_comment` 记录
   2026-09-11 开通实时权限后「期权与指数实测 `ticker.marketDataType=1`」——
   与本次实测一致 ⇒ **任务书的 `=3` 是过期预期，实测为准**。不改代码。
2. **`health.mode = "delayed"` 会长期显示"延迟"**，而单合约实际是实时。
   这是 `market_data_type=3` 的推导语义（择优模式的固有表现），**非缺陷**；
   但顶栏「延迟」字样与实测权限不一致，若 KAI 认为误导，需要单独裁定改法（本轮不动）。
3. **`Error 10197 competing live session` 累计 324 次**（最早 2026-09-11 14:30:41），
   本机另有他方 IB 会话（观测到 `Option_v4` uvicorn:8001 于 09:25 启动）。
   属既有环境现象，非本轮引入；但它会间歇性压掉行情，值得另开条目跟进。
4. **`features/persistence.py::recover()` 每段尾部 ≤20 桶假 0 带**仍残留（速查卡 K），
   本轮未动。截图热力图左侧 4 段孤立色块与该现象一致，但**不据截图 OCR 下结论**。
5. 本轮两次独立会话探针（clientId=97）本身会短暂与常驻会话争行情；
   已实测未踢掉常驻进程，但**不宜高频重复**。
