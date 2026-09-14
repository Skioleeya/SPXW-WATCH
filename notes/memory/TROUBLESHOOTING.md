# 核心避坑指南（已踩坑记录）

> 本文件 = T1 层：已验证的陷阱、已证伪的假设、踩过的坑。
> 更新时同步改 `MEMORY.md` §3 的时间戳。
> 归档标准：>1 个月无复现且无相关改动的条目，移入 `archive/`。

---

## 1. IBKR 限速与配额

### 1.1 两个"限流"别混
- `health.rate_limit` = 库层**消息速率**（超限 Error **100**，连 3 次终止会话）
- `health.sub_limit_backoff` = **Error 300**（行情行数）退避
- 对应 `SubscriptionManager.in_backoff`/`limit_events`/`note_limit_hit()`
- **刻意不出现 `throttle*`** —— 属性名是信号，别混用

### 1.2 限速桶写入位置
- 配置 `ibkr.json::rate_limit_max_requests=45`/`rate_limit_interval_s=1.0`
- 经 `acquisition/rate_limit_watch.py` 写入 **`ib.client`**
- ⚠️ `IB` 类**不转发**，必须直接拿 `ib.client`
- `MaxRequests`/`RequestsInterval` 是类属性，`Client.reset()` 不清

### 1.3 忽略码
- `_IGNORED_CODES`（14 个，`feed_service.py:43`）
- `2119`/`10090` 是"**部分**未订阅"的环境通知，**非"无权限"**
- 忽略以免淹没真正的 100/300

## 2. 行情权限

- **按合约分档，不是全局**：SPXW 期权与 SPX 指数均实测 `marketDataType=1`
- `ibkr.json::market_data_type` **必须写 3**：3 = "有实时就给、没有才降级"（择优），**非**强制延迟
- 写 1 = 只接受实时，**任一份**订阅无权限即回 Error **354**、零 tick → `_await_spot` 超时退出（fail-closed）
- `health.mode` 派生自本键

## 3. 106 模型 Greeks

- `generic_tick_list: "106"` 确实推 `tickOptionComputation`
- 四档 greeks 并存且值不同 ⇒ MODEL_OPTION 独立通道
- ⚠️ `ib_async` 把 tickType 13/83 合并到同一属性
- `TickRouter.source_tick_type` 恒为 13（**名义值**）

## 4. 端口

- **端口 `4002`**（IB Gateway 模拟盘）—— 原 `7497` 报 `ConnectionRefusedError`

## 5. ECharts 版本

- **ECharts = 5.5.1**，zrender = 5.6.0
- `t.version` vs `t.dependencies.zrender`
- 另有内部 painter `version:"5.6.0"` —— 别搞混

## 6. 热力图配色

- `web/config.js::heatmap.palette` = Plotly **`Turbo` 15 色顺序色阶**
- **色板无机械回归**
- **ΔIV ≈ 0 不退回中性色**（KAI 决策，0 = 亮黄绿 `#a4fc3b`）

## 7. 已踩的历史坑（已修复，留档防回退）

| 时间 | 坑 | 根因 | 修复 |
|---|---|---|---|
| 09-11 | `SessionClock` 没实现 `ClockPort.now()` | 协议缺方法 | 实现协议 + 新增 `check_clock_protocol.py` |
| 09-11 | 死键 `state.json.prune_interval_s` | 配置写了但全仓无代码读 | 接进 L6 维护循环 |
| 09-11 | `visualMap.pieces` 在 ECharts 5.5.1 无效 | 版本 API 差异 | 改用 `inRange` + `color` |
| 09-13 | `web/skew.js` docstring 提前闭合 ⇒ 整文件语法错误 | 13 个回归全绿，但 `web/*.js` 从未被加载 | 新增 `check_web_syntax.py`（按目录枚举） |
| 09-13 | 分组回归期望前缀由分组表自推 ⇒ 删一组吞失败 | 守卫失明 | `group_guard.py`（独立常量前缀） |
| 09-13 | 热力图纵轴方向不一致（帧升序 vs 屏幕降序） | 两处未成对改 | KAI 定"屏幕降序"，统一全链路 |

## 8. 限速桶读数

- **不上前端**（KAI 决策，`web/` 不动）

## 9. IBKR 美国农场掉线 ⇒ Error 10197 / `SpotUnavailableError`

**现象**：`run.py` 启动即 fail-closed ——
`Error 10197 No market data during competing live session` 打在 reqId 4（SPX 指数）
+ 6/7/8（ES 期货），随后 `core.errors.SpotUnavailableError: 20s 内未收到标的现价`。
常驻进程则表现为**现价冻结**（2026-09-14 10:46:06 起 `7601.06` 恒定 58 分钟），
但仍照常推帧、日志里毫无异样。

**判据（三条一起看，缺一条都可能误判）**：

1. **`qualify` 成功而行情被拒** ⇒ 不是合约问题，是行情会话/农场。
   （合约详情走另一套服务，农场挂了它照样通。）
2. **`Error 1102` 的"已连接农场"清单里缺 `usfarm.nj` / `usfuture` / `usopt`** ⇒ 美国农场掉线。
   正常应为 `usfarm.nj; hfarm; usfuture; usopt; secdefhk`（`apachmds` 常掉，**不影响美股**，
   不要拿它当判据）。2026-09-14 盘中从 09:28 的完整清单掉到 11:25 的 `hfarm; secdefhk`。
3. **独立 `client_id` 探针复现** ⇒ 账户/网络级，与 `run.py` 代码无关。

**探针**：`tmp/probe_ibkr_spot.py` —— 独立 `client_id=99`、只读、不订期权，
打印 `managedAccounts` / 各合约 `marketDataType` / 全部错误码与农场事件。
**这是把"代码问题"与"外部条件"分开的最快手段；不要用反复重启 `run.py` 来试**
（两次同样的失败只是噪声，不是信息）。

**本机特有因素（2026-09-14）**：默认路由整个走 **`Meta Tunnel`**（Clash.Meta / mihomo TUN，
`198.18.0.0/30`，网关 `198.18.0.1`）；`ibgateway.exe` 的三个出站 ESTABLISHED 全部指向
`198.18.0.255:4001/4000`（fake-IP）。**香港农场活、美国农场死**的选择性
⇒ 优先怀疑代理规则/节点，其次才是 IBKR 侧。

**处置顺序**：① 代理给 IBKR 直连（或临时关 TUN）→ ② 重启 IB Gateway（强制重新登录 +
重连全部农场）→ ③ 再拉 `run.py`，验证 `订阅 81/92`（±20 生效的判据）。

**不要做**：放宽 `spot_ready_timeout_s`、改 `_await_spot`、反复重启 `run.py`。
前两者是对外部条件打补丁，会让"拿冻结指数顶上"重新变成可能（速查卡 H/I）。

**复盘注意**：`logs/spxw_swatch.log` **不含应用层告警**（`FeedService._note()` 不写 logging，
见项目 `MEMORY.md` 速查卡 R）。查"有没有告警"要看页面状态区，别只看日志。
