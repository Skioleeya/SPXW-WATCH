# Open Tasks — record-reconciliation

## Active（本会话）

- [x] 加载 `notes/context/*` + `.workbuddy-ai/memory/*` + 5 个会话根。
- [x] 实测当前现实：`run.py --check`（11/11）、行数、文件数、`tools/check_*` 计数、git 状态。
- [x] 逐项对照，定位 4 处不一致。
- [x] 在活文档上改正（README / notes/context ×2 / memory/MEMORY.md）。

## Closed（本会话）

- [x] **[记录腐烂] `feed_service.py` 行数** —— 记录 396 → 实测 **397**（余 3 行）。
      三处活文档同步改正。
- [x] **[记录腐烂] README §9 状态行** —— 「69 个文件 / 最长 395 行 / 10 项检查」
      → 「**70 个 / 397 行 / 11 项**」。
- [x] **[记录腐烂] README §9 检查表** —— 缺 `[11]` 行（已补）；`[5]` 关键键
      40 → **41**（自检实测口径）。
- [x] **[结论过时] README §10「实盘未验证」** —— 与事实相反。已改为
      「实盘链路已实测联通（2026-09-11）；仍**未验证**的是 paper 无实时 OPRA
      权限导致的 `tickOptionComputation` / 106 模型 Greeks 落地」。
- [x] **[记录腐烂] README §10 端口** —— 默认 `7497`（TWS 模拟）→ **`4002`**
      （IB Gateway 模拟，已实测联通）。
- [x] **[记录腐烂] `.workbuddy-ai/memory/MEMORY.md`** —— `check_*` 「8 个」→ **7 个**
      （实测 `ls tools/check_*.py | wc -l` = 7）。

## 转出（不属于本会话，仍挂在 `notes/context/open_tasks.md`）

- [ ] **[待 KAI 定] IV 热力图 ΔIV ≈ 0 是否退回中性色**（Turbo 是顺序色阶，
      0 现为亮黄绿 `#a4fc3b`）。
- [ ] **[低] 色板缺机械回归** —— 色值被误改没有任何检查会红。
- [ ] **[低] 联通与限速无常驻回归** —— 仍是手工脚本，未收进 `tools/`。
- [ ] **实盘 tick 回流后的 106 模型 Greeks 落地**（paper 无实时 OPRA 权限）。
- [ ] **`notes/` 与 `.workbuddy-ai/memory/` 是否收敛为一套** —— 本会话再次暴露
      该问题的代价：同一事实散落 4 处，改一处就得改四处。
