# Project State — simulator-hard-cut

## 1. 删除清单（物理删除，无开关、无兼容分支）

| 路径 | 规模 | 说明 |
|---|---|---|
| `simulator/__init__.py` | 20 行 | 包导出 |
| `simulator/scenario.py` | 136 行 | 冲击场景 / 漂移 / 毛刺探针 |
| `simulator/sim_clock.py` | 110 行 | 合成时钟（基于 `time.monotonic()`） |
| `simulator/synthetic_feed.py` | 316 行 | 合成行情源，实现 `FeedPort` |
| `config/simulator.json` | — | 模拟源配置 |
| **合计** | **582 行 Python + 1 配置** | |

备份位置（仓库之外，符合"临时产物不进工程目录"约定）：
`E:\US.market\SPXW SWATCH\simulator_removed_20260913\`

## 2. 产品代码改动

### 2.1 `run.py`（63 行）

删除 `--sim` / `--live` 两个开关与 `_resolve_simulate()`。CLI 现在只剩 `--check`。
`Pipeline(simulate=...)` → `Pipeline()`。

**为什么不留 `--live`**：只有一个模式时，开关就是纯粹的假信息 ——
它暗示"还有别的模式"，而实际上没有。硬切的意义正在于此。

### 2.2 `app/pipeline.py`（367 → **341 行**）

删除 `simulate` 形参、`_cfg["simulator"]` 取键、SimClock 分支、
SyntheticFeed 分支、`FeedMode` import。`mode` 属性改为直接转发：

```python
return str(self._feed.mode)
```

### 2.3 `contracts/enums.py`

删除 `FeedMode.SIM`，只留 `FeedMode.LIVE`。

⚠️ **保留 `FeedMode` 这个枚举本身**（而不是把它内联成字符串）—— 它是跨层契约的
一部分，L1 的 `mode` 与帧 JSON 的 `health.mode` 都依赖它的取值域。

### 2.4 文档串同步

`contracts/ports.py` / `core/clock.py` / `acquisition/__init__.py` 的 docstring
里"模拟模式"措辞改为"实盘 + 离线回归"。**`ClockPort` 协议本身保留** ——
它的第二个实现从 `SimClock` 换成了 `tools/fixtures.py::FakeClock`。

## 3. 关键交付物：`tools/fixtures.py`（新增，188 行）

**这是硬切里唯一"新增"的东西，也是让 4 个离线回归活下来的原因。**

从被删的 `simulator/` 里抽出**最小确定性内核**，降级为测试夹具而非产品代码：

```python
class FakeClock:
    """可推进的合成时钟，实现 contracts.ports.ClockPort。"""
    __slots__ = ("_tz", "_open_min", "_base_day", "_offset")
    def now(self) -> float: return self._open_epoch() + self._offset
    def advance(self, session_seconds: float) -> None: self._offset += float(session_seconds)
    def reset(self) -> None: self._offset = 0.0
    def set_day(self, day: datetime) -> None: self._base_day = day.date()

class SyntheticSurface:
    __slots__ = ("_slope", "_curvature", "_delta_scale")
    def iv_at(self, strike, spot, atm_iv) -> float
    def call_delta_at(self, strike, spot) -> float   # 0.5 + 0.5*tanh(-x/_delta_scale)
    def put_delta_at(self, strike, spot) -> float    # call_delta - 1.0
    def delta_for(self, strike, spot, is_put) -> float
    @staticmethod
    def strike_grid(spot, step, each_side) -> tuple[float, ...]
```

**刻意不移植的东西**：冲击场景、现价漂移、随机噪声、毛刺探针。
那些是"造故事"的能力，回归不需要故事，只需要**确定性**。

**`FakeClock` 比被删的 `SimClock` 更确定**：它完全不碰 `time.monotonic()`，
时间只由 `advance()` / `set_day()` 驱动，不存在"真实时间溜进来"的可能。

## 4. 自检登记项清理

| 文件 | 删除项 | 漏删的后果 |
|---|---|---|
| `tools/selfcheck_core.py` | `LAYER_OF["simulator"]`、`REQUIRED_KEYS["simulator"]` | 检查 [2] 静默跳过该层；检查 [5] 去读已不存在的 JSON |
| `tools/selfcheck_hardcode.py` | `EXEMPT_CONSTANTS["simulator/scenario.py"]` | 死条目 —— 豁免一个不存在的文件，属静默腐烂 |

⚠️ **这是硬切最容易漏的一步**：删了目录、检查器还在找，`--check` 不一定报错，
可能只是**悄悄少检查一层**。所以两处登记项与目录删除在**同一轮**完成。

## 5. 回归改写（4 个）

`tools/check_clock_protocol.py` / `check_side_flip.py` /
`check_session_rollover.py` / `smoke_test.py` 全部改为 import `tools.fixtures`。
`smoke_test.py` 里 `FeedMode.SIM` → `FeedMode.LIVE`。

## 6. `README.md` 同步

- 删除 `--sim` / `--live` 的用法说明。
- L6 层级表与配置清单里移除 `simulator`。
- §8「模拟模式」整节改写为「离线回归」，说明夹具位置与用途。
- **修正过期数字**：模块配置 10 → **9**；关键配置项 41 → **37**。

## 7. 验证结论（本次重跑，非回填）

| 项 | 命令 | 结果 |
|---|---|---|
| 自检 | `run.py --check` | **11/11 全部通过**（78 文件 / 最长 `tools/smoke_test.py` 363 行 / 9 配置 / 37 关键键 / 137 处取键 / 9 条硬编码例外） |
| 本地回归 ×11 | `smoke_test` `check_clock_protocol` `check_side_flip` `check_subscription_qualify` `check_tick_router` `check_session_rollover` `check_matrix_codec` `check_period_aggregation` `check_reconnect_gap` `check_persistence` `check_reconnect_flow` | **11/11 exit 0** |
| 需服务 ×4 | `check_web_contract` `check_page_render` `check_ws_compression` `ws_probe` | 全部 exit 1，**原因均为 8060 无服务**（`ConnectionRefusedError` / `Cannot connect to host 127.0.0.1:8060`），与本次改动无关 |

`check_web_contract` 的失败点已定位到 §[3]（载荷字段需活连接）：
§[1] DOM id（JS 引用 21 / HTML 定义 26）与 §[2] CFG 路径（JS 引用 30 条）
**均通过** ⇒ 失败与硬切无关。

## 8. 本会话第二部分：记录体系拓扑

同一会话内 KAI 追加三项，属流程/工具而非产品代码：

1. **导入 skill `notes-session-records`**（源：`C:\Users\Lenovo\.codex\skills\`）
   → 安装到 `C:\Users\Lenovo\.workbuddy-ai\skills\notes-session-records\`。
   安装前按安全审计流程走完，结论 **P2（安全）**：0 脚本、0 网络、
   0 敏感路径、0 依赖安装、0 base64。
2. **放宽该 skill 的验证流程**（SKILL.md 160 → 133 行）—— KAI 判定原流程过于严格：
   - `## Validation`：不再硬绑定某个仓库的 strict 脚本；"没有可跑的东西"时
     写 `N/A:<reason>` 是**可接受结果，不是失败**。
   - `## Handoff Markers`：**27 个强制标记 → 5 个核心标记**
     （`CHANGED-PATHS` / `VALIDATION-SUMMARY` / `COMMAND-EVIDENCE` /
     `NOTES-PATHS` / `OPEN-RISKS`），其余降为可选组；删除 Rust 算法相关标记。
   - `## Final Check`：5 条 → 3 条。
   - `## Context Indexes`：删掉"恰好一个"的硬计数，改为"只保留最新态"原则。
   - 开头加一句"按任务深度匹配记录深度，不要给小任务套仪式"。
   - 删除 `agents/openai.yaml`（Codex 专用，workbuddy 不读）。
3. **记忆层级重排（消除重复真相）**：
   - **5 条工程要求提升到用户级** `~/.workbuddy-ai/MEMORY.md`，标注"所有项目通用"。
   - **项目级 `MEMORY.md` 只留检查器映射**，条文改为指针，不再复述。
   - `notes/` 按 KAI 决策**复活**（2026-09-11 曾废弃）——
     记录落点回到 `notes/sessions/YYYY-MM-DD/<task-id>/`。
   - `tools/selfcheck_core.py::NON_SOURCE_DIRS["notes"]` 的理由串同步更新。

**归属规则（本会话确立）**：跨项目工程要求 → 用户级 `MEMORY.md`；
项目检查器映射 → 项目级 `MEMORY.md`；当天做了什么 → `notes/sessions/...`；
操作手法 → skill。**同一事实只写一处。**

## 9. 踩到的坑

- **`tools/fixtures.py` 定义 `__slots__` 类** ⇒ 受检查 [8] 管辖；且 `tools/`
  只豁免 [2]/[9]/[10]，**不豁免 [1] 行数** ⇒ 该文件必须 < 400 行（实测 188 行）。
  这个豁免范围是**读 `selfcheck_structure.py` / `selfcheck_slots.py` 实测确认的**，
  不是猜的。
- **git 全程刷 `LF will be replaced by CRLF` 警告** —— 仓库 `autocrlf` 历史残留，
  对内容无影响，**不是本次改动引入的**。
