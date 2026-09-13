# Startup: session-rollover-and-render-fix

STARTUP-PROOF: baseline=run.py --check 通过(58 文件/最长 386 行) + ws_probe 20/20 + 4 个回归全过；改动前已确认 61 文件前的全部基线为绿

## Session

- 日期：2026-09-11
- 仓库根：`E:\US.market\SPXW SWATCH\spxw_swatch`
- 会话目标：续做上一轮的遗留项，并在"没人真正用浏览器看过页面"这个盲区上做封口验证

## Scope Understanding

- In scope:
  - 补 L1 `acquisition/` 层的离线执行覆盖（此前从未被离线跑过）
  - 用真实浏览器验证前端渲染，并修掉暴露出来的渲染缺陷
  - 验证并修掉跨会话（交易日翻篇）的数据污染
  - 为上述每一项建立可重复的回归测试
  - 更新 README 的辅助工具清单、约束说明与已知边界
- Out of scope:
  - 实盘（`run.py --live`）的"连上之后能否收到数据"——需要真实 TWS / IB Gateway，本会话无法验证
  - 改变任何业务参数或色标取值（本会话只修正确性缺陷，不调参）
  - 引入新依赖（保持纯标准库 + `ib_async` + `aiohttp`）

## Prior Context Read

- `spxw_swatch/README.md`（分层架构、六条约束、已知边界）
- `.workbuddy-ai/memory/2026-09-11.md`（前两轮：热力图恒为 null 的根因、
  GLITCH 污染、色标硬编码、Gemini 两条外部主张的稽核、订阅前未确认合约的 bug）
- `features/feature_engine.py`、`features/heatmap_engine.py`、`features/skew_engine.py`、
  `state/tick_store.py`、`core/clock.py`、`acquisition/tick_router.py`
- `web/app.js`、`web/skew.js`、`web/heatmap.js`、`web/ws_client.js`、`web/config.js`、`web/index.html`
- `tools/` 下既有 7 个工具的全部实现

## Recent Git Context

- Key commits reviewed: `N/A:该目录不是 git 仓库（git rev-parse 报 "not a git repository"）`

## Worker Readiness

- Risks noticed:
  - 前一轮的"探针 20 项全绿"制造了虚假的安全感：探针只校验后端发的数据，
    对"前端能不能画出来"零覆盖。同类盲区可能还有（实盘路径、浏览器交互）。
  - 模拟会话在 60× 加速下只有约 6.5 真实分钟，跑完 feed 会主动停手；
    验证前端必须先重启服务，否则拿到的是"收盘后无数据"的假失败。
  - 跨会话污染这类缺陷不会报错，只会产出**看起来完全正常**的假信号，
    因此必须靠"构造跨会话场景并断言具体数值"来暴露，不能靠观察。
- Blockers noticed:
  - 无。`agent-browser` CLI 的守护进程不稳定，已改用 Chrome headless
    `--dump-dom` 绕开，不构成阻塞。
