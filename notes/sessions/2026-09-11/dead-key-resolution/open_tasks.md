# Open Tasks — dead-key-resolution

## Closed（本会话）

- [x] **7 个死配置键的去留** —— 4 接线 + 3 删除，`UNWIRED_IS_FAILURE` 已置 `True`。
- [x] **`feed_service.py` 超 400 行** —— 拆出 `acquisition/spot_tap.py`，现 395 行。
- [x] **非空转验证** —— 3 组共 20 项，全部按预期（含一次真实的超时分支命中）。

## Open（移交）

- [ ] **实盘"连上之后能否收到数据"**（中）—— 需真实 TWS / IB Gateway。本轮新增的
      两个行为（`max_underlying_age_s` 现价陈旧闸、`reset_feature_state_on_reconnect`
      重连清状态）**只在单元/生命周期层面验证过**，真实断线场景待实盘确认。
- [ ] **`notes/` 与 `.workbuddy-ai/memory/` 是否收敛为一套**（低）—— 两套证据体系
      并行，上一轮已出现过"前置记忆整个丢失"的实例。方案待定。
- [ ] **`check_clock_protocol.py` 是否并入 `--check` 常驻**（低）—— 它目前是回归，
      靠"有人记得跑"而不是自动拦截。

## 建议（本会话新增）

- [ ] **给 `_shutdown_step` 的超时路径补一个常驻回归**（低）—— 本轮的非空转验证
      证明"用 `wait_for` 会让超时上限形同虚设"，这个坑很容易复发。但目前该验证
      只存在于临时脚本里，建议沉淀为 `tools/check_shutdown_timeout.py`。
