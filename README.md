# SPXW SWATCH — 0DTE 日内 IV 动能雷达

把 SPX 当日期权（SPXW 0DTE）链上 **IV 的"变化速度"** 做成一张可盯的雷达图。

不是波动率曲面，不是持仓盈亏，不是 GEX 矩阵。只有两件事：

1. **日内动能热力图** —— 纵轴 ±18 档行权价，横轴 09:30→16:00 的分钟桶，
   颜色 = ΔIV（波动率点），即"哪个行权价在哪个时刻被重新定价"。
2. **25Δ Skew 实时折线** —— 25-Delta Put 与 25-Delta Call 的 IV 之差，
   用于捕捉恐慌态切换。

> 为什么画 ΔIV 而不是 IV：0DTE 的 IV 绝对水平在日内几乎是一条平线，画出来是
> 一片均匀色块。有信息量的是**变化**。

---

## 1. 快速开始

```bash
# 依赖（Windows 上 tzdata 是必需的，见 §6）
pip install -r requirements.txt

# 离线模拟：无 TWS、无行情权限也能跑通全链路
python run.py --sim

# 浏览器打开
#   http://127.0.0.1:8060

# 架构与配置自检（不需要联网）
python run.py --check

# 实盘：需要 TWS / IB Gateway 已开 API，端口与 client_id 见 config/ibkr.json
python run.py --live
```

辅助工具：

```bash
python tools/smoke_test.py                     # L0–L4 离线冒烟测试
python tools/check_side_flip.py                # 回归：取边翻转不得劈断热力图行历史
python tools/check_subscription_qualify.py     # 回归：订阅前必须确认合约
python tools/check_tick_router.py              # 回归：L1 分流层的模型值优先与脏值拦截
python tools/check_session_rollover.py         # 回归：跨会话不得共用桶序号
python tools/check_web_contract.py             # 回归：前端引用 → 后端定义的对照
python tools/check_page_render.py              # 回归：真浏览器打开，断言画出来了
python tools/ws_probe.py --frames 24           # 作为独立客户端抓帧并校验结构
python tools/heatmap_stats.py                  # 打印矩阵里 ΔIV 的实际分布
python tools/heatmap_stats.py --rows           # 逐行覆盖情况（排查"空洞"用）
```

`tools/ws_probe.py` 的存在是为了把"数据链路坏了"和"前端渲染坏了"分开定位 ——
页面白屏时，先跑它。

`tools/heatmap_stats.py` 用来回答"色标下限对今天的行情是不是设歪了"：
色标是纯呈现参数，但它直接决定信号看不看得见，只能靠实际分布来定，不能拍脑袋。
加 `--rows` 后逐行打印覆盖情况 —— 这是排查热力图上"空洞"的关键视图，因为洞既
可能是**真的没数据**，也可能是**有数据但值恒为 0**（渲染成背景色，看着像没数据），
两者修法完全不同。

`tools/check_tick_router.py` 补的是 L1 采集层的离线覆盖 —— 在此之前整层
`acquisition/` 从未被离线执行过：模拟模式在 `app/pipeline.py::_build_feed` 里懒加载
绕过它，`acquisition/__init__.py` 又是刻意留空的。这正是"只会在实盘暴露的 bug"能
藏住的结构性原因（订阅前未确认合约那条就是从这里漏出去的）。它用忠实的假对象把
`TickRouter` 真跑一遍，钉住两条规则：`use_model_greeks=true` 时**拒绝**降级到
`lastGreeks`/`bidGreeks`（宁可无值，也不拿过期值冒充模型值），以及 IV 越界 / `None` /
`NaN` / `inf` 一律拦下、NaN 的 Greeks 归一化为 `None`。假对象自身先自证保真
（`marketPrice()` 在空数据时返回 `nan`，与 `ib_async` 一致），否则测试就成了自说自话。

`tools/check_session_rollover.py` 钉的是"两个交易日的 IV 不得被当成同一条序列"。
热力图与 Skew 序列的键都是**会话内**桶序号（`0..389`），只在一天之内唯一；跨会话
复用同一个键空间，新一天第 1 桶的 IV 会去减上一天第 1 桶的 IV，差出一个**凭空
造出来的冲量**。回归同时覆盖第二条泄漏路径：旧会话的 tick 不会被毛刺过滤器拦下
（`STALE` 属于可信质量），所以还必须按到期日把非本会话的合约过滤掉。

`tools/check_web_contract.py` 做的是"引用 → 定义"的三向对照：JS 里 `el("x")` 引用的
DOM id 必须在 `index.html` 里存在；`CFG.a.b` 必须在 `config.js` 里存在；前端声明的
载荷字段路径必须在后端实际发出的帧里存在（**键缺失算失败，值为 null 不算** ——
`null` 是"还没到那个时间"的合法语义）。字段名差一个字母不会报任何错，只会安静地
渲染成 `--`，这个检查专门堵这种缝。

`tools/check_page_render.py` 是"没人真正看过页面"这个盲区的封口检查：用 headless
Chrome 打开面板，断言没有渲染回调异常、热力图与 Skew 的 meta 都已填充、canvas
已生成、顶栏读数不是占位符。它存在的直接原因是 Skew 面板曾经因为一个 `visualMap`
配置在 ECharts 5.6.0 上必抛异常而整块曲线画不出来 —— 而当时探针 20 项全绿、契约
检查也全绿。找不到 Chrome 时它会跳过并返回 0，不会把"没装浏览器"误判成"页面坏了"。

---

## 2. 分层架构（L0 → L6，单向）

```
L0  core/        环形缓冲、会话时钟、日志、异常
    contracts/   ← 层间唯一通信媒介（DTO + Protocol）
L1  acquisition/ IBKR 采集：合约、链解析、订阅管理、tick 路由
L2  state/       分片时序存储 + 只读聚合
L3  features/    毛刺过滤 → IV 冲量 → ΔIV 矩阵 → 25Δ Skew
L4  serialization/ 契约对象 → JSON 文本
L5  transport/   HTTP 静态 + WebSocket 广播（fail-closed）
L6  simulator/   合成行情源、合成时钟
    app/         组装根（唯一允许 import 所有层的模块）
```

数据流严格单向，反向**没有任何一条路径**：

```
feed (L1) ──tick──▶ store (L2) ──series──▶ engine (L3)
                                              │
                                           bundle
                                              ▼
                    server (L5) ◀──json── builder (L4)
```

这条规则不是靠约定维持的，而是靠 `contracts/` 作为 L0 契约层结构性地保证：
L2 拿到的是 L0 的 `FeedStatus` 而不是 `IbkrFeed` 对象；L5 拿到的是成品字符串
而不是 L4 的编码器。因此**传输层拿不到 store，特征层拿不到 socket** —— 这正是
"前端卡顿不影响行情连接"的结构性保证，而不是一句设计意图。

`run.py --check` 的检查项 [2] 用 AST 扫描每个文件的 import，对照 `LAYER_OF`
映射表逐条验证方向，出现反向依赖会直接失败。

---

## 3. 配置：一模块一文件，零交叉引用

```
config/
  loader.py         通用加载器（不认识任何模块名与字段名，缺键即失败）
  app.json          SPX / IND / CBOE / SPXW / 时区 / 会话时段
  ibkr.json         连接参数、generic_tick_list="106"、IV 边界
  subscription.json ±档位、订阅总上限、重连与 Error 300 退避
  state.json        环形缓冲容量与年龄、健康阈值
  features.json     冲量窗口、毛刺过滤五道闸门、25Δ 目标与容差
  serialization.json 时间桶粒度、色标量程取法、小数位
  transport.json    监听地址、WS 路径、推送频率、客户端队列深度
  simulator.json    合成行情与合成时钟参数
  pipeline.json     计算/裁剪/统计循环的节奏
  logging.json      日志级别与格式
```

三条硬规则：

* **不硬编码。** 任何业务常量都必须来自配置。`loader.py` 刻意不知道模块名和
  字段名，也不提供业务默认值 —— 缺键就直接抛 `ConfigError`，而不是静默用一个
  谁也记不住的常数。
* **配置之间零引用。** 禁止 `$ref` / `include` / `extends` 之类的跨文件引用
  （检查项 [4]）。一旦允许交叉引用，改一个文件就得推演依赖图。
* **前端不复制后端取值。** 端口、WS 路径、推送频率由 `/runtime-config.js`
  在启动时注入 `window.SWATCH_RUNTIME`。`web/config.js` 里只有**呈现**参数，
  复制一份后端取值就等于制造"两份真相"。

---

## 4. 采集层：为什么不会触发 Error 300

IBKR 对单连接的同时行情订阅有硬上限（100 条）。这里用三层独立防护：

1. **容量反推。** `ChainResolver.effective_each_side()` 从配置的总上限反推
   每侧最多几档，而不是无条件信任 `num_strikes_each_side`。
   当前：`±18 档 → 4×18+1 = 73 条`（自设上限 92，IBKR 上限 100）。
   `guard_capacity()` 在超限时**抛异常**而不是"尽量多发几条"。
2. **先撤后订。** 换档时先取消旧订阅再发新订阅，避免瞬时数量翻倍。
3. **Error 300 指数退避。** 一旦被限流，暂停新增并逐步退避到上限，恢复后
   自动 `resubscribe_all()`。

IV 与 Greeks **全部来自券商推送**：`reqMktData(contract, "106", ...)` 里的
`"106"` 是打开 `tickOptionComputation` 的开关，`TickRouter` 只读
`ticker.modelGreeks`（Tick ID 13，延迟模式下 83）。`use_model_greeks=true` 时
会**拒绝**回退到 bid/ask/last Greeks。

> 本地不做任何高频 BSM 重算。25Δ 定位用的是 `DeltaLocator` —— 在**券商给的
> delta** 上做线性插值，不是重新算 delta。

### 订阅前必须先确认合约（qualify）

`ib_async` 用 `hash(contract)` 索引 ticker，而 `Contract.__hash__` 在
`conId == 0` 时**直接抛 `ValueError`**：

```
Contract Option(...) can't be hashed because no 'conId' value exists.
Qualify contract to populate 'conId'.
```

`reqMktData` 的第一件事就是 `wrapper.startTicker` → `hash(contract)`，所以
**未确认的合约根本订阅不了**。期权合约必须先在 `qualify_many()` 里回填 conId
（`qualifyContractsAsync` 会原地更新传入对象，返回值与输入等长、失败位为 `None`），
再交给 `reqMktData`。

这条曾经真的踩了：期权走 `option_from_ref()` 生成、从未 qualify，而订阅处的
`except Exception: return` 又把异常静默吞掉 —— 实盘会"启动成功、报告就绪、
然后整场收不到任何期权数据，且没有任何报错"。现在订阅失败会记进
`SubscriptionPlan.failed` 并上报到界面状态栏，绝不静默。
`tools/check_subscription_qualify.py` 是这条规则的回归测试。

批量确认按 `qualify_batch_size` 分批（默认 40）并留间隔，因为一次性并发上百个
`reqContractDetails` 会触发 IBKR 的每秒消息数限流。

---

## 5. 特征层：五道闸门与两个引擎

### 毛刺过滤（`features/glitch_filter.py`）

0DTE 下午盘，深度虚值期权价格会跌到 0.05 以下，此时 IV 本质上是"极小时间价值
÷ 极小价格"，分母效应会让它在毫无信息的情况下飙到 200%。五道闸门任一不过即
判为 `GLITCH`：

1. IV 绝对值越界
2. 期权绝对价格过低 ← **分母效应的根因**
3. 与上一笔 tick 的跳变超过阈值
4. 偏离近期中位数超过 `mad_multiplier` 倍 **MAD**（用 MAD 而非标准差，
   因为标准差本身会被离群点污染）
5. tick 过旧

被标记的点**不会**进入热力图与 Skew 计算 —— 一个毛刺点会同时污染它自己的冲量和
整个时间桶的差分，所以必须"先过滤再算动能"。

这条排除规则只在 L0 的 `TRUSTWORTHY_QUALITIES` 里定义一次。曾经它在特征编排器、
热力图引擎、Skew 引擎里各写了一遍，后两者漏掉了 `GLITCH`，导致过滤器拦下来的
尖峰转头就被写进矩阵（实测能到 32 个波动率点，一个完全虚假的信号）。
`tools/smoke_test.py` 里有一条针对性回归：注入 ×10 尖峰并断言它进不了矩阵。

### IV 冲量引擎（`features/impulse_engine.py`）

逐档计算 ΔIV/Δt，窗口长度来自 `impulse_windows_seconds`（默认 60 / 300 秒）。
历史不足时返回空窗口，而不是编一个数出来 —— `RingBuffer.at_or_before()` 在
找不到容忍范围内的时间点时返回 `None`，"历史不足"因此是一个显式状态。

### 热力图引擎（`features/heatmap_engine.py`）

按时间桶累积每档 IV，然后**前向填充 + 取相邻桶差分**得到 ΔIV 矩阵。
前向填充是必要的：并非每档每分钟都有成交，直接留空会让矩阵碎成噪点；沿用
上一个已知 IV 后，没有成交的桶自然得到 0 变化，语义正确且视觉连续。

矩阵里的 `null` 表示"还没到那个时间桶"，与 `0`（"IV 没变"）语义完全不同，
前端会跳过 `null` 而不是填 0。

**行的身份只认行权价，不认方向。** 每档只取虚值一侧，而现价一旦穿越某档，
这一行的取边就会从 Put 翻成 Call。若时间桶按 `(行权价, 方向)` 分键，翻转之后
这一行就看不到翻转之前的任何数据 —— 前半段明明采到了，却躺在另一个键下，
图上表现为"现价附近凭空出现一块黑色空洞"。方向不是行的身份，只是"当前读哪张
合约"的展示属性，因此键只认行权价。`tools/check_side_flip.py` 是这条规则的
回归测试。

### 纵轴会随现价滑动（已知特性，非缺陷）

订阅窗口是"以现价为中心的 ±18 档"，所以现价走动时纵轴也跟着走：新进入窗口的
档位在它进入之前**确实没有数据**，那一行左侧自然是空的。这是滑动窗口的固有
代价 —— 不可能有"当时没订阅的合约"的历史。想要一条全天固定的行权价轴，就得
放弃动态 ATM 窗口、改用固定区间订阅，那会白白占掉订阅额度。

### Skew 引擎（`features/skew_engine.py`）

25Δ Put IV − 25Δ Call IV，单位波动率点。两侧在 Delta 空间插值定位，容差由
`skew_delta_tolerance` 控制；插值点不足 `skew_min_points` 时判定为未定义。

---

## 6. 传输层：Fail-Closed 是怎么做到的

广播路径上**没有任何 await**：

```python
def broadcast(self, text: str) -> int:   # 同步函数
    for client in self._clients:
        self._offer(client, text)        # put_nowait，队满丢最旧
```

每个客户端一个 `asyncio.Queue(maxsize=1)`，入队用 `put_nowait`，队满时**丢弃
最旧的帧**而不是阻塞生产者。发送由每客户端独立的协程负责，并用
`asyncio.wait_for(send_str, timeout)` 兜底。

结果：生产者（特征计算循环）物理上无法被消费者拖慢。前端全部掉线、某个
客户端 TCP 窗口打满、浏览器主线程卡死 —— 特征循环与 IBKR 连接都不受影响。

另外 `json.dumps(..., allow_nan=False)` 是刻意的：Python 默认把 NaN 写成裸
`NaN`，那是**非法 JSON**，浏览器 `JSON.parse` 会直接抛错、整条推送链路静默
死掉。关掉之后，漏网的 NaN 会在服务端立刻炸出来，而不是在前端变成一片空白。

---

## 7. 前端

原生 JS + ECharts 5.5.1（`web/vendor/echarts.min.js` 已本地化，完全离线可用）。

| 文件 | 职责 |
|---|---|
| `index.html` | 结构：顶栏读数、会话进度条、热力图、Skew、状态栏 |
| `style.css` | 深色主题，CSS 变量，等宽数字 |
| `runtime-config.js` | **由后端注入**（`window.SWATCH_RUNTIME`） |
| `config.js` | 仅呈现参数：重连退避、渲染节流、色板、小数位 |
| `ws_client.js` | 断线指数退避 + 抖动、帧合并（只留最新）、缺口统计 |
| `heatmap.js` | ECharts heatmap，`animation:false`，`progressive` 分片绘制 |
| `skew.js` | 25Δ Skew 主曲线 + ATM/Put25/Call25 副轴，纵轴不自动缩放 |
| `app.js` | 装配、渲染分发、陈旧看门狗 |

两个细节值得说明：

* **陈旧看门狗用本地收帧时间**，不用帧里的 `ts` —— 模拟模式下会话时间被加速
  60 倍，拿它算"多久没更新"会立刻误报。
* **Skew 纵轴范围来自后端的 `skew_min`/`skew_max`**，不让 ECharts 自动缩放。
  自动缩放会让曲线在剧烈波动时"看起来变平"，掩盖真实的量级变化。

---

## 8. 模拟模式

`run.py --sim` 用 `SyntheticFeed` 替换 `IbkrFeed`，`SimClock` 替换墙钟。
因为 L1–L5 全部通过 L0 契约通信，**替换行情源不需要改动其他任何一层**。

合成时钟把 390 分钟的交易日压缩到约 6.5 分钟跑完（`session_speedup: 60`）。
关键在于下游完全不知道时间被加速了 —— `SessionClock` 只是拿到一个更大的 epoch
数值，分桶、到期日、剩余时间全部照常工作。

`acquisition/__init__.py` 刻意留空、`app/pipeline.py` 的 `_build_feed()` 用
延迟 import —— 两者共同保证离线模式下**永远不会加载 `ib_async`**。

场景 `chop_then_shock` 先横盘再向下冲击，并周期性在最外侧两档注入 3 倍 IV
尖峰，用来验证毛刺过滤既拦得住分母效应、又不误杀正常点。

---

## 9. 自检覆盖的六条约束

| 约束 | 落地方式 | 检查项 |
|---|---|---|
| 不可反向依赖 | `contracts/` 作为 L0 契约层，层间只交换 DTO 与 Protocol | [2] AST 扫描 import 方向 |
| 每个文件 < 400 行 | 单一职责拆分 | [1] 全量行数统计 |
| 模块化、单一职能 | 每文件一个类/一组纯函数 | [1] + 目录分层 |
| L0→L1→…→L6 单向 | `LAYER_OF` 映射 + 组装根唯一例外 | [2] |
| 禁止硬编码 | 全部业务常量进 `config/`，`loader` 无业务默认值 | [3][5] |
| 配置按模块、零耦合 | 每模块一份 JSON，禁止跨文件引用 | [4] |

额外一条 [7] 是踩坑之后加的：`__slots__` 类里任何 `self.x = ...` 都必须已在
`__slots__` 中声明。这个错误在开发过程中反复出现四次，每次都只在运行时才暴露，
所以用 AST 静态检查彻底堵死。

当前状态：**61 个 Python 文件，最长 386 行，全部检查通过。**

---

## 10. 已知边界

* **端口必须与客户端类型匹配。** `config/ibkr.json` 默认 `7497`，指向
  **TWS 模拟盘**。若你跑的是 IB Gateway，必须改成 `4001`（实盘）或 `4002`
  （模拟），否则连不上：

  | 客户端 | 实盘 | 模拟 |
  |---|---|---|
  | TWS | 7496 | 7497 |
  | IB Gateway | 4001 | 4002 |

  连接失败时会打印包含这条提示的错误信息，不会只丢一个裸的 socket 错误。
* **`zoneinfo` 在 Windows 上需要 `tzdata`**。`requirements.txt` 里带了它，并
  注明了原因 —— 否则会得到 `ZoneInfoNotFoundError: 'America/New_York'`。
* **实盘未验证。** `run.py --live` 需要 TWS / IB Gateway 在
  `config/ibkr.json` 指定的端口上开启 API。离线链路已完整验证；实盘的连接
  失败路径已实测（错误信息可操作），但"连上之后能否收到数据"尚未验证。
* **不依赖 numpy / pandas。** 全链路纯标准库 + `ib_async` + `aiohttp`，
  降低部署摩擦（毛刺过滤用的 MAD、分位数统计都是手写的）。
* **不做本地 IV 重算。** 这是设计约束而非能力缺失：本地重算的 IV 与券商
  推送的 IV 会出现微小偏差，在盯"变化量"的场景里这种偏差本身就是噪声。
* **时间桶是会话内坐标，必须按会话隔离。** 桶序号 `0..389` 不带日期，所以会话
  身份只能从时钟取（取当日到期日 —— 0DTE 的到期日就是这张合约的身份）。跨会话
  有两条独立泄漏路径，都必须堵：一是桶序号被复用（靠 `FeatureEngine._sync_session()`
  翻篇时 `reset()`），二是旧会话的 tick 被判为 `STALE`（可信）后写进新会话的桶
  （靠 `_session_refs()` 按到期日过滤）。**两条都通向同一个后果：拿昨天的数据造
  今天的信号**，而且看上去完全正常 —— 颜色、量级都对，只是它从来不存在。
  这条约束的回归是 `tools/check_session_rollover.py`。
* **`visualMap` 的 `pieces` 模式在本项目的 ECharts 5.6.0 上不可用。** 只要用
  `pieces`，渲染时必抛 `Cannot read properties of undefined (reading 'coord')`，
  整块面板渲染中断（`type:'piecewise'` / `show:true` / 二维数据 / 去掉
  `seriesIndex` 全都一样失败；`continuous` 模式正常）。因此 Skew 的正负着色改成
  把主序列**拆成两条同名曲线**、各自固定颜色、另一侧填 `null` —— 效果与硬分割
  一致，且不依赖 visualMap 的实现细节。
* **会话翻篇瞬间面板会短暂留上一场的画面。** 前端在收到 `heatmap: null` 时会保留
  上一帧（刻意如此，避免闪白），而翻篇后后端确实会先给出空矩阵直到新数据到来。
  此时状态行的会话进度会显示 `0/390`，据此可区分"画面是上一场的"与"当前真的没
  数据"。这是刻意的取舍，不是缺陷。
* **页面渲染需要真浏览器才能验证。** 数据链路与字段契约都可以离线校验，但"画没
  画出来"不行 —— `tools/check_page_render.py` 用 headless Chrome 补上这一环。
  它依赖本机装了 Chrome；找不到时会跳过（返回 0）而不是误报失败。
