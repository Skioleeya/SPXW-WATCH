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

> ⚠️ **必须用项目自带的 `venv/Scripts/python.exe`，不要用裸 `python`。** 裸解释器没有
> `ib_async` / `aiohttp` ⇒ `check_reconnect_flow`、`check_web_contract` 在 **import 阶段**就崩，
> 且 `run.py --check` 的 `[13]` 会**误报**"端口开放但 WS 握手失败，跳过动态检查"。
> 同一份代码、同一时刻实测：裸 `python` = **15 RC=0 / 5 RC=1**；`venv` = **17 RC=0 / 3 RC=1**。
> **看到红先确认解释器，再怀疑代码。**

```
<VENV>/python.exe run.py --check                  # RC=0（13 组；2026-09-14 10:3x 实跑）
<VENV>/python.exe tools/smoke_test.py             # RC=0
<VENV>/python.exe tools/check_*.py                # 20 个；18 RC=0 / 2 RC=1（2026-09-14 10:3x 实跑）
                                                  #   红 = check_page_render / check_ws_compression
<VENV>/python.exe tools/check_persistence.py      # RC=0（5/5）
<VENV>/python.exe tools/check_skew_viewport.py    # RC=0（21 项 + 7 变异）
<VENV>/python.exe tools/check_skew_colors.py      # RC=0（6 项 + 3 变异）三条 IV 曲线配色
<VENV>/python.exe tools/check_skew_alignment.py   # RC=0
<VENV>/python.exe tools/check_web_syntax.py       # RC=0（13 个 JS 文件）
<VENV>/python.exe tools/ws_probe.py               # RC=0（需服务在跑）
```

**两个已知红，都不是"随手就能改绿"的：**
- `check_ws_compression` —— 压缩比 71.8% < 80% 阈值（需服务在跑）。是阈值与实测的取舍问题。
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
  因为没人按目录清点跑过全部 20 条。已改为派生（`5/5`）。
- 排查手法：`git log -S '<新键>' -- tools/` 若只有产品代码命中、测试夹具没命中，就是漏了。

## 7. 环境

- **后台任务约 1 小时会被杀**（实测 1h0m49s）—— 盯盘须 KAI 在本地终端自己起 `run.py`
- **站点** `http://127.0.0.1:8060/`，行情 `ws://127.0.0.1:8060/ws`
- HTTP 比管道先就绪：`/health` 200 时 `frames` 可能仍为 0；判据 `frames > 0`
- 冷启动 <1 分钟 `ws_probe` 报「0 格」不是缺陷 —— 热力图存 ΔIV 差分，需 ≥2 桶
- **8060 常被长期运行的 `run.py` 占着**（再起报 `OSError 10048`）
- 临时探针一律写 `<项目根>/tmp/`，必须同时登记 `.gitignore` + `NON_SOURCE_DIRS`
