# Open Tasks

Archive: notes/context/archive/open_tasks_2026-09.md

## Active

- [ ] **[中] 实盘首次出图未验证** —— 模拟盘已物理删除，系统只剩实盘路径。
  2026-09-13（周日）起服务只走到 0DTE 切片即 `ChainResolveError`（fail-closed 正确，
  无当日到期）。**下一交易日盘中**应确认：`mode` 正确、48 条订阅（±12 档 × Put/Call）、
  热力图出图（**肉眼确认纵轴高行权价在上**）、`health.rate_limit` 四要素，
  以及**两块图横轴按同一周期标签对齐**（2026-09-13 skew-period-consistency
  会话新改，只做过离线验证 —— 改了 `web/` 的 `app.js` / `period.js` / `skew.js`
  三个文件）。
  已设**一次性**定时任务（automation id `8b4fe600-261f-4ab8-9930-217dbf6b9eef`，
  2026-09-14 09:45 ET）；若该次未成，需另设下一个交易日。
  ⚠️ **2026-09-13 复核发现**：上一轮记录的 id `e4ad7495-…` 在系统里**并不存在**
  （`automation list` 空、`view` 报 not found）—— 「开盘后补验收」当时没有任何
  触发点。已按原时间重建（即上面的新 id），prompt 写成自包含。
- [ ] **[中] 4 个需服务的检查未跑通** —— `check_web_contract` /
  `check_page_render` / `check_ws_compression` / `ws_probe`。
  ⚠️ 硬切后**服务无法在非交易日常驻**（无当日到期即退出）⇒ 这 4 项
  **从此只有盘中能跑**；盘前/盘后/周末"回归全绿"永远不成立，
  这是取舍的必然结果而非回归破坏。
  ⚠️ 2026-09-13 skew-period-consistency 会话中，`check_web_contract` 的
  **第 1、2 段**（DOM id 21 引用、CFG 路径 30 条）已用**桩模块离线补跑 → 全 PASS**；
  **第 3 段**（载荷字段）用**离线等价物**补验（真实流水线造帧 → 55/55 路径命中，
  且确认 `skew.series.skew_min/max` 已不在帧里）。
  ⇒ 该检查的三段都已离线覆盖过，**但走的都不是它自己的入口**（被顶层
  `import aiohttp` 挡住，见下一条）。盘中仍应用它本身的入口复跑一次。
- [ ] **[低] `check_web_contract.py` 顶层 `import aiohttp`** 使第 1、2 段
  （纯静态对照）也无法在无 aiohttp 的环境运行。是否把 import 挪进函数内
  **待 KAI 定** —— 改动小，但属"重构现有工具"，未获指令不擅自动。
- [ ] **[低] `skew_scale_window_seconds = 3600.0` 待盘中校准** ——
  它的作用是"让早盘尖峰随时间退出量程窗口"。太短则量程频繁跳、曲线呼吸；
  太长则退化成旧的全序列极值。当前值是经验值，**未经真实盘中数据校准**。
- [ ] **[低] 色板缺机械回归** —— `check_web_contract` 只校验 CFG **路径存在**、
      `check_page_render` 只断言"画出来了"，色值被误改**没有任何检查会红**。
- [ ] **[低] `check_clock_protocol.py` 是否并入 `--check` 常驻** ——
      目前靠"有人记得跑"而不是自动拦截。
- [ ] **[低] 联通与限速无常驻回归** —— 全靠手工 `run.py` + `tools/ws_probe.py`。
- [ ] **[低] 本机缺 `ib_async` 与 `aiohttp`** —— 只有纯标准库的回归能跑，
  `check_reconnect_flow`（缺 `ib_async`）与 `check_web_contract`（缺 `aiohttp`）
  在本环境直接 `ModuleNotFoundError`。要跑全量离线回归需先装项目依赖。

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

- **限速桶读数不上前端**（数据已到帧 `health.rate_limit`，`web/` 刻意不动）。
- **IV 热力图 ΔIV ≈ 0 不退回中性色** —— 维持 `Turbo` **顺序**色阶
  （0 = 亮黄绿 `#a4fc3b`）。理由：忠实参考项目截图 + 原指令就是"只改色调"。
- **冷数据键序也统一为降序**（2026-09-13 复核时 KAI 选定）—— 与帧 `strikes` 同向。
  `dump_bucket()` 改 `sorted(..., reverse=True)`，回归
  `check_persistence.py::_case_key_order_descending`。
- **`check_web_contract.py` 的 `import aiohttp` 不内移**（2026-09-13 复核时 KAI
  未选）—— 保持顶层 import 原样，静态两段仍靠桩模块离线补跑。
- **`notes/` 与 `.workbuddy-ai/memory/` 的分工**（2026-09-13）：
  `notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`），
  `memory/` 为根路由器（只留指针与跨项目约定）。**同一事实只写一处。**
