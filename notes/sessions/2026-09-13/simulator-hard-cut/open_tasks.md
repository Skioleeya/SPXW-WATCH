# Open Tasks — simulator-hard-cut

## Closed（本会话）

- [x] **[高] 硬切删除模拟盘全部依赖** —— 物理删除 `simulator/`（4 文件 582 行）
      + `config/simulator.json`；`run.py` 只剩 `--check`；`app/pipeline.py`
      367 → 341 行；`FeedMode.SIM` 已移除。备份在仓库外
      `E:\US.market\SPXW SWATCH\simulator_removed_20260913\`。
- [x] **[高] 保住 4 个离线回归** —— 抽出 `tools/fixtures.py::FakeClock` /
      `SyntheticSurface`（188 行），改写 `check_clock_protocol` /
      `check_side_flip` / `check_session_rollover` / `smoke_test`。
      `FakeClock` 完全不碰 `time.monotonic()`，比被删的 `SimClock` 更确定。
- [x] **[中] 清理自检里对 `simulator` 的登记项** ——
      `LAYER_OF["simulator"]` / `REQUIRED_KEYS["simulator"]` /
      `EXEMPT_CONSTANTS["simulator/scenario.py"]` 三处，与目录删除同轮完成。
- [x] **`README.md` 同步** —— 删除 `--sim`/`--live`、L6 表与配置清单去
      `simulator`、§8 改写为「离线回归」、修正 10→9 配置数 与 41→37 关键键数。
- [x] **记录体系拓扑（KAI 三项追加指令）** —— skill `notes-session-records`
      导入并放宽（160 → 133 行，27 强制标记 → 5 核心标记）；5 条工程要求
      提升到用户级 `MEMORY.md` 并在项目级去重；`notes/` 复活。
- [x] **[已定] `notes/` 与 `.workbuddy-ai/memory/` 的收敛方案** ——
      KAI 2026-09-13 定：**`notes/` 为记录落点，`memory/` 为根路由器**
      （只留指针与跨项目约定，不复述细节）。此前反复出现的
      "同一事实两处写 → 数字腐烂" 由此从结构上消除。

## Active

- [ ] **[待 KAI 定] 硬切改动尚未提交** —— 工作树 18 个文件（+186 / −814）
      加 2 个未跟踪项（`notes/`、`tools/fixtures.py`）。HEAD 仍是
      `3eeb55b`。**是否提交并推送 `origin/main` 待 KAI 指示。**
- [ ] **[中] 4 个需服务的检查未在本次跑通** —— `check_web_contract` /
      `check_page_render` / `check_ws_compression` / `ws_probe` 本机 8060
      无服务，全部 `ConnectionRefusedError`。**与本次改动无关**
      （`check_web_contract` 的 §[1] DOM id 与 §[2] CFG 路径均通过，
      只 §[3] 载荷字段需活连接）。下次起服务后应补跑。
- [ ] **[中] 硬切后的首次实盘联通未验证** —— 删除模拟盘后，系统只剩实盘路径。
      本轮**未跑 `run.py` 实盘**（需 IB Gateway 在 4002 监听）。
      下次实盘启动应确认：`mode` 正确、72 条订阅、热力图出图。
- [ ] **[低] 色板缺机械回归** —— `check_web_contract` 只校验 CFG **路径存在**、
      `check_page_render` 只断言"画出来了"，色值被误改没有任何检查会红。
- [ ] **[低] `check_clock_protocol.py` 是否并入 `--check` 常驻** ——
      目前靠"有人记得跑"而不是自动拦截。
- [ ] **[低] 联通与限速无常驻回归** —— 全靠手工 `run.py` + `tools/ws_probe.py`。

## Stale / Needs Verification

- [ ] **`check_reconnect_gap.py` 的假冲量场景未在真实断线下复现** ——
      断线 >900s 时两道毛刺闸门因样本被裁双双失效这一推断，仍是静态分析结论。
- [ ] **现价延迟** —— SPX 指数无实时权限（`marketDataType=3`），
      窗口居中偏约 1–3 档。`OptionTick.und_price` 恒为 `None`，不可用作替代源。
