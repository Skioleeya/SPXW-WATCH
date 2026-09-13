# Handoff — selfcheck-hardening

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: baseline=run.py --check 通过（61 文件 / 最长 tools/selfcheck.py 386 行，
7 项）+ 7 个回归全过 + ws_probe 20/20；改动前基线为绿

## 结论

三件事：

1. **接死键**：`state.prune_interval_s` 真正接进 L6 维护循环，裁剪节奏归 L2 所有
   （组装层只按它驱动循环，不替 L2 选参数）。取值 10.0 不变，行为零变化。
2. **顺带修掉一个真缺陷**：`SessionClock` 没实现 `ClockPort.now()`，导致
   `TickStore.prune()` 每 10 秒抛 `AttributeError` 并被 `except` 吞成 warning ——
   **时间窗裁剪从未真正执行过**，而所有探针与回归当时都是绿的。
3. **补齐三条机械检查**（[7] 配置键归属与接线、[9] 单一职能、[10] 禁止硬编码），
   并把已达 386/400 行的 `tools/selfcheck.py` 按单一职能拆成 7 个文件。

CHANGED-PATHS: 14 个文件（9 新增 + 5 改），明细见下
- `tools/selfcheck.py`（改）— 从 386 行的单体改为纯编排器
- `tools/selfcheck_core.py`（新增）— 共享常量、输出原语、AST 扫描工具
- `tools/selfcheck_structure.py`（新增）— [1] 文件长度、[2] 依赖方向
- `tools/selfcheck_config.py`（新增）— [3][4][5][6] + [7] 配置键归属与接线
- `tools/selfcheck_slots.py`（新增）— [8] `__slots__` 一致性
- `tools/selfcheck_duty.py`（新增）— [9] 单一职能
- `tools/selfcheck_hardcode.py`（新增）— [10] 禁止硬编码
- `tools/selfcheck_code.py`（删除）— 被上面三个文件按职能拆开替代
- `tools/check_clock_protocol.py`（新增）— 时钟协议一致性 + 真实裁剪路径回归
- `state/tick_store.py`（改）— 读 `prune_interval_s`、新增同名只读属性、`__slots__` 同步
- `app/pipeline.py`（改）— `_prune_loop` 改为读 `self._store.prune_interval_s`
- `core/clock.py`（改）— `SessionClock` 新增 `now()`（实现 `ClockPort`），`now_ts()` 改为别名
- `config/pipeline.json`（改）— 删掉 `prune_interval_s`；`config/state.json`（改）— 注释说明裁剪节奏
- `README.md`（改）— §1 工具清单、§3 配置规则三条→四条、§9 检查表 7→10 项、§10 已知边界

VALIDATION-SUMMARY: 全部通过。`run.py --check` **10/10**（含 7 条死键 warn，不阻塞）；
**8 个回归全过**；`ws_probe` 20/20；页面实拍两块面板均出图。**6 项非空转验证**
全部按预期 FAIL 且文件已还原。

COMMAND-EVIDENCE: 明细见下
- `python run.py --check` → `结果: 全部通过`（68 个文件全部合规，最长
  `acquisition/feed_service.py` = 376 行；未发现反向依赖；10 个模块配置全部可读；
  未发现配置之间的相互引用；39 个关键配置项齐备；档位 ±18 → 73 条行情；
  **148 处取键调用全部落在其声明的配置文件里**；`__slots__` 一致；
  单一职能通过；未发现模块级硬编码常量（显式例外 7 条））
- `python tools/smoke_test.py` → exit 0
- `python tools/check_side_flip.py` → exit 0
- `python tools/check_subscription_qualify.py` → exit 0
- `python tools/check_tick_router.py` → exit 0
- `python tools/check_session_rollover.py` → exit 0
- `python tools/check_clock_protocol.py` → exit 0
  （三个时间源均满足 ClockPort；`prune()` 丢弃 2 个样本，剩余 期权 0 / 现价 0）
- `python tools/check_web_contract.py` → exit 0（JS id / CFG 键 / 载荷字段三向对上）
- `python tools/check_page_render.py` → exit 0
  （无渲染回调异常 / 热力图 36 档 × 19 桶 · 612 格 · 色标 ±0.50 / Skew 18 点 /
  connected · sim / 2 canvas / 现价 6499.4）
- `python tools/ws_probe.py --frames 6` → `结果: 全部通过`（矩阵含有效数值 180 格；
  Skew 序列 6 点、各列等长、25Δ = 0.717）
- 运行期证据：接线前服务日志每 10s 一行
  `WARNING pipeline 裁剪异常: 'SessionClock' object has no attribute 'now'`；
  修复后同一路径 **0 条裁剪异常**（实测 grep 计数 = 0）
- 非空转验证（注入违规 → 必须 FAIL，全部命中且已还原）：
  - `module=_CFG` → `module="features"` → FAIL `键与文件错位`
  - `UNWIRED_IS_FAILURE=True` → FAIL `7 个死键全部转红`
  - 追加 3 个公开类 → FAIL `顶层公开类 5 个`
  - `state/__init__.py` 追加函数 → FAIL `__init__.py 只能做导出`
  - 追加 `_MAX_RETRIES = 5` → FAIL `模块级字面量常量`
  - 摘掉 `SessionClock.now()` → FAIL `不满足 ClockPort` + `prune() 抛 AttributeError`

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 本会话把"靠人记住"的约束变成了可执行检查，并把两个此前
**完全无人覆盖**的验证面补上了：
1. 检查 [7] 一次抓出 **7 个死配置键**（配置写着、没有任何代码读）。这类缺陷
   比硬编码更难发现 —— 硬编码能在代码里搜到，死键搜不到，只能靠静态对照。
2. `check_clock_protocol.py` 暴露出 `SessionClock` 未实现 `ClockPort`，
   使 `prune()` 长期静默失效。**这是"探针全绿但实际是坏的"的又一个实例**：
   它藏在 `except Exception` → warning 的吞异常路径后面。
3. 新增三条检查全部做过非空转验证，且各自声明了覆盖边界（[9] 是粗粒度代理、
   [10] 只覆盖模块级），不假装比实际更强。

NOTES-PATHS: 8 个文件（会话根 5 件 + 上下文索引 3 件），明细见下
- `notes/sessions/2026-09-11/selfcheck-hardening/startup.md`
- `notes/sessions/2026-09-11/selfcheck-hardening/project_state.md`
- `notes/sessions/2026-09-11/selfcheck-hardening/open_tasks.md`
- `notes/sessions/2026-09-11/selfcheck-hardening/handoff.md`
- `notes/sessions/2026-09-11/selfcheck-hardening/meta.yaml`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 5 条，明细见下
1. **7 个死配置键尚未处理（中）** —— 每个都需要产品决策（接线 or 删除）。
   其中 `transport.access_log` 是"配置写了、代码里硬编码"的组合，同时违反
   第 3 条与第 7 项检查的意图。检查 [7] 目前只 `[warn]`；去留定了才能把
   `UNWIRED_IS_FAILURE` 置 `True` 收紧。
2. **实盘未验证（中）** —— 需要真实 TWS / IB Gateway。
3. **`notes/` 与 `.workbuddy-ai/memory/` 并行（低）** —— 本会话按项目既有约定
   写 `notes/`，`memory/` 只留指针。上一轮已出现过"前置记忆整个丢失"的实例，
   建议尽快定收敛方案。
4. **`check_clock_protocol.py` 靠人记得跑（低）** —— 它是回归不是自检项，
   不在 `--check` 里。是否并入自检待定。
5. **本机三个解释器都没有 `tzdata`（低，环境）** —— 5 个回归会抛
   `ZoneInfoNotFoundError`。本会话用隔离 venv
   （`C:/Users/Lenovo/.workbuddy-ai/binaries/python/envs/default`）绕开，
   并在 `meta.yaml` 记录。另外本机回环请求会被代理拦成 502，需设
   `NO_PROXY=127.0.0.1,localhost`。

FAST-FAIL-CHECK: 通过 —— 背压仍是 fail-closed（每客户端 `Queue(maxsize=1)`、
`put_nowait` 丢最旧、生产者从不 await）；本会话未改动该路径。新增检查一律
fail-fast：判定不通过即计入失败，不用"尽量报几条"的软处理。
NO-COMPAT-BRANCH: 通过 —— 未引入任何兼容分支或双写路径。配置键是**迁移**而非
兼容：`pipeline.prune_interval_s` 直接删除，不做"两个位置都读"的过渡。
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径。
NO-PATCH-BANDAGE: 通过 —— 关键的一处：`SessionClock` 缺 `now()` 的修法是**实现
协议**（`contracts/ports.py::ClockPort`），而不是把 `TickStore` 里的
`clock.now()` 改成 `clock.now_ts()`。后者会让 L2 反过来迁就一个不满足 L0 契约的
对象，把问题从"实现方违约"变成"调用方绕行"。同理，检查 [7] 用工程既有的
`module=` 约定判定归属，而不是新造一张"键→模块"映射表（那会是第二份真相）。
NO-FALLBACK-BEHAVIOR: 通过（产品行为）—— 未新增任何静默降级。唯一新增的"跳过"
在 `check_page_render.py`（缺 Chrome 时返回 0），属既有测试夹具的显式跳过。
检查 [7] 对死键报 `[warn]` 而非 `[FAIL]` 是**刻意的显式降级**：在 7 个键的去留
决定之前，升级为失败会让 `--check` 长期变红。该开关与代价都写在代码注释与
README §9/§10 里，不是隐藏行为。

TRIGGER-PATHS: N/A:本项目为 Python，非 Rust 算法范围
TRIGGER-BASIS: N/A:同上
CHANGE-BEHAVIOR-CLASS: N/A:同上
TRIGGER-DECISION: N/A:同上
RESEARCH-PACKAGE-PATH: N/A:同上
RESEARCH-REPORT: N/A:同上
RLLM-REPORT: N/A:同上
STRICT-COMMAND: N/A:该仓库无 `scripts/validate_session.sh` 等 governance 脚本；
  等效的最小严格校验为 `python run.py --check` + 全部回归，已在上方 COMMAND-EVIDENCE 记录
