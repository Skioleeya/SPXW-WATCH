```text
TASK-ID: b2b-spot-synthesis
DATE: 2026-09-14
TIER: T2
STATUS: done
CHANGE-ID: N/A:纯实现任务，无关联 OpenSpec change
```

# Handoff — b2b-spot-synthesis

STARTUP-PROOF: 见 `startup.md`（`HEAD=92a516c`，改动前工作区只有 notes 改动）。

## 结论（一句话）

KAI 拍板的 **B2b** 已落地并跑通：GTH 段现货由 ES 前后月期货反解 carry 合成，
09:25 一过立刻下线合成、切回指数直读，**期权订阅窗口自动重建**（锚跳 8.15 档 >
trigger 3 档）。`--check` 基线从 `RC=1 / 2582 项` 恢复到 **`RC=0`**。

端到端证据（实盘冒烟，GTH 正在交易）：

```
02:08:28 INFO pipeline 帧 137 | 客户端 1 | 分片 48 | 现价 7620.26 | 订阅 48/92
```

**现价 7620.26 = 合成值**，而同一时刻 IBKR 给的 SPX 指数是冻结的 **7656.98**
（周五收盘）。合成链路在真实链路上确实生效了。

## 做了什么（对应 KAI 的 5 条拍板）

| KAI 指令 | 落地 |
|---|---|
| ① `config/spot.json` 独立文件 | 新增（9 个键 + 4 段说明），已在 `selfcheck_core::REQUIRED_KEYS` 登记 |
| ② 09:25 交班下线 GTH 锚定、订阅 SPX | `synthesised_zones=["gth"]` ⇒ 09:25 起现货源切回指数；**窗口重建由既有 `WindowFollower` 自动完成**，未加特殊代码 |
| ③ `ĉ` 两层闸门 | `max_abs_carry=0.15` fail-closed + `max_carry_jump=0.005` 拒收该桶（基准跟上，非死锁） |
| ④ 不做 09:30 单点对拍 | 未做 |
| ⑤ `--check` 按 `pyvenv.cfg` 识别 venv | `iter_py_files()` 新增 `_in_virtualenv()`，与目录名解耦 |

## CHANGED-PATHS

```
config/spot.json                          (新增)
acquisition/spot_synthesis.py             (新增：B2b 合成 + 两层闸门)
acquisition/spot_source.py                (新增：按区段选源，TickSink 实现)
core/session_grid.py                      (新增：从 clock.py 拆出的网格几何纯函数)
tools/check_spot_synthesis.py             (新增回归，16 项)
tools/check_spot_source.py                (新增回归，11 项)
contracts/tick.py                         (改：+FutureTick，说明它为何不进 TickSink)
acquisition/contract_factory.py           (改：+future()；构造签名加 spot_cfg)
acquisition/ibkr_gateway.py               (改：+fetch_future_months / subscribe_future)
acquisition/tick_router.py                (改：+期货分流 + 显式 future_sink)
acquisition/feed_service.py               (改：+spot_cfg / selector / synthesis / _subscribe_futures)
core/clock.py                             (改：拆出几何；+current_zone_id)
core/__init__.py                          (改：minutes_of_day/parse_hm 改从 session_grid 导出)
app/pipeline.py                           (改：装载并注入 spot 配置)
tools/selfcheck_core.py                   (改：iter_py_files 排除 venv；REQUIRED_KEYS +spot)
tools/check_period_aggregation.py         (改：minutes_of_day 改从 session_grid import)
tools/check_session_grid.py               (改：同上)
notes/context/handoff.md · open_tasks.md  (改)
.workbuddy-ai/memory/2026-09-14.md · MEMORY.md (改)
```

## COMMAND-EVIDENCE

```
# ① 基线回绿 + 判据非空转
venv/Scripts/python.exe run.py --check
  修复前 → RC=1，2582 项（全部来自 .venv/ 与 venv/ 的 site-packages）
  修复后 → RC=0，"90 个 Python + 14 个前端脚本全部合规"
摘掉判据（mv .venv/pyvenv.cfg .venv/pyvenv.cfg.off）→ RC=1 / 1291 项
恢复后复跑 → RC=0                       （已复原，352 字节，mtime 未变）

# ② 两个新回归
venv/Scripts/python.exe tools/check_spot_synthesis.py → RC=0，16 项全通过
venv/Scripts/python.exe tools/check_spot_source.py    → RC=0，11 项全通过

# ③ 非空转：临时摘掉修复，跑完已恢复（diff 校验两文件完全一致）
M1 摘绝对闸门      → RC=1 / 3 项 FAIL
M2 摘跳变闸门      → RC=1 / 1 项 FAIL
M3 摘报价年龄过滤  → RC=1 / 1 项 FAIL
M4 摘区段判断      → RC=1 / 2 项 FAIL
M5 摘指数丢弃      → RC=1 / 2 项 FAIL

# ④ 期货探针（tmp/probe_es_future.py，clientId=98，与产品 71 隔离）
reqContractDetails(ES/FUT/CME，不给月份) → 返回 21 个月
  每条带 conId 与 realExpirationDate（精度到日，如 '20260918'）
  升序前 3：ESU6(20260918) / ESZ6(20261218) / ESH7(20270319)
期货 ticker → marketDataType=1，marketPrice()=7616.0，bid/ask 正常
⇒ 合约月与到期日**全部来自 IBKR**，代码不推算任何日期

# ⑤ 端到端冒烟（timeout 75 venv/Scripts/python.exe run.py）
02:07:17 启动 delayed | 到期 20260914 | is_open=True
02:07:17 界面地址 http://127.0.0.1:8060/
02:07:28 流水线已就绪
02:08:28 帧 137 | 客户端 1 | 分片 48 | 现价 7620.26 | 订阅 48/92

# ⑥ 既有失败对照（git worktree tmp/head_tree HEAD，跑完已 remove + prune）
check_page_render / check_skew_alignment / check_skew_viewport /
check_web_contract / check_ws_compression / check_period_aggregation
  → 6 个在 HEAD 上**同样 RC=1** ⇒ 均为既有，与本轮无关
全量实测：ls tools/check_*.py | wc -l → 19；13 个 RC=0，6 个 RC=1

# ⑦ 收尾自查抓到一处**本轮自己引入的假信号**（已修）
run.py --check → [4] 配置零耦合
  [warn] config/spot.json 的取值里出现了 subscription.json，请确认不是引用
根因：`_handover_comment` 里写了 `subscription.json::recenter_trigger_strikes`
  —— 是注释里的**文件名**触发了启发式扫描，不是真引用
处置：改为"订阅侧的 recenter_trigger_strikes（3 档）"（不出现别的配置文件名）
复跑 → 该 warn 消失，仅剩 [13] 的 8060 无服务（非交易日预期）；RC=0
```

## VALIDATION-SUMMARY

- `run.py --check` → **RC=0**（修复前 RC=1 / 2582 项）。
- 新回归 `check_spot_synthesis` **16/16**、`check_spot_source` **11/11**。
- 非空转 **5/5 变异被抓**（摘掉任一修复即报 FAIL），跑完两文件 diff 校验一致。
- 端到端：实盘现货 = 合成值 7620.26（指数冻结在 7656.98）。
- 全量 **19** 个 `check_*.py`（实测 `ls tools/check_*.py | wc -l`）：**13 `RC=0` / 6 `RC=1`**；
  6 个失败全部经 HEAD 对照确认既有（见 COMMAND-EVIDENCE ⑥）。

## 关键数值（都来自实测，不是估计）

| 量 | 值 | 来源 |
|---|---|---|
| 冻结指数（GTH 期间恒定） | 7656.98 | 探针，且 `marketDataType` 仍报 1 |
| 真实 ES 前月 / 次月 | 7619.0 / 7686.25 | `tmp/gth_probe.csv` 第 1 行 |
| 反解 `ĉ` | 0.03524813 | 与探针记录逐位一致（容差 1e-9） |
| B2b 合成值 | 7616.0575 | 复算 |
| **独立口径 B3（期权平价）** | **7616.0** | 跨数据源对拍，差 0.06 点 |
| 指数 − 合成值 | ≈ 40.6 点 = **8.15 档** | ⇒ 交班必然触发窗口重建 |

## OPEN-RISKS

1. **跳变闸门的语义是"毛刺过滤"，不是"永久拒收"** —— 拒收一桶后基准即跟上新值。
   若某次合约选错导致 `ĉ` 长期偏离（但仍在 15% 内），两层闸门都不会持续拦。
   缓解：月份一律由 IBKR 枚举 + 按到期月排序，结构上不会错位。
2. **ES 前月在到期日附近流动性下降** —— 前月消失时自动改用（次月, 次次月），
   属自愈；但换月当天若只剩一个月，会 fail-closed 一整天。已订 3 个月作余量。
3. **期货 3 条订阅占 IBKR 行情行** —— 当前 48/92，压力可忽略；但配额是账户级的，
   换账户/换机器后需复核（与 `market_data_type` 同类，属账户侧配置）。
4. **前端看不到"现货来源"** —— 切源消息进 `health.messages` 可读，但帧里没有
   "此刻用合成还是指数"的显式字段。要在面板上区分，需扩 `FeedStatus`/帧契约（未做）。
5. **`--check` 的 6 个既有失败未修**（`check_page_render`/`check_skew_alignment`/
   `check_skew_viewport`/`check_web_contract`/`check_ws_compression`/
   `check_period_aggregation`）—— 已用 HEAD 对照证明非本轮引入。
   其中 `check_period_aggregation` 的根因已定位：`sliceZones` 已从 `web/period.js`
   拆到 `web/period_align.js`，而它的 node 驱动仍只加载 `period.js`。
6. **`core/clock.py` 的拆分**属职责分离（为满足 <400 行硬约束），影响 4 个文件的
   import。相关回归已复跑（`check_session_grid` / `check_reconnect_gap` /
   `check_session_rollover` / `check_clock_protocol` 全绿）。
7. **未在交易日 RTH 段验证** —— 09:30 后指数是否真的恢复实时、切源是否平滑，
   需盘中确认。A 段（RTH 精度对拍）按 KAI 指令不做。

## Closed in session

- B2b 全链路落地：配置 → 契约 → 采集（期货枚举/订阅/分流）→ 合成 → 源选择 → 接线。
- `--check` 基线回绿（venv 按 `pyvenv.cfg` 识别）。
- 两个常驻回归 + 5 条非空转变异。
- 端到端冒烟证明合成在实盘生效。
- 收尾自查清掉**本轮自己引入**的一处假信号（`[4]` 配置零耦合告警）。

## NOTES-PATHS

- `notes/sessions/2026-09-14/b2b-spot-synthesis/{startup,project_state,handoff}.md`
- `notes/sessions/2026-09-14/gth-spot-basis-research/`（上一会话：调研与 B2/B3 判别实验）
- `notes/context/handoff.md`、`notes/context/open_tasks.md`
- `.workbuddy-ai/memory/2026-09-14.md`
