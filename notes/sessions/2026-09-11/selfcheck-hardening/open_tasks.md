# Open Tasks — selfcheck-hardening

## Active

- （无）本会话范围内的任务已全部关闭。

## Closed in session

- [x] 把 `state.prune_interval_s` 接进 L6 维护循环（节奏归 L2 所有）
- [x] 修掉 `SessionClock` 未实现 `ClockPort.now()` 导致的裁剪静默失效
- [x] 新增回归 `tools/check_clock_protocol.py`（含非空转验证）
- [x] 新增检查 [7] 配置键归属与接线
- [x] 新增检查 [9] 单一职能
- [x] 新增检查 [10] 禁止硬编码
- [x] 按单一职能拆分 `tools/selfcheck.py`（386 行 → 7 个文件，最长 376 行）
- [x] 六项非空转验证全部按预期 FAIL，文件已还原
- [x] 全量验证：`--check` 10 项 + 8 个回归 + `ws_probe` 20/20 + 页面实拍
- [x] README 同步：§1 工具清单、§3 配置规则（三条 → 四条）、§9 检查表（10 项）、
      §10 已知边界（ECharts 版本归属纠正 + 7 个死键清单）

## Stale / Needs Verification

- [ ] **7 个死配置键的去留待定** —— `features.atm_max_bracket_strikes`、
      `ibkr.{handshake_timeout_s, chain_ready_timeout_s, max_underlying_age_s}`、
      `pipeline.{shutdown_timeout_s, reset_feature_state_on_reconnect}`、
      `transport.access_log`。每个都需要一次产品决策（接线 or 删除），不是机械
      修改，因此本会话**没有动它们**，检查 [7] 对它们只报 `[warn]`。
      其中 `transport.access_log` 最严重：`transport/server.py:101` 硬编码了
      `access_log=None`，配置项从未被读 —— 配置写 `false`、真实取值在代码里，
      同时违反第 3 条与第 7 项检查的意图。
      **决定去留后**，把 `tools/selfcheck_config.py::UNWIRED_IS_FAILURE` 置 `True`
      即可把死键升级为失败。
- [ ] **实盘"连上之后能否收到数据"** —— 需要真实 TWS / IB Gateway。
      已验证：连接被拒时抛出可操作的 `ConnectionFailed`。
      未验证：合约确认、订阅、tick 路由、106 模型 Greeks 的实际到达。
- [ ] **`notes/` 与 `.workbuddy-ai/memory/` 是否收敛为一套** —— 本会话按项目既有
      约定写 `notes/`，`memory/` 只留指针，避免再次出现"前置证据丢失"。
      最终是否合并为一套仍待确认。
- [ ] **`check_clock_protocol.py` 是事后补的回归，不是检查** —— 它靠"有人记得跑"
      而不是靠 `--check`。若认为这类协议一致性也应在 `--check` 里常驻，
      可把它并入自检（当前未做，避免自检项无限膨胀）。
