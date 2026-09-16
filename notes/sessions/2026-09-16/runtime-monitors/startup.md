# Startup: runtime-monitors

STARTUP-PROOF: 开工前基线（2026-09-16 08:2x ET，服务在跑，PID 1228）：
`curl --noproxy '*' http://127.0.0.1:8060/health` → `frames=14492`
`run.py` 日志尾部 `08:25:46 帧 14003 | 现价 7612.92 | 订阅 80/92`
判据：本会话新写两个 `tmp/` 探针，不改产品代码，故基线只需"服务可用"。

> 说明：本条为**补记**。探针写作在 08:1x 开始，当时的端口/帧号证据
> 保留在 `tmp/app_run.log.bak_085908` 里，未在开工瞬间落纸。

## Session

KAI 要求：写独立的前后端监听脚本，用于验证四件事 ——
(1) 脚本本身可用；(2) 新网格出列后数值不再变；(3) 每周期按 ET 挂钟推进；
(4) 各周期 ΔIV 独立互不干扰。写完后启动整个系统。

## Scope Understanding

- In scope:
  - `tmp/monitor_backend.py` —— 从 WS 原始帧判 T2/T3/T4
  - `tmp/monitor_frontend.js` —— 用 Playwright 读**页面上真正渲染出来的矩阵**判 T1–T4
  - 两者各自做"摘掉修复要能报 FAIL"的非空转验证
  - 重启后端使代码改动生效
- Out of scope:
  - 不改任何产品代码（`acquisition/` `features/` `web/` 等一律只读）
  - 不建常驻检查器（KAI 明令：只产出代码，不额外搭检查/校验模块）
  - 前端曲面残差副图（KAI 已驳回："前端会变得很挤"）

## Prior Context Read

- `notes/context/open_tasks.md`、`notes/context/project_state.md` ——
  约束：`spxw_swatch` 正在基于原版重写，`tools/` 只剩 1 个 `check_*.py`；
  引用进度只认 `open_tasks.md` 顶部「重写」块。
- `notes/memory/QUICKREF.md`（静默错值型速查卡）—— 约束：改代码前必扫；
  本会话不改产品代码，故仅用于理解"假绿"为何是本项目头号禁忌。
- `web/period.js`、`web/period_align.js`、`web/matrix_codec.js` ——
  约束（取自源码注释，非复述）：
  - 出列语义「周期走满才出列，出列即定稿」
  - 挂钟等价 `72900 % 30/60/180/300/900 == 0`
  - `bm16` 位图 + 小端 int16 的真实编码约定（探针必须逐位对齐）
- `contracts/feature.py`、`features/heatmap_engine.py` ——
  约束：`cols() == bucket_index`，矩阵只含**已走满**的桶。

## Recent Git Context

- Key commits reviewed:
  - `bedbf11` fix(web): 周期只出已走满的组 + 论证「桶分组 ≡ 挂钟整点分分组」
    —— 这正是 T3 判据的来源。
  - `2db39eb` docs(notes): 记录 Top-3 高亮的亚像素缺陷 + 提交后实盘复核结论
- 工作区：`HEAD = bedbf11`，产品代码大面积未提交（重写中间态）。

## Worker Readiness

- Risks noticed:
  - 探针最容易犯的错是**读了帧里不存在的字段**（`heatmap.values`），
    于是"0 改写"看着像通过、实际什么都没看。已在两个探针里各设一道闸。
  - 前端中间有 4 层变换（`sliceZones`→`aggregate`→`clipTail`→`applyViewport`），
    **后端全绿 ≠ 前端不抖**，所以前端探针必须读页面而非读帧。
  - 指纹的**键**若用行号或裁剪后的轴标签，会报出几万条假改写（已实测踩到）。
  - 本地有透明代理，loopback 请求必须 `trust_env=False` / `--noproxy '*'`。
- Blockers noticed: none
