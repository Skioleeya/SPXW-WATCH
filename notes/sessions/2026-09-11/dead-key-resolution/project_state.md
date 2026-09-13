# Project State — dead-key-resolution

## 1. 四个接线

### 1.1 `transport.access_log`（`transport/server.py`）

`__slots__` 加 `_access_log`；`__init__` 读配置；`start()` 把它传给
`web.AppRunner(app, access_log=self._access_log)`，替换原先硬编码的 `None`。

**这里有个坑，差点写错。** 先看 aiohttp 3.14.3 的实际签名：

```
AppRunner(app, *, handle_signals=False, access_log_class=AccessLogger, **kwargs)
```

没有显式的 `access_log` 参数 —— 它经 `**kwargs` 一路透传到 `RequestHandler`，
而 `web_protocol.py:186` 是：

```python
access_log: Logger = access_logger        # access_logger = getLogger("aiohttp.access")
```

`access_logger` 是 truthy，所以 **不传 = 访问日志开启**；`None` 才关闭。
项目里那句 `access_log=None` 正是在关掉它 —— 所以**不能**把这个参数简单删掉，
删了等于意外打开访问日志。这条已写进 README §10。

第二个坑：接线时不能直接传 `aiohttp.access` 这个 logger。`core/logging_setup.py:72`
把 `aiohttp.access` 放进了第三方降噪列表（压到 `WARNING`），而
`AccessLogger.enabled` 判的是 `logger.isEnabledFor(logging.INFO)` —— 传进去会被
算成"未启用"，**配置写 `true` 也永远不出日志**。改用项目自己的
`get_logger("transport.access")` 命名空间才真正生效。

### 1.2 `ibkr.max_underlying_age_s`（`acquisition/feed_service.py`）

新增 `_spot_stale()`，在 `_reconcile_loop` 里于 `spot <= 0` 检查之后调用：

```python
if self._spot_stale():
    # 只在状态翻转时记一次日志，避免每轮刷屏
    ...
    continue
```

**为什么这是正确性问题而不是洁癖**：窗口跟随用现价决定"以哪一档为中心"。
现价断流时 `last_spot` 仍保留最后一个值，代码上看不出异常 —— 但那可能已是几分钟
前的价格。用它重建窗口 = 按错误的中心重新订阅行权价，纵向对齐整体偏掉，且
**不报任何错**。0DTE 上现价断流比整条期权链断流常见得多。

时间戳单位已核实：`_SpotTap.last_spot_ts` 来自 `tick_router.py:133` 的
`SpotTick(price=..., ts=now_ts())`，是墙钟 epoch 秒，与 `_reconcile_loop` 里的
`now_ts()` 同源，可直接相减。

### 1.3 `pipeline.shutdown_timeout_s`（`app/pipeline.py`）

`stop()` 拆成"取消后台任务 + 逐个关闭组件"，每步经 `_shutdown_step()` 加时间上限。

**关键实现细节：必须用 `asyncio.wait` 而不是 `wait_for`。**
`wait_for` 超时后会 cancel 目标并**继续等它结束**；目标若在取消后还要跑很久，
"上限"就是假的。这一点是**被非空转验证实测抓到的**：第一版用 `wait_for`，测试
里一个普通任务被取消后瞬间结束，`stop()` 耗时 0.0s，超时分支根本没走到；换成
`asyncio.wait` 后，一个清理需 3s 的任务在 2s 上限处被如实放弃并打印
「强制继续关闭」（实测 `stop()` = 2.0s）。

同时修掉旧代码的反模式：`except (asyncio.CancelledError, Exception): pass`
会把取消异常吃掉，于是"取消成功"变成假象 —— 任务可能根本没结束。

### 1.4 `pipeline.reset_feature_state_on_reconnect`（跨 4 个文件）

这是唯一需要**新增跨层链路**的一个：

- `contracts/ports.py` — `FeedPort` 加 `set_reconnect_hook(hook)` 方法
- `acquisition/feed_service.py` — 实现它，并在 `_on_reconnect()` 里触发
- `simulator/synthetic_feed.py` — 实现为 no-op（模拟源不重连）
- `app/pipeline.py` — 注册 `_on_feed_reconnect`，按配置决定是否 `engine.reset()`

**为什么钩子要写进协议而不是只长在 `IbkrFeed` 上**：L6 只认识 `FeedPort`，
钩子若只存在于实盘实现里，任何一次"换数据源"或"新写实现"都会静默漏掉它。
这与上一轮 `ClockPort.now()` 的教训同源 —— 接口不写进协议，实现就会漏、
调用方就得碰运气。

L1 不认识 L3，所以链路必须绕组装层：L1 只报告"我重连了"，
"要不要清状态"由 L6 按配置决定。默认 `false`，**行为与接线前完全一致**。

## 2. 三个删除

- `features.atm_max_bracket_strikes` + `strike_window.py::atm_bracket()`
  —— 死代码配死键，一起删。`Sequence` 也随之从 import 移除。
- `ibkr.handshake_timeout_s` —— `connectAsync(timeout=)` 已是连接+握手总超时，
  再拆一个属重复建模；且 ib_async 不暴露握手阶段钩子，真接线只能靠轮询。
- `ibkr.chain_ready_timeout_s` —— `reqSecDefOptParams` 分片推送、**没有明确的
  "完成"信号**，"就绪"判据只能是启发式；保留 `chain_settle_s` 更简单可控。
  这是可逆的保守选择，实盘若真出现链不完整再接线。

## 3. 顺带拆出 `acquisition/spot_tap.py`

接线后 `feed_service.py` 涨到 **429 行**，被检查 [1] 拦下。这暴露了一个真问题：
`_SpotTap` 是个独立概念（"把现价就地留一份，避免 L1 反向依赖 L2"），却寄生在
门面文件里。按项目"单一文件单一职能"的约定，正确解法是**拆出去**而不是硬砍注释。

拆出后 `feed_service.py` = 395 行，`SpotTap` 成为公开类，`_SpotTap` 的两处引用
与模块 docstring 同步更新，`SpotTick` 变成未使用 import 已删除。

## 4. 收紧检查

`tools/selfcheck_config.py::UNWIRED_IS_FAILURE` 由 `False` 改为 `True`。

`REQUIRED_KEYS` **不需要改** —— 这 7 个键本来就不在其中（必需键列表是"少了就
必须报错"的最小集，与"是否有消费者"是两件事）。

## 5. 验证结论

| 项 | 结果 |
|---|---|
| `run.py --check` | **10/10 全部通过**（69 文件 / 最长 395 行 / **无死键**） |
| 8 个回归 + `ws_probe` | 全过 |
| 非空转验证 A（检查 [7]） | 注入死键 → `[FAIL] ... 没有任何代码读取` ✅ |
| 非空转验证 B（4 个接线） | **11/11** ✅ |
| 非空转验证 C（全链路） | **8/8** ✅ |

非空转验证 B 的关键证据：

```
[1] max_underlying_age_s   新鲜/超阈/从未收到 → False/True/True
[2] reset_on_reconnect     true→调用 reset；false→不调用；钩子已注册
[3] shutdown_timeout_s     stop() 实测 2.0s（上限 2s，任务清理需 3s）
                           且返回时任务仍在清理中 → 确实走了超时分支
[4] access_log             false→捕获 0 行；true→捕获 1 行
```

非空转验证 C 另跑了一次真实的 `start() → 运行 12s → stop()`，确认：
产出 29 帧、日志出现「已停止」、**无裁剪异常**（跨过了一个完整裁剪周期）、
无后台任务超时、无 ERROR/Traceback。

## 6. 测试构造上踩到的两个坑（值得记住）

1. **`asyncio.create_task()` 后立刻 `cancel()`，任务不会执行协程体。**
   它还没被事件循环调度，`cancel()` 直接把它标记为 cancelled。所以想测"取消后
   还要跑很久"的场景，必须先 `await asyncio.sleep(0.05)` 让任务真正进入 await。
2. **`logging_setup.configure()` 会清空 root 的所有 handler。**
   在 `pipeline.start()` 之前挂的测试 handler 会被移除，捕获到空字符串 ——
   那会让后续所有断言**假通过**（空串里当然没有"裁剪异常"）。必须在 `start()`
   之后再挂，并额外断言"日志确实非空"来防止这种假通过。
