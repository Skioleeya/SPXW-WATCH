# Open Tasks

Archive: notes/context/archive/open_tasks_2026-09.md

## Active

- [ ] **[待 KAI 定] 硬切改动未提交** —— 工作树 18 个文件（+186 / −814）
      加 2 个未跟踪项（`notes/`、`tools/fixtures.py`）；HEAD 仍 `3eeb55b`。
      **是否提交并推送 `origin/main` 待 KAI 指示。**
- [ ] **[中] 硬切后的首次实盘联通未验证** —— 模拟盘已物理删除，系统只剩实盘路径，
      而本轮**未起 IB Gateway**。下次实盘启动应确认：`mode` 正确、72 条订阅、
      热力图出图、`--check` 之外的真实链路。
- [ ] **[中] 4 个需服务的检查未跑通** —— `check_web_contract` /
      `check_page_render` / `check_ws_compression` / `ws_probe`，本机 8060 无服务。
      已定位与硬切无关（`check_web_contract` §[1] DOM id 与 §[2] CFG 路径均通过，
      只 §[3] 载荷字段需活连接）。起服务后补跑。
- [ ] **[中] 现价延迟** —— SPX 指数无实时权限（`marketDataType=3`），窗口居中 /
      现价标注偏约 1–3 档。出路：开通 CBOE 指数实时，或换 spot 来源
      （`OptionTick.und_price` 恒为 `None`，不可用）。
- [ ] **[低] 色板缺机械回归** —— `check_web_contract` 只校验 CFG **路径存在**、
      `check_page_render` 只断言"画出来了"，色值被误改**没有任何检查会红**。
- [ ] **[低] `check_clock_protocol.py` 是否并入 `--check` 常驻** ——
      目前靠"有人记得跑"而不是自动拦截。
- [ ] **[低] 联通与限速无常驻回归** —— 全靠手工 `run.py` + `tools/ws_probe.py`。

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

## 已决策（KAI）—— 不要再当待办重提

- **限速桶读数不上前端**（数据已到帧 `health.rate_limit`，`web/` 刻意不动）。
- **IV 热力图 ΔIV ≈ 0 不退回中性色** —— 维持 `Turbo` **顺序**色阶
  （0 = 亮黄绿 `#a4fc3b`）。理由：忠实参考项目截图 + 原指令就是"只改色调"。
- **`notes/` 与 `.workbuddy-ai/memory/` 的分工**（2026-09-13）：
  `notes/` 为记录落点（`notes/sessions/YYYY-MM-DD/<task-id>/`），
  `memory/` 为根路由器（只留指针与跨项目约定）。**同一事实只写一处。**
