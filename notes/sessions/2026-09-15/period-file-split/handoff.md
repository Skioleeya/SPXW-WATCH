---
task: period-file-split
date: 2026-09-15
time: 05:4x EDT
phase: GTH
head_at_start: 0261177
status: 未提交（改动 + 新文件均在工作区）
tests: "check_period_aggregation --selftest RC=0（6 项全抓）；selfcheck.py RC=0；结构检查器 [1]/[2] ok"
---

# 拆 period 回归的超限文件 + 修 2 条失效变异锚点

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

## 未做 / 未验证

- **改动未提交**（`git status` 含上轮遗留的多文件脏态，非本会话全部）。
- 本仓库**禁用 `git rm` / `git mv`**（见 2026-09-14/webgl-to-echarts 事故），
  拆分产生的两个新文件尚未 `git add`。
- 未跑全量 `tools/check_*.py` 回归矩阵（本会话只动了 `tools/` 三个文件，
  且已由结构检查器与目标回归覆盖）。

## 归属

- `check_period_aggregation` / `period_reference` / `period_node` / `period_selftest`
  四个文件的行数与职责，见本文件上表 —— **不进 `QUICKREF.md`**（一次性实例，非不变量）。
