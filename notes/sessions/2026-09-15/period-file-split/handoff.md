---
task: period-file-split
date: 2026-09-15
time: 06:0x EDT
phase: GTH
head_at_start: 0261177
head_at_end: 0d30943
status: 已提交并推送（0d30943）；系统服务已启动并实盘验证
tests: "run.py --check RC=0（[13] 走真实联通）；ws_probe RC=0；period --selftest RC=0；selfcheck [1]/[2] ok"
---

# 拆 period 回归的超限文件 + 修 2 条失效变异锚点（并入上一会话的成交量边框功能提交）

## 起因

`tools/` 两个文件超 400 行上限（项目硬约束 #1，由 `tools/selfcheck_structure.py::check_file_sizes`
机械判定，阈值 `MAX_LINES=400`、判据为 `lines >= MAX_LINES` ⇒ 400 行本身即违规）。

- `tools/period_reference.py` **441 行**（改动前 398 ⇒ **是我上轮改超的**）
- `tools/check_period_aggregation.py` **416 行**

`selfcheck_structure.py` 无 `__main__` 块，由统一入口 `tools/selfcheck.py` 调用，
是 `run.py --check` 的 `[1]`/`[2]` 两项 ⇒ **确会判红**，非纸面规则。

## 改动

### ① 拆出 `tools/period_node.py`（新，120 行）

从 `period_reference.py` 移出 node 驱动（`NODE_DRIVER` 字符串 + `run_node()`）——
IO 职责与"造数 + 参考实现"（纯计算）分离。`period_reference.py` 保留
`from tools.period_node import run_node`（**re-export，调用点零改动**）。

441 → **349 行**。

### ② 拆出 `tools/period_selftest.py`（新，90 行）

从 `check_period_aggregation.py` 移出"注入缺陷证明判据会红"那一半 ——
那里管"对拍"，这里管"证明对拍会红"，两件事各自会长。

判据函数由调用方以 `evaluate` 回调传入 ⇒ **本模块不反向 import 检查器**，
无循环依赖，"被审计的对象"只有一份。

416 → **346 行**。

## 顺带修掉的真缺陷（本会话主要发现）

`--selftest` 的变异表里有 **2 条锚点早已失效**：

| 变异名 | 旧锚点所在 | 实际已迁至 |
|---|---|---|
| 切列忽略区段过滤 | `period.js` | `period_align.js` |
| alignSkew 忽略时段映射 | `period.js` | `period_align.js` |

旧表写死"锚点都在 `period.js`"，`sliceZones` / `alignSkew` 拆走之后那两条**长期打印
"变异点已失效"** —— 即：非空转自证在最该有效的地方失效了。

**修法**（按仓库既有写法，对齐 `check_skew_alignment.py`）：变异表从 4 元组改为
**5 元组** `(名称, 目标文件, 原文, 替换, 期望判据前缀)`，加目标文件；
`WEB_FILES = ("period.js", "period_align.js")` 每轮**两个文件都重写**（防上一轮变异残留
⇒ "已抓住"来自累积坏文件）。

## 验证（全部实测，非引用旧结论）

解释器：`C:\Users\Lenovo\.workbuddy-ai\binaries\python\versions\3.13.12\python.exe`

- `tools/selfcheck.py` ⇒ **RC=0**，`[1]` 97 个 Python + 13 个前端脚本全部合规，
  最长 `tools/check_session_grid.py` = 399；`[2]` 无反向依赖。
- `tools/check_period_aggregation.py` ⇒ **RC=0 全部通过**（7 组对照）。
- `tools/check_period_aggregation.py --selftest` ⇒ **RC=0**：
  - 守卫 2 条用例全抓（清空分组表 / 去掉最后一组）
  - 注入缺陷 **5 条全抓**且全部落在**期望前缀**上：
    `聚合系数偏移→aggregate(11项)` / `色标漏掉下限保护→bound(2项)` /
    `组数取整方向反了→aggregate(29项)` / `切列忽略区段过滤→sliceZones(19项)` /
    `alignSkew 忽略时段映射→时段映射(2项)`
- **非空转反向验证**（关键，防"变异表全是坏的却仍报绿"）：
  故意把 `alignSkew` 那条锚点改成 `index[b];  // NOPE`（原文不存在）⇒
  **`[FAIL] ...变异点已失效` + `结果: 1 项失败` + `RC=1`**；
  还原后立刻回 `RC=0`。⇒ 锚点校验本身不是装饰。

## 提交与启动（05:57–06:04）

### 提交推送

- 提交 **`0d30943`**（15 文件 / +662 −210），已推送到 `origin/main`。
- 远端真值核对：`git ls-remote origin refs/heads/main` = `0d3094388eeb…6a4d`
  = 本地 `HEAD`；`git status --porcelain` 空。
- ⚠️ **本批改动不是单一需求**：`web/config.js` 的 `heatmap.volumeBorder`、
  `web/period*.js` 的 volumes 聚合、4 个文件的注释同步，属**上一会话未提交**的
  "成交量驱动边框"功能；本会话只做了 `tools/` 三个文件的拆分 + 变异锚点修复。
  两者在同一批文件里交错（`period.js` / `period_align.js` 两轮都动过），
  **文件级无法拆分** ⇒ 合并为一个提交，与 2026-09-15/persistence-session-files
  的 ③ 同理。提交信息已分别记录两部分。
- 推送首跑 `RC=128`（`Connection closed by 198.18.1.93 port 22`）——
  瞬时断连，非权限问题：`ssh -T git@github.com` 返回 `Hi Skioleeya!` 认证正常，
  重试即 `RC=0`（`0261177..0d30943`）。
- 本仓库**禁用 `git rm` / `git mv`**，全程用 `git add -A`。

### 启动系统服务

前置：8060 无监听（新起）；IB Gateway **4002 LISTENING**（PID 7764，KAI 已启动）。

- `./venv/Scripts/python.exe run.py`，后台运行，控制台输出转 `logs/run_console.log`。
- `05:57:54 启动 delayed | 到期 20260915`、`05:58:10 流水线已就绪`；
  8060 `LISTENING`（PID 6572），页面 + 6 个前端资源 `curl` 全 **200**。
- 恢复：`已从 SQLite 恢复 492 个历史桶 + 492 个 Skew 点（会话 20260915）`。

### 实盘验证（全部实测）

- `tools/ws_probe.py` ⇒ **RC=0 全部通过**：24 档 × 1171→1172 桶（在长）、
  12,778 格、Skew 498 点、`25Δ = 2.842`、现货 7597.09、
  `7563.25 < 7597.09 < 7620.88`（Put/Call 定位正确）。
- `run.py --check` ⇒ **RC=0 全部通过**，且 **`[13]` 走真实联通路径**
  （有服务时不再 warning）：`connected / mode=delayed`、订阅 **80/92**、
  热力图 **24 档 × 1176 桶**、Skew **502 点**。
- **成交量链路由端到端确认**（本轮提交的核心）：WS 帧含
  `vol_bm` / `vol_i16` / `vol_filled`；`unpack(..., scale=1)` 解码
  **215 格非空、`vol_filled` 声明值 = 解码值 215（逐格对齐）**、min 19 / max 66、
  非零格 215。⇒ 新边框的数据源在实盘上确实有货。
- 持久化在写：`data/sessions/20260915.db` 700,416 → **704,512 B**、
  桶数 **505 → 506**（30 秒窗口内增长），表为 `heatmap_buckets` + `skew_points`。

### 未验证

- **未做浏览器取像素**（不生成/不截图 ⇒ 无多模态校验）：逐格边框的**实际视觉宽度**
  与 `maxRatio=0.35` 的观感未确认。数据源（vol_*）与前端消费点（`buildOption`
  逐格 `itemStyle.borderWidth`）已各自验证，但"边框看起来对不对"仍需 KAI 盘中肉眼确认。
- 未跑全量 `tools/check_*.py` 回归矩阵（本会话只动 `tools/` 三个文件 + 前端注释，
  已由结构检查器与目标回归覆盖）。
- 服务为**后台进程对**（23000 父 / 6572 工作），本会话的 shell 生命周期结束后
  是否存活未验证 —— 若被回收，需 KAI 用 `tools/start_detached.py` 或手动重启。

## 归属

- `check_period_aggregation` / `period_reference` / `period_node` / `period_selftest`
  四个文件的行数与职责，见本文件上表 —— **不进 `QUICKREF.md`**（一次性实例，非不变量）。
