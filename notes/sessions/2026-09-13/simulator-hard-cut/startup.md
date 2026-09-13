# Startup — simulator-hard-cut

STARTUP-PROOF: baseline=`run.py --check` **11/11** 通过（改动前 78+4 文件 /
最长 `acquisition/ibkr_gateway.py` 360 行 / 9 个模块配置 / 37 个关键键）+
本地回归 11 个全过 + 服务端 4 个需服务在跑（本机 8060 未起，不计入基线）；
改动前基线为绿。

## Session

KAI 指令原文：

> 1.硬切删除模拟盘的所有依赖，让系统是的实盘系统

「硬切」= 不要特性开关、不要兼容分支、不要回退路径 —— 物理删除，不留后门。
同一次会话内 KAI 追加了记录体系的三项工作（skill 导入与放宽、`MEMORY.md`
路由化、`notes/` 复活），一并记在本会话。

## Scope Understanding

- **In scope**
  - 物理删除 `simulator/` 4 个文件与 `config/simulator.json`。
  - 删除 `run.py` 的 `--sim` / `--live` 分支与 `_resolve_simulate()`。
  - 删除 `app/pipeline.py` 的 `simulate` 参数、SimClock / SyntheticFeed 分支、
    `FeedMode` import。
  - 删除 `contracts/enums.py::FeedMode.SIM`。
  - **保住 4 个原本靠模拟源跑起来的离线回归** —— 这是硬切的最大风险点：
    直接删模拟盘会让 `check_clock_protocol` / `check_side_flip` /
    `check_session_rollover` / `smoke_test` 一起死掉。
  - 同步 `tools/selfcheck_core.py` / `selfcheck_hardcode.py` 里对 `simulator`
    的登记项。
  - 同步 `README.md`（层级表、配置清单、`--sim`/`--live` 说明、过期数字）。
- **Out of scope**
  - 不动 `web/`（前端与数据来源无关）。
  - 不动限速桶、订阅容量、`market_data_type` 等既有已决策项。
  - 不为"将来可能恢复模拟"预留任何开关 —— KAI 明确要硬切。

## Prior Context Read

| 载体 | 读到什么 |
|---|---|
| `notes/context/project_state.md` | 2026-09-11 末态：70 文件 / 最长 397 行 / 11 项检查；端口 4002；Turbo 色板；限速桶已显式化 |
| `notes/context/open_tasks.md` | 3 条已决策（不上前端 / `feed_service.py` 不拆 / ΔIV≈0 不退回中性色）+ 2 条待验证 |
| `notes/sessions/2026-09-11/dead-key-resolution/handoff.md` | `simulator/synthetic_feed.py` 曾是 `set_reconnect_hook` 的 no-op 实现 —— **这是硬切必须一起处理的反向依赖** |
| `.workbuddy-ai/memory/MEMORY.md` | 五条硬约束、`NON_SOURCE_DIRS` 排除表设计理由、`iter_py_files()` 的"排除表 vs 白名单"取舍 |
| `tools/selfcheck_core.py` | `LAYER_OF["simulator"]`、`REQUIRED_KEYS["simulator"]`、`NON_SOURCE_DIRS` |
| `tools/selfcheck_hardcode.py` | `EXEMPT_CONSTANTS["simulator/scenario.py"]` |
| `tools/selfcheck_structure.py` / `selfcheck_slots.py` | 实测确认 `tools/` 的豁免范围：**豁免 [2] 分层 / [9] 单一职能 / [10] 硬编码；不豁免 [1] 行数 / [8] `__slots__`** —— 决定 `tools/fixtures.py` 必须 < 400 行 |

## Recent Git Context

- Key commits reviewed:
  - `3eeb55b feat(persistence): persist 25D skew series across restarts`（本会话起点 HEAD）
  - `2447d53 fix(market-data): CBOE real-time + reconnect gap + persistence`
  - `755b221 Initial commit: SPXW SWATCH — 0DTE IV impulse heatmap & 25Δ skew radar`
- 工作树在本会话开始时干净（`3eeb55b` 已推送 `origin/main`）。

## Worker Readiness

- Risks noticed:
  1. **[高] 离线回归会随模拟盘一起死。** 4 个回归（`check_clock_protocol` /
     `check_side_flip` / `check_session_rollover` / `smoke_test`）此前依赖
     `simulator.sim_clock.SimClock` 与 `simulator.synthetic_feed.SyntheticFeed`。
     硬切必须**先把可复用的确定性内核抽出来**再删。
  2. **[中] 自检里的 `simulator` 登记项若漏删，检查 [2] 会静默跳过该层、
     检查 [5] 会去读一个已不存在的 JSON。** 属"删了目录但检查器还在找"的
     典型半删状态。
  3. **[中] `FeedPort.set_reconnect_hook` 的 no-op 实现原本长在
     `synthetic_feed.py` 里** —— 删掉后协议仍保留（单实现也要留协议，
     否则换数据源会造成反向依赖），但注释与文档必须同步。
  4. **[低] `README.md` 里的文件数 / 配置数 / 关键键数会因删除而全部过期。**
- Blockers noticed:
  - 无。本机 8060 端口未起服务，故 4 个需服务的检查不在本次基线内 ——
    与本次改动无关，已在 handoff 中显式标注。
