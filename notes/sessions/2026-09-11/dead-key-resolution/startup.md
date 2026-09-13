# Startup — dead-key-resolution

## 起点

上一会话（`selfcheck-hardening`）把检查 [7] 上线，一次抓出 **7 个死配置键**。
当时 `UNWIRED_IS_FAILURE = False`，只报 `[warn]`，理由是"每个都需要产品决策"。
本会话的任务就是替这 7 个键逐个定性。

## 改动前基线

| 项 | 值 |
|---|---|
| `run.py --check` | 全部通过（68 文件 / 最长 `acquisition/feed_service.py` 376 行 / 10 项） |
| 回归 | 8 个全过（`check_web_contract` / `check_page_render` / `ws_probe` 需服务在跑） |
| 死键 | **7 个**，全部 `[warn]` 不阻塞 |

## 先做的事实核查（写代码之前）

判断"接线还是删除"不能靠猜，先把每个键**在代码里的真实状态**查清楚：

| 键 | 代码侧事实 | 定性 |
|---|---|---|
| `transport.access_log` | `transport/server.py:101` 硬编码 `access_log=None`；aiohttp 里 `None` = 关闭 | 有硬编码等着被替代 |
| `ibkr.max_underlying_age_s` | `_SpotTap.last_spot_ts` **只写不读**（死字段）；`_reconcile_loop` 只看 `spot > 0` | 行为不存在，接线=补功能 |
| `pipeline.shutdown_timeout_s` | `stop()` 里 `await task` 无超时；且 `except (CancelledError, Exception): pass` 吞取消 | 行为不存在 |
| `pipeline.reset_feature_state_on_reconnect` | `_on_reconnect` 只做重订阅，不碰 L3 | 行为不存在（默认值 false 与现状一致） |
| `features.atm_max_bracket_strikes` | `strike_window.py` 的 `atm_bracket()` **无任何调用点**；在用 `nearest_strike()` | **死代码配死键** |
| `ibkr.handshake_timeout_s` | `connectAsync(timeout=self._connect_timeout)` 已是连接+握手总超时 | 语义重叠 |
| `ibkr.chain_ready_timeout_s` | `fetch_chain` 后用固定 `chain_settle_s` sleep，无"等待就绪"逻辑 | 行为不存在，但判据只能启发式 |

结论：7 个键**不是同一类问题**，混在一起做"接线 or 删除"的二选一会出错。

## 决策（KAI 确认）

**4 接线 / 3 删除**。接线：`access_log`、`max_underlying_age_s`、
`shutdown_timeout_s`、`reset_feature_state_on_reconnect`（默认值不变）。
删除：`atm_max_bracket_strikes`、`handshake_timeout_s`、`chain_ready_timeout_s`。
