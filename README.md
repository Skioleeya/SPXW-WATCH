# SPXW SWATCH — 0DTE 日内 IV 动能雷达

把 SPX 当日期权（SPXW 0DTE）链上 **IV 的"变化速度"** 做成一张可盯的雷达图。

不是波动率曲面，不是持仓盈亏，不是 GEX 矩阵。只有两件事：

1. **日内动能热力图** —— 纵轴 ±12 档行权价（降序，高行权价在上），
   横轴是**整个交易日网格**（GTH 20:15 → 次日 09:25、RTH 09:30 → 16:00，
   30 秒一桶，共 2370 桶）的时间桶，可切「GTH / RTH / 全时段」，
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

# 启动：需要 TWS / IB Gateway 已开 API，端口与 client_id 见 config/ibkr.json
python run.py

# 浏览器打开
#   http://127.0.0.1:8060

# 架构与配置自检（不需要联网）
python run.py --check
```

辅助工具：

```bash
python tools/smoke_test.py                     # L0–L4 离线冒烟测试
python tools/check_side_flip.py                # 回归：取边翻转不得劈断热力图行历史
python tools/check_subscription_qualify.py     # 回归：订阅前必须确认合约
python tools/check_window_tolerance.py         # 回归：现价往返不得退订显示窗口内的档位（订阅/显示容差）
python tools/check_tick_router.py              # 回归：L1 分流层的模型值优先与脏值拦截
python tools/check_session_rollover.py         # 回归：跨会话不得共用桶序号
python tools/check_session_grid.py             # 回归：多会话网格铺满交易日、空档留白
python tools/check_clock_protocol.py           # 回归：注入下层的时间源必须满足 ClockPort
python tools/check_persistence.py              # 回归：SQLite 旁路持久化的写入 ↔ 恢复往返
python tools/check_web_contract.py             # 回归：前端引用 → 后端定义的对照
python tools/check_page_render.py              # 回归：真浏览器打开，断言画出来了
python tools/check_period_aggregation.py       # 回归：前端周期聚合 ↔ 后端定义逐值对拍
python tools/check_matrix_codec.py             # 回归：热力图数值块 Python 打包 ↔ JS 解包
python tools/check_web_syntax.py               # 门禁：web/*.js 必须能被 JS 解析器读通
python tools/check_skew_alignment.py           # 回归：Skew 折线与热力图列网格逐列对齐（含周期一致性）
python tools/check_skew_viewport.py            # 回归：Skew 图例两条同名曲线 / 刻度精度读配置 / 读数随视口
python tools/check_ws_compression.py           # 回归：WebSocket 必须真的协商 permessage-deflate
python tools/ws_probe.py --frames 24           # 作为独立客户端抓帧并校验结构
python tools/heatmap_stats.py                  # 打印矩阵里 ΔIV 的实际分布
python tools/heatmap_stats.py --rows           # 逐行覆盖情况（排查"空洞"用）
```

`tools/check_clock_protocol.py` 钉的是"注入下层的时间源必须满足 L0 的
`ClockPort`"。`TickStore` 拿到的时钟是组装层注入的 `SessionClock`，而它曾经
只提供 `now_ts()`、没有实现协议要求的 `now()` —— 于是 `prune()` 里那句
`self._clock.now()` 每 10 秒抛一次 `AttributeError`，被维护循环的 `except`
吞成一行 warning。表现出来只是"按时间窗裁剪从未真正发生"，缓冲区只靠 `maxlen`
兜底，`option_buffer_seconds` 形同虚设 —— 而所有探针、所有回归当时都是绿的。
这个脚本既断言三个时间源（`WallClock` / `FakeClock` / `SessionClock`）都满足
协议，也用真实的 `SessionClock` 走一遍裁剪路径、断言过期样本确实被丢掉。
（`FakeClock` 是 `tools/fixtures.py` 里的测试夹具 —— 时间只随显式 `advance()`
前进，因此回归每次运行都落在相同的桶号上。）

`run.py --check` 里的第 [7] 项专门盯"配置键有没有接线"：它按工程既有的
`module=` 约定，把每处取键调用与它声明的配置文件对照。这项检查一上线就抓出
7 个**死键**（配置里写着、没有任何代码读），它们已全部定性处理完（4 接线、
3 删除），检查也随之收紧为"死键即失败"—— 详见 §10 已知边界。

`tools/ws_probe.py` 的存在是为了把"数据链路坏了"和"前端渲染坏了"分开定位 ——
页面白屏时，先跑它。

`tools/heatmap_stats.py` 用来回答"色标下限对今天的行情是不是设歪了"：
色标是纯呈现参数，但它直接决定信号看不看得见，只能靠实际分布来定，不能拍脑袋。
加 `--rows` 后逐行打印覆盖情况 —— 这是排查热力图上"空洞"的关键视图，因为洞既
可能是**真的没数据**，也可能是**有数据但值恒为 0**（渲染成背景色，看着像没数据），
两者修法完全不同。

`tools/check_tick_router.py` 补的是 L1 采集层的离线覆盖 —— 在此之前整层
`acquisition/` 从未被离线执行过：`app/pipeline.py::_build_feed` 里 `ib_async` 是
懒加载的，离线回归根本走不到那里，`acquisition/__init__.py` 又是刻意留空的。这正是
"只会在实盘暴露的 bug"能藏住的结构性原因（订阅前未确认合约那条就是从这里漏出去的）。它用忠实的假对象把
`TickRouter` 真跑一遍，钉住两条规则：`use_model_greeks=true` 时**拒绝**降级到
`lastGreeks`/`bidGreeks`（宁可无值，也不拿过期值冒充模型值），以及 IV 越界 / `None` /
`NaN` / `inf` 一律拦下、NaN 的 Greeks 归一化为 `None`。假对象自身先自证保真
（`marketPrice()` 在空数据时返回 `nan`，与 `ib_async` 一致），否则测试就成了自说自话。

`tools/check_session_rollover.py` 钉的是"两个交易日的 IV 不得被当成同一条序列"。
热力图与 Skew 序列的键都是**交易日网格内**的桶序号（`0..2369`，从 GTH 开盘
20:15 起算），只在一天之内唯一；跨会话
复用同一个键空间，新一天第 1 桶的 IV 会去减上一天第 1 桶的 IV，差出一个**凭空
造出来的冲量**。回归同时覆盖第二条泄漏路径：旧会话的 tick 不会被毛刺过滤器拦下
（`STALE` 属于可信质量），所以还必须按到期日把非本会话的合约过滤掉。

`tools/check_session_grid.py` 钉的是网格**几何**：`config/app.json` 的 `sessions`
被展开成一张铺满整个交易日、可跨午夜的时间桶网格（会话时长 + 会话之间的空档，
必须能被桶宽整除），区段表首尾相接无缝无叠，且**每个区段起点桶必须留白** ——
跨过 09:25–09:30 空档的第一笔 IV 若与空档前最后一笔做差，整段空档的变化会被压进
一个 30 秒桶，画出一堵与真冲量无法区分的假墙（与断线恢复是同一类假信号）。
判据全部从 `config` 推出来，不写死 20:15 / 09:25 / 2370。

`tools/check_web_contract.py` 做的是"引用 → 定义"的三向对照：JS 里 `el("x")` 引用的
DOM id 必须在 `index.html` 里存在；`CFG.a.b` 必须在 `config.js` 里存在；前端声明的
载荷字段路径必须在后端实际发出的帧里存在（**键缺失算失败，值为 null 不算** ——
`null` 是"还没到那个时间"的合法语义）。字段名差一个字母不会报任何错，只会安静地
渲染成 `--`，这个检查专门堵这种缝。

`tools/check_page_render.py` 是"没人真正看过页面"这个盲区的封口检查：用 headless
Chrome 打开面板，断言没有渲染回调异常、热力图与 Skew 的 meta 都已填充、canvas
已生成、顶栏读数不是占位符。它存在的直接原因是 Skew 面板曾经因为一个 `visualMap`
配置（`pieces` 模式）必抛异常而整块曲线画不出来 —— 而当时探针 20 项全绿、契约
检查也全绿。找不到 Chrome 时它会跳过并返回 0，不会把"没装浏览器"误判成"页面坏了"。
（那个异常的版本归属一度记错，见 §10。）

---

## 2. 分层架构（L0 → L6，单向）

```
L0  core/        环形缓冲、会话时钟、日志、异常
    contracts/   ← 层间唯一通信媒介（DTO + Protocol）
L1  acquisition/ IBKR 采集：合约、链解析、订阅管理、tick 路由
L2  state/       分片时序存储 + 只读聚合
L3  features/    毛刺过滤 → IV 冲量 → ΔIV 矩阵 → 25Δ Skew（+ 旁路持久化）
L4  serialization/ 契约对象 → JSON 文本
L5  transport/   HTTP 静态 + WebSocket 广播（fail-closed）
L6  app/         组装根（唯一允许 import 所有层的模块）
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
  app.json          SPX / IND / CBOE / SPXW / 时区 / sessions（会话定义，网格唯一真相）
  ibkr.json         连接参数、generic_tick_list="106"、IV 边界
  subscription.json ±档位、订阅总上限、重连与 Error 300 退避
  state.json        环形缓冲容量与年龄、健康阈值、本层自己的裁剪节奏
  features.json     冲量窗口、毛刺过滤五道闸门、25Δ 目标与容差
  persistence.json  旁路 SQLite 热备：开关、库路径、队列深度、写入间隔
  serialization.json 时间桶粒度、色标量程取法、小数位
  transport.json    监听地址、WS 路径、推送频率、客户端队列深度
  pipeline.json     计算/统计循环的节奏与生命周期
  logging.json      日志级别与格式
```

四条硬规则：

* **不硬编码。** 任何业务常量都必须来自配置。`loader.py` 刻意不知道模块名和
  字段名，也不提供业务默认值 —— 缺键就直接抛 `ConfigError`，而不是静默用一个
  谁也记不住的常数。
* **配置之间零引用。** 禁止 `$ref` / `include` / `extends` 之类的跨文件引用
  （检查项 [4]）。一旦允许交叉引用，改一个文件就得推演依赖图。
* **前端不复制后端取值。** 端口、WS 路径、推送频率由 `/runtime-config.js`
  在启动时注入 `window.SWATCH_RUNTIME`。`web/config.js` 里只有**呈现**参数，
  复制一份后端取值就等于制造"两份真相"。

第四条是检查项 [7] 加上的，也是**同一条"两份真相"原则在配置内部的延伸**：

* **一个键只属于一个模块，而且必须真的接线。** 每次取键都按既有约定写明
  `module="<配置模块>"`，检查项 [7] 拿它和实际配置文件对照。两个方向都会报：
  键被"非本模块"的代码读（键放错了文件），或者键**根本没有任何代码读**
  （死键 —— 看起来是个旋钮，拧了没有任何效果）。后一种情况现在直接判失败，
  不再是警告：配置项一旦没人读，它记录的就是一份过期的真相。

---

## 4. 采集层：为什么不会触发 Error 300

IBKR 对单连接的同时行情订阅有硬上限（100 条）。这里用三层独立防护：

1. **容量反推。** `ChainResolver.effective_each_side()` 从配置的总上限反推
   每侧最多几档，而不是无条件信任 `num_strikes_each_side`。
   当前：`±20 档 → 4×20 = 80 条`（自设上限 92，IBKR 上限 100）。
   窗口是 `below[-side:] + above[:side]`（**不含中心档**），× Put/Call 两个权利
   ⇒ `4 × num_strikes_each_side` 条；现货是另一条订阅，不计入该数。
   实盘核对：±12 → 48、±18 → 72、±20 → 80。
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

### 订阅窗口必须比显示窗口宽（容差）

热力图的纵轴行取自**显示窗口**（`features.json::heatmap_rows_each_side`），行情订阅
取自**订阅窗口**（`subscription.json::num_strikes_each_side`）。两个独立的半径，必须
留出余量：

```
容差（档） = num_strikes_each_side − heatmap_rows_each_side ≥ recenter_trigger_strikes
```

余量不足会出**时间空洞**。现价一移动，`WindowFollower` 就按触发步长重建窗口，
`cancel_stale_before_add` 让滚出窗口的档位**立刻退订**；那几档在现价往返期间收不到
任何 tick，而 `HeatmapEngine._prune()` **只按时间裁剪、从不按行权价裁剪** —— 该行
不会被删掉，只在中间空一截。现价回来之后空洞留在原地，看起来像数据源丢包。
**前端忠实渲染，错在订阅窗口没留容差。**

下限的推导：两次重建之间中心最多滞后 `T` 档（`T = recenter_trigger_strikes`），故现价
可探出已订阅窗口 `T` 档；要求「显示窗口最低一档不低于订阅窗口最低一档」即得
`S − R ≥ T`。2026-09-14 之前的配置两个半径都是 12（容差 0 档），这条空洞必然出现；
现在 `20 − 12 = 8 ≥ 3`，余量 5 档。

守这条的是一对：静态的 `run.py --check [6]`（配置算术），行为侧的
`tools/check_window_tolerance.py`（逐点重放窗口跟随，并用容差 `T−1` / `T` 两条对照
把边界钉死 —— 判据是推出来的，不是拿观测拟合的）。

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

订阅窗口是"以现价为中心的 ±12 档"，所以现价走动时纵轴也跟着走：新进入窗口的
档位在它进入之前**确实没有数据**，那一行左侧自然是空的。这是滑动窗口的固有
代价 —— 不可能有"当时没订阅的合约"的历史。想要一条全天固定的行权价轴，就得
放弃动态 ATM 窗口、改用固定区间订阅，那会白白占掉订阅额度。

### Skew 引擎（`features/skew_engine.py`）

25Δ Put IV − 25Δ Call IV，单位波动率点。两侧在 Delta 空间插值定位，容差由
`skew_delta_tolerance` 控制；插值点不足 `skew_min_points` 时判定为未定义。

### 旁路持久化：重启后接着画（`features/persistence.py`）

ΔIV 矩阵与 25Δ Skew 序列**不会因为服务重启而清零** —— 原始 IV 桶由
`AsyncPersistenceWriter` 异步写入 `data/session.db`（SQLite），启动时由组装层
`recover()` 回灌进 `HeatmapEngine` / `SkewEngine`。

三个设计点：

* **旁路**：写入走独立的 `asyncio.Queue`，队列满时**丢桶而不阻塞**行情主循环
  （丢桶数在日志里可见）。行情接收与 WS 推送的节奏完全不受磁盘 I/O 影响。
* **存原始 IV，不存 ΔIV**：ΔIV 是差分产物，前一个桶有没有值会改变差分结果。
  存原始值让恢复后的引擎**自己重走一遍差分**，语义与不中断时一致。
* **默认开启**（`persistence.json::enabled`）。置 `false` 时完全不碰 SQLite，
  行为与没有持久化时一致。

落盘快照的 `ivs` 键序由产出点显式排序为**降序**（高行权价在前），与对外帧的
`strikes` 同向 —— 冷数据与帧不再方向相反。由
`tools/check_persistence.py::_case_key_order_descending` 守着。

`data/` 在 `.gitignore` 里，不进版本控制。回归：`tools/check_persistence.py`。

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

### 线上体积：两级压缩，实测省 99%

| 措施 | 线上速率 | 一个交易日 / 客户端 |
|---|---|---|
| 无 | 184 KB/s | 4.41 GB |
| permessage-deflate | 16 KB/s | 0.40 GB |
| 再加「位图 + 定标整数」数值块 | ≈5 KB/s | **≈0.10 GB** |

第一级由 `config/transport.json::ws_compression` 显式开启（`aiohttp` 的
`WebSocketResponse` 默认就是 `compress=True`，但**靠库默认值等于没人知道也没人守**：
开关一次是 11 倍流量。`tools/check_ws_compression.py` 用裸 socket 握手断言扩展被
回显，并用"不 offer 扩展"做对照证明这组断言不是空转）。

第二级见 `serialization/bitmap_codec.py`：热力图矩阵 88% 的格子是空的，JSON 里
每个空格最少 5 字节（`null,`），实测占整帧 71%。改成「位图标记哪些格有值 +
小端 int16 定标整数只存有值的格」后，**在 deflate 之上再省 85%**。
前端镜像在 `web/matrix_codec.js`，两侧由 `tools/check_matrix_codec.py` 逐值对拍
（位序 / 字节序 / 遍历顺序三种缺陷都能抓住）。

---

## 7. 前端

原生 JS + ECharts 5.5.1（`web/vendor/echarts.min.js` 已本地化，完全离线可用；
内置 zrender 5.6.0，别把两者的版本号搞混）。

| 文件 | 职责 |
|---|---|
| `index.html` | 结构：顶栏读数、会话进度条、热力图、Skew、状态栏 |
| `style.css` | 深色主题，CSS 变量，等宽数字 |
| `runtime-config.js` | **由后端注入**（`window.SWATCH_RUNTIME`） |
| `config.js` | 仅呈现参数：重连退避、渲染节流、色板、小数位、「全时段」档的显示名 |
| `ws_client.js` | 断线指数退避 + 抖动、帧合并（只留最新）、缺口统计 |
| `period.js` | 时间周期切换：时段切列（`sliceZones`）、基线桶并组（ΔIV 相加）、尾部截断、色标重算、**Skew 列对齐（消费同一份切列映射）** |
| `matrix_codec.js` | 热力图数值块解包（位图 + 定标整数 → `block.values`） |
| `heatmap.js` | ECharts heatmap，`animation:false`，`progressive` 分片绘制 |
| `skew.js` | 25Δ Skew 主曲线 + ATM/Put25/Call25 副轴，纵轴不自动缩放 |
| `app.js` | 装配、渲染分发、陈旧看门狗 |

两个细节值得说明：

* **陈旧看门狗用本地收帧时间**，不用帧里的 `ts` —— 帧里的 `ts` 是**会话时间**
  （由 `SessionClock` 给出），它与墙钟之间没有固定关系（离线回归还会把它推进
  若干小时），拿它算"多久没更新"会立刻误报。
* **Skew 纵轴量程 = 当前视口内极值**，不让 ECharts 自动缩放。自动缩放会让曲线
  在剧烈波动时"看起来变平"，掩盖真实的量级变化；但若按**整条序列**取极值，早盘
  一次瞬时尖峰会把量程永久撑大，之后全天 0~1 的波动被压成一条平线。所以量程只认
  **眼前这一段**：滚轮放大到哪一段，纵轴就按那一段的高度自适应（0 恒在量程内）。
  ⚠️ 曾经按**时间窗口**（后端下发 `window_s` = 最近一小时）取极值，与视口无关 ——
  后果是缩放到早盘段时，早盘读数（+8.4）落在量程（按最近一小时算出的 0~0.84）
  之外，**整条曲线被裁到画面外、屏幕一片空白且不报错**（实测视口内 21/21 点越界）。
  2026-09-13 改为视口自适应，`skew.scale_policy` 这条链整体删除。
  meta 行的 `N/M 点` 与量程**同一口径**（都按可见列算，`SkewPanel::_readout`），
  缩放时由 `setViewportHook` 通知宿主立刻重写 —— 否则图缩到 21 列、读数仍报
  `780/780 点`。纵轴**刻度标签**的小数位来自 `web/config.js::skew.axisDecimals`，
  与 `decimals.skew` / `decimals.iv` 那套**数据精度**是两回事：刻度够分辨量级
  就行，位数给多了反而糊成一团。

### 时段切列：空档是"切掉"，不是"涂白"

顶栏有三个时段按钮：**GTH / RTH / 全时段**。按钮**不写死在前端** —— 时段真相在
`config/app.json` 的 `sessions`，由后端随帧下发到 `session.zones`（含 `id` /
`label` / `is_session` / `first` / `last`），前端照着生成。在前端抄一份 "GTH / RTH"
就是把会话定义抄了第二遍：后端加一个时段，前端不会跟着变，只会静默少一个按钮。

区段表里 `is_session=false` 的是两个会话之间的**空档**（09:25–09:30，5 分钟不交易）。
前端把它的列**整段切掉**（`period.js::sliceZones`），而不是填 `null`：横轴是类别轴，
填 `null` 只是不画颜色，那几列照样占宽度，屏幕上留一条空洞 —— 等于告诉人"这里本该
有数据"。切掉之后 GTH 段与 RTH 段直接相邻，与"这段时间没交易"的读法一致。

切列会破坏"桶号 → 列号"的整除关系（RTH 段每一点都左移了 10 列），所以
`sliceZones` 同时产出一份 `index` 映射，**两块图共用**：`alignSkew` 先查表再整除平移。
让 skew 自己再推一遍，就是把网格几何抄第二遍，切错一列不会有任何报错，只会让上下
两块图的横坐标指向不同时刻。**顺序也是契约**：必须先切列再并组 —— 反过来的话一个组
会横跨空档，把两个会话的桶并进同一列。

### 周期一致性：两块图共用一套列网格

前端有 30 秒 / 1 分钟 / 3 分钟 / 5 分钟 / 15 分钟五个周期标签。**选了哪个周期，
IV 热力图与 Skew 折线就必须都是哪个周期** —— 否则同一屏幕的横坐标在两块图里指向
不同时刻，上下没法对着看。

实现上只有**一份**列网格：热力图先算（`period.js::sliceZones` 切列 →
`aggregate` 并组 → `clipTail` 截尾），Skew 再对齐过去（`period.js::alignSkew`，
并消费 `sliceZones` 产出的那份 `index` 映射）。两处口径不同，各自算一遍就是把
分组与切列规则抄了两遍：

* 热力图聚合的是 ΔIV（**增量，可加**），组内求和 —— 望远镜相消后
  `Σ(k=a..b) ΔIV[k] = IV[b] − IV[a−1]`，是恒等式不是近似；
* Skew 是**水平量**（两点 IV 之差），组内求和没有金融含义，取**组内末值**
  （"这一格画的是该周期结束时的读数"，与 K 线取收盘价同理）。

回归 `tools/check_skew_alignment.py` 钉住这条链，且判据刻意避开恒真断言：
`alignSkew` 的 `label` 是从热力图网格**复制**来的，所以"两块图逐列标签相同"永远为
真、抓不到任何东西；真正可失败的是 **[C1]** 聚合确实发生、**[C2]** 每列的 `ts` 落在
该列覆盖的**时间区间**内（只用 `ts`，不碰 `bucket` 字段）、**[C4]** 取的是末值而非
首值、**[C6]** 量程窗口生效。切列与映射由 `tools/check_period_aggregation.py` 的
**[5][6]** 两组单独钉住（切列逐格对照 + 映射表逐元素对照，且"忽略映射"这条变异
必须被抓出来）。

### 前端脚本语法门禁

`tools/check_web_syntax.py` 按目录枚举 `web/*.js`，逐个跑 `node --check`。它存在
的直接原因是一次真实事故：改动把 `web/skew.js` 的模块 docstring 拆成两段、中间多留
了一个 `*/`，块注释提前闭合，后面的说明文字掉到注释外面，整个文件成了语法错误 ——
`window.SkewPanel` 根本不存在，**Skew 面板整块空白**。

而当时 `tools/` 里 13 个回归全绿：`check_period_aggregation.py` 只加载 `period.js`，
`check_matrix_codec.py` 只加载 `matrix_codec.js`，`check_web_contract.py` 只加载
`config.js` —— `skew.js` / `heatmap.js` / `app.js` / `ws_client.js` **没有任何检查器
加载过**。不是断言写错了，是根本没人在看这几个文件。门禁按目录枚举而不写死名单，
新增前端文件自动纳入。

---

## 8. 离线回归：不连 IBKR 也能验证 L0–L4

运行时是**纯实盘**的 —— 数据源只有 `IbkrFeed` 一条路径，没有模拟分支。但
L0–L4 的回归全部离线运行，靠的是 `tools/fixtures.py` 里的两件测试夹具：

* `FakeClock` —— 实现 L0 的 `ClockPort`，时间**只随显式 `advance()` 前进**，
  不掺真实时间流逝。同一份脚本每次运行都落在完全相同的桶号上，这是回归能给出
  确定性断言的前提。
* `SyntheticSurface` —— 解析式的 IV 微笑与 Delta 曲线，同参数必然同结果，
  不含任何随机数。

它们**不是产品代码**：位于 `tools/`，因此不参与分层检查（[2]）、单一职能检查
（[9]）与禁止硬编码检查（[10]），但仍受文件长度（[1]，< 400 行）与 `__slots__`
一致性（[8]）约束。夹具刻意只保留回归真正用到的部分 —— 随机噪声、冲击剧本、
毛刺探针都不在其中：回归走的是确定性路径，夹具越小，"测试通过"越能说明
产品代码本身正确。

`app/pipeline.py` 的 `_build_feed()` 用延迟 import、`acquisition/__init__.py`
刻意留空 —— 两者共同保证 `run.py --check` 与上述离线回归**永远不会加载
`ib_async`**（它是本工程唯一的重依赖，缺包时自检仍要能跑完）。

### 临时探针写在哪

一次性脚本与取样产物一律写在 **`<项目根>/tmp/`**（2026-09-13 KAI 定）。

此前它们散在用户级 `~/.workbuddy-ai/tmp/` —— 那个目录被**所有项目共用**，跨项目
串味、也没法按项目清理。约定当时写成"工程目录之外（`…/.workbuddy-ai/tmp/`）"，
省略号没指明是哪一级，而**只有用户级那个真实存在**，于是每次都落到那里。

落点换到工程内之后，必须同时在**两处**登记，缺一条就会误报：

| 位置 | 作用 |
|---|---|
| `.gitignore` 的 `tmp/` | 探针不入库 |
| `tools/selfcheck_core.py::NON_SOURCE_DIRS` 的 `"tmp"` | 不进 `iter_py_files()`，不被 `[1][2][9][10]` 误报 |

⚠️ 探针里几乎必然有硬编码（端口、URL、阈值），那正是 `[10]` 要抓的东西 —— 所以
排除表这一条不是"图省事"，是**必须**。

配套原则：**探针用完即弃，判据要落成常驻回归**（`tools/check_*.py`）才算数。只在
一次性探针里守着的东西，下次谁改坏了不会有任何东西报红 —— 2026-09-13 的
Skew 三项修复就踩过这个坑，现已落成 `tools/check_skew_viewport.py`。值得留档的
探针把源码贴进 `notes/sessions/<日期>/<task-id>/artifacts/`（`.txt`）。

---

## 9. 自检：五条硬性约束怎么变成可执行检查

`run.py --check` 共 11 项，把项目约束从"靠人记住"变成"跑一遍就知道"。
检查代码本身也按单一职能拆开：`tools/selfcheck.py` 只做编排，
`selfcheck_core` 是共享基础设施，其余各文件一组检查。

| # | 检查 | 对应约束 | 落地方式 | 强度 |
|---|---|---|---|---|
| [1] | 文件长度 | 文件 < 400 行 | 全量行数统计（`.py` + `web/*.js`） | **强**（全量） |
| [2] | 依赖方向 | L0→L1→…→L6 单向 | `LAYER_OF` 映射 + AST 扫描 import 方向 | **强** |
| [3] | 配置可读 | 禁止硬编码 | 10 份 JSON 逐个解析 | 强 |
| [4] | 配置零耦合 | 配置彼此独立 | 禁 `$ref`/`include` 等跨文件引用键 | 强 |
| [5] | 关键键存在 | 禁止硬编码 | 40 个关键配置项逐一核对 | 中 |
| [6] | 订阅容量 | 不触发 Error 300 | ±12 档 → 49 条 ≤ 自设 92 ≤ IBKR 100；显示窗口 ≤ 订阅窗口 | 强 |
| [7] | 配置键归属与接线 | 一个文件不得含跨模块变量 | 按 `module=` 约定对照归属；死键即失败 | **强** |
| [8] | `__slots__` 一致性 | 单一职能的静态护栏 | AST 比对声明与赋值 | **强** |
| [9] | 单一职能 | 单一文件单一职能 | 顶层公开类计数 + `__init__.py` 只做导出 | 中（粗粒度代理） |
| [10] | 禁止硬编码 | 禁止硬编码 | 模块级字面量扫描 + 逐条登记的例外表 | 中（仅模块级） |
| [11] | 出站限速桶容量 | 禁止硬编码 | 读 `ibkr.json` + `subscription.json` 核对跨文件不变量 | **强**（跨文件核对） |

四处**诚实声明的覆盖边界**，不假装它们比实际更强：

* **[1] 现已覆盖 `web/*.js`，并如实报出 3 个超限文件。** 纳入之前 `--check` 报
  "82 个文件全部合规"，对 `app.js` / `skew.js` / `period.js` **没有任何覆盖** ——
  那不是合规，是门禁缺口。纳入后 [1] 变红是**预期**的：红的是真实违规，不是门禁
  坏了。长度约束与语言无关，`.js` 进不了 AST 类检查（[2][9][10]），但进得了 [1]。
* **[9] 是粗粒度代理。** 它用"顶层公开类数量 ≤ 2"近似"职能数量"，拦住的是
  "一个文件里堆了好几个互不相关的类"这种最明显的违规。一个类也可以塞进三个
  职能 —— 那靠目录分层和人评审。异常分类与枚举是"定义词汇"这一个职能，天然
  是一堆类，因此按基类链识别后豁免。
* **[10] 只覆盖模块级字面量。** 函数体内的魔法数字不在范围内（需要更复杂的
  数据流分析，误报率高）。例外逐条登记在 `EXEMPT_CONSTANTS` 里并写明理由，
  只有"非可调参数"才准进表；例外表条目失效也会报警告，防止表本身腐烂。
* **[7] 的死键判定是失败而非警告。** 开关是
  `selfcheck_config.py::UNWIRED_IS_FAILURE`，已置 `True` —— 任何新出现的死键都会
  直接让 `--check` 变红。它曾经是 `False`：一次上线抓出 7 个死键、每个都需要产品
  决策，先留着警告免得自检长期变红。那 7 个已于同日逐个定性处理完（4 接线、
  3 删除，见 §10），开关随之收紧。

第 [8] 项是踩坑之后加的：`__slots__` 类里任何 `self.x = ...` 都必须已在
`__slots__` 中声明。这个错误在开发过程中反复出现四次，每次都只在运行时才暴露，
所以用 AST 静态检查彻底堵死。

`tools/group_guard.py`（2026-09-13 加）守的是**回归报告自身**的完整性。分组式回归
按前缀分组打印，若**分组表自己定义期望前缀集合**，删掉一组时期望集合跟着变小、
守卫失明 —— 而那一组的判据连报告都进不去：失败的判据一条都不计数、退出码仍是 0。
实测 `check_skew_viewport.py` 删掉 `[G4]` 组后，该组 3 条失败被静默吞掉、报告照样
"全部通过"。所以期望前缀是**独立常量**，且三条都查（分组表**恰好**覆盖期望集合 /
每条判据都被某个组认领 / 每个期望前缀都真有判据）；`guard_cases` 再对守卫自身做
非空转验证（削掉一组必须被报出来）。⚠️ `check_period_aggregation.py` 与
`check_skew_alignment.py` 有同样的分组结构、**目前完全没有守卫**，属待办。

当前状态：**[1] 门禁覆盖 90 个文件（83 个 `.py` + 7 个 `web/*.js`），其中 3 个前端
脚本超限** —— `skew.js` 536 / `app.js` 524 / `period.js` 490，2026-09-13 把
`web/*.js` 纳入 [1] 后暴露的**真实违规**（此前无任何覆盖），拆分待办；其余 10 项
检查全部通过，Python 侧最长 399 行（`tools/check_period_aggregation.py`）。

---

## 10. 已知边界

* **多会话网格（GTH + 空档 + RTH）与时段切列只做过离线验证（2026-09-13）。**
  `core/clock.py` 的 `SessionClock`、`session.zones` 随帧下发、前端的
  `sliceZones` / `alignSkew(index)` 三处改动全部由离线回归覆盖（
  `check_session_grid` / `check_period_aggregation` 的 [5][6] 两组 /
  `check_skew_alignment`），但**没有一张真实链路的截图**。2026-09-13 是周日，
  无当日 SPXW 到期 ⇒ 服务 fail-closed（`ChainResolveError`），起不来。
  下一交易日盘中需确认：`mode` 正确、48 条订阅、热力图出图（纵轴高行权价在上）、
  两块图横轴按同一周期对齐、GTH / RTH / 全时段三个按钮切换正常。
  ⚠️ 另有 4 个检查（`check_web_contract` / `check_page_render` /
  `check_ws_compression` / `ws_probe`）**从此只有盘中能跑** —— 模拟盘已物理删除，
  服务无法在非交易日常驻；盘前/盘后/周末"回归全绿"永远不成立，这是取舍的必然结果。
* **SPXW 的 GTH 收盘是 `09:25`，不是 IBKR 脚注写的 `09:15`。** SPXW 属 GTH 品种：
  ET `20:15 → 09:25`（周日 20:15 起）+ RTH `09:30 → 16:00`，中间 5 分钟空档。
  IBKR 的 `cboe.php` 脚注 3 与 overnight 脚注 5 都还写着 GTH 止 **9:15 AM**，而
  Cboe/OPRA 自 2024-08-26 起已是 **9:25** ⇒ **时段以 Cboe/OPRA 为准，别抄 IBKR 脚注。**
* **"IB Gateway 在 GTH 对 SPXW 推实时 tick" 只有间接证据。** 依据是"可交易 +
  OPRA 有 GTH 报价流 + IBKR 分发"，**未取到直证**；且期权隔夜行情**不含**在免费的
  隔夜股票行情里，需 OPRA 订阅。首日盘中验证要专门确认这一点。
* **端口必须与客户端类型匹配。** `config/ibkr.json` 默认 `4002`，指向
  **IB Gateway 模拟盘**（本项目实测联通用的就是它）。换客户端类型时必须同步改，
  否则连不上：

  | 客户端 | 实盘 | 模拟 |
  |---|---|---|
  | TWS | 7496 | 7497 |
  | IB Gateway | 4001 | 4002 |

  连接失败时会打印包含这条提示的错误信息，不会只丢一个裸的 socket 错误。
* **`zoneinfo` 在 Windows 上需要 `tzdata`**。`requirements.txt` 里带了它，并
  注明了原因 —— 否则会得到 `ZoneInfoNotFoundError: 'America/New_York'`。
* **实盘链路已实测联通，106 模型 Greeks 落地已证实（2026-09-11）。**
  `run.py --live` 需要 TWS / IB Gateway 在 `config/ibkr.json` 指定的端口
  （默认 `4002`）上开启 API。实测：**11～14 秒就绪**，错误码仅
  `72 × Error 10090`（无 100/300/200）；`tools/ws_probe.py` 全过
  （72/92 订阅、热力图 36 档 × 25 桶、36 格有效数值、25Δ Skew 与现价均有值）。
  ⚠️ 该次实测的档位配置为 **±18 档**（72 条 option 订阅 + 1 条现价）。2026-09-13
  起改为 **±12 档**，按同一口径应为 48 条订阅 / 热力图 24 档 ——
  **该数值尚未在交易日实测**（周末无法起服务，见 `notes/context/open_tasks.md`）。
  直接订阅探针另证：`generic_tick_list: "106"` 确实让 IBKR 推送
  `tickOptionComputation`，`ticker.modelGreeks` 第 5s 出现，且与 bid / ask / last
  三档 greeks **四者并存、值互不相同** ⇒ MODEL_OPTION 是独立 tick 通道，
  项目拿到的 IV / Δ 就是这一组（`use_model_greeks: true` 时其余三档被拒）。

  ⚠️ 两点必读：

  1. **状态行里的 `delayed` 是配置键推导出来的，不是观测值。** `health.mode`
     由 `ibkr.json::market_data_type=3` 经 `FeedMode.from_market_data_type()`
     得出 —— 写 3 就**恒显示** `delayed`，与账户实际拿到什么无关（3 的语义是
     "有实时给实时、没有才降级"，是**择优**）。要看**某一份订阅**实际是实时
     还是延迟，得看 `ticker.marketDataType`（1 实时 / 3 延迟）。实时权限本身是
     **账户侧配置**，换账户 / 换机器后必须重新确认。
  2. **Error 10090 的原文是 "Part of requested market data is not subscribed"
     （部分未订阅），不代表没有权限** —— 别拿它判断状态。
     另：`ib_async` 把 tickType 13（实时模型）与 83（延迟模型）合并到同一个
     `modelGreeks` 属性，**属性层无法区分**，所以 `TickRouter.source_tick_type`
     恒为 13，是名义值不是观测值。
* **不依赖 numpy / pandas。** 全链路纯标准库 + `ib_async` + `aiohttp`，
  降低部署摩擦（毛刺过滤用的 MAD、分位数统计都是手写的）。
* **不做本地 IV 重算。** 这是设计约束而非能力缺失：本地重算的 IV 与券商
  推送的 IV 会出现微小偏差，在盯"变化量"的场景里这种偏差本身就是噪声。
* **时间桶是交易日网格内的坐标，必须按交易日隔离。** 桶序号 `0..2369` 不带日期
  （`0` = GTH 开盘 20:15），所以会话身份只能从时钟取（取当日到期日 —— 0DTE 的
  到期日就是这张合约的身份）。跨会话
  有两条独立泄漏路径，都必须堵：一是桶序号被复用（靠 `FeatureEngine._sync_session()`
  翻篇时 `reset()`），二是旧会话的 tick 被判为 `STALE`（可信）后写进新会话的桶
  （靠 `_session_refs()` 按到期日过滤）。**两条都通向同一个后果：拿昨天的数据造
  今天的信号**，而且看上去完全正常 —— 颜色、量级都对，只是它从来不存在。
  这条约束的回归是 `tools/check_session_rollover.py`。
* **`visualMap` 的 `pieces` 模式在本项目的 ECharts 上不可用。** 版本要说准：
  本地 `web/vendor/echarts.min.js` 是 **ECharts 5.5.1**，内置 **zrender 5.6.0**
  （文件里 `t.version="5.5.1"`、`t.dependencies={zrender:"5.6.0"}`）—— 本节此前
  把版本写成了 "ECharts 5.6.0"，那是 zrender 的版本号，不是 ECharts 的。
  只要用 `pieces`，渲染时必抛
  `Cannot read properties of undefined (reading 'coord')`，
  整块面板渲染中断（`type:'piecewise'` / `show:true` / 二维数据 / 去掉
  `seriesIndex` 全都一样失败；`continuous` 模式正常）。因此 Skew 的正负着色改成
  把主序列**拆成两条曲线**、各自固定颜色、另一侧填 `null` —— 效果与硬分割
  一致，且不依赖 visualMap 的实现细节。两条曲线的 series `name` **必须不同**
  （`25Δ Skew` / `25Δ Skew·负`），再靠 `legend.formatter` 抹成同名**显示**：
  真给同名的话，ECharts 图例按 name 去重后只剩一条、且只带暖色，图例就只
  说明了曲线的一半（实测图例带冷色像素 0，而画布上冷色 1744px）。
  提示框同样过 `displayName`，免得内部后缀漏到界面上。
* **会话翻篇瞬间面板会短暂留上一场的画面。** 前端在收到 `heatmap: null` 时会保留
  上一帧（刻意如此，避免闪白），而翻篇后后端确实会先给出空矩阵直到新数据到来。
  此时状态行的会话进度会显示 `0/2370`，据此可区分"画面是上一场的"与"当前真的没
  数据"。这是刻意的取舍，不是缺陷。
* **死键已清零，而且从此不会再悄悄出现。** 检查项 [7] 上线时一次抓出 7 个"写着
  但没有任何代码读"的配置键。它们比硬编码更难发现 —— 硬编码至少能在代码里搜到，
  死键搜不到，只能靠静态对照。这 7 个已逐个定性并处理完：

  | 配置 | 键 | 处置 | 理由 |
  |---|---|---|---|
  | `transport.json` | `access_log` | **接线** | 代码里曾硬编码 `access_log=None`，配置写了也不生效，同时违反第 3 条 |
  | `ibkr.json` | `max_underlying_age_s` | **接线** | 防用陈旧现价重建窗口 —— 会订错档位且不报任何错，属正确性问题 |
  | `pipeline.json` | `shutdown_timeout_s` | **接线** | 停机保底退出，并顺手修掉吞掉 `CancelledError` 的反模式 |
  | `pipeline.json` | `reset_feature_state_on_reconnect` | **接线** | 防跨断线的 IV 跳变被误判为冲量；默认值仍为 `false`，行为不变 |
  | `features.json` | `atm_max_bracket_strikes` | **删除** | 配套的 `atm_bracket()` 是死代码，实际在用 `nearest_strike()` |
  | `ibkr.json` | `handshake_timeout_s` | **删除** | `connectAsync(timeout=)` 已是连接+握手的总超时，再拆一个属重复建模 |
  | `ibkr.json` | `chain_ready_timeout_s` | **删除** | "链就绪"没有明确信号，判据只能靠启发式；`chain_settle_s` 已够用 |

  三条值得记下来的坑：

  1. **`access_log` 接线不能传 aiohttp 的 `aiohttp.access` logger。** 它在
     `core.logging_setup` 的第三方降噪列表里被压到 `WARNING`，而
     `AccessLogger.enabled` 判的是 `isEnabledFor(INFO)` —— 传进去会被算成
     "未启用"，配置写 `true` 也永远不出日志。改用项目自己的 `transport.access`
     命名空间才真正生效（实测：`false` 捕获 0 行、`true` 捕获 1 行）。另外
     aiohttp 的 `RequestHandler` 默认就是 `access_log=access_logger`（**默认
     开启**），所以**不能**把 `access_log=None` 这个参数简单删掉 —— 删了等于
     意外打开访问日志。
  2. **`shutdown_timeout_s` 要用 `asyncio.wait` 而不是 `wait_for`。**
     `wait_for` 超时后会 cancel 目标并**继续等它结束**；目标若在取消后还要跑
     很久，所谓"上限"就是假的。这一点被非空转验证实测抓到：一个清理需 3s 的
     任务，用 `wait_for` 时 `stop()` 会等满 3s，换成 `asyncio.wait` 后如实
     在 2s 上限处放弃并打印「强制继续关闭」。
  3. **`reset_feature_state_on_reconnect` 的链路必须绕组装层。** L1 不认识 L3，
     所以钩子写进了 `FeedPort` 协议，而不是只长在 `IbkrFeed` 上 —— 否则换个
     数据源或新写一个实现就会静默漏掉它。这与 `ClockPort.now()` 的教训同源：
     接口不写进协议，实现就会漏、调用方就得碰运气。

  （`state.json` 的 `prune_interval_s` 曾是第 8 个死键，已接线：裁剪节奏改由
  L2 自己拥有，组装层只按它驱动循环。）
* **页面渲染需要真浏览器才能验证。** 数据链路与字段契约都可以离线校验，但"画没
  画出来"不行 —— `tools/check_page_render.py` 用 headless Chrome 补上这一环。
  它依赖本机装了 Chrome；找不到时会跳过（返回 0）而不是误报失败。
