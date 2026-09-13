# Project State — record-reconciliation

## 本会话性质

**只读核对 + 活文档校正。零生产代码改动。**
本会话不是功能开发会话，产出的不是代码，而是"把记录改对"。

## 实测基线（本会话当场跑，命令见 `handoff.md`）

| 事实 | 实测值 | 命令 |
|---|---|---|
| Python 文件数 | **70** | `python run.py --check` → `[1] 70 个文件全部合规` |
| 最长文件 | `acquisition/feed_service.py` = **397 行** | 同上 + `wc -l` |
| 自检 | **11/11 全部通过** | `python run.py --check` |
| `tools/check_*.py` | **7 个** | `ls tools/check_*.py \| wc -l` |
| git | 仅 1 个提交；31 个 `M` + 9 个未跟踪 `.py` | `git log --oneline` / `git status --short` |

## 项目当前能力状态（未改动，转录自 `notes/context/project_state.md`）

- 五条硬约束均有机械检查兜底，`--check` 11 项、死键归零
  （`selfcheck_config.py::UNWIRED_IS_FAILURE = True`）。
- 实盘链路已实测联通（`port=4002`，IB Gateway 模拟盘）：11～14 秒就绪，
  错误码仅 72 × Error 10090，无 100/300/200。
- 出站限速桶已显式化（`config/ibkr.json` 的 45 条 / 1s）+ 可观测
  （`health.rate_limit`）；`SubscriptionManager` 的 Error 300 退避已改名
  `in_backoff` 消歧。
- 前端热力图色调 = 参考项目的 Turbo 15 色顺序色阶 + cell 边框。

## 本会话改了什么（全部是事实性数字/结论，无行为改动）

| 文件 | 改动 |
|---|---|
| `README.md` | §9 检查项 10 → 11；补 [11] 行；关键键 40 → 41；状态 69 文件/395 行/10 项 → 70/397/11 项；§10 端口默认 7497 → 4002；§10「实盘未验证」→「已实测联通（Greeks 落地仍未验证）」 |
| `notes/context/project_state.md` | 最长 396 → 397；`feed_service.py` 396/400 余 4 行 → 397/400 余 3 行 |
| `notes/context/open_tasks.md` | 同上（396/400 余 4 行 → 397/400 余 3 行） |
| `.workbuddy-ai/memory/MEMORY.md` | 396/400 → 397/400；`check_*` 8 个 → **7 个**（并列出哪 5 个本地、哪 2 个需服务） |

## 不改什么（刻意）

- `notes/sessions/2026-09-11/{dead-key-resolution,ibkr-rate-limit-audit,...}/**`
  里出现的 395 / 396 —— **历史快照，保持原样**。
- 任何 `.py` / `.js` / `.css` / `.json`。
