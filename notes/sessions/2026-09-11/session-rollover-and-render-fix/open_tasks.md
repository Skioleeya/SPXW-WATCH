# Open Tasks — session-rollover-and-render-fix

## Active

- （无）本会话范围内的任务已全部关闭。

## Closed in session

- [x] 跑 `tools/check_tick_router.py` 并处理结果 —— 7 组全过，L1 采集层首次被离线执行
- [x] README 登记 `check_tick_router.py`
- [x] 用真实浏览器打开页面 —— 发现并修掉 Skew 面板渲染中断（缺陷 A）
- [x] 定位并修掉跨会话数据污染（缺陷 B）
- [x] 新增 `check_session_rollover.py`（含非空转验证）
- [x] 新增 `check_web_contract.py`（含非空转验证）
- [x] 新增 `check_page_render.py`（含非空转验证）
- [x] 更新 README：辅助工具清单、三向对照与渲染检查说明、已知边界新增 4 条
- [x] 全量回归（`run.py --check` 7 项 + 7 个回归 + `ws_probe` 20/20）

## Stale / Needs Verification

- [ ] **实盘"连上之后能否收到数据"** —— 需要真实 TWS / IB Gateway，本会话无法验证。
      已验证的部分：连接被拒时抛出可操作的 `ConnectionFailed`（含 host:port/clientId
      + 端口对照表指引）。未验证的部分：连上之后合约确认、订阅、tick 路由、
      106 模型 Greeks 的实际到达。风险等级：中（离线链路已完整验证）。
- [ ] **`notes/` 目录与本项目既有证据体系的关系** —— 本项目原本用
      `.workbuddy-ai/memory/` + README「已知边界」+ 回归工具承载证据；
      `notes/` 是随全局 skill 引入的第二套。是否长期并行、或把其中一套收敛掉，
      待确认。
- [ ] **前端在会话翻篇瞬间会短暂保留上一场的画面** —— 刻意取舍（避免闪白），
      已在 README 记为已知边界。若认为有误读风险，可改为按 `session.expiry`
      变化主动清空面板。
