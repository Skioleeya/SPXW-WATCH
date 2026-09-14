TASK-ID: heatmap-mirror-ffill-grid
DATE: 2026-09-14
TIER: T2
STATUS: complete
CHANGE-ID: N/A:无 OpenSpec change
STARTUP-PROOF: N/A:本会话首个写操作（`web/gl_heatmap.js` 去镜像）早于基线捕获，按约定**不回填** `startup.md`

# Handoff — heatmap-mirror-ffill-grid

承接 `notes/sessions/2026-09-14/frontend-render-fix-and-skill-split`（该会话补的逐格边框，
其 `>=3.0` 双侧阈值正是本轮"细档位没有纵线"的成因）。本会话 KAI 报了两条现象，
排查中又挖出第三条；三条同属**热力图渲染正确性**，故合成一个会话根。

## 交付 1 —— 缺陷 D：热力图**上下镜像**（KAI 未报，排查中挖出）

**现象**：满宽的行出现在**屏幕顶部**，而帧里满宽的是**最后几行**；逐行颜色对应
"关于窗口中心镜像"的那个档位。

**根因**：两套行映射各自为政 —— 坐标轴标签与现货线走 `web/heatmap.js` 的 HTML overlay
（`:156` `y = g.y + (i+0.5)/rows*g.h` ⇒ 索引 0 在最上），数据走 fragment shader
（`gl_heatmap.js:68` `row = floor((u_grid.y - v_uv.y)/gh*cells.y)` ⇒ 屏幕顶 = texture 行 0）。
两边都从 0 起，本该一致；但 `update()` 里写成 `var tr = rows - 1 - r;`（注释称 "inverse Y"）
⇒ **屏幕第 i 行 = 帧第 rows-1-i 行**。

**修法**：去掉 `tr`，按帧行序直接写 texture（`var i = (r * cols + c) * 4`），
并把理由写成契约注释（"帧行序 ≡ texture 行序，**不要再反转**"）防复发。

## 交付 2 —— 缺陷 C：20:15 那条**假 0 带**（KAI 报："系统不是 20:15 启动，前端却把第一列放在 20:15"）

**根因链**：`features/persistence.py::recover()` 读 `heatmap_buckets` **全部行**（无时间窗/运行期过滤）
→ `app/pipeline.py:175-177` → `HeatmapEngine.load_snapshot()` → `_row_values()` 的 `carried`
**无上限前向填充** ⇒ 一个孤立的旧桶被一路沿用，在图右侧拉出满宽 `ΔIV=0` 的亮黄绿带，
与真"IV 没变"无法区分。

**修法**：新增 `config/serialization.json::heatmap_max_ffill_buckets`(20 = 30s×20 = 10 分钟)；
`HeatmapEngine` 加 `_max_ffill` slot，`_row_values()` 用 `last_seen` 记账，
跨度超限即输出 `None`（留白）；模块与函数 docstring 同步补第五种留白情形。
回归 `tools/check_reconnect_gap.py::case_long_gap_is_blanked`（阈值从 config 读，走真实
`load_snapshot()` 入口）；`--selftest` 扩为**两处注入**（吞 `break_now` + 上限推到无穷）。

## 交付 3 —— 需求 2：细档位**没有纵线**，看着是长条（KAI 报 + 参考图）

**根因**：默认周期 = 1 分 ⇒ 630 列 ⇒ 格宽 **2.40px**，低于上一轮 `>=3.0` 的双侧阈值 ⇒
纵线被判"太窄不画"，只剩横向。5 分档（126 列 / 12px）本来就有完整网格 ⇒ **档位相关**，非损坏。

**修法**：`web/gl_heatmap.js` 把 `>=3.0` 双侧判定换成**单侧自适应步长**
`stride = ceil(u_borderMinPx / cellPx)`，线仍落在**真实格边界**上（只取子集）；
`stride = 1` 时退化为旧行为（每格都画）。新增 uniform `u_borderMinPx` +
`web/config.js::heatmap.cellBorderMinPx = 5`（**物理像素** —— `resize()` 把 `u_resolution`
设成 `c.width = CSS px × dpr`），`web/heatmap.js` 调用点透传。

## 交付 4 —— 重启进程，让前向填充上限真正生效（KAI 指令）

**停机**：PID 896 的启动命令行 = `venv\Scripts\python.exe run.py`，实测是**父子两进程**
（8908 venv 存根 ~8MB 父 / 896 真实解释器 ~100MB 子，同秒创建、命令行相同）。
`run.py` **只认 Ctrl-C**（`Pipeline.stop()` 打印 `已停止`），无 HTTP / 文件 / 信号入口
⇒ 沙箱内只能硬杀。`taskkill /T /PID 8908` 报 `The process "8908" not found`，
但 `tasklist` 复核**两个都已消失**（父存根随子退出而自行结束）。
**判据：日志里没有 `已停止` 行 ⇒ 属硬杀**，未走优雅停机。

**硬杀安全性**（三条都核过）：SQLite `journal_mode=delete`（回滚日志，不损坏）·
`_batch_write()` 每批 commit ⇒ 最多丢一个未提交批次 · `recover()` 会把已提交桶捞回。
停后 `PRAGMA integrity_check` = `ok`，行数 334（与停前一致）。

**重启**：`cd` 项目根 → `venv/Scripts/python.exe run.py`（后台）。日志：
`07:19:49 启动 delayed | 到期 20260914 | ... bucket_index 1329` →
`已从 SQLite 恢复 335 个历史桶` / `335 个历史 Skew 点` → `07:19:59 流水线已就绪`。

**验证（核心）**：抓活帧看最低几档的**非空列分段**，假 0 带应恰好 = 上限桶数。

| | 重启前（旧代码） | 重启后（新代码） |
|---|---|---|
| row 19（7575）分段 | `first=1 / nonnull=1308`（满宽） | `[(1, 20), (449, 554), (706, 726), (1065, 1331)]` |
| 假 0 带宽度 | **1308 列**（≈9 小时） | **20 列**（= `heatmap_max_ffill_buckets` 上限） |

`(449,554)` / `(706,726)` / `(1065,1331)` 是**真实**数据段（分别对应 DB 的
`(448,473)+(494,534)` 区间、`(704,706)` 区间、以及 05:07 那次启动起的连续段）。
对照行 2（7660）无 `(1,20)` 段 —— 该档 20:15 时不在窗内，所以本来就不该有带。⇒ 修的是**带**，不是真实数据。

CHANGED-PATHS:
- web/gl_heatmap.js — 去掉 `tr = rows-1-r`（去镜像，带契约注释）；`>=3.0` 双侧阈值 → `stride` 自适应步长；新增 uniform `u_borderMinPx`
- web/heatmap.js — `setCellBorder(...)` 调用点透传 `CFG.heatmap.cellBorderMinPx`
- web/config.js — 新增 `heatmap.cellBorderMinPx: 5`（含 stride 公式注释）
- features/heatmap_engine.py — `__slots__`/`__init__` 加 `_max_ffill`；`_row_values()` 前向填充加上限 + docstring
- config/serialization.json — 新增 `heatmap_max_ffill_buckets: 20` + `_ffill_comment`
- tools/check_reconnect_gap.py — 新增 `case_long_gap_is_blanked()` 并注册；`--selftest` 扩为两处注入
- tmp/{probe_heat_align,dump_frame,analyze_heat,compare_orient,compare2,compare3,compare4,measure_grid,measure_grid2}.py — 一次性探针（`tmp/` 已 gitignore）
- tmp/{grid1m,grid_final,after,mut_mirror,period5m,final_live,after_restart}.png — 证据截图（同上）
- notes/context/{handoff,open_tasks,project_state}.md — 索引改指向本会话
- .workbuddy-ai/memory/{MEMORY.md,2026-09-14.md} — 速查卡 A/K 重写、新增 L；当日记录
- ~/.workbuddy-ai/skills/spxw-live-verify/SKILL.md — §5 改为"停 / 重启服务"（含双进程树 + 后端改动需重启）
- ~/.workbuddy-ai/skills/spxw-live-verify/references/pitfalls.md — 第 11 条重写（双进程树 / PowerShell 写盘回读 / 硬杀判据与安全边界）
- ~/.workbuddy-ai/skills/spxw-live-verify/references/frontend.md — 补"WebGL 行序与标签互为镜像"陷阱

COMMAND-EVIDENCE:
- 基线：`git status --porcelain` → `21 M + 7 ??`，`HEAD=92a516c`
- `./venv/Scripts/python.exe run.py --check` → `RC=0`，13/13；`[13]` 活链路
  `热力图 24 档 × 1333 桶`、`Skew 序列 338 点`、订阅 `48/92`、`connected / mode=delayed`
- `./venv/Scripts/python.exe tools/check_reconnect_gap.py` → `RC=0`；
  `case_long_gap_is_blanked` 实测 `上限内 ΔIV=0.0 / 上限外 ΔIV=None / 恢复桶 ΔIV=None [上限 20 桶]`
- `... check_reconnect_gap.py --selftest` → `RC=0`，注入两处缺陷后**变红两例**：
  `['断流恢复的第一桶留白', '长空洞不拉出假 0 带']` ⇒ 判别力成立（非空转）
- 镜像变异：临时改回 `rows-1-r` 重截 → 满宽行跑回屏幕顶部（`tmp/mut_mirror.png`）；
  复原后逐行对上帧（`706/706`、`450/449`、`2/1`）
- 纵线变异：`cellBorderMinPx=0` ⇒ `stride=1` ⇒ 纵线塌成密纹，四条扫描线仅检出 0–9 条、无周期
- 纵线实测（`tmp/grid_final.png`，1 分档，扫描线 y=200/250/330/380）→
  **合计 653 条纵线，间距中位 5.0 px**（最小 3 / 最大 42）
- 停服务：`taskkill /T /PID 8908` → 报 `8908 not found`，但 `tasklist /FI "PID eq 896"` 与
  `"PID eq 8908"` **均为空**；`netstat -ano | grep 8060` 无监听；日志**无 `已停止`** ⇒ 硬杀
- 硬杀后 DB：`PRAGMA integrity_check` → `ok`；`journal_mode` → `delete`；
  `heatmap_buckets` 334 行、段 `[(0,0),(448,473),(494,534),(704,706),(1064,1326)]`（与停前一致）
- 重启后 DB：338 行、段 6 个，新增 `(1330,1332)` = 新进程 `07:19:49` 起写（1330×30s = 07:20）
- **前向填充上限生效验证**（活帧逐行非空列分段）：
  重启前 row 19 `first=1 / nonnull=1308` → 重启后 row 19 `[(1,20),(449,554),(706,726),(1065,1331)]`
  ⇒ 假 0 带 **1308 列 → 20 列**（= 上限）
- 活截图：`tmp/final_live.png`（96511 B，重启前）· `tmp/after_restart.png`（96719 B，重启后）
- `md5sum` → `web/gl_heatmap.js ec7df7d4…`（旧 `c257dd1e…`）· `web/heatmap.js 4a24e526…` ·
  `web/config.js 42108155…` · `features/heatmap_engine.py b77c711f…` ·
  `config/serialization.json 79fef00e…` · `tools/check_reconnect_gap.py bb1553f0…`
- 行数：`heatmap_engine.py 388` · `gl_heatmap.js 275` · `heatmap.js 363` ·
  `config.js 142` · `check_reconnect_gap.py 353` —— 全部 < 400

VALIDATION-SUMMARY:
- `run.py --check` → `exit 0`（13/13）
- `check_web_syntax.py` → `exit 0`（14 文件）
- `check_reconnect_gap.py` → `exit 0`
- `check_reconnect_gap.py --selftest` → `exit 0`（两例被变异打红）
- 纵线/镜像各自变异均被抓；前端为静态文件 + `Cache-Control: no-store` ⇒ **刷新即生效**
- 重启前后对比：假 0 带 1308 → 20 列（**上限真实生效**）

NOTES-PATHS:
- notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/handoff.md（本文件）
- notes/sessions/2026-09-14/heatmap-mirror-ffill-grid/project_state.md
- notes/context/handoff.md · notes/context/open_tasks.md · notes/context/project_state.md
- .workbuddy-ai/memory/2026-09-14.md · .workbuddy-ai/memory/MEMORY.md

OPEN-RISKS:
- **残留：bucket 0 本身仍被恢复** —— `features/persistence.py::recover()` 仍读 `heatmap_buckets`
  **全部行**（无时间窗/运行期过滤），本轮只加了前向填充上限
  ⇒ 假 0 带由 ~9 小时缩到 **20 列（10 分钟）**，**未归零**。
  彻底消除需在 `recover()` 只取**最后一段连续桶**；KAI 上一轮**未选**该方案。
- **本次重启是硬杀** —— 未走 `Pipeline.stop()`，故 IB 连接是被 TCP 复位断开的（非主动注销）。
  实测重启后 `connected / mode=delayed`、订阅 48/92 正常，**无可见影响**，但属"未走设计路径"。
- **RTH 段（09:30–16:00）实盘仍未验证** —— GTH 段已跑通，切源是否平滑待盘中确认。
- **6 个既有失败回归未修**（`check_page_render` / `check_skew_alignment` / `check_skew_viewport` /
  `check_web_contract` / `check_ws_compression` / `check_period_aggregation`）——
  均 HEAD worktree 对照确认非本轮引入。
- **图例两项同名 `25Δ Skew`** —— 产品决策，待 KAI 定。
- **细档位纵线未在真实高 dpi 屏确认** —— `cellBorderMinPx` 是物理像素，dpr=2 时线距按 CSS px 减半。
- **本会话改动未提交** —— 全树 `21 M + 7 ??`，基线 `HEAD=92a516c`。

## Closed in session

- ~~热力图上下镜像（行序被反了两次）~~ —— **已修**（交付 1，带契约注释防复发）
- ~~20:15 起满宽假 0 带（`recover()` 孤桶 + 无上限前向填充）~~ —— **已修**（交付 2，带常驻回归 + 变异自证）
- ~~前向填充上限"已落盘但未生效"（活进程跑旧代码）~~ —— **已重启并实测生效**（交付 4：1308 → 20 列）
- ~~细档位（30秒/1分）没有纵线，看着是长条~~ —— **已修**（交付 3，自适应步长，实测中位线距 5.0px）
- ~~上一轮 `spxw-live-verify` 截图命令带 `--disable-gpu` 会假报 "WebGL 不可用"~~ —— **已修**（改 SwiftShader）
- ~~`spxw-live-verify` 只写了"用 TaskStop 停服务"，没说 `run.py` 是双进程、只能硬杀~~ ——
  **已补**（SKILL.md §5 + `pitfalls.md` 第 11 条重写）

