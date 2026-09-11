# Handoff — session-rollover-and-render-fix

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: baseline=run.py --check 通过 + ws_probe 20/20 + 既有 4 个回归全过；改动前基线为绿

## 结论

本会话修掉两个"探针全绿但实际是坏的"缺陷，并为每个缺陷建立了非空转的回归：

1. **Skew 面板从未渲染成功过**（前端）—— `visualMap` 的 `pieces` 模式在
   ECharts 5.6.0 上必抛 `Cannot read properties of undefined (reading 'coord')`。
2. **跨会话数据污染**（后端）—— 桶序号被跨会话复用，且旧会话的 tick 被判为
   `STALE` 后写进新会话的桶。两条路径都通向"拿昨天的数据造今天的信号"。

CHANGED-PATHS: 8 个文件（4 改 + 4 新增），明细见下
- `web/skew.js`（改）— 新增 `splitBySign()`；正负着色由 visualMap 改为双同名序列；
  图例去重；新增提示框 formatter 过滤 null 一侧；模块 docstring 记录 ECharts 限制
- `web/ws_client.js`（改）— 渲染回调异常时补 `console.error(e)`（保留堆栈，UI 消息仍简洁）
- `features/feature_engine.py`（改）— 新增 `_sync_session()`（翻篇清空）与
  `_session_refs()`（按到期日过滤合约）；`__slots__` 增 `_session_key`
- `README.md`（改）— 辅助工具清单增至 10 条；新增三项回归的说明；已知边界新增 4 条
- `tools/check_tick_router.py`（新增）— L1 离线回归，7 组
- `tools/check_session_rollover.py`（新增）— 跨会话回归，4 组
- `tools/check_web_contract.py`（新增）— 引用→定义三向对照
- `tools/check_page_render.py`（新增）— 真浏览器渲染断言

VALIDATION-SUMMARY: 全部通过。`run.py --check` 7/7；7 个回归全过；
`ws_probe` 20/20；页面实拍两块面板均出图。三个新回归均已验证非空转
（注入缺陷能报 FAIL）。

COMMAND-EVIDENCE: 9 条校验命令全部通过 + 3 项非空转验证全部按预期 FAIL，明细见下
- `python run.py --check` → `结果: 全部通过`
  （61 个文件全部合规，最长 tools/selfcheck.py = 386 行；未发现反向依赖；
  10 个模块配置全部可读；未发现配置之间的相互引用；40 个关键配置项齐备；
  档位 ±18 → 73 条行情（上限 92，IBKR 上限 100）；__slots__ 一致）
- `python tools/smoke_test.py` → exit 0
- `python tools/check_side_flip.py` → exit 0（首个有值列 2，允许偏移 ≤ 2）
- `python tools/check_subscription_qualify.py` → exit 0
- `python tools/check_tick_router.py` → exit 0（7 组全过）
- `python tools/check_session_rollover.py` → exit 0（4 组全过）
- `python tools/check_web_contract.py` → exit 0（43 条载荷路径 + 20 个 DOM id +
  26 条 CFG 路径全部对得上）
- `python tools/check_page_render.py` → exit 0
  （无渲染回调异常 / 热力图 36 档 × 234 桶 · 7,320 格 / Skew 233 点 / connected / 4 canvas）
- `python tools/ws_probe.py --frames 6` → `结果: 全部通过`（20 项）
- 非空转验证（摘掉修复）：
  - `check_session_rollover.py` → FAIL：`第 1 桶不得跨会话差分 值=1.9999999999999991`、
    `Skew 序列只含新会话的点 6 点`、`无新 tick 时不再推送旧矩阵 有值格=108`
  - `check_page_render.py` → FAIL：`渲染回调异常: Cannot read properties of
    undefined (reading 'coord')`、`Skew 曲线已渲染 meta 为空（面板未渲染）`
  - `check_web_contract.py` → FAIL：`缺失: atm.butterfly, health.store_cells`

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上
HARNESS-IMPROVEMENT: 新增三个回归工具，其中 `check_page_render.py` 与
  `check_web_contract.py` 填补了两个此前完全无人覆盖的验证面（"页面画出来没有"、
  "前端读的字段后端发没发"）。两者都做了非空转验证。

NOTES-PATHS: 8 个文件（会话根 5 件 + 上下文索引 3 件），明细见下
- `notes/sessions/2026-09-11/session-rollover-and-render-fix/startup.md`
- `notes/sessions/2026-09-11/session-rollover-and-render-fix/project_state.md`
- `notes/sessions/2026-09-11/session-rollover-and-render-fix/open_tasks.md`
- `notes/sessions/2026-09-11/session-rollover-and-render-fix/handoff.md`
- `notes/sessions/2026-09-11/session-rollover-and-render-fix/meta.yaml`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 4 条（实盘未验证 / notes 与既有证据体系并行 / 翻篇瞬间留旧画面 / 渲染检查依赖 Chrome），明细见下
1. **实盘未验证（中）** —— `run.py --live` 的"连上之后能否收到数据"需要真实
   TWS / IB Gateway。连接失败路径已实测可操作；订阅与 106 模型 Greeks 的实际
   到达未验证。
2. **`notes/` 与既有证据体系并行（低）** —— 本项目原有 `.workbuddy-ai/memory/`
   + README + 回归工具三处承载证据，`notes/` 是随全局 skill 引入的第二套。
   长期并行会造成"改一处忘一处"，建议后续收敛。
3. **翻篇瞬间前端短暂留上一场画面（低）** —— 刻意取舍（避免闪白），
   已在 README 记为已知边界；状态行的 `0/390` 可区分该状态。
4. **`check_page_render.py` 依赖本机 Chrome（低）** —— 找不到时跳过并返回 0，
   意味着在无 Chrome 的环境里这条检查会静默失效而非报错。

FAST-FAIL-CHECK: 通过 —— 背压仍是 fail-closed（每客户端 `Queue(maxsize=1)`，
`put_nowait` 丢最旧，生产者从不 await）；本会话未改动该路径。
NO-COMPAT-BRANCH: 通过 —— 未引入任何兼容分支或双写路径；两处修复都是替换实现。
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径。反而**否决**了一个更"省事"的方案
  （翻篇时清空 `TickStore`），因为它在模拟模式下依赖调用顺序、会误删新数据。
NO-PATCH-BANDAGE: 通过 —— 两处修复都落在正确的层：Skew 的着色改在配置构造处
  而非吞掉异常；跨会话隔离落在 `FeatureEngine`（唯一知道会话翻篇的地方）。
NO-FALLBACK-BEHAVIOR: 通过（产品行为）—— 未新增任何静默降级。唯一的新增"跳过"
  在 `check_page_render.py`（缺 Chrome 时返回 0），属测试夹具的显式跳过，
  不触及产品行为，且已在 OPEN-RISKS 记录其代价。

TRIGGER-PATHS: N/A:本项目为 Python，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check` + 全部回归，已在上方 COMMAND-EVIDENCE 记录
