# 开发规范与避坑指南

> 本文件 = T1 层：工程约束、接口约定、编码规则、回归纪律。
> 更新时同步改 `MEMORY.md` §3 的时间戳。

---

## 1. 工程约束（全部有机械校验）

| # | 约束 | 检查器 | 强度 |
|---|---|---|---|
| 1 | 代码文件 **< 400 行** | `selfcheck_structure.py` [1] | 强 |
| 2 | **单一文件单一职能**；顶层公开类 ≤ 2 | `selfcheck_duty.py` [9] | 中 |
| 3 | **禁止硬编码**；业务常量进配置 | `selfcheck_hardcode.py` [10] | 强 |
| 4 | **严格分层单向依赖** | `selfcheck_structure.py` [2] | 强 |
| 5 | **配置零耦合**；禁止跨文件引用 | `selfcheck_config.py` [3][5][7] | 强 |

**`web/*.js` 已于 2026-09-13 纳入 [1]**（`iter_web_scripts()`，按目录枚举）。暴露 3 项**真违规**：`app.js` 524 / `skew.js` 536 / `period.js` 490 超 400。KAI 决策不拆 ⇒ `--check` **长期 RC=1**。

## 2. 关键接口约定（静默错值型）

> 本节讲**接口该怎么写**；同属"静默错值型"的**故障判据**在 `QUICKREF.md`（速查卡 A–V）。
> 同一事实只留一处：本节不重复卡片内容，卡片也不重复本节的接口约定。

### 2.1 Skew 与热力图共用列网格
- `app.js::renderHeatmap` 返回 `view`，`period.js::alignSkew` 消费它
- 热力图聚合 ΔIV（可加，组内求和）；Skew 是**水平量**取**组内末值**
- ⚠️ `alignSkew` 的 `label` 复制自热力图网格 ⇒ "两块图标签相同"恒真、不可作判据
- 有效判据：**时间域**（每列 `ts` 落在该列区间内）

### 2.2 纵轴量程
- = **当前可见列**内极值 ∪ {0} + 留白（`skew.js::axisRange`）
- 随 `dataZoom` 视口走，**不按时间窗**（`scale_policy` 已全链路删除）

### 2.3 X 轴与缩放
- `boundaryGap: true`（`false` 会压左轴线）
- `dataZoom` inside，**不设 minSpan/maxSpan**，双击复位
- 窗口按**列索引**存（后端每帧追加列，百分比窗口会漂）
- **热力图不跟着缩放**

### 2.4 Skew 曲线命名
- **series name 必须不同**（`NAME_POS`/`NAME_NEG`）
- 靠 `legend.formatter` 抹成同名显示（真同名会被图例去重、只剩暖色）

### 2.5 刻度与读数
- 刻度位数：`skew.axisDecimals`（**≠** `decimals.skew`）
- meta 的 `N/M 点`：`_readout()` 按**可见列**算
- 缩放经 `setViewportHook` 重写（缩放不走 `update()`）

### 2.6 热力图纵轴 = 高行权价在上
- 帧 `strikes` 由 `HeatmapEngine.build()` 显式 `sorted(..., reverse=True)`
- `web/heatmap.js::yAxis.inverse = true` 让索引 0 在最上
- ⚠️ **两处必须成对改**：只改帧不设 `inverse`，屏幕翻转成"低价在上"

### 2.7 冷数据键序
- `dump_bucket()` 输出前 `sorted(..., reverse=True)`，与帧同向

## 3. 编码与传输

### 3.1 线格式（`serialization/bitmap_codec.py` docstring 为唯一真源）
- `heatmap.values` → `enc`/`scale`/`bm`/`i16`/`filled`
- `null` 语义不变（位图 0 位 = 原 null）
- ⚠️ **JS 里 `""` 是 falsy** —— 判"字段在不在"必须用 `=== undefined`

### 3.2 scale 推导
- 由 `10 ** impulse_decimals` 推导、随帧下发
- 超 int16 直接抛 `SerializationError`

### 3.3 WS 压缩
- `transport.json::ws_compression` → `ws_broadcaster` 显式传 `compress=`
- 靠库默认时开关一次 11 倍流量

## 4. 时间粒度

- **基线桶宽 = 30s**（`serialization.json::heatmap_bucket_seconds`）
- `heatmap_max_buckets` = `skew_series_max_points` = **2370**（全网格 GTH+RTH）
- 前端只做整数倍聚合（`web/period.js`），**不得复制基线桶宽**
- `maxColumns = 2370` = 全网格桶数 ⇒ 交易日内截断永不生效

### 4.1 聚合在前端
- ΔIV 可加：`Σ(k=a..b) ΔIV[k] = IV[b] − IV[a−1]` 恒等式 ⇒ 零损失
- 色标量程须前端同规则重算：`period.js::bound()` 是 `numeric.robust_bound` 的镜像

### 4.2 SPXW 时段
- ET **20:15–09:25 + 09:30–16:00**，**9:25–9:30 空档**
- SPXW 属 GTH 品种

## 5. 前端是空壳（KAI 2026-09-13 裁定）

- **不给 `web/` 加语义门禁** —— 后端报多少就渲染多少
- "网格自适应""行序"属后端 L3 不变量，前端复制即第二份真相

## 6. 回归与检查器纪律

### 6.1 基线验证命令

> ⚠️ **必须用带依赖的 venv 解释器，不要用裸 `python`。** 本仓库自带的
> `venv/Scripts/python.exe`（实测 Py 3.13.14 / `ib_async` 2.1.0 / `aiohttp` / `tzdata` 齐备）
> 即可；裸解释器没有 `ib_async` / `aiohttp` ⇒ `check_reconnect_flow`、`check_web_contract`
> 在 **import 阶段**就崩，且 `run.py --check` 的 `[13]` 会**误报**"端口开放但 WS 握手失败，
> 跳过动态检查"。同一份代码、同一时刻实测（2026-09-15 01:4x，服务在跑，同为 22 个检查）：
> 裸 `python` = **18 RC=0 / 4 RC≠0**；`venv` = **20 RC=0 / 2 RC=1**。
> **看到红先确认解释器，再怀疑代码。**

```
<VENV>/python.exe run.py --check                  # RC=0（14 组；2026-09-15 01:4x 实跑，需服务在跑）
<VENV>/python.exe tools/smoke_test.py             # RC=0
<VENV>/python.exe tools/check_*.py                # 22 个；20 RC=0 / 2 RC=1（2026-09-15 01:4x 实跑）
                                                  #   红 = check_page_render / check_ws_compression
                                                  #   ⚠️ 第二个红会随服务/行情状态换身份：10:3x 是
                                                  #   check_ws_compression，11:1x 是 check_web_contract
                                                  #   —— 都是"需服务在跑"那一类，别把当时的红名
                                                  #   当永久事实。09-15 01:4x 复现的就是它：
                                                  #   压缩比 70.7% < 80% 阈值。
<VENV>/python.exe tools/check_persistence.py      # RC=0（7/7）
<VENV>/python.exe tools/check_persistence_sessions.py # RC=0（7/7）一交易日一文件 + 历史归档（启动归档非当前会话；同名不覆盖）
<VENV>/python.exe tools/check_window_tolerance.py # RC=0（8 项，含 T−1 / T 边界对照）
<VENV>/python.exe tools/check_skew_viewport.py    # RC=0（21 项 + 7 变异）
<VENV>/python.exe tools/check_skew_colors.py      # RC=0（6 项 + 3 变异）三条 IV 曲线配色
<VENV>/python.exe tools/check_skew_alignment.py   # RC=0
<VENV>/python.exe tools/check_web_syntax.py       # RC=0（13 个 JS 文件）
<VENV>/python.exe tools/ws_probe.py               # RC=0（需服务在跑）
```

**[14] TickRouter 语义（2026-09-14 接入，此前是"孤岛回归"）**
`tools/check_tick_router.py` 原本谁也不调（`grep -rn check_tick_router tools/ run.py` 只命中它
自己的 docstring），已被 `selfcheck.py` 作为第 14 组接入。它守的是**采集层唯一被离线执行的
机会**：`acquisition/` 在模拟模式下被延迟 import 绕开，缺陷只在实盘暴露。用忠实模拟的
`ib_async` 结构断言 7 组语义（拒绝降级、IV 越界、标的分流、坏数据不打断整批等，共 27 条）。
- **子标题用 `1. ` … `7. `，不得用 `[1]` … `[7]`** —— 会与顶层 `--check` 编号撞车，
  让 `grep '^\[1\]'` 同时命中两处。
- 改造时把全局 `PASSED`（布尔）换成 `FAILURES`（计数），并在入口 `FAILURES = 0` 重置
  —— 已验证**重复调用幂等**（连跑三次返回 `0 0 0`）；不重置会跨次累积。

**两个已知红，都不是"随手就能改绿"的：**

- `check_ws_compression` —— **状态依赖，不是稳定红**：2026-09-14 10:3x 实测
  「压缩比 71.8% < 80% 阈值」，同日 11:1x 复跑却是 RC=0，两次之间只发生过 IBKR 断线
  （未动该门禁、也未动被测代码）。⇒ 红/绿随行情状态漂移，机制**未验证**。
  这也说明"绝对阈值"型的门禁不适合当基线锚点，见 §6.6。
- `check_page_render` —— 两件事叠加，**其中一件结构性不可能通过**：
  1. 断言「有且仅有一个周期处于选中态」（`tools/check_page_render.py:218`）把页面上**所有**
     `<button>` 收成一个列表，而页面有**两组**独立按钮（会话 `全时段/GTH/RTH` + 周期
     `30秒/1分/…`），各有一个 `on` ⇒ `len(chosen) == 1` **恒不成立**（实测选中 `全时段、1分`）。
  2. 虚拟时间窗口极窄：`--budget 14000` 太小（0 个 canvas）→ `20000` 面板全出图但报
     「数据陈旧 19s」→ `120000` 报「数据中断 55s」。旧记的「`--budget 60000` 即恢复」
     **已失效** —— 窗口会随首帧体积移动（当帧 161 KB）。⇒ 要修它，先改断言语义、再换掉
     虚拟时间方案，不是调个数就完事。

**node 沙箱的脚本清单只有一个来源**：`tools/skew_reference.py::WEB_SCRIPTS`。
`web/` 拆文件时忘了补它，会让回归在**驱动阶段**就崩（`P.alignSkew is not a function`）
—— 2026-09-14 修过一次，三个回归（skew_viewport / skew_alignment /
period_aggregation）同时红。加/删 `web/*.js` 后先看这里。

### 6.2 分组式回归守卫
- **期望前缀不得由分组表自推**（`known = [p for _, ps in GROUPS …]`）—— 删掉一组时期望集合跟着变小、守卫失明
- 守卫 `tools/group_guard.py`（期望前缀 = 独立常量；接口契约 `prefixes: tuple[str,...]`）

### 6.3 目录清点原则
- **回归覆盖面按"目录"清点**，别按"我记得测过什么"清点
- `web/*.js` 由 `tools/check_web_syntax.py`（按目录枚举）封口
- **"检查里写了" ≠ "检查里跑了"** —— 函数在、标题在，evaluate() 没串进去就是零次执行

### 6.4 变异锚点跟着代码位置走
- 变异表里的 `(文件, 原文)` 是**硬锚点**：代码被拆到别的文件后，锚点找不到原文，
  `--selftest` 会报"变异点已失效"。2026-09-14 `skew.js` 拆出 `skew_helpers.js` /
  `skew_option.js`，viewport 回归的 4 条变异全部失效（检查器**主动报出来**了，
  没有静默通过 —— 这是好设计，别把它改回去）。
- 判断"修复真的被守住"的唯一标准：**摘掉修复要能报 FAIL**。跑 `--selftest`。

### 6.5 测试夹具不得手写键表
- 回归里给引擎造配置时，**从真配置派生**：`dict(loader.load("serialization"))`
  （取浅拷贝 —— `loader.load` 带缓存，直接改会污染其它检查），与
  `tools/check_reconnect_gap.py` 同一手法。**不要手写整份键表。**
- 理由：`HeatmapEngine.__init__` 每加一个必读键，手写夹具就漏，而加载器按
  "缺键即抛错" fail-fast ⇒ **整条回归变红**。手写的测试夹具是**第二份真相**，必然漂移。
- 2026-09-14 实例：`tools/check_persistence.py` 手写 3 个键，`6828e3a` 新增
  `heatmap_max_ffill_buckets` 后它**自那天起就是红的**（`3/5 通过`）而无人察觉 ——
  因为没人按目录清点跑过全部 `tools/check_*.py`。已改为派生（`5/5`）。
- 排查手法：`git log -S '<新键>' -- tools/` 若只有产品代码命中、测试夹具没命中，就是漏了。

### 6.6 配置算术不变量：静态门禁 + 行为回归成对
- 只在配置里算数（`run.py --check [6]`）证明不了行为；只跑行为回归又慢又重。**成对**：
  静态那条永远跑、钉住下限；行为那条逐点重放机制，并**自带对照**把边界钉死
  （`tools/check_window_tolerance.py` 用容差 `T−1` / `T` 两条对照证明 `S − R ≥ T` 是紧的，
  而不是一个人为选的数字）。
- 不变量优先**推导**，不要拿观测拟合。`S − R ≥ T` 是从"两次重建之间中心最多滞后
  `T` 档"推出来的；拟合出来的绝对阈值会随观测漂移（`check_ws_compression` 就是例子）。
- 窗口那对不变量（2026-09-14）：
  - `heatmap_rows_each_side ≤ num_strikes_each_side`（显示 ≤ 订阅，超出的档永远没数据）
  - `num_strikes_each_side − heatmap_rows_each_side ≥ recenter_trigger_strikes`（容差下限，
    否则现价一走就退订显示档 ⇒ 行权价轴上的时间空洞）
- **测试夹具的靶档不得用 `strike_grid(...)[3]`**：那个阶梯是 `-each_side … +each_side`
  对称的，第 4 根的行权价会随**订阅**半径漂移（12 档 → 6455；20 档 → 6415，落到显示
  窗口之外 ⇒ 假红）。用 `tools.fixtures.display_window_strike()`，它锚在现价上并按
  显示半径设界。
- **`use_model_greeks` 必须为 `true`**（2026-09-14 加入，`selfcheck_config.py [6]` 尾部
  `_check_model_greeks_prerequisite`）：这是**跨模块耦合**——`config/ibkr.json` 的一个
  开关 ⇔ 热力图合并序列的正确性。热力图每档只留一条**不带方向**的 IV 序列，现价穿越
  行权价时取边 Put↔Call 翻转，只有 model 口径两侧同值（实测差 0.000）才无跳变；关闭后
  走 last 口径两侧差 5.5~6.3 个波动率点（色标仅 ±0.5）⇒ 每次穿越打出一根随现价漂移的
  竖直假亮条，**且不报任何错**。它此前只写在 `heatmap_engine.py` / `strike_window.py`
  的注释里（无门禁）。变异验证：置 `false` → `[FAIL]` + `RC=1`；置字符串 `"true"`
  → `[FAIL]`（类型错也要响）。逐档实测表见 `TROUBLESHOOTING.md §10`。

## 7. 环境

- **后台任务约 1 小时会被杀**（实测 1h0m49s）—— 盯盘须 KAI 在本地终端自己起 `run.py`
- **站点** `http://127.0.0.1:8060/`，行情 `ws://127.0.0.1:8060/ws`
- HTTP 比管道先就绪：`/health` 200 时 `frames` 可能仍为 0；判据 `frames > 0`
- 冷启动 <1 分钟 `ws_probe` 报「0 格」不是缺陷 —— 热力图存 ΔIV 差分，需 ≥2 桶
- **8060 常被长期运行的 `run.py` 占着**（再起报 `OSError 10048`）
- 临时探针一律写 `<项目根>/tmp/`，必须同时登记 `.gitignore` + `NON_SOURCE_DIRS`
