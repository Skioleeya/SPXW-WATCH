# Handoff — dead-key-resolution

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: baseline=`run.py --check` 通过（68 文件 / 最长 acquisition/feed_service.py
376 行 / 10 项，含 7 条死键 warn）+ 8 个回归全过 + ws_probe 全过；改动前基线为绿

## 结论

上一会话的检查 [7] 抓出 7 个死配置键，当时只报 `[warn]`。本会话逐个定性并处理完：

1. **4 个接线**：`transport.access_log`（消除硬编码）、`ibkr.max_underlying_age_s`
   （防用陈旧现价重建窗口 —— 正确性问题）、`pipeline.shutdown_timeout_s`
   （停机保底退出）、`pipeline.reset_feature_state_on_reconnect`
   （防跨断线假冲量，默认值仍 false，行为不变）。
2. **3 个删除**：`features.atm_max_bracket_strikes`（连同死方法 `atm_bracket()`）、
   `ibkr.handshake_timeout_s`、`ibkr.chain_ready_timeout_s`。
3. **收紧检查**：`UNWIRED_IS_FAILURE` → `True`，死键从此即失败。
4. **顺带拆出** `acquisition/spot_tap.py`（`feed_service.py` 曾涨到 429 行被 [1] 拦下）。

CHANGED-PATHS: 11 个文件（1 新增 + 10 改），明细见下
- `acquisition/spot_tap.py`（新增）— `SpotTap` 从 `feed_service` 拆出，独立成文件
- `transport/server.py`（改）— 读 `access_log`，传给 `AppRunner`，替换硬编码 `None`
- `contracts/ports.py`（改）— `FeedPort` 新增 `set_reconnect_hook`
- `acquisition/feed_service.py`（改）— `max_underlying_age_s` 接线（`_spot_stale`）、
  实现 `set_reconnect_hook`、`_on_reconnect` 触发钩子、拆出 `SpotTap`（429→395 行）
- `simulator/synthetic_feed.py`（改）— `set_reconnect_hook` 的 no-op 实现
- `app/pipeline.py`（改）— 注册重连钩子 + `_on_feed_reconnect`；`stop()` 拆为
  `_shutdown_step`，用 `asyncio.wait` 加停机超时
- `features/strike_window.py`（改）— 删死方法 `atm_bracket()` 与 `Sequence` import
- `config/ibkr.json`（改）— 删 `handshake_timeout_s`、`chain_ready_timeout_s`
- `config/features.json`（改）— 删 `atm_max_bracket_strikes`
- `tools/selfcheck_config.py`（改）— `UNWIRED_IS_FAILURE` → `True`
- `README.md`（改）— §1 §3 §9 §10 同步（死键表改为处置表 + 三条坑）

VALIDATION-SUMMARY: 全部通过。`run.py --check` **10/10**（69 文件 / 最长 395 行 /
**死键 0**）；**8 个回归 + ws_probe 全过**；**3 组非空转验证共 20 项全部按预期**，
其中一次真实命中了停机超时分支。

COMMAND-EVIDENCE: 明细见下
- `python run.py --check` → `结果: 全部通过`
  （69 个文件全部合规，最长 `acquisition/feed_service.py` = 395 行；未发现反向依赖；
  10 个模块配置全部可读；未发现配置之间的相互引用；39 个关键配置项齐备；
  档位 ±18 → 73 条行情；**158 处取键调用全部落在其声明的配置文件里**；`__slots__`
  一致；单一职能通过；未发现模块级硬编码常量（显式例外 7 条））
- `python tools/smoke_test.py` → exit 0
- `python tools/check_side_flip.py` → exit 0
- `python tools/check_subscription_qualify.py` → exit 0
- `python tools/check_tick_router.py` → exit 0
- `python tools/check_session_rollover.py` → exit 0
- `python tools/check_clock_protocol.py` → exit 0
- `python tools/check_web_contract.py` → exit 0（JS id / CFG 键 / 载荷字段三向对上）
- `python tools/check_page_render.py` → exit 0
  （热力图 36 档 × 16 桶 · 504 格 · 色标 ±0.50 / Skew 15 点 / connected · sim /
  2 canvas / 现价 6499.8）
- `python tools/ws_probe.py` → `结果: 全部通过`（末帧 spot=6500.34，
  热力图 36 档 × 25 桶，25Δ = 0.81，载荷 18,586 字节）
- 非空转验证 A（`spxw_probe_deadkey.py`）：向 `features.json` 注入 `dead_key_probe`
  → `[FAIL] config/features.json 的 'dead_key_probe' 没有任何代码读取（未接线/死键）`
  + 整体判定变为不通过 → 文件已还原 ✅
- 非空转验证 B（`spxw_probe_wiring.py`）→ **11/11**：
  - `max_underlying_age_s`：新鲜 → `False`；超阈 → `True`；从未收到 → `True`
  - `reset_feature_state_on_reconnect`：钩子已注册；`true` → 调用 `engine.reset()`；
    `false` → 不调用
  - `shutdown_timeout_s`：`stop()` 实测 **2.0s**（上限 2s、任务清理需 3s），
    返回时任务仍在清理中 → **确实走了超时分支**；对照：正常任务 0.00s 被取消
  - `access_log`：`false` → 捕获 0 行；`true` → 捕获 1 行
- 非空转验证 C（`spxw_probe_lifecycle.py`）→ **8/8**：真实 `start()` → 运行 12s
  （跨过一个完整裁剪周期）→ `stop()`；产出 29 帧、日志出现「已停止」、
  **无裁剪异常**、无后台任务超时、无 ERROR/Traceback
- 源码级证据：aiohttp 3.14.3 `web_protocol.py:186`
  `access_log: Logger = access_logger`（`= getLogger("aiohttp.access")`，truthy）
  → 不传即开启，故不能删掉 `access_log=None` 参数

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 本会话把"检查抓出的问题"真正闭环，并新增三个验证面：
1. **死键从"报警"升级为"失败"**，且这个升级本身做了非空转验证 —— 证明它不是
   空转的开关。
2. **`asyncio.wait` vs `wait_for` 的差异被实测抓出。** 第一版用 `wait_for` 时，
   `stop()` 在一个清理需 3s 的任务上会等满 3s，超时上限形同虚设。这个坑极容易
   复发，已记入会话记录并建议沉淀为常驻回归。
3. **接线前先做事实核查**（`last_spot_ts` 只写不读、`atm_bracket()` 无调用点、
   aiohttp 默认值），避免"照着键名猜功能"。7 个键最终分属三类不同问题，
   混在一起做二选一会出错。

NOTES-PATHS: 8 个文件（会话根 5 件 + 上下文索引 3 件），明细见下
- `notes/sessions/2026-09-11/dead-key-resolution/startup.md`
- `notes/sessions/2026-09-11/dead-key-resolution/project_state.md`
- `notes/sessions/2026-09-11/dead-key-resolution/open_tasks.md`
- `notes/sessions/2026-09-11/dead-key-resolution/handoff.md`
- `notes/sessions/2026-09-11/dead-key-resolution/meta.yaml`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 4 条，明细见下
1. **新接线未过实盘（中）** —— `max_underlying_age_s`（现价陈旧闸）与
   `reset_feature_state_on_reconnect`（重连清状态）只在单元/生命周期层面验证过。
   真实断线场景需要 TWS / IB Gateway 才能确认。
2. **实盘"连上之后能否收到数据"仍未验证（中）** —— 承接上一会话，未变化。
3. **`notes/` 与 `.workbuddy-ai/memory/` 并行（低）** —— 两套证据体系，收敛方案待定。
4. **`check_clock_protocol.py` 与停机超时验证都靠人记得跑（低）** —— 两者都不在
   `--check` 里，属"靠自觉"的回归。

FAST-FAIL-CHECK: 通过 —— 背压仍是 fail-closed（每客户端 `Queue(maxsize=1)`、
`put_nowait` 丢最旧、生产者从不 await）；本会话未改动该路径。新增的
`_spot_stale` 是**跳过**而非降级：跳过窗口重建，不会用陈旧数据产出帧。
NO-COMPAT-BRANCH: 通过 —— 未引入任何兼容分支或双写路径。删除的 3 个键是**直接
删除**，不做"保留但标记废弃"的过渡；接线是**读取配置**，不是"配置与硬编码双写"。
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径。
NO-PATCH-BANDAGE: 通过 —— 三处关键选择都是"改对地方"而不是"绕开症状"：
(i) `access_log` 的修法是**读配置**，而不是把 `server.py` 的硬编码注释掉；
(ii) `shutdown_timeout_s` 的修法是**换用 `asyncio.wait`**（真正不等待），而不是
在 `wait_for` 外面再套一层 `wait_for`；
(iii) `feed_service.py` 超行数的修法是**按职能拆出 `SpotTap`**，而不是砍注释凑数。
同理，重连钩子写进了 `FeedPort` 协议，而不是让 L6 用 `getattr` 探测实现 ——
后者会让"接口漏写"再次变成静默失败。
NO-FALLBACK-BEHAVIOR: 通过（产品行为）—— 未新增静默降级。唯一新增的"跳过"是
`_reconcile_loop` 里现价陈旧时**不做窗口重建**，且它在状态翻转时**会记一次
WARN/INFO 日志**（不是静默），消息明确说明"避免用陈旧现价订错档位"。两个新增的
默认值（`access_log=false`、`reset_feature_state_on_reconnect=false`）都保持了
接线前的既有行为，未改变产品语义。

TRIGGER-PATHS: N/A:本项目为 Python，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check` + 全部回归，已在上方 COMMAND-EVIDENCE 记录
