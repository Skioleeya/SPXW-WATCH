# Handoff — persistence-session-identity

```text
TASK-ID: persistence-session-identity
DATE: 2026-09-15
TIER: T2
STATUS: complete
CHANGE-ID: N/A:本项目无 OpenSpec change 流程
```

STARTUP-PROOF: `notes/sessions/2026-09-15/persistence-session-identity/startup.md`
（含改动前 00:27–00:33 EDT 的逐条读数；改动前的 `run.py --check` 基线 N/A:未捕获）

## 一句话

**启动成功**；核验时挖出**跨会话持久化污染**（帧把昨天 14:26:48 的 Skew 点当"最新"、
热力图把昨天 RTH 的数据画在今天 GTH 的时刻上），根因是持久化表**没有会话身份**。
已做结构性修复：会话身份进主键 + 恢复按会话过滤 + 旧表一次性丢弃（可数）+ 新增回归。

## CHANGED-PATHS

```text
 M features/persistence.py          表结构 session_key、recover/recover_skew 按会话过滤、旧表迁移、空身份拒绝
 M features/feature_engine.py       _persist_current_bucket 带会话身份（无身份则不写）
 M app/pipeline.py                  恢复传 self._clock.expiry_str()；迁移丢弃数进 WARNING 日志
 M tools/check_persistence.py       8 组回归（新增跨会话隔离 / 旧表迁移 / 空身份拒绝）
 M tools/check_session_grid.py      修"交易日推导"用例隐含"锚点必须是周一"的夹具缺陷（399 行）
 M README.md                        §5 持久化设计补"每行都带会话身份"一节
 M notes/context/open_tasks.md      关闭 Active#1（根因已修）
 M notes/context/handoff.md         指向本会话
 M .workbuddy-ai/memory/2026-09-15.md 当日工作日志
 M .workbuddy-ai/memory/MEMORY.md      新增速查卡 T（持久化会话身份）、收紧 K 的残留表述（7698/8000 字符）
 A notes/sessions/2026-09-15/persistence-session-identity/{startup,project_state,handoff}.md
```

仓库**之外**（用户级 skill，不在本项目版本控制内）：

```text
 M ~/.workbuddy-ai/skills/spxw-live-verify/SKILL.md               §1 补"必须用 run_in_background，不要用 start_detached.py"；Top 5 → Top 6；条数 16 → 17
 M ~/.workbuddy-ai/skills/spxw-live-verify/references/pitfalls.md §11.2 补 netstat 取 PID 的省事路径；§11.4 补新日志行；新增第 17 条
```

NOTES-PATHS: `notes/sessions/2026-09-15/persistence-session-identity/{startup,project_state,handoff}.md`、
`notes/context/{open_tasks,handoff}.md`、`.workbuddy-ai/memory/{2026-09-15.md,MEMORY.md}`

临时探针（`tmp/` 已 gitignore，用完即弃）：`probe_skew_detail.py`、`probe_col_ranges.py`、
`probe_mutation_cross_session.py`。

## VALIDATION-SUMMARY

- `run.py --check` → `RC=0`
- `tools/check_persistence.py` → `8/8 通过`
- `tmp/probe_mutation_cross_session.py` → 非空转成立（跨会话用例被抓）
- `tools/ws_probe.py --frames 8`（修复前 → 修复后）→ `26/27` → **`25/25`**
- SQLite `pragma integrity_check` → `ok`
- 全量回归扫描（21 个 `tools/check_*.py`，venv 解释器）→ **20 `RC=0` / 1 `RC=1`**
  （唯一红 = `check_page_render`，既有缺陷）
- `tmp/probe_session_grid_dow.py` / `tmp/probe_mutation_trading_day.py` → 夹具缺陷定性 + 非空转成立

## COMMAND-EVIDENCE

修复前（00:27–00:33 EDT，详见 `startup.md`）：

- `tools/ws_probe.py --frames 8` → `26/27`；FAIL = `25Δ Put 行权价低于现价 7626.51 < 7605.41`
- 帧 `skew.latest.ts` = `2026-09-14T14:26:48`（昨天）；`skew.series.count` = `915`、bucket `0..2183`
- `sqlite3` 直读：`heatmap_buckets` / `skew_points` 各 915 行，日期分布
  `{09-13: 3, 09-14: 906, 09-15: 6}`；两表列中**无会话列**

修复后（00:38+ EDT）：

- `venv/Scripts/python.exe run.py --check` → `RC=0`（`[1]`–`[14]` 全通过）
- `tools/check_persistence.py` → `8/8 通过`
- 重启日志 → `00:38:46 WARNING 丢弃 1830 行无会话身份的旧持久化数据`；
  **不再出现** `已从 SQLite 恢复 N 个历史桶`（新表里本会话无数据）
- `tools/ws_probe.py --frames 8` → **全部通过**；
  `25Δ Put 行权价低于现价 7567.52 < 7603.93` / `25Δ Call 行权价高于现价 7631.84 > 7603.93`
  （7567.52 与按 `cells` 逐档 delta 插值算出的 ≈7569 一致 ⇒ **delta 定位一直是对的**，
  坏的只是那个陈旧点）
- 帧：`skew.series.count = 5`、bucket `527..531`、ts `00:38:59 → 00:40:57`、
  `skew.latest.ts = 2026-09-15T00:40:30`（**今天**）
- 截图对照：`tmp/startup_panel_20260915_0030.png`（108,869 B，含左侧假 0 带 + 右侧昨天数据）
  → `tmp/fixed_panel_0041.png`（79,531 B，只剩重启后的最新几列，
  **20:15–20:35 假 0 带一并消失**）
- 停服前 `pragma integrity_check` = `ok`、`journal_mode` = `delete`、两表各 915 行未变
  （硬杀安全性复核通过）
- 文件行数：`features/persistence.py` 384 / `tools/check_persistence.py` 373 /
  `app/pipeline.py` 362 / `features/feature_engine.py` 364 / `tools/check_session_grid.py` 399
  —— 全部 < 400
  ⚠️ 修 `check_session_grid` 时第一版注释把文件撑到 **402 行**，被 `run.py --check [1]`
  **当场抓红**（`[FAIL] tools/check_session_grid.py 共 402 行，超出上限`）——
  门禁有效，非空转。收紧注释到 399 行后 `RC=0`。

### 第二个缺陷：`check_session_grid` 的"交易日推导"用例隐含"锚点必须是周一"

全量扫描时发现它 **4 红**，且**不在任何既有失败清单里**。定性过程：

- 失败项全部是"交易日推导"的周末用例，形如
  `周日白天（网格之外） → 2026-09-15  2026-09-14`（期望 vs 实际）。
- 夹具用 `monday`（= `clock.trading_day()`，**今天**）作锚点，再按
  `friday/saturday/sunday = monday - 3/2/1 天` 推星期。
  今天 2026-09-15 是**周二** ⇒ 派生出的三个"周末"实际是 **Sat / Sun / Mon**
  （`tmp/probe_session_grid_dow.py` 打印）。
- **决定性验证**：同一套 27 条判据 —— 锚点取今天（周二）→ **4 红**；
  锚点取真正的周一（2026-09-14）→ **0 红**。
- ⇒ **日期驱动的夹具缺陷**：只在周一通过。判据本身没问题，`trading_day()` 也
  没问题（活进程日志 `到期 20260915` 正确）。
- 修法（3 行）：`_trading_day_checks()` 开头把锚点归一到周一
  `monday -= timedelta(days=monday.weekday())`。
- 非空转：`tmp/probe_mutation_trading_day.py` 把产品侧 `trading_day()` 换成
  "直接返回日历日" ⇒ 该组抓 **5 条**；还原后 0 红。
  `--selftest` 3/3 变异仍全抓 ⇒ **没有削弱门禁**。

- 全量回归 **20 `RC=0` / 1 `RC=1`**；唯一红 `check_page_render`（既有：断言
  "有且仅有一个周期处于选中态"把会话按钮与周期按钮收成一组，恒不成立 +
  虚拟时间窗口漂移）。**本轮未动它**。

## Closed in session

- **`tools/check_session_grid.py` 的"交易日推导"用例隐含"锚点必须是周一"** ——
  修掉（锚点归一到周一）。这是**日期驱动的假红**：只在周一通过，
  其余六天报 4 条"看着像产品坏了"的失败。定性证据与非空转见上。
- `notes/context/open_tasks.md` Active#1「**假 0 带残留：bucket 0 本身仍被恢复**」——
  **关闭**。它登记的根因（`recover()` 读全部行、无过滤）就是本轮的修复对象；
  旧表丢弃后假 0 带一并消失（截图对照）。
  ⚠️ 但**只关了它写下的那一条**：另一条"`recover()` 只取最后一段连续桶"的彻底方案
  **KAI 本轮未选**（见下 OPEN-RISKS）。

## OPEN-RISKS

- **`notes/context/*` 与 `web/config.js` 含另一会话未提交的改动**，
  以及未跟踪的 `notes/sessions/2026-09-14/live-render-verify/`。
  本轮**未替它背书、未纳入**；索引指向本会话的同时，那批改动仍在工作区。
- **`recover()` 仍不做"只取最后一段连续桶"**（KAI 未选）。会话身份修好之后这条
  已**不再是错值来源**（别的交易日的行读不进来），只剩"同一会话内孤桶被前向填充
  沿用 ≤ `heatmap_max_ffill_buckets`(20) 桶"这一个形状 —— 由既有
  `check_reconnect_gap.py::case_long_gap_is_blanked` 守着。
- **本轮全部改动未提交**（`HEAD = 9ec4fb9`）。`data/session.db` 的旧行已由代码迁移丢弃，
  不可逆（已核算：丢的是跨三个自然日的 1830 行，其中今天的部分只有 ~25 桶）。
- **前端未验证渲染正确性**：截图只做了肉眼对照（面板不再有未来的线、右侧块消失）。
  前端是空壳、本轮未改，未跑 `check_page_render`（该检查默认 budget 下必失败，
  属既有缺陷）。
- 底栏一条 `WARN ibkr: 11587 Sec-def data farm connection is broken:secdefhk`
  （香港 sec-def 农场，早期出现、已滑出最近 6 条消息窗口）。**未定性为缺陷**：
  美股侧正常（744 个行权价 qualify 成功、80/92 订阅在位、`last_tick_age_s = 0.1`、
  日志零错误码）。按项目既有纪律，香港农场不作为判据。
- **服务是用 Bash 工具的 `run_in_background=true` 起的，不是 `tools/start_detached.py`。**
  本轮实测它跨 10+ 次工具调用持续存活（`frames` 646 → 932 单调增长）。
  ⚠️ **但它能否活过"本轮对话结束"未验证** —— 若下次探 8060 发现服务已停，
  正确做法是 KAI 在**自己的终端**跑 `venv/Scripts/python.exe tools/start_detached.py`
  （该工具就是为脱离 WorkBuddy 进程树设计的）。
