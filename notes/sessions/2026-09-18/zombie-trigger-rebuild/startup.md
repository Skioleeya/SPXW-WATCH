# Startup: zombie-trigger-rebuild

TASK-ID: zombie-trigger-rebuild
DATE: 2026-09-18
TIER: T2
STARTUP-PROOF: 树基线 = `70cba0c`（`git log --oneline -8` 的 HEAD）+ `git status --short`
**输出为空**（工作区干净）。
服务基线（**开工前**探的，2026-09-18 03:2x EDT）：`:8060` / `:4001` / `:4002` **全部 closed**，
`tasklist | grep -i ibgateway` **无进程** ⇒ 后端与 IB Gateway 都没在跑。
时间基线：本机 `date` = `Fri Sep 18 03:34:00 EDT 2026`，与外部 HTTP `Date` 头
（`Fri, 18 Sep 2026 07:34:02 GMT`）**一致** ⇒ 时钟可信；此刻**美股休市**（09:30 EDT 开盘）
⇒ 按 `spxw-live-verify` 的纪律**不起服务做验证**（盘前起 `run.py` 会在 0DTE 处 fail-closed）。

## Session

承接 `frontend-data-outage` / `frontend-stale-reconnect`（2026-09-17）。那两轮把
「后端僵尸」和「前端看门狗只报不改」都修了，但**触发条件一次都没重建过** ——
待办里挂着的正是这条：「哪段 JS 占住了主线程导致 >1s 背压，无法重建」。

## Scope Understanding

- **In scope**：① 把「浏览器侧触发僵尸」的条件真的造出来（假设检验，不成立要如实报）；
  ② 用非空转 A/B 证明新旧后端在**同一触发**下行为相反；③ 验证真僵尸下前端自愈是否真的有用。
- **Out of scope**：不改产品代码行为（只给 `transport/ws_broadcaster.py` 补一段 docstring）；
  不动 `:8060` / IB Gateway（它们本来就没跑，也不在本轮去起）；不建常驻检查器（按 KAI 明令）。

## Prior Context Read

- `notes/context/open_tasks.md`（`frontend-data-outage` 块）—— 取的**约束**：
  「触发点未重建」是本轮要关掉的那条；「探针无回归保护」继续留着不关。
- `notes/sessions/2026-09-17/frontend-data-outage/handoff.md` 与
  `frontend-stale-reconnect/{handoff,project_state}.md` —— 取的**约束**：
  注销必须由「发送协程结束」触发（`748cd56`）；前端两个活体信号必须分开、
  基准用 `max(最后一帧, 连接建立时刻)`（`87fa904`）。**不复述其内容。**
- `tmp/probe_zombie_ws.py` —— 取的**约束**：裸 socket「只握手不读」已证明**机制**存在；
  本轮要证的是**浏览器能触发它**，不是再证一遍机制。

## Recent Git Context

- Key commits reviewed: `70cba0c`（HEAD）、`87fa904`（看门狗拆两个信号）、
  `748cd56`（僵尸修复 —— 本轮 A/B 的「旧版」= `748cd56^`）。

## Worker Readiness

- Risks noticed: ① 浏览器网络层可能替页面把帧全吞掉 ⇒ 假设可能**不成立**，
  探针必须能报出来（不许改判据迁就结论）；② 判据若只看末态会误判 ——
  页面重连之后 `clients` 会回到 1，那不是僵尸。
- Blockers noticed: 无。自带后端（产品自己的 `WsBroadcaster` + `StaticHandler`）
  + 真帧样本（`tmp/frame_sample.json`）⇒ 不依赖行情、不依赖 IB Gateway。
