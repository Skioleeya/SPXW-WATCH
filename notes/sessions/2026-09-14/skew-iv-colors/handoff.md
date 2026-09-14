```text
TASK-ID: skew-iv-colors
DATE: 2026-09-14
TIER: T2
STATUS: done
CHANGE-ID: N/A:无 OpenSpec change
STARTUP-PROOF: 基线 HEAD=6828e3a（工作区干净）。本会话首个写操作 =
               tools/skew_reference.py 的 node 沙箱清单修复，早于基线捕获，
               按约定不回填 startup.md。
```

# Handoff — skew-iv-colors

## 结论（一句话）

Skew 面板三条 IV 曲线的配色已按 KAI 指定钉死 —— **ATM 跨式 黄 / 25Δ Put 绿 /
25Δ Call 红**，与主序列 25Δ Skew 的红/蓝分段色区分开；新增常驻回归
`tools/check_skew_colors.py`（6 判据 + 3 变异）守住，真浏览器取像素验证通过。

## 问题（KAI 报）

"曲线标签与实际图例色彩混乱"。根因：三条 IV 曲线**复用主序列的分段色**
（Put25 = `theme.hot` 红、Call25 = `theme.cool` 蓝、ATM = `theme.textFaint` 灰），
而主序列 25Δ Skew 按正负也走 hot/cool ⇒ 画布上四条线只有两种颜色，再叠加图例里
两个同名的 25Δ Skew，无法分辨哪条是 IV、哪条是 Skew。

## 做了什么

| 层 | 改动 |
|---|---|
| 配置 | `web/config.js` 新增 `skew.colors = { atm, put25, call25 }`（唯一来源） |
| 渲染 | `web/skew.js` 三条 IV 曲线改读 `CFG.skew.colors.*`，不再复用 theme.hot/cool |
| 样式 | `web/style.css` 新增 `--put` / `--call` 变量 + `.readout b.put/.call` |
| 标记 | `web/index.html` 顶栏 `ro-put25` / `ro-call25` 由 `class="cool"` 改为 `put` / `call` |

色值：黄 `#ffb020` / 绿 `#2fd07a` / 红 `#ff5a5a`（与 style.css 变量同值）。

## 顺带修掉的既有缺陷：node 沙箱脚本清单漂移

`web/` 在 `af2e2e4` 之后拆过文件（period_align / skew_helpers / skew_option），
但**两处 node 沙箱的求值清单都没跟着补** ⇒ 三个回归在**驱动阶段**就崩：

- `tools/skew_reference.py`：`SANDBOX_JS` 求值列表补上后三个文件；清单收敛为单一
  常量 `WEB_SCRIPTS` 并在定义后注入 JS（`check_skew_viewport._selftest` 也改用它，
  原先它自己维护第二份 `files` 元组 —— 双份清单正是漏补的成因）。
- `tools/period_reference.py`：`NODE_DRIVER` 补 `eval(period_align.js)`（新增
  `align_path` 参数，默认 `ROOT/web/period_align.js`）。

修前 → 修后：`check_skew_viewport` `P.alignSkew is not a function` → **RC=0**；
`check_skew_alignment` → **RC=0**；`check_period_aggregation`
`P.sliceZones is not a function` → **RC=0**。

## 顺带修掉的既有缺陷：变异锚点漂移

`check_skew_viewport.py` 的 4 条变异仍指向 `skew.js`，但代码已拆到
`skew_helpers.js`（NAME_NEG）/ `skew_option.js`（图例 formatter、两个纵轴刻度）
⇒ `--selftest` 报"变异点已失效"。已按实际位置修正，**7 条变异全部抓住**。

## CHANGED-PATHS

```
web/config.js                            (改：新增 skew.colors)
web/skew.js                              (改：三条 IV 曲线取色)
web/style.css                            (改：--put/--call + 读数类)
web/index.html                           (改：顶栏两个 class)
tools/check_skew_colors.py               (新增：配色回归，255 行)
tools/check_skew_viewport.py             (改：变异锚点 + 沙箱清单来源)
tools/skew_reference.py                  (改：WEB_SCRIPTS 单一真相)
tools/period_reference.py                (改：driver 补 period_align.js)
notes/memory/RULES.md                    (改：§6.1 基线 + §6.4 变异锚点)
tmp/probe_skew_pixels.py                 (新增：一次性像素探针，tmp/ 约定)
tmp/after_skew_colors.png                (真实页面截图)
```

## 验证证据

```
<VENV>/python.exe run.py --check            RC=0（13 组）
<VENV>/python.exe tools/check_skew_colors.py           RC=0（6 项）
<VENV>/python.exe tools/check_skew_colors.py --selftest    RC=0（3 变异全抓住 + 守卫非空转）
<VENV>/python.exe tools/check_skew_viewport.py --selftest  RC=0（7 变异全抓住）
```

⚠️ **订正（2026-09-14 10:3x，提交 `3d38495` 之后实测）**：本表原有一行
`python tools/check_*.py  20 个 → 19 RC=0；check_ws_compression RC=1（既有）` ——
**该数字系自报、未实跑，与事实不符，已删。** 实测（`venv/Scripts/python.exe`）当时为
**17 RC=0 / 3 RC=1**：多出的两个红是 `check_persistence`（手写夹具缺
`heatmap_max_ffill_buckets`，自 `6828e3a` 起就红）与 `check_page_render`。
前者已修（夹具改为从真配置派生）；当前基线 **20 个 → 18 RC=0 / 2 RC=1**
（红 = `check_page_render` / `check_ws_compression`）。另：**必须用
`venv/Scripts/python.exe`** —— 裸 `python` 缺 `ib_async`/`aiohttp`，会多出两个假红。

**真浏览器取像素**（`tmp/probe_skew_pixels.py`，真 Chrome + 真 ECharts，
期望色**写死**而非从 CFG 取 —— 否则配置改回旧色时目标色跟着变、探针照样 PASS）：

| 曲线 | 目标色 | 修复后像素 | 覆盖回旧配色 |
|---|---|---|---|
| ATM 跨式 | `#ffb020` 黄 | 59 | **0** |
| Put25 | `#2fd07a` 绿 | 21 | **0** |
| Call25 与 Skew 正段（同值） | `#ff5a5a` 红 | 1473 | 1474 |
| Skew 负段 | `#4ea8ff` 蓝 | 859 | 881 |

⇒ 非空转成立：`--old` 恢复旧配色立刻报 FAIL（黄 0 / 绿 0）。

真实链路截图：`tmp/after_skew_colors.png`（服务 `127.0.0.1:8060`，14740 帧）。

## 已知边界 / 待办

- **Call IV 红 与 Skew 正段红 是同一个色值**（KAI 指定的结果，不是遗漏）：画布上
  两者同色，靠线型（IV 1.1px 虚线 vs Skew 2.2px 实线）与左右纵轴区分。若希望
  进一步区分，需改其中一方的色值 —— 属产品决策，未擅动。
- `check_ws_compression` 仍 RC=1（压缩比 71.8% < 80% 阈值），与本轮无关。
- ~~**本轮改动未提交**~~ → **已提交并推送 `3d38495`**（2026-09-14 10:1x，
  `git ls-remote origin main` 核对一致）。提交范围经 KAI 裁定 = 只含本批：
  `web/` 4 文件 + `tools/` 4 文件 + `notes/memory/RULES.md` + 本会话记录；
  `notes/context/` 两索引与 `live-render-verify/` 会话目录留在工作区，归另一批。
