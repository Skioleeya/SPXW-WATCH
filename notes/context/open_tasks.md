# Open Tasks

Archive: notes/context/archive/open_tasks_2026-09.md

## Active

- [ ] **[中] 实盘首次出图未验证** —— **部分验证完成**（2026-09-13）。
  KAI 启动 IB Gateway，系统实际跑通：
  - ✅ `mode=delayed`（周日正确）
  - ✅ **48 条订阅**（±12 档 × Put/Call）
  - ✅ SPX 现价 **7591.70**
  - ✅ WS 帧流正常（seq 1→5，0 缺口）
  - ✅ `health.rate_limit` 四要素（桶 45/s）
  - ✅ 网格 **2370 桶**，3 区段（GTH/空档/RTH），铺满无缝隙
  - ⚠️ 热力图出图、Skew 数据、按钮切换、横轴对齐 —— **需浏览器肉眼确认**
  - ⚠️ 周日市场关闭，`Skew=None` / 热力图 0 格 = **预期行为**，不是缺陷
  ✅ **由 KAI 在 GTH 时段手动验证前端渲染**（2026-09-13 KAI 明确：不要设置自动任务）。

- [ ] **[中] 4 个需服务的检查 — 1/4 已跑通** —— 
  - ✅ `ws_probe`（2026-09-13）：23/27 通过，4 项失败全部是周日市场关闭预期行为
  - ❌ `check_web_contract` / `check_page_render` / `check_ws_compression` —— 仍需盘中复跑
  ⚠️ 2026-09-13 `multi-session-grid` 会话中，`check_web_contract` 的**三段**都已用
  **离线等价物**补验（第 1、2 段用桩模块绕过顶层 `import aiohttp`：
  DOM id 22 个 / CFG 路径 32 条全存在；第 3 段用真实流水线造帧：
  **61/61** 载荷路径命中，含新增的 `session.zones` 及其 5 个子路径）。
  ⇒ 三段都覆盖过，**但走的都不是它自己的入口**（被顶层 `import aiohttp` 挡住）。
  盘中仍应用它本身的入口复跑一次。

- [ ] **[低] `check_web_contract.py` 顶层 `import aiohttp`** 使第 1、2 段
  （纯静态对照）也无法在无 aiohttp 的环境运行。是否把 import 挪进函数内
  **待 KAI 定** —— 改动小，但属"重构现有工具"，未获指令不擅自动。

- [ ] **[低] `~/.workbuddy-ai/tmp/` 下约 40 个历史探针未迁移** ——
  新约定落点已是 `<项目根>/tmp/`，但历史文件仍在用户级目录（被所有项目共用）。
  KAI 2026-09-13 拍板：**下一个会话做**（"代办"）。本轮不动用户目录。
  ⇒ 开始前先列清单（按 mtime / 大小 / 是否含 `import`），让 KAI 一眼能拍"全迁/部分迁/只登记不动"。

- ~~**[低] 本机缺 `ib_async` 与 `aiohttp`**~~ —— **已解决**（2026-09-13 KAI 启动 Gateway 后安装）。
  `check_reconnect_flow` / `check_web_contract` / `ws_probe` 现在都能跑。

## Stale / Needs Verification

- [ ] **`check_reconnect_gap.py` 的假冲量场景未在真实断线下复现** ——
      "断线 >900s 时两道毛刺闸门因样本被裁双双失效"仍是静态分析结论。
      （`reset_feature_state_on_reconnect=false` 是**刻意默认值**，不是缺陷。）
- [ ] **`ibkr.max_underlying_age_s` 与重连清状态的真实断线场景未确认** ——
      2026-09-11 接线时只在单元/生命周期层面验证过，需 TWS / IB Gateway 实测。
- [ ] **`tools/fixtures.py::SyntheticSurface` 是简化曲面** —— 只保证确定性，
      不保证与真实 IV 曲面同形。依赖它的 `check_side_flip` 只验结构性事实，
      但**后续若有人拿它做数值断言会得到与实盘不符的结论**。
- [ ] **ib_async 合并 tickType 13/83** —— `TickRouter.source_tick_type` 恒为 13
      （名义值），属性层无法区分实时模型与延迟模型 greeks。
- [ ] **`git fetch` 在本环境不落地 remote-tracking ref（根因未定位）** ——
      `git fetch` 退出 0、输出 `[new branch] main -> origin/main`、并写了
      `.git/logs/refs/remotes/origin/main`，但 `refs/remotes/origin/main` **不存在**；
      手动建好后**下次 fetch 又被删**。全环境**无任何 prune 配置**；
      对照仓库 `live-volatility-surface` 正常。**不影响提交/推送**
      （`git ls-remote` 已核实远端 = 本地 HEAD），只让 `git status -sb` 显示 `[gone]`。
      需 KAI 在自己终端复现一次才能判定是否为工具沙箱侧现象。

## 已决策（KAI）—— 不要再当待办重提

- **RTH 收盘 = `16:00`，不是 Cboe 官方页写的 `4:15 PM`**（2026-09-13 KAI 明确）——
  理由：**KAI 只在正股的 RTH 时间（09:30–16:00）交易**，网格按自己的交易时段切。
  与 Cboe 指数期权到 16:15 的口径差异**不是缺陷**，不要再提。
- **不设任何验收自动任务**（2026-09-13 KAI 明确）—— 由 KAI **手动在 GTH 时段验证**。
  此前记录的"定时任务不见了"**是预期行为**（KAI 有意不让它存在），
  不是工具缺陷，不要再当 bug 排查、也不要再重建。
- **限速桶读数不上前端**（数据已到帧 `health.rate_limit`，`web/` 刻意不动）。
- **IV 热力图 ΔIV ≈ 0 不退回中性色** —— 维持 `Turbo` **顺序**色阶
  （0 = 亮黄绿 `#a4fc3b`）。理由：忠实参考项目截图 + 原指令就是"只改色调"。
- **冷数据键序也统一为降序**（2026-09-13 复核时 KAI 选定）—— 与帧 `strikes` 同向。
  `dump_bucket()` 改 `sorted(..., reverse=True)`，回归
  `check_persistence.py::_case_key_order_descending`。
- **`web/*.js` 已拆分完成**（2026-09-13）—— `app.js` / `skew.js` / `period.js` 三文件
  拆分为 9 个模块，全部 < 400 行；`--check` `[1]` 全绿 `RC=0`。
  `.js` 只进 `[1]`，不进 AST 类检查（`[2][9][10]`）。
- **同族守卫缺口已修**（2026-09-13）—— `check_period_aggregation.py` 与
  `check_skew_alignment.py` 已接入 `tools/group_guard.py`，`--selftest` 各自抓全
  守卫 2 条用例 + 全部变异。`group_guard.py::prefixes` 契约 = `tuple[str, ...]`
  （不要传 `str`）。
- **`~/.workbuddy-ai/tmp/` 40 个历史探针推迟到下一个会话**（2026-09-13 KAI 拍板）—— 动
  用户目录需明令。已登记 `Active` 段，待下一会话开清单。
- **临时探针落点 = `<项目根>/tmp/`**（2026-09-13 KAI 拍板）—— 不再写用户级
  `~/.workbuddy-ai/tmp/`（那个被所有项目共用、已串味）。配套：**必须在
  `.gitignore` 与 `NON_SOURCE_DIRS` 两处登记**；探针用完即弃，判据要落成常驻回归。
- **`check_web_contract.py` 的 `import aiohttp` 不内移**（2026-09-13 复核时 KAI
  未选）—— 保持顶层 import 原样，静态两段仍靠桩模块离线补跑。
- **`notes/` 与 `.workbuddy-ai/memory/` 的分工**（2026-09-13）：
  `notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`），
  `memory/` 为根路由器（只留指针与跨项目约定）。**同一事实只写一处。**
- **色板缺机械回归 = 不做**（2026-09-13 KAI 明确）—— 前端是空壳，色彩映射由后端值驱动；
  色值变更的责任在后端，不需要前端做机械回归。从 Active 剔除。
- **`check_clock_protocol.py` 已并入 `--check` 常驻**（2026-09-13 KAI 批准）——
  作为 `[12]` 检查项，验证三个时间源满足 `ClockPort` + `TickStore.prune()` 真实裁剪。
- **联通与限速已并入 `--check` 常驻**（2026-09-13 KAI 批准）—— 作为 `[13]` 检查项，
  `selfcheck_connectivity.py`：若 8060 有服务则连 WS 抓帧校验结构；无服务时跳过（warning，
  非交易日预期），不视为失败。
