# Project State — selfcheck-hardening

## 结论一句话

五条项目硬约束现在**全部有机械检查兜底**（此前只有 1、4 是硬的）；接死键的过程中
暴露出一个**从未被任何探针发现的运行期缺陷**：`SessionClock` 没实现 `ClockPort.now()`，
导致 L2 的时间窗裁剪一直在抛异常并被吞掉。

## 当前代码状态

- 文件数：**68 个 Python 文件**，最长 `acquisition/feed_service.py` = 376 行（上限 400）
- `run.py --check`：**10 项全过**（含 7 条 `[warn]` 死键，不阻塞）
- 回归：**8 个全过**（smoke / side_flip / subscription_qualify / tick_router /
  session_rollover / **clock_protocol（新增）** / web_contract / page_render）
- 端到端探针：`ws_probe` 20/20（矩阵 180 格、Skew 6 点）
- 页面实拍：热力图 36 档 × 19 桶 · 612 格；Skew 18 点；2 canvas；现价已填充

## 本会话的三件事

### A. 接死键：裁剪节奏归 L2

- `state/tick_store.py` 新增 `_prune_interval_s`（读 `state.json`）+ 只读属性
  `prune_interval_s`；`__slots__` 同步。
- `app/pipeline.py::_prune_loop` 改为 `interval = self._store.prune_interval_s`。
- `config/pipeline.json` 删掉 `prune_interval_s`（它属于 L2，不属于组装层）；
  `selfcheck_core.py::REQUIRED_KEYS["pipeline"]` 同步收缩为 `("compute_interval_ms",)`。
- 取值不变（10.0 → 10.0），**行为零变化**。

### B. 顺带修掉的真缺陷：SessionClock 不满足 ClockPort

- 现象：接线后服务日志每 10 秒一行
  `WARNING pipeline 裁剪异常: 'SessionClock' object has no attribute 'now'`。
- 根因：`contracts/ports.py::ClockPort` 要求 `now()`；`WallClock` 有，**`SessionClock`
  只有 `now_ts()`**。而组装层注入 L2/L3 的时钟恰恰是 `SessionClock`。于是
  `TickStore.prune()` 里 `self._clock.now()` 必抛 `AttributeError`，被
  `except Exception` 吞成 warning。
- 影响面：`prune()` 从未真正执行过 —— 缓冲区只靠 `maxlen` 兜底，
  `option_buffer_seconds` / `spot_buffer_seconds` 两个配置项形同虚设。
  `last_option_age_s` / `last_spot_age_s` 同病（当前无调用者，属潜伏）。
- 修法：给 `SessionClock` 加 `now()`（实现协议），`now_ts()` 改为它的别名。
- 回归：新增 `tools/check_clock_protocol.py`（协议一致性 + 真实裁剪路径），
  已做非空转验证（摘掉 `now()` 能复现原始 AttributeError）。

### C. 补齐三条机械检查 + 拆分自检

原 `tools/selfcheck.py` 386 行、只剩 14 行余量，加检查必然越界，故按单一职能拆分：

| 文件 | 职责 |
|---|---|
| `selfcheck.py` | 编排（只调用与汇总） |
| `selfcheck_core.py` | 共享常量、输出原语、AST 扫描工具 |
| `selfcheck_structure.py` | [1] 文件长度、[2] 依赖方向 |
| `selfcheck_config.py` | [3][4][5][6] + **[7] 配置键归属与接线** |
| `selfcheck_slots.py` | [8] `__slots__` 一致性 |
| `selfcheck_duty.py` | **[9] 单一职能** |
| `selfcheck_hardcode.py` | **[10] 禁止硬编码** |

新增三条检查的判定与已声明边界：

- **[7] 配置键归属**：按工程既有的 `module=` 约定（148 处取键调用，**0 处缺 `module=`**）
  把每处调用与它声明的配置文件对照。键错位 → FAIL；键无人读（死键）→ WARN。
  不另建"键→归属"映射表，避免制造第二份真相。
- **[9] 单一职能**：顶层公开类 ≤ 2（`contracts/`、`tools/` 豁免）+ `__init__.py`
  只做导出。**粗粒度代理**：一个类也能塞三个职能，那靠分层与评审。异常/枚举按
  基类链识别为"词汇表"豁免（否则 `core/errors.py` 的 15 个异常类会误报）。
- **[10] 禁止硬编码**：模块级字面量扫描。允许恒等值、空容器、dunder、配置模块名
  指针；其余须进 `EXEMPT_CONSTANTS` 例外表并写明理由（7 条：IBKR 协议错误码 ×3、
  IBKR tick ID 表、领域结构不变量 `_RIGHTS_PER_STRIKE`、方向语义映射、MIME 表）。
  例外表条目失效也会报警告，防表腐烂。**只覆盖模块级**，函数体内魔法数字靠评审。

## 非空转验证（注入违规 → 必须 FAIL）

| 注入 | 结果 |
|---|---|
| `state/market_state.py` 的 `module=_CFG` 改成 `"features"` | FAIL：键与文件错位 ✓ |
| `UNWIRED_IS_FAILURE=True` | FAIL：7 个死键全部转红 ✓ |
| `core/ring_buffer.py` 追加 3 个公开类 | FAIL：顶层公开类 5 个 ✓ |
| `state/__init__.py` 追加 `def helper()` | FAIL：`__init__.py` 只能做导出 ✓ |
| `state/market_state.py` 追加 `_MAX_RETRIES = 5` | FAIL：模块级字面量常量 ✓ |
| 摘掉 `SessionClock.now()` | FAIL：不满足 ClockPort + prune 抛 AttributeError ✓ |

全部 6 项按预期 FAIL，且脚本用 `try/finally` 保证文件还原（还原后 `--check` 退出码 0）。

## 未改动但已确认

- 分层方向、`__slots__` 一致性、订阅容量、10 份配置的业务取值均未受影响。
- 唯一的行为改动是 `SessionClock` 多了 `now()` 方法（纯增量，无调用点被改变语义）。
