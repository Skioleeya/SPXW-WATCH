# Handoff — simulator-hard-cut

CHANGE-ID: N/A:该仓库未使用 OpenSpec，无 change id
PROPOSAL-PATH: N/A:同上，无 proposal
TASKS-PATH: N/A:同上，无 tasks 文件
STARTUP-PROOF: baseline=`run.py --check` **11/11** 通过（改动前 78+4 文件 /
最长 `acquisition/ibkr_gateway.py` 360 行 / 9 配置 / 37 关键键）+ 本地回归
**11/11 exit 0**；改动前基线为绿。4 个需服务的检查因本机 8060 无服务不在基线内。

## 结论

KAI 指令「硬切删除模拟盘的所有依赖，让系统是的实盘系统」已执行完毕：

1. **物理删除** `simulator/` 4 个文件（582 行）+ `config/simulator.json`。
   无特性开关、无兼容分支、无回退路径。
2. **CLI 收敛**：`run.py` 只剩 `--check`；`--sim` / `--live` 与
   `_resolve_simulate()` 一并删除。
3. **`app/pipeline.py` 367 → 341 行**：删 `simulate` 形参、`_cfg["simulator"]`、
   SimClock 分支、SyntheticFeed 分支、`FeedMode` import。
4. **`FeedMode.SIM` 移除**（枚举本身保留 —— 它对应 IBKR `marketDataType`，
   是跨层契约的一部分）。
5. **关键交付物 `tools/fixtures.py`（新增，188 行）** —— 把被删模拟源里的
   **最小确定性内核**抽成测试夹具，让 4 个原本依赖模拟盘的离线回归活下来。
   `FakeClock` 完全不碰 `time.monotonic()`，**比被删的 `SimClock` 更确定**。
6. **自检登记项同轮清理** —— `LAYER_OF["simulator"]`、`REQUIRED_KEYS["simulator"]`、
   `EXEMPT_CONSTANTS["simulator/scenario.py"]`。漏删会让检查 [2] 静默跳过该层。
7. **`README.md` 同步** + 修正过期数字（配置 10 → 9、关键键 41 → 37）。

同会话第二部分的记录体系工作见 `project_state.md` §8。

CHANGED-PATHS: 20 个路径（1 新增 / 15 改 / 5 删），明细见下

**产品代码（改）**
- `run.py` — 删 `--sim`/`--live`/`_resolve_simulate()`；`Pipeline()` 无参
- `app/pipeline.py` — 367 → **341 行**，删 `simulate` 参数与两条分支
- `contracts/enums.py` — 删 `FeedMode.SIM`
- `contracts/ports.py` — docstring 改（模拟模式 → 实盘 + 离线回归）
- `core/clock.py` — 同上
- `acquisition/__init__.py` — 同上
- `README.md` — 层级表 / 配置清单 / §8 / 过期数字

**工具（改）**
- `tools/selfcheck_core.py` — 删 `LAYER_OF["simulator"]`、`REQUIRED_KEYS["simulator"]`；
  更新 `NON_SOURCE_DIRS["notes"]` 理由串
- `tools/selfcheck_hardcode.py` — 删 `EXEMPT_CONSTANTS["simulator/scenario.py"]`
- `tools/check_clock_protocol.py` — 改用 `tools.fixtures.FakeClock`
- `tools/check_side_flip.py` — 改用 `tools.fixtures.SyntheticSurface`
- `tools/check_session_rollover.py` — 改用 `tools.fixtures.FakeClock`
- `tools/smoke_test.py` — 改用 `tools.fixtures`；`FeedMode.SIM` → `FeedMode.LIVE`

**工具（新增）**
- `tools/fixtures.py` — 188 行；`FakeClock`（实现 `ClockPort`）+ `SyntheticSurface`

**删除**
- `simulator/__init__.py`（20 行）
- `simulator/scenario.py`（136 行）
- `simulator/sim_clock.py`（110 行）
- `simulator/synthetic_feed.py`（316 行）
- `config/simulator.json`

**仓库之外的记录体系改动**
- `C:\Users\Lenovo\.workbuddy-ai\skills\notes-session-records\SKILL.md`（160 → 133 行）
- `C:\Users\Lenovo\.workbuddy-ai\skills\notes-session-records\agents\openai.yaml`（删除）
- `C:\Users\Lenovo\.workbuddy-ai\MEMORY.md`（新增「工程要求」节，所有项目通用）
- `<repo>\.workbuddy-ai\memory\MEMORY.md`（五条硬约束改为指针，去重）
- `<repo>\notes\`（复活，52 文件）

VALIDATION-SUMMARY: `run.py --check` **11/11**；本地回归 **11/11 exit 0**；
4 个需服务的检查 exit 1，**原因均为 8060 无服务**，已定位与本次改动无关。

COMMAND-EVIDENCE: 明细见下

- `python run.py --check` → `结果: 全部通过`
  ```
  [1] 78 个文件全部合规，最长 tools/smoke_test.py = 363 行
  [2] 未发现反向依赖，9 个包按 L0–L6 分层
  [3] 9 个模块配置全部可读
  [4] 未发现配置之间的相互引用
  [5] 37 个关键配置项齐备
  [6] 档位 ±18 → 73 条行情（自设上限 92，IBKR 上限 100）
  [7] 137 处取键调用全部落在其声明的配置文件里
  [8] 所有 __slots__ 类都未出现未声明的实例属性
  [9] 顶层公开类均不超过 2 个（豁免: contracts, tools）；__init__.py 只做导出
  [10] 未发现模块级硬编码常量（显式例外 9 条）
  [11] 桶 45 条 / 1s = 45 条/s（官方上限 50；qualify 单批 40 条；订阅节奏 20 条/s）
  ```
  ⚠️ 注意 **[9]/[10] 的豁免列表里仍有 `tools`，但没有 `simulator`** ——
  说明登记项清理生效。
- 本地回归（全部 `exit 0`）：
  - `python tools/smoke_test.py` → exit 0
  - `python tools/check_clock_protocol.py` → `结果: 全部通过`
  - `python tools/check_side_flip.py` → `[ok] 首个有值列之后无空洞（78 列全有值）`
  - `python tools/check_subscription_qualify.py` → exit 0
  - `python tools/check_tick_router.py` → exit 0
  - `python tools/check_session_rollover.py` → exit 0
  - `python tools/check_matrix_codec.py` → `[ok] Python 自洽（pack→unpack 还原）10 例`
  - `python tools/check_period_aggregation.py` → `结果: 全部通过`
  - `python tools/check_reconnect_gap.py` → `结果: 全部通过`
  - `python tools/check_persistence.py` → `结果: 4/4 通过`
  - `python tools/check_reconnect_flow.py` → `结果: 6/6 通过`
- 需服务（全部 `exit 1`，原因已定位）：
  - `python tools/check_web_contract.py` → §[1] DOM id（JS 引用 21 / HTML 定义 26）
    **ok**；§[2] CFG 路径（JS 引用 30 条）**ok**；
    §[3] `无法连接 ws://127.0.0.1:8060/ws  Cannot connect to host 127.0.0.1:8060`
    → **失败点仅在活连接，与硬切无关**
  - `python tools/check_page_render.py` → `结果: 存在失败项`（需活服务）
  - `python tools/check_ws_compression.py` → `ConnectionRefusedError: [WinError 10061]`
  - `python tools/ws_probe.py` → 需活服务（本次未跑）
- 规模证据：`git diff --stat` = **18 files changed, 186 insertions(+), 814 deletions(-)**；
  另有 2 个未跟踪项（`notes/`、`tools/fixtures.py`）。
- 行数证据：`app/pipeline.py` **341** 行；`tools/fixtures.py` **188** 行；
  `run.py` **63** 行；被删的 4 个模拟盘文件合计 **582** 行。

ACCEPTANCE-BUNDLE: N/A:该仓库无 acceptance bundle 机制
ACCEPTANCE-MODE: N/A:同上
ACCEPTANCE-RESULT: N/A:同上
ACCEPTANCE-EVIDENCE: N/A:同上

HARNESS-IMPROVEMENT: 本会话产出一条可复用的硬切方法论，值得沉淀：

1. **"删目录"必须与"删检查器登记项"同轮完成。** `LAYER_OF` / `REQUIRED_KEYS` /
   `EXEMPT_CONSTANTS` 里残留的条目**不会报错** —— 检查 [2] 只会静默少查一层。
   这类"半删状态"比彻底删错更危险，因为它绿着。
2. **删掉测试依赖前，先抽确定性内核。** 硬切最容易的失误是"连回归一起删"。
   正确顺序是：先抽出夹具（`tools/fixtures.py`）→ 改写回归 → 再删源。
   而且抽出来的夹具**往往比原实现更确定**（`FakeClock` 零 `monotonic()`）。
3. **`tools/` 的豁免范围要实测确认，不能假设。** 实测结论：`tools/` 豁免
   [2] 分层 / [9] 单一职能 / [10] 硬编码，**不豁免 [1] 行数与 [8] `__slots__`**
   —— 直接决定 `fixtures.py` 必须 < 400 行。
4. **记录体系拓扑确立**（跨项目可复用）：跨项目工程要求 → 用户级 `MEMORY.md`；
   项目检查器映射 → 项目级 `MEMORY.md`（指针，不复述条文）；
   当天做了什么 → `notes/sessions/...`；操作手法 → skill。**同一事实只写一处。**

NOTES-PATHS: 8 个文件（会话根 5 件 + 上下文索引 3 件），明细见下
- `notes/sessions/2026-09-13/simulator-hard-cut/startup.md`
- `notes/sessions/2026-09-13/simulator-hard-cut/project_state.md`
- `notes/sessions/2026-09-13/simulator-hard-cut/open_tasks.md`
- `notes/sessions/2026-09-13/simulator-hard-cut/handoff.md`
- `notes/sessions/2026-09-13/simulator-hard-cut/meta.yaml`
- `notes/context/project_state.md`
- `notes/context/open_tasks.md`
- `notes/context/handoff.md`

OPEN-RISKS: 5 条，明细见下
1. **改动未提交（高）** —— 工作树 18 文件 +186/−814 加 2 个未跟踪项，HEAD 仍是
   `3eeb55b`。**待 KAI 指示是否提交并推送 `origin/main`。**
2. **硬切后未跑实盘（中）** —— 系统现在只剩实盘路径，而本轮**未起 IB Gateway**。
   "删掉模拟盘之后实盘是否仍正常出图"尚未验证。
3. **4 个需服务的检查未跑通（中）** —— 本机 8060 无服务。已定位与本次改动无关，
   但"无关"是**推理 + 部分证据**（`check_web_contract` §[1]/§[2] 通过），
   不是完整反证。
4. **`tools/fixtures.py` 里的 `SyntheticSurface` 是简化曲面（低）** ——
   它只保证确定性，不保证与真实 IV 曲面同形。依赖它的
   `check_side_flip` 只验"首个有值列之后无空洞"这类结构性事实，
   不依赖曲面保真度；但后续若有人拿它做数值断言，会得到与实盘不符的结论。
5. **本机无 `tzdata`（低）** —— 3 个解释器都没有，必须用隔离 venv
   （`C:/Users/Lenovo/.workbuddy-ai/binaries/python/envs/default`），
   否则 `SimClock` 类的时间构造抛 `ZoneInfoNotFoundError`。

FAST-FAIL-CHECK: 通过 —— 背压仍是 fail-closed（每客户端 `Queue(maxsize=1)`、
`put_nowait` 丢最旧、生产者从不 await）；本会话未改动该路径。删除模拟盘后
**不存在"连不上就退回模拟源"的降级路径**，实盘连不上就是 `ConnectionFailed`
（fail-closed）。
NO-COMPAT-BRANCH: 通过 —— 本会话正是**反向的**：删除所有兼容分支。
未保留任何"兼容旧 `--sim` 调用"的 shim，未保留"`FeedMode.SIM` 标记废弃"的过渡值，
未保留"`simulator` 包但内容为空"的占位。**硬切 = 直接删。**
NO-ROLLBACK-PATH: 通过 —— 未新增回滚路径。备份（`simulator_removed_20260913/`）
刻意放在**仓库之外**，是灾备副本而非运行时回滚开关。
NO-PATCH-BANDAGE: 通过 —— 四处关键选择都是"改对地方"：
(i) 离线回归的修法是**抽出确定性夹具**（`tools/fixtures.py`），而不是在回归里
写 `try: import simulator except ImportError: skip` 让它静默跳过；
(ii) 自检登记项的修法是**同轮删除**，而不是留着死条目等下次报错；
(iii) `run.py` 的修法是**删掉两个开关**，而不是把 `--sim` 改成报错提示；
(iv) `FeedPort.set_reconnect_hook` 的 no-op 实现随 `synthetic_feed.py` 一起消失后，
**协议方法本身保留** —— 单实现也留协议，否则换数据源会造成反向依赖。
NO-FALLBACK-BEHAVIOR: 通过（产品行为）—— 未新增静默降级。删除模拟盘后
系统**少了一条降级路径**，不是多了一条。

---

**本会话第二部分（记录体系）的对应标记：**

NO-FALLBACK-BEHAVIOR（工具）: 通过 —— 放宽 skill 验证流程时，**没有**把它改成
"永远不校验"。改为"跑该仓库真实提供的检查；确实没有可跑的才写
`N/A:<reason>` 并点名残余风险"。这是**降低仪式感**，不是**取消证据**。
NO-PATCH-BANDAGE（记忆）: 通过 —— 工程要求去重是**改归属**（提升到用户级），
不是"在项目级删掉但在用户级复述"；项目级留的是**指针**。
