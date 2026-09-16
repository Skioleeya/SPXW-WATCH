# Handoff — gate-tools-rewrite

TASK-ID: gate-tools-rewrite
DATE: 2026-09-15
TIER: T2
STATUS: complete
CHANGE-ID: N/A:项目未使用 OpenSpec

STARTUP-PROOF: N/A:本会话是 `rebuild-from-original` 的续作，接手时基线
（`run.py --check` 覆盖 **5/16**）由上一会话
`notes/sessions/2026-09-15/rebuild-from-original/handoff.md` 记录；
本会话动手前未另行捕获基线快照（`startup.md` 因此省略，属如实结果而非失败）。

## 来源：KAI 两条明令

> **1. 必须重写，禁止移植失败品**
> **2. README.md 必须重写**
> **3 和 4 待定**

⇒ 本会话范围 = **`#15 tools/` 门禁剩余 11 项** + **`README.md`**。
⇒ **明确不做**：在线验证、曲面残差无方向字段（KAI 明示待定）。

**为什么"重写"而不是"移植"**：旧项目 `tools/` 的 43 个文件在 `HEAD` 里完好，
但**层号口径不同** —— 旧 `serialization` = **L4**、新 = **L6**（新架构是 9 层，
`contracts` = L0）。机械字符串替换必然产生口径错配的"移植失败品"，
故 16 项**全部按新架构重写，未从 `HEAD` 移植一行**。

## CHANGED-PATHS

### tools/ —— 门禁重写（5 新建 / 8 改写）

新建：

- `tools/selfcheck_clock.py` —— [12] 时钟协议与裁剪路径
- `tools/selfcheck_router.py` —— [14] TickRouter 语义（32 条判据）
- `tools/selfcheck_connectivity.py` —— [13] 帧契约一致性 + 活链路
- `tools/selfcheck_reads.py` —— 键转发器追踪（两遍 AST 扫描）
- `tools/selfcheck_config_invariants.py` —— [6][11]
- `tools/selfcheck_code.py` —— [8][10]
- `tools/fixtures.py` —— `[12][13][14]` 共用的离线替身（改写）

改写：

- `tools/selfcheck.py` —— 编排器 **5 → 16 项**；`--selftest` 判据升级
- `tools/selfcheck_core.py` —— 移出 `const_strings` / `ReadSite` / `collect_reads`
- `tools/selfcheck_structure.py` —— [1][2][2b]
- `tools/selfcheck_duty.py` —— [9][9b]
- `tools/selfcheck_config.py` —— [3][4][5][7]
- `tools/check_web_contract.py` —— 随 `web/` 契约更新

### 配置 —— 删除真死键 + 注释标注"待建"

- `config/transport.json` —— **删 `bucket_seconds_s` 键**（真死键）；注释改写为
  `_push_comment`，明写"**不对齐是刻意的**"
- `config/serialization.json` —— 3 处注释标注引用的检查器"**待建**"
- `config/subscription.json` —— 1 处同上
- `config/app.json` / `features.json` / `logging.json` / `persistence.json` /
  `pipeline.json` / `spot.json` / `state.json` / `loader.py` / `__init__.py` —— 随重写更新

### 文档

- `README.md` —— **按 9 层新架构重写**（10 节）
- `notes/memory/ARCHITECTURE.md` —— **§16 整体重写**（5/16 → 16/16）；
  §4 / §5 / §8 / §9 / §10 同步过期内容
- `notes/context/open_tasks.md` —— `#15` 与 `README.md` 两条标记完成
- `notes/context/{handoff,project_state}.md`、`notes/memory/{QUICKREF,RULES,TROUBLESHOOTING}.md`
  —— 随重写更新

### 一次性探针

- `tmp/l2l3_smoke.py` —— 修 `serial_cfg` 未声明（本轮删了 `transport_cfg::bucket_seconds_s`
  后该探针的引用悬空，`NameError`）；取键来源改到 `serialization.json::heatmap_bucket_seconds`

### 清空的旧工具（重写前清理，非本会话新增）

`tools/` 下 43 个来自 `HEAD` 的旧文件已删（`D`），含
`check_clock_protocol` / `check_matrix_codec` / `check_tick_router` / `ws_probe` /
`group_guard` / `period_reference` / `skew_reference` 等 —— 它们是 6 层口径的产物。

## COMMAND-EVIDENCE

```text
$ venv/Scripts/python.exe run.py --check
  [1]  文件长度（上限 400 行，严格小于）
      [warn] acquisition/ibkr_gateway.py = 399 行，距上限只剩 1 行
      [warn] features/persistence_store.py = 398 行，距上限只剩 2 行
  [3]  配置文件可读性（含 JSON 重复键）
  [6]  订阅容量、显示窗口与网格容量（IBKR 硬上限 100）
  [7]  配置键归属与接线（读取点 ↔ 声明键双向推导）—— 取键调用全部落位，无死键
  [10] 禁止硬编码
      [warn] 待接线包 models/forecasting/：RV 信号引擎已移植但**未接线**
  [13] 联通与数据通道（帧契约一致性 + 活链路）
      [ok]   11 个契约字段全部被编码器覆盖（含 1 处显式折叠）
      [warn] 127.0.0.1:8060 无服务，跳过活链路检查（非交易日/盘前为预期）
             —— 上面三项离线判据仍然有效
  结果: 16/16 项全部通过                                        RC=0

$ venv/Scripts/python.exe tools/selfcheck.py --selftest         RC=0（2m06s）
  [ok] 对照（未变异副本）→ 全绿
  [ok] [1]…[14] → 16 项全部已抓住
  变异自检: 16/16 项全部被抓到（且每一条都验的是**目标检查项自己**报了 FAIL）

$ venv/Scripts/python.exe tmp/l2l3_smoke.py                     RC=0   PASS 37 / FAIL 0
$ venv/Scripts/python.exe tmp/l5_smoke.py                       RC=0   PASS 32 / FAIL 0（20s）
$ venv/Scripts/python.exe tmp/l6_smoke.py                       RC=0   PASS 39 / FAIL 0
$ venv/Scripts/python.exe tmp/l8_smoke.py                       RC=0   PASS 30 / FAIL 0
$ venv/Scripts/python.exe tmp/web_e2e.py                        RC=0   PASS 34 / FAIL 0
$ venv/Scripts/python.exe tools/check_web_contract.py --offline --selftest
  变异自检：DOM id 对照 → 已抓住 / CFG 路径对照 → 已抓住            RC=0

$ for n in check_matrix_codec check_reconnect_gap check_session_grid \
        check_surface_payload check_window_tolerance check_ws_compression \
        check_period_aggregation ws_probe; do find . -name "$n.py" ...; done
  ⇒ **8 个检查器全部不存在**（`venv/` 已排除）

$ venv/Scripts/python.exe -c "json.load(...)"   # 三个改过的配置
  config/serialization.json OK 18 keys / config/subscription.json OK 12 keys
  / config/transport.json OK 15 keys
```

## VALIDATION-SUMMARY

- `run.py --check` → `exit 0`（16/16）
- `tools/selfcheck.py --selftest` → `exit 0`（16/16 变异全抓）
- 四个冒烟 + web 对拍 → 全部 `exit 0`（37 + 32 + 39 + 30 + 34 = **172 条判据**）
- `check_web_contract --offline --selftest` → `exit 0`
- 配置 JSON 合法性 → 3/3 OK（改注释后复跑 `--check` 仍 16/16）

## NOTES-PATHS

- `notes/sessions/2026-09-15/gate-tools-rewrite/handoff.md`（本文件）
- `notes/sessions/2026-09-15/gate-tools-rewrite/project_state.md`
- `notes/memory/ARCHITECTURE.md` §16（重写）
- `notes/context/open_tasks.md`（#15 / README 条目）

## Closed in session

- **`#15 tools/` 门禁：覆盖 5/16 → 16/16**，`--check` RC=0，
  `--selftest` 16/16 变异全抓。
- **`README.md` 重写完成**（9 层架构 / 10 节 / 检查器状态表 + "设计意图非既成事实"警告）。
- **删除真死键 `config/transport.json::bucket_seconds_s`**（及其描述不存在机制的注释）。
- **配置注释里 6 处引用不存在的检查器 → 逐条标注"待建"**。
- **修 `tmp/l2l3_smoke.py` 的 `NameError`**（上一轮改取键来源时漏声明 `serial_cfg`）。
- 全量复扫取证完成（172 条冒烟判据 + 门禁 + 变异自检并列 RC）。

## OPEN-RISKS

- ⚠️ **`tools/` 下 8 个独立检查器仍待建**（不在 `--check` 里）：
  `check_matrix_codec` / `check_grid_contract` / `check_period_aggregation` /
  `check_session_grid` / `check_surface_payload` / `check_reconnect_gap` /
  `check_window_tolerance` / `check_ws_compression` / `ws_probe`。
  **`check_grid_contract.py` 尚未建 = 当前最大的门禁缺口** ——
  "网格单元 = 已走满的桶"这条核心契约目前只由 `tmp/l5_smoke.py` 的**一次性探针**守着。
  状态表见 `README.md §6`。
- ⚠️ **`check_grid_contract.py` 不得断言"没有 `g == 1` 短路"** ——
  `g=1` 时短路路径与聚合路径**数值恒等**（实测 120 格全等、误差 0），
  断言它会把正确代码判违规。详见 `ARCHITECTURE.md §15.2`。
- ⚠️ **`tools/` 里 3 个文件余量告急**：`acquisition/ibkr_gateway.py` = 399 行（余 1）、
  `features/persistence_store.py` = 398 行（余 2）。再补两行注释就违规。
- ⚠️ **工作区脏态大**（`git status --short` = 133 项，含 43 个 `D`）—— **未提交**。
  `notes/context/*` 与 `tools/` 的改动全部悬在工作区。
- ⚠️ **本会话未做在线验证**（KAI 明示待定）：`[13]` 的活链路项在无服务时
  `warn` 跳过（离线三项照跑）。L2/L3 的真实链路（`IbkrFeed` 连 Gateway /
  300 退避 / 区段切换 / 窗口重建）**仍只有离线冒烟**。
- ⚠️ **曲面残差逐 reqId、同 strike 出两条、契约无方向字段**（KAI 明示待定）——
  详见 `notes/context/open_tasks.md`。

## HARNESS-IMPROVEMENT

本轮沉淀两条**判据级**教训（已写进 `ARCHITECTURE.md §16.3 / §16.6`）：

1. **"目标检查项自己报了 FAIL" ≠ "退出码非 0"** —— 后者下任一无关项变红就会让
   "抓住了"的结论变成**假绿**。配套要求：段落标题必须打在 `run_*_checks()` 里，
   只在 `main()` 里打会让段落切分失败 ⇒ **恒判为"抓住"（判据恒真 = 空转）**。
2. **"变异无效"与"判据空转"必须分得清** —— 前者是测试代码的 bug（如
   `return None` → `continue` 而后续槽位本就为空 ⇒ 行为等价），后者是被测判据的
   bug，修的地方完全不同。

## NO-FALLBACK-BEHAVIOR / NO-PATCH-BANDAGE

`N/A:本会话只改门禁与注释，未改运行时行为；未引入兼容分支或补丁式绕过。`
