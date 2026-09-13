# Project State — recheck-keyorder-memory

## 本轮的主判断：上一轮报告属实，但有一处静默失效

逐条复核 `skew-period-consistency` 的终态报告，**全部对上**（7/7 前端语法、自检
11/11、两个新门禁 `--selftest` 变异全抓、帧里已无 `skew_min`/`skew_max`、
`MEMORY.md` 7958 字符）。

**唯一新发现**：报告与 `open_tasks.md` 都写着"已设一次性定时任务
（`e4ad7495-…`，2026-09-14 09:45 ET）"，但该任务在系统里**不存在**
（`automation list` 全局与按 cwd 均为空、`view` 报 not found）—— "开盘后补验收"
这条链路当时**没有任何触发点**。

→ 教训（与 `check_page_render` 假通过同族）：**"记录里写了"不等于"系统里有"。**
凡是"已设 / 已开 / 已生效"这类状态，判据必须是**去系统里读一次**，不是读记录。

## 冷数据键序：为什么统一为降序（KAI 2026-09-13 选定）

- 背景：同日早上 `cold-data-strike-order` 给冷数据加了 `sorted()`（**升序**）；
  同日晚 `frame-strike-order-descending` 把帧 `strikes` 改成**降序**，并**刻意**
  没动冷数据，代价是"冷数据升序、帧降序"并存。
- 被拒的选项：**保持两者相反**（理由"不同层，各自有回归"）—— 层不同是真的，
  但"同一系统里两处行序相反"对读代码的人是纯粹的陷阱，收益为零。
- 选定：**统一为降序**，与帧同向（高行权价在前）。
- 改动落在**产出点**：`HeatmapEngine.dump_bucket()` 的
  `sorted(self._buckets, reverse=True)` —— **不在** `recover()` / `load_snapshot()`
  侧重排。读侧重排等于第二处真相（写侧一个方向、读侧再翻一次），正是要避免的。
- 为什么不担心破坏恢复：`_buckets` 是 dict，键序不影响查找；`build()` 自己显式
  `sorted(..., reverse=True)`。冷数据键序只是**落盘产物**的一个不变量。
- 回归也翻向：`_case_key_order_ascending` → `_case_key_order_descending`，
  四条断言（内存 / 落盘 / `recover` / `load_snapshot`）全部改成降序期望。

## `MEMORY.md` 蒸馏的取舍

判据来自文件头："错了会**静默出错值**的约束留本文件；错了会**立刻报错**的坑放
skill"。

| 处理 | 内容 |
|---|---|
| 移出（改指针） | 下行体积的实测数字 / 消融口径 → README §6 与 `memory/2026-09-11.md`；限速桶的证伪手法 / 扰动值 / 端到端基线 → skill `spxw-live-verify` |
| 保留（压缩后） | `null` 语义、JS `""` 是 falsy、`scale` 由 `10 ** impulse_decimals` 推导、`enc` 名字对不上即报错、两个"限流"别混、`MaxRequests` 是类属性、`_IGNORED_CODES`、前端不得复制基线桶宽 |
| 新增 | 冷数据键序 = 降序（与帧同向） |

结果：**7958 → 7445 字符（余量 42 → 555）**。移出的内容**全部已有载体**，
没有信息消失。

## 未验证 / 残留

- 冷数据降序**只在本机离线回归上验过**（`check_persistence.py` 5/5 + 双向证伪）。
  `data/` 已清空，没有真实 `session.db` 可跑 —— 但代码路径与回归覆盖的就是
  产出点本身（`dump_bucket`），落盘/恢复/回灌三段都在用例里。
- 真实链路渲染验收仍未做（周日 fail-closed），已重建定时任务指向 2026-09-14 盘中。
