TASK-ID: recheck-keyorder-memory
DATE: 2026-09-13
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change（KAI 直接指派）
STARTUP-PROOF: 见 `startup.md`（基线读数采集于任何编辑之前）

# Handoff — recheck-keyorder-memory

## Scope Understanding

见 `startup.md::## Scope Understanding`。一句话：**复核上一轮交接 + 收尾**
（重建丢失的定时任务、冷数据键序统一降序、`MEMORY.md` 蒸馏、补记录缺口、提交）。

## 复核结论：上一轮报告属实，另有一处静默失效

逐条复核 `skew-period-consistency` 的终态报告，**七条全部对上**（见
`COMMAND-EVIDENCE`）。**唯一新发现**：报告与 `open_tasks.md` 都记着"已设一次性
定时任务 `e4ad7495-…`（2026-09-14 09:45 ET）"，但该任务**不存在** ——
`automation list`（全局与按 cwd）均为空、`view` 报 not found ⇒
"开盘后补验收"当时**没有任何触发点**。已按原时间重建。

顺带修正一处记录精度：`project_state.md` 写"`serialization/` 3 文件"，
git 实际只有 2 个（`frame_encoder.py` / `skew_series.py`）。

CHANGED-PATHS:
- `features/heatmap_engine.py` — `dump_bucket()` 的 `sorted(self._buckets)` →
  `sorted(self._buckets, reverse=True)`；docstring 增一节"为什么是降序（2026-09-13
  统一）"。299 → 307 行。
- `tools/check_persistence.py` — `_case_key_order_ascending` →
  `_case_key_order_descending`（四条断言全部翻向：内存 / 落盘 / `recover` /
  `load_snapshot`）；模块 docstring 第 6 条改写。
- `README.md` — §5 旁路持久化加一句：落盘 `ivs` 键序为降序、与帧 `strikes` 同向。
- `.workbuddy-ai/memory/MEMORY.md`（**不在 git 跟踪内**）— 按主题蒸馏
  （7958 → 7445 字符）+ 新增"冷数据键序 = 降序"。
- `notes/context/handoff.md` · `open_tasks.md` · `project_state.md` — 索引与当前态。
- `notes/sessions/2026-09-13/skew-period-consistency/handoff.md` — **补记**
  `tools/check_page_render.py` 到 `CHANGED-PATHS`（该改动发生在原 handoff 写完之后，
  KAI 本轮批准补写）。
- `notes/sessions/2026-09-13/recheck-keyorder-memory/` — 本会话记录（三件套）。

⚠️ **同一次提交里还带着上一会话（`skew-period-consistency`）的未提交改动**：
`web/app.js` · `web/period.js` · `web/skew.js` · `serialization/frame_encoder.py` ·
`serialization/skew_series.py` · `config/serialization.json` ·
`tools/check_page_render.py` · `tools/check_web_contract.py` ·
`tools/selfcheck_core.py` · `README.md`，以及三个新工具
（`tools/check_web_syntax.py` · `tools/check_skew_alignment.py` ·
`tools/skew_reference.py`）。两者分不开（同一工作区连续作业），故一并提交。

VALIDATION-SUMMARY:
- `python run.py --check` → `rc=0`（11/11）
- `python tools/check_persistence.py` → 5/5，`rc=0`
- 键序回归**双向非空转证伪**：不排序 / 退回旧升序 → 均 `[FAIL] dump_bucket 未降序`、
  `EXIT=1`；还原后 `rc=0`
- 12 个本地回归批量 → 全部 `rc=0`（含两个新门禁）
- `node --check web/*.js` → 7/7 OK
- `MEMORY.md` 字符数 → 7445/8000（余量 555）
- 4 个需服务的检查 + `check_reconnect_flow` → `N/A:周日无当日到期服务 fail-closed；
  本机缺 aiohttp / ib_async`
- 定时任务重建 → `automation view` 返回 ACTIVE，`nextRunAt` = 2026-09-14 09:45 ET

COMMAND-EVIDENCE:

`[recheck]` 上一轮七条断言的复核（只读）：

```
node --check web/*.js            → 7/7 OK
python run.py --check            → 全部通过（取键调用 138 处）
check_web_syntax --selftest      → 7/7 变异全抓
check_skew_alignment --selftest  → 4/4 变异全抓
grep skew_min|skew_max           → 只剩 skew_min_points（25Δ 插值点数），非残留
len(MEMORY.md) = 7958            （wc -c 给 12587 是**字节**数，不能比 8000）
grep SENTINELS check_page_render → 4 个哨兵 + missing_sentinels，已落地
```

`[recheck]` 定时任务（**本轮的实质发现**）：

```
automation list                  → automations: []
automation list cwds=<工程目录>   → automations: []
automation view e4ad7495-…       → not found
```

`[post]` 键序改动的非空转证伪（工程外探针，`python -c` 内联、不落文件）：

```
变异 A 完全不排序     → [FAIL] dump_bucket 未降序: [5500, 5505, 5510, 5490, 5485]
变异 B 退回旧升序     → [FAIL] dump_bucket 未降序: [5485, 5490, 5500, 5505, 5510]
变异 B 真实 EXIT=1；还原后 EXIT=0
```

⇒ 两条变异**方向相反**却都被抓住，说明断言真的在区分方向，不是"排了序就算过"。

`[post]` 12 个本地回归：`check_clock_protocol` / `check_matrix_codec` /
`check_period_aggregation` / `check_persistence` / `check_reconnect_gap` /
`check_session_rollover` / `check_side_flip` / `check_subscription_qualify` /
`check_tick_router` / `check_web_syntax` / `check_skew_alignment` / `smoke_test`
→ 逐个 `rc=0`。

`[post]` 行数：`features/heatmap_engine.py` 307/400、`tools/check_persistence.py`
239/400 —— 均未越界。

NO-PATCH-BANDAGE: 键序统一改在**产出点**（`dump_bucket`），不在 `recover()` /
`load_snapshot()` 侧重排 —— 读侧重排等于"写侧一个方向、读侧再翻一次"的第二处真相。

NO-FALLBACK-BEHAVIOR: 无。`dump_bucket` 不提供"要不要排序"的开关，也不嗅探
`_buckets` 现有键序；方向是硬编码的契约，由回归守着。

NO-COMPAT-BRANCH: 无。不写"旧升序库也能读"的分支 —— `load_snapshot()` 收的是
dict，键序对它本就无意义；真正依赖方向的是**直接读 `session.db` 的人**，
用文档 + 回归把方向钉死，比加兼容分支干净。

HARNESS-IMPROVEMENT: 无新增门禁（本轮只把既有回归的方向翻正）。
**但记一条工具外的教训**：`automation view` 是本轮唯一能发现"记录说已设、
系统里没有"的手段 —— 凡"已设 / 已开 / 已生效"这类状态，判据是去系统读一次，
不是读记录。（与 `check_page_render` 假通过同族。）

NOTES-PATHS:
- `notes/sessions/2026-09-13/recheck-keyorder-memory/handoff.md`（本文件）
- `notes/sessions/2026-09-13/recheck-keyorder-memory/startup.md`
- `notes/sessions/2026-09-13/recheck-keyorder-memory/project_state.md`
- `notes/context/handoff.md` · `project_state.md` · `open_tasks.md`
- `notes/sessions/2026-09-13/skew-period-consistency/handoff.md`（补记一行）

## Closed in session

- **复核通过**：上一轮 `skew-period-consistency` 的终态报告**无虚假断言**；
  它自报"未验证"的三项（真实链路渲染、4 个需服务的检查、`3600s` 未校准）
  本轮同样无法推翻 —— 周日服务起不来，如实保留。
- **定时任务已重建**（`8b4fe600-261f-4ab8-9930-217dbf6b9eef`，2026-09-14 09:45 ET，
  prompt 自包含）—— 补上了"开盘后补验收"缺失的触发点。
- **冷数据键序统一为降序**（KAI 选定），与帧 `strikes` 同向；产出点 + 回归同时翻向，
  双向证伪通过。
- **`MEMORY.md` 蒸馏完成**：7958 → 7445 字符（余量 42 → 555），移出的内容全部
  已有载体（README §6 / `memory/2026-09-11.md` / skill `spxw-live-verify`）。
- **记录缺口已补**：`tools/check_page_render.py` 记入上一会话的 `CHANGED-PATHS`。
- **未提交改动已提交并推送 `792e4a3`**（33 文件，+3967/−97，含上一会话累积的
  `web/` 3 文件、两个新门禁与 P0 修复）；远端已核实 `git ls-remote` == 本地 HEAD。

OPEN-RISKS:
- **真实链路渲染仍未验证**（两个会话累计改了 3 个前端文件，**没有一张真实链路
  截图**）。周日无当日 SPXW 到期 ⇒ 服务 fail-closed；已重建定时任务指向
  2026-09-14 盘中补跑 `check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`，并肉眼确认两块图横轴对齐、纵轴高行权价在上。
- **`skew_scale_window_seconds = 3600.0` 仍是经验值**，未经盘中数据校准。
- **冷数据降序只在离线回归上验过** —— `data/` 已清空，没有真实 `session.db`
  可跑；但覆盖的正是产出点本身（`dump_bucket`），落盘 / `recover` / `load_snapshot`
  三段都在用例里。
- **`check_web_contract.py` 顶层 `import aiohttp`** 仍挡住它自己第 1、2 段的独立运行
  —— KAI 本轮**未选**内移，保持原样（见 `notes/context/open_tasks.md`）。
- **本机缺 `ib_async` / `aiohttp`** ⇒ `check_reconnect_flow` 与 `check_web_contract`
  在本环境跑不了。
