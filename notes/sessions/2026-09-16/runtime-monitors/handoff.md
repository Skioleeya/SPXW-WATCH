TASK-ID: runtime-monitors
DATE: 2026-09-16
TIER: T2
STATUS: complete
CHANGE-ID: N/A:本轮不涉及 OpenSpec 变更，只新增两只只读探针

# Handoff: runtime-monitors

KAI 要求：写独立的前后端监听脚本，验证四件事，然后启动整个系统。

## CHANGED-PATHS

新增（只读探针，不改产品代码）：
- `tmp/monitor_backend.py`    —— 从 WS 原始帧判 T2/T3/T4
- `tmp/monitor_frontend.js`   —— Playwright 读页面真实渲染的矩阵，判 T1–T4
- `tmp/monitor_backend.json` / `tmp/monitor_frontend.json` —— 机器可读报告
- `tmp/monitor_backend_after_restart.out` / `.json`
- `tmp/monitor_frontend_after_restart.out` / `.json`
- `tmp/monitor_frontend.png`  —— 页面截图
- `notes/sessions/2026-09-16/runtime-monitors/{startup,project_state,handoff}.md`

删除（本轮自查用的临时脚手架，用完即弃）：
- `tmp/_diag_*.py`（10 个）、`tmp/_repro_*.py`（2 个）、`tmp/_probe_*.js`（3 个）、
  `tmp/_peek_hm.py`、`tmp/_mk_mutants.py`、`tmp/_mutant_*`（6 个）、
  `tmp/_gate_check.out`、`tmp/_probe_t4*.out`

未触碰：`acquisition/` `core/` `features/` `models/` `serialization/`
`transport/` `web/` `app/` `config/` 下任何产品文件。

## TASK-ID: 四项要求的结论

| # | KAI 的要求 | 后端探针 | 前端探针 |
|---|---|---|---|
| 1 | 写独立脚本 | `tmp/monitor_backend.py` | `tmp/monitor_frontend.js` |
| 2 | 新网格出列后数值不变 | 7133 格指纹 / **0 改写** | 3385 格 + 6796 格指纹 / **0 改写** |
| 3 | 按 ET 挂钟推进出列 | 3 个新列全部落在挂钟整 30s | 2 个新列全部落在挂钟整 60s |
| 4 | 各周期 ΔIV 独立 | 组和可加性 24 行 / 0 违反 | 对拍 144 列 / 3405 格全部吻合 |

## COMMAND-EVIDENCE

**重启前（服务 PID 1228，`HEAD = bedbf11`）**

```
venv/Scripts/python.exe run.py --check                        → RC=0  「16/16 项全部通过」
venv/Scripts/python.exe tmp/monitor_backend.py --seconds 200 --warmup 15
  → RC=0  PASS
     逐格指纹 5571 个，改写 0；列数 1469 → 1476，单调=True，cols==bucket_index=True
     新列 7 次全部落在挂钟整 30s；出列滞后中位 30.25s / 最坏 30.39s
     整行重建痕迹 0 行；组和可加性 24 行实测，违反 0
     行身份（第 0 行）换过 29 次 ← 「指纹不能按行号存」的活证据
node tmp/monitor_frontend.js --seconds 200 --warmup 20           → RC=0  PASS
     T1 连接 connected·delayed；帧 17069→17496；桶 1509→1515；订阅 80/92
     T2 显示 3309 格 / 基线 6648 格，均 0 改写；列数 754→757，回退 0
     T3 4 个新列全部落在挂钟整 60s；横轴标签全部是 ET HH:MM
     T4 对拍 131 列 / 3092 格全部吻合
     自检 5 个页面代码模板串，无反引号污染
```

**非空转验证（摘掉修复要能报 FAIL）**

```
后端变异 M1（解码器 return None）
  → RC=1  FAIL 3 条
     "逐格指纹 0 个"
     "✗ 帧 #17775 的矩阵解不开 —— 逐格判据在这帧上是空转的"
     ⇒ 没有把"什么都没看"报成 PASS

前端变异 M1（指纹键改回行号 + 绝对列号）
  → RC=1  FAIL 2 条
     "显示矩阵被改写 67870 处"、"基线矩阵被改写 6200 处"
     ⇒ 假改写被如实报出
```

**重启（本轮 KAI 明确要求）**

```
taskkill /PID 1228 /F                                          → SUCCESS
venv/Scripts/python.exe run.py（后台）                          → 新 PID 20636，:8060 LISTENING
日志 08:59:29 启动 delayed | 到期 20260916 | bucket_index 1528 / 2370
日志 08:59:29 已从 SQLite 恢复 278 个历史桶（会话 20260916）
日志 08:59:41 流水线已就绪
curl --noproxy '*' http://127.0.0.1:8060/health                 → frames=32, dropped=0, static_enabled=true
venv/Scripts/python.exe tmp/monitor_backend.py --seconds 90 --warmup 15
  → RC=0  PASS  指纹 7133 个 / 0 改写；3 个新列全部挂钟对齐
node tmp/monitor_frontend.js --seconds 130 --warmup 20           → RC=0  PASS
     T2 显示 3385 格 / 基线 6796 格，均 0 改写
     T4 对拍 144 列 / 3405 格全部吻合
     列数 767（**未归零** ⇒ 重启后 278 个历史桶确实抵达前端）
```

## VALIDATION-SUMMARY

- `run.py --check` → RC=0，16/16（重启前后各一次）
- `tmp/monitor_backend.py` → 重启前 RC=0 PASS；重启后 RC=0 PASS
- `tmp/monitor_frontend.js` → 重启前 RC=0 PASS；重启后 RC=0 PASS
- 后端变异体 → RC=1 FAIL（3 条反例，判据非空转）✔
- 前端变异体 → RC=1 FAIL（2 条反例，判据非空转）✔
- 未激活的变异（后端 T3 恒真 / 前端 T4 不标记）→ **未验证**，见 OPEN-RISKS

## NOTES-PATHS

- `notes/sessions/2026-09-16/runtime-monitors/startup.md`
- `notes/sessions/2026-09-16/runtime-monitors/project_state.md`
- `notes/sessions/2026-09-16/runtime-monitors/handoff.md`
- `notes/context/{handoff,project_state,open_tasks}.md`（已同步指针）

## Closed in session

- 「出列即定稿」在后端帧层面成立：7133 格指纹、0 改写（含重启后复验）
- 「出列即定稿」在**前端渲染层面**也成立：两套键各 3000+/6700+ 格、0 改写
- 每周期按 ET 挂钟推进：后端 7+3 列、前端 3+2 列，**全部**落在整 30s/60s
- 各周期 ΔIV 独立：后端组和可加性 24 行 0 违反；前端跨档位对拍 144 列 3405 格 吻合
- 后端代码改动已通过重启生效；278 个历史桶跨重启保全
- 本轮临时脚手架（22 个 `tmp/_*` 文件）已清理

## OPEN-RISKS

1. **两个变异未被激活**（诚实标注，不冒充通过）：
   - 后端 T3「挂钟对齐」判据恒真
   - 前端 T4「把不一致故意不标记」
   本轮观测期内不存在真违例，所以变异体没被执行到。
   要验它们必须先构造一个"真违例"输入。**未构造 ⇒ 未验证。**
2. **`tmp/` 探针仍是临时件**，未纳入 `tools/`、未进门禁。
   按 KAI 明令（"不额外搭检查/校验模块"）它们就该停在 `tmp/`，
   但这也意味着**没有回归保护**：产品代码日后改动，这两只探针不会被自动跑。
3. **前端偶发 `cols != bucket_index`** 已按"允许差 1 且落后"处理；
   若将来看出差 >1 或超前，说明真把未走满的桶发了 —— 那是必须 FAIL 的。
4. **本轮已提交并推送**（2026-09-16 09:2x，KAI 要求「提交远端，让工作区干净」）：
   提交 **`76e00d3`**（157 文件 / 77 M + 40 A + 35 D），把自 2026-09-15 白纸重写
   以来的全部中间态一并落盘（重写主体 + 本会话 + `surface-residual-right`）。
   远端真值核对：`git ls-remote origin main` = `76e00d3b...` = 本地 `HEAD`；
   `git status --porcelain` **0 项**。
   ⚠️ `tmp/` 两只探针按 `.gitignore` **留本地**，因此**仍未进版本库** —— 与第 2 条
   的"无回归保护"是同一件事，提交并未改变它。
5. IBKR 侧 `Error 10197（ES 期货实盘竞态）` / `322（账户摘要请求超限）`
   偶发出现，属外部环境，不影响本轮判据。
