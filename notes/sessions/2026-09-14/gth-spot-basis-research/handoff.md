```text
TASK-ID: gth-spot-basis-research
DATE: 2026-09-14
TIER: T2
STATUS: in-progress
CHANGE-ID: N/A:本轮为只读调研，未改任何代码，无关联 OpenSpec change
```

# Handoff — gth-spot-basis-research

STARTUP-PROOF: 见 `startup.md`（`HEAD=92a516c`，工作区干净，改动前捕获）。

## 结论（一句话）

业界做法**确实是**"用 ES 期货合成隐含现货"，但**主流变体不是"冻结 RTH 观测基差"**，
而是成本携带模型（B2，公开发布口径）或同到期日平价反推（B3，波动率台做法）。
B1 可作单日简化，**换月日会静默错值**，必须有 B2/B3 之一做闸门。

**KAI 决定（2026-09-14 01:38）：主口径 = B2b（前后月 ES 期货反解 carry）；A 段不做。**

完整论证与逐字引用见 `artifacts/research_gth_spot_basis.md`（E1 官方 / E2 业界 / E3 学术 / E4 IBKR tick）；
判别实验见 `artifacts/verify_b2_vs_b3.md`；实现方案与待拍板项见 `project_state.md`。

## 三处修正 / 新发现

1. **上一轮被否的理由不成立** —— 复算 `S = 7687 × e^{−(0.0401−0.0075)×0.2685} = 7620.01`，
   与记录的"期权反推价 7620"差 **0.01 点**。所谓 67 点偏差 = Dec-2026 的 3 个月携带（计算值 66.99），
   属**远期/现货量纲错配**，不是算法或数据源错。方向仍应选 ES，平价反推降级为**交叉校验**。
2. ~~**`现货 7591.70` 与 SPX 官方周五收盘不符**~~ —— **已撤回，原判断的前提是错的**。
   KAI 更正：`7591.70` 是上一轮被驳回算法自己算出来的产物，不是 IBKR 给的值。
   **实测证实**（探针 01:25–01:27）：IBKR 在 GTH 给的 SPX 指数 = **7656.98 = 周五官方收盘，恒定**，
   且 `marketDataType = 1`（报"实时"）。⇒ "IBKR 给的是冻结的 RTH 收盘价"这个说法**是对的**；
   ⇒ 顺带钉死一条本项目关键事实：**`marketDataType` 判不出新鲜度**，
   `ibkr.max_underlying_age_s` 拦不住这个值的原因就在这（此前只是推断）。
3. **`--check` 基线已漂移（现在 RC=1）** —— 见下。**原因已定位**（KAI 说"原因不知道"）：
   `.venv/` 与 `venv/` 两个虚拟环境未登记 `NON_SOURCE_DIRS`。

## B2 vs B3 判别实验（KAI 指令：需要有验证方法）

方法 + 实测 + 结论见 `artifacts/verify_b2_vs_b3.md`。**四部分：A 精度对拍 / B 可用性 / C 自洽性 / D 非空转。**

**GTH 实测（01:25:38 → 01:27:13，20 样本）：**

- **三个候选两两相差 ≤ 0.5 点**（B2a 7613.78–7615.78 / B2b 7613.54–7615.56 / B3 7613.60–7615.50）
  ⇒ 它们是同一个量的三条路径，判别轴是**失效模式与可用性**，不是精度。
- **`ĉ`（前后月反解 r−q）中位 = 0.03526，波动仅 2.7bp**；外部 `r−q = 0.03260` ⇒ **差 26.6bp**。
  折价：T=0.011 时值 0.22 点，**T=0.25 时值 5.04 点** ⇒ **B2a 的外部 r/q 实测就是错的**。
- **B3 可用率 100%**（7 档同档双边报价）；ES 前月 100%。
- **GTH 期间 SPX 指数比 ES 推算现货高 40.4–42.0 点 ≈ 8.1–8.4 档** ⇒ 陈旧指数的档位偏移量被定量钉死。

**非空转结果**：`--perturb q` → C 报 51.5bp 红 ✅；`--basis-month dec` → B2a 偏 +4.8 点 ✅；
`--no-interp` → **未报红，该变异不成立**（`C−P` 对 `K` 严格仿射，插值与不插值数学同值）
⇒ 由此修正对 B3 的认识：**B3 的判别轴是可用性，不是精度**。

**建议**：主口径 **B2b**（前后月反解 carry，无外部输入）；**B3 作实时交叉校验**（差 >2 点 fail-closed）；
**B2a 弃用**（静默偏 26.5bp）；**B1 弃用**（换月静默错值）。

**未完成**：A 段（RTH 精度对拍）需 09:30 ET 后跑；GTH 冷时段（03:00–06:00 ET）可用性未采样。

## CHANGED-PATHS

```
notes/sessions/2026-09-14/gth-spot-basis-research/startup.md              (新增)
notes/sessions/2026-09-14/gth-spot-basis-research/project_state.md        (新增)
notes/sessions/2026-09-14/gth-spot-basis-research/handoff.md              (新增)
notes/sessions/2026-09-14/gth-spot-basis-research/artifacts/research_gth_spot_basis.md (新增)
notes/sessions/2026-09-14/gth-spot-basis-research/artifacts/verify_b2_vs_b3.md           (新增)
tmp/basis_check.py                                                        (新增，一次性探针)
tmp/probe_spot_basis.py                                                   (新增，一次性探针)
tmp/gth_probe.csv                                                         (新增，探针产物)
notes/context/handoff.md                                                  (改：Latest session 指针)
notes/context/open_tasks.md                                               (改：登记新发现)
.workbuddy-ai/memory/2026-09-14.md                                        (追加)
~/.workbuddy-ai/skills/spxw-live-verify/SKILL.md                          (改：修正过期的 --check 判定标准 + 新增 venv 坑)
```

**未改动任何产品代码**（`app/ acquisition/ features/ core/ serialization/ transport/ state/ contracts/ config/ tools/ web/ run.py` 全部未触碰）。

## COMMAND-EVIDENCE

```
git status --porcelain                    → ?? notes/sessions/2026-09-14/   （其余为空）
git diff --check                          → 无输出（无空白错误）
venv/Scripts/python.exe tmp/basis_check.py
  → impliedopen 页面 ES 7620.75 → S=7556.36（页面显示 7556.08，差 +0.28）
  → 上一轮记录 ES 7687.00 → S=7620.01（记录反推价 7620，差 +0.01）
venv/Scripts/python.exe run.py --check
  → RC=1，2584 项不通过；失败项全部来自 .venv/ 与 venv/ 的 site-packages
netstat -ano | grep :8060                 → LISTENING  PID 15612（残留进程）
grep -o "现货 [0-9.]*" logs/spxw_swatch.log | sort -u
  → 只有 `现货 7591.70`（495 条读数，无一例外）
grep -c venv tools/selfcheck_core.py      → 0（NON_SOURCE_DIRS 未登记虚拟环境）
MSYS_NO_PATHCONV=1 taskkill /F /PID 15612 → SUCCESS；随后 netstat :8060 无输出（已释放）
tmp/probe_spot_basis.py --seconds 100 --interval 5 --csv tmp/gth_probe.csv   （GTH 主跑，20 样本）
  → SPX 7656.98 恒定 md=1；F1 7616.50–7618.50；F2 7684.25–7686.00
  → B2a 7613.78–7615.78 / B2b 7613.54–7615.56 / B3 7613.60–7615.50（两两 ≤ 0.5 点）
  → c_hat 中位 0.03526 vs 外部 0.03260（差 26.6bp）；B3 可用率 100%；指数−推算 = +41.4~42.0 点
tmp/probe_spot_basis.py --perturb q           → C 段差 51.5bp，报红            （非空转 D1 ✅）
tmp/probe_spot_basis.py --basis-month dec     → B2a 偏 +4.8 点                 （非空转 D2 ✅）
tmp/probe_spot_basis.py --no-interp           → 未报红，变异不成立              （非空转 D3 ❌ 已解释）
```

## VALIDATION-SUMMARY

- `run.py --check` → **RC=1**（2584 项），原因见 OPEN-RISKS #1；本轮**未修**。
- 复算脚本 `tmp/basis_check.py` → 两条断言均吻合（|差| ≤ 0.28 点）。
- 实盘探针 `tmp/probe_spot_basis.py` → GTH 主跑 + 3 条变异，全部有读数；
  **非空转 2/3 报红，第 3 条经分析确认变异本身不成立**（不是漏检）。

## 缺陷（新发现，未修，待 KAI 定）

**`--check` 的两处登记不一致。** `.gitignore:27-28` 登记了 `.venv/` 与 `venv/`，
但 `tools/selfcheck_core.py:54` 的 `NON_SOURCE_DIRS` **没有**虚拟环境条目
（`grep -c venv tools/selfcheck_core.py` → 0）。而 `iter_py_files()` 只排除
`__pycache__` 与 `NON_SOURCE_DIRS` 顶级目录（`selfcheck_core.py:129-135`），
于是 `ROOT.rglob("*.py")` 把两个 venv 的 site-packages 全收进来 → `[1][2][8][9][10]` 集体误报 2584 项。

- 与项目自己的纪律直接冲突：`NON_SOURCE_DIRS` 里 `tmp` 那条注释写着
  "⚠️ 本条与 .gitignore 的 `tmp/` 是一对，缺一条就会让探针被 [1][2][9][10] 误报" ——
  `venv` 就是缺的那一条。
- **不是本会话造成的**：`.venv/` mtime = 2026-09-13 14:18、`venv/` mtime = 2026-09-13 23:55；
  09-13 那次"全绿"跑在两者出现之前，所以当时的绿是真的，**之后环境漂移、没人再跑过**。

## Closed in session

- GTH 现货基准的业界做法调研完成，含官方/业界/学术三类逐字来源。
- 上一轮 FairSpotEstimator 被否理由的数值复核（结论：理由不成立，但方向仍选 ES）。
- 定位到残留进程（PID 15612）与 `现货 7591.70` 与官方收盘不符两处异常。

## OPEN-RISKS

1. **`--check` 基线红（中）** —— `.venv`/`venv` 未登记 `NON_SOURCE_DIRS`，2584 项误报、RC=1。
   最小修法是补两条目录条目；更结构化的修法是让 `iter_py_files()` 按 `pyvenv.cfg` 识别虚拟环境
   （与目录名解耦）。**属"重构现有工具"，未获指令不擅自动**。修之前，
   `notes/context/handoff.md` 里"`[1]`–`[13]` 全绿"的结论**在当前工作树上不可复现**。
2. ~~`现货 7591.70` 来源未定位~~ —— **已关闭**：KAI 更正 + 探针实测 = 那是被驳回算法的产物，
   IBKR 实际给 7656.98（周五收盘，恒定，md=1）。残余风险转为下一条。
3. ~~残留进程 PID 15612~~ —— **已中断**（KAI 指令）。`netstat :8060` 已无监听。
   ⚠️ 但它跑的是已撤回构建这件事说明：**实盘验证前必须先确认 8060 上没有别的进程**，
   否则看到的可能是别的代码的行为。
4. **`marketDataType` 判不出新鲜度（中）** —— 实测：GTH 期间 SPX 指数恒定 7656.98，
   但 `marketDataType = 1`（报"实时"）。⇒ `ibkr.max_underlying_age_s = 10.0`
   那条闸门**结构上拦不住这类值**。需决定闸门应改判什么（例如"指数是否在变动"）。
5. ~~主口径待 KAI 拍板~~ —— **已定：B2b**（KAI 2026-09-14 01:38）。
   **A 段（RTH 精度对拍）经 KAI 判定不做**：GTH 段结束于 09:25、09:30 起指数恢复实时，
   RTH 段直接用指数、不用合成值 ⇒ 无需回答"合成值在 RTH 贴不贴"。
   **实现要点与 4 个待拍板项见 `project_state.md`**（未动代码）。
6. **B2b 实现未启动（中）** —— 方案已写：新增 ES 三个月订阅 + `acquisition/` 下的
   现货合成单一职能文件 + `config/spot.json` + `REQUIRED_KEYS` 登记 + fail-closed 条件。
   待 KAI 定 4 项：配置文件落点 / 09:30 交班处窗口重建 / `ĉ` 取值闸门阈值 /
   是否采纳"09:30 单点对拍"的免费校验。
7. **GTH 冷时段可用性未采样（低）** —— 03:00–06:00 ET 的 B3 可用率未知。
   注：B3 已降为**可选**校验通道，本项优先级随之降低。

## NOTES-PATHS

- `notes/sessions/2026-09-14/gth-spot-basis-research/{startup,project_state,handoff}.md`
- `notes/sessions/2026-09-14/gth-spot-basis-research/artifacts/research_gth_spot_basis.md`
- `notes/context/handoff.md`、`notes/context/open_tasks.md`
- `.workbuddy-ai/memory/2026-09-14.md`

## 未做的事（等 KAI 指令）

- 未加任何**产品侧**订阅（未订 ES、未请求 generic tick 162）—— 探针用的是自己的 clientId=98，与 `run.py` 无关。
- 未改任何产品代码 / 配置。
- 未修 `--check` 的 venv 登记问题（修法待 KAI 定）。
- 未跑 A 段（RTH 精度对拍），需 09:30 ET 后执行。
