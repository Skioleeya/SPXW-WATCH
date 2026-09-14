TASK-ID: subscription-window-tolerance
DATE: 2026-09-14
TIER: T2
STATUS: complete
CHANGE-ID: N/A:本仓库不走 OpenSpec
STARTUP-PROOF: N/A:改动前的基线未落 startup.md（首个写操作早于基线归档）；改动前后由 A/B 对照给出，见 COMMAND-EVIDENCE

# Handoff — subscription-window-tolerance

## 问题（KAI 报）

实盘中现价上下移动时，IV 热力图在**行权价轴**上出现时间空洞：现价持续下跌 ⇒
`+12` 档以外的 Call 拿不到数据，只有等现价反弹才恢复；Put 侧同理。

## 根因

两个窗口半径以前是**同一个数**：

| 键 | 归属 | 改前 | 改后 |
|---|---|---|---|
| `num_strikes_each_side` | `config/subscription.json`（**订阅**窗口） | 12 | **20** |
| `heatmap_rows_each_side` | `config/features.json`（**显示**窗口） | 12 | 12（不动） |

容差 = 订阅 − 显示 = **0 档**。链条：

1. `ChainResolver.centre_moved()` 按 `recenter_trigger_strikes`(3) 判定重建；
2. `feed_reconcile.WindowFollower` 重建窗口 → `cancel_stale_before_add` 让滚出的档位
   **立刻退订**；
3. 那几档在现价往返期间**收不到任何 tick**；
4. `HeatmapEngine._prune()` **只按时间裁剪、从不按行权价裁剪** ⇒ 该行不会被删，
   只在中间空一截 —— 图上就是「行权价轴上的一条时间空洞」，现价回来后空洞留在原地。

**前端是空壳、忠实渲染，错在订阅窗口没留容差。**

## 修法与判据

判据（**推导**，非拟合）：两次重建之间中心最多滞后 `T` 档 ⇒ 现价可探出已订阅窗口
`T` 档 ⇒ 要求「显示窗口最低一档 ≥ 订阅窗口最低一档」即得

```
num_strikes_each_side − heatmap_rows_each_side ≥ recenter_trigger_strikes
```

当前 `20 − 12 = 8 ≥ 3`，余量 5 档。上限仍由 `4×side+1 ≤ 92` 约束 ⇒ `side ≤ 22`。

## 顺带修掉的夹具缺陷（**这是本轮真正的坑**）

`num_strikes_each_side` 一改，`check_session_rollover` 与 `smoke_test` 双双变红。
A/B 定位到是**我改坏的**（@12 RC=0 / @20 RC=1）。根因不在产品代码，而在夹具：

`SyntheticSurface.strike_grid()` 生成的是 `-each_side … +each_side` 的**对称**阶梯，
两个回归都拿 `grid[3]` 当"现价下方第 3 档"，而它的行权价 = `现价 − (each_side−3)×步长`，
**随订阅半径漂移**：

| 订阅半径 | 阶梯 | `grid[3]` | 在显示窗口 [6445..6560] 内 |
|---|---|---|---|
| 12 | 6440..6560 | 6455 | ✅ |
| 20 | 6400..6600 | **6415** | ❌ ⇒ 该行根本不在矩阵里 ⇒ 假红 |

修法：新增 `tools/fixtures.display_window_strike()`，靶档**锚在现价上**、按**显示**半径
设界，越界直接抛错（fail-fast，而不是静默给一根窗口外的行权价）。两个回归改用它。

`tools/smoke_test.py::_status()` 里硬编码的 `subscribed=74` 也一并改为从配置推导
（`4 × each_side + 1`）—— 74 与 49 / 81 都对不上，是凭空多出来的第二份真相。

## CHANGED-PATHS

- `config/subscription.json` — `num_strikes_each_side` 12 → 20；新增 `_window_comment`
  说明两个窗口的关系与容差下限
- `tools/fixtures.py` — 新增 `display_window_strike()`
- `tools/check_session_rollover.py` — 靶档改用 `display_window_strike()`
- `tools/smoke_test.py` — 靶档改用 `display_window_strike()`；`_status()` 订阅数改派生
- `tools/selfcheck_config.py` — `[6]` 新增「容差 ≥ 重建触发」不变量
- `tools/check_window_tolerance.py` — **新增**回归（8 项，含 `T−1` / `T` 边界对照）
- `README.md` — 工具清单加新回归；`±12 档 → 49 条` 订正为 `±20 档 → 81 条`；
  新增「订阅窗口必须比显示窗口宽（容差）」一节
- `notes/memory/RULES.md` — §6.1 基线订正；§6.6 新增「配置算术不变量：静态门禁 +
  行为回归成对」+ 夹具靶档纪律
- `notes/sessions/2026-09-14/subscription-window-tolerance/` — 本会话记录

## COMMAND-EVIDENCE

靶档漂移的取证（改前）：

```
venv/Scripts/python.exe -c "...strike_grid(spot,5,side); StrikeWindow.window_strikes(...)"
  @12: grid[3]=6455  在显示窗口内? True    显示窗口 6445..6560
  @20: grid[3]=6415  在显示窗口内? False   显示窗口 6445..6560
```

A/B（隔离"是不是我改坏的"）：

| 检查 | @12 | @20 |
|---|---|---|
| `check_session_rollover` | `RC=0` | `RC=1` ← 我改坏的 |
| `smoke_test` | `RC=0` | `RC=1` ← 我改坏的 |
| `check_web_contract` | `RC=1` | `RC=1` ← 断线，与改动无关 |

修复前失败原文：

```
[FAIL] 观察行已建立  行权价 6415
[FAIL] 翻篇后仍产出矩阵
[FAIL] 尖峰被标记为 GLITCH  quality=未找到该网格点
```

故意做坏（**证明断言非空转**）：

```
变异 1  features/heatmap_engine.py:141  if cell.quality not in TRUSTWORTHY_QUALITIES → if False
        smoke_test → [FAIL] 尖峰未写入矩阵  矩阵值=128.37088757396455  RC=1
变异 2  features/feature_engine.py:337  self.reset() → 注释掉
        check_session_rollover → [FAIL] 第 1 桶不得跨会话差分  值=1.9999999999999991
                              → [FAIL] Skew 序列只含新会话的点  6 点            RC=1
（两处变异均已还原；grep MUTATION-TEST 无残留）
```

修复后：

```
venv/Scripts/python.exe tools/check_session_rollover.py   → RC=0
venv/Scripts/python.exe tools/smoke_test.py               → RC=0
venv/Scripts/python.exe tools/check_window_tolerance.py   → RC=0
venv/Scripts/python.exe run.py --check                    → [6] 三条全 ok
```

新回归 `check_window_tolerance` 的输出（含边界对照）：

```
订阅窗口 ±20 档 · 显示窗口 ±12 档 · 重建触发 3.0 档   容差 = 8 档
[ok] 容差 ≥ 重建触发步长  8 档 ≥ 3.0 档
[ok] 单边下行：无空洞  401 步 / 0 个空洞
[ok] 单边上行：无空洞  401 步 / 0 个空洞
[ok] 先跌后弹再回落：无空洞  1603 步 / 0 个空洞
[ok] 容差 2 档（S = R + T − 1） → 应出洞  52 个空洞   首个：现价 6489 时缺 6430
[ok] 容差 3 档（S = R + T）     → 应无洞  0 个空洞
[ok] 容差 0 档（S = R，改前配置）→ 应出洞  322 个空洞  首个：现价 6499 时缺 6440
```

坏配置对照（临时把订阅半径压到 14 = 容差 2 档，验完已还原 20）：

```
run.py --check [6]  → [FAIL] 窗口容差只有 2 档（订阅 ±14 − 显示 ±12），小于窗口重建触发 3.0 档
check_window_tolerance → RC=1（[1] 红 + [2] 三条路径分别 52 / 76 / 257 个空洞）
                        [3] 边界对照仍全绿（不依赖配置，证明它不是在回显配置）
```

## VALIDATION-SUMMARY

- `tools/check_session_rollover.py` → `RC=0`
- `tools/smoke_test.py` → `RC=0`
- `tools/check_window_tolerance.py` → `RC=0`（8 项，含 `T−1` / `T` 边界对照）
- `run.py --check` → `RC=1`（**2 项，均为 IBKR 断线所致**，非本轮引入：`连接状态 degraded`、
  `热力图未生成或行列异常` / `Skew 序列为空`）
- `tools/check_*.py` 全量 → 21 个，19 `RC=0` / 2 `RC=1`（红 = `check_page_render` 既有 /
  `check_web_contract` 断线）

## NOTES-PATHS

- `notes/sessions/2026-09-14/subscription-window-tolerance/handoff.md`（本文件）
- `notes/sessions/2026-09-14/subscription-window-tolerance/project_state.md`
- `notes/memory/RULES.md`（§6.1 基线订正 + §6.6 新增）

## Closed in session

- 现价往返导致的行权价轴时间空洞（KAI 报）—— 配置级修复 + 静态/行为双重回归封口
- `check_session_rollover` / `smoke_test` 夹具靶档随订阅半径漂移（本轮自己引入的假红）
- `tools/smoke_test.py::_status()` 硬编码 `subscribed=74`（第二份真相）
- 我改 `config/subscription.json` 时在 `_window_comment` 里写了字面量 `features.json`，
  触发 `run.py --check [4]` 的跨文件引用 warn —— 已改措辞（**改注释，不改检查器**）

## OPEN-RISKS

- **±20 需要重启 `run.py` 才生效。** 当前常驻进程仍是 `±12`（`run.py --check [13]` 报
  `订阅数 48/92`；按 20 应为 81）。未强杀 KAI 的常驻进程。
- **容差 8 档 = 40 点只是"够用"，不是"够到趋势日"。** 单边趋势超过 40 点时，滚出的档位
  仍会在显示窗口内留下空洞 —— 这是 KAI 选项 B（`WindowFollower` 改为"走过路径的显示
  窗口并集"，容差 ~105 点）要解决的问题，本轮未做。
- **`run.py --check [13]` 的两项红依赖 IBKR 状态**，断线时必红。判据是
  `health.connection` / `last_tick_age_s`，**不是 `seq` 在涨**。
- **`tools/check_*.py` 的"第二个红"会随服务/行情状态换身份**：10:3x 是
  `check_ws_compression`（压缩比 71.8% < 80%），11:1x 是 `check_web_contract`。别把
  当时的红名当永久事实（已记入 `RULES.md §6.1`）。
- **`notes/context/handoff.md` / `open_tasks.md` 与 `notes/sessions/2026-09-14/live-render-verify/`
  仍是另一个会话（只读实盘验证）的未提交改动，本轮刻意不纳入提交** —— 那批结论我未独立
  核验，替它背书违反"不吹绿"。⇒ 提交后 `notes/context/` 索引仍指向
  `2026-09-14/webgl-to-echarts`（该版本自洽），本会话尚未进索引。
