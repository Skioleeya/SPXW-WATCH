TASK-ID: skew-dual-axis-zoom
DATE: 2026-09-17
TIER: T2
STATUS: complete
CHANGE-ID: N/A:非 OpenSpec 仓库，无变更单
COMMIT: `ab853d3`（2026-09-17 五轮改动合并提交）—— 该会话结束时未提交（工作区 7 项脏：6 改 1 新，见 CHANGED-PATHS）
STARTUP-PROOF: notes/sessions/2026-09-17/skew-dual-axis-zoom/startup.md
NO-FALLBACK-BEHAVIOR: 删掉 `skew_helpers.js` 的 `FALLBACK_YCFG`（配置的第二份真相）；
  `skew_zoom.js::zoomCfg()` 缺键即抛错，不静默兜底。
NO-PATCH-BANDAGE: 没有在"缩 Y 时回滚 dataZoom 的 X 变更"上打补丁，
  而是把滚轮的**唯一主人**收进 `skew_zoom.js`（关掉 `zoomOnMouseWheel`）。

# Handoff — skew 图「双纵轴 + 时间轴」缩放

一句话：左轴 25Δ Skew 与右轴 IV **同一格滚轮一起缩**，X 轴时间范围一动不动；
双击复位两者。**顺带查实**：2026-09-15 那版"绑在容器上"的纵轴缩放
**从未执行过**（zrender 阻断传播），本次一并修掉。

---

## 需求与裁定

| 项 | 取值 | 出处 |
|---|---|---|
| 触发方式 | **滚轮**（网格内 = 缩两条纵轴；网格外 = 缩 X 时间轴）+ **双击复位** | KAI 2026-09-15 裁定，本轮沿用 |
| 步长 | 一格滚轮 `×1.15`（放大 `÷1.15`），来自 `config.js::skew.zoom.step` | 配置 |
| 纵轴范围限制 | `minSpan = 0.05` / `maxSpan = 500`（**波动率点**，两条轴共用一组） | `config.js::skew.zoom` |
| 横轴范围限制 | 窗口最少保留 `minCols = 8` 列 | 同上 |
| 锚点 | 指针所在的数值在缩放前后保持不动（两条轴**各按自己那条轴**的数值锚） | `zoom.anchorAtPointer` |
| 锁定语义 | 一次缩放 ⇒ **两条轴同时**进入锁定态，不再被自动量程覆盖 | 见 `project_state.md §3` |
| 复位 | 双击：X 回全宽 + 两条轴回自动量程 | 同上 |

---

CHANGED-PATHS

- `web/skew_zoom.js` —— **新增**（328 行）。缩放交互层：挂 zr 事件、算新量程 / 新窗口、
  派发 dataZoom、持有锁定态。对外：`bind()` / `yAxisPatch()` / `locked()` /
  `anyLocked()` / `reset()` / `clear()`。组件契约（技术栈 / 输入属性 / 输出形式）在文件头。
- `web/skew.js` —— 378 → **321** 行。删掉死掉的 `_bindWheel` / `_inGrid` /
  `_anchoredValue` / `_resetZoom` / `resetY`；接上 `SkewZoom`；`_yLocked`（单轴）
  → 由 `SkewZoom` 持有两条轴；X 窗口字段 `_zoom` 改名 `_xWin`（避免与缩放对象撞名）；
  `_readout()` 增加两条轴的锁定区间。
- `web/skew_helpers.js` —— 183 → **230** 行。`zoomRange()` 的上下限改为**显式参数**
  （原来内部读配置 + 带 `FALLBACK_YCFG` 兜底，已删）；新增纯函数 `zoomWindow()`
  （X 窗口按倍率 + 指针锚点缩放，含 `minCols` 夹取）。
- `web/skew_option.js` —— `buildFullOption()` 增加 `yPatch` 参数（两条轴的 `{min,max}`
  由 `skew_zoom.js` 统一给）；`dataZoom.zoomOnMouseWheel` `true` → **`false`**（附理由）。
- `web/config.js` —— `skew.yZoom` → `skew.zoom`：新增 `minCols`、`anchorAtPointer`，
  文件头写明三条触发分支与"一次缩放锁两条轴"的理由。
- `web/index.html` —— 面板头加一行手势说明；`<script src="skew_zoom.js">` 排在
  `skew_helpers.js` 之后、`skew.js` 之前。
- `web/app_render.js` —— `writeSkewMeta()` 在读数里同时报出两条轴的锁定区间
  （只报一条的话，右轴有没有跟着动在界面上看不出来）。
- `tmp/_probe_skew_yzoom.js` —— **新增**（探针，不入库）：真机 + 真帧的双轴缩放判据，19 条。
- `tmp/_diag_skew_wheel.js` / `tmp/_diag_xanchor.js` —— **新增**（探针，不入库）：
  定位"监听为何不触发"与"坐标换算用哪个 finder"。
- `tmp/_mutate_skew_yzoom.sh` —— **新增**（探针，不入库）：四处变异的非空转验证。
- `notes/sessions/2026-09-17/skew-dual-axis-zoom/{startup,project_state,handoff}.md` —— 本会话记录。

---

COMMAND-EVIDENCE

```text
# 真机 + 真实帧（后端 PID 7784 :8060，IB Gateway PID 1232 :4002，GTH 段）
NODE_PATH=<playwright> node tmp/_probe_skew_yzoom.js          → RC=0，PASS 19 / FAIL 0
  before  y0=[-0.57816,3.79016] y1=[14,20]   dz=[0,100]
  after   y0=[-0.18058,3.61796] y1=[14.54609,19.76348] dz=[0,100]   ← X 一动不动
  锚点（指针在网格 25% 宽 / 30% 高处）：
    左轴 2.4797 → 2.4784（不变）；右轴 18.2000 → 18.1983（不变）
    反证：同一滚轮下 50% 高度处的数值 1.6060 → 1.7187 **确实变了** ⇒ 锚点判据非恒真
  网格外滚轮：dz [0,100] → [3.26,90.22]，两条轴 span 完全不变
  双击：y0 3.7985→4.3683、y1 5.2174→6.0000、dz→[0,100]
  连缩 60 格：左轴 span 恰好 0.050000（= minSpan），两条轴均未塌成零宽
  连缩 120 格：左轴 span 500.000（= maxSpan，未超）
  `min:null,max:null`：auto [14,20] → pin [9,25] → 置 null → 回 [14,20]

# 非空转（4 处变异，各跑一次探针；还原后 cmp 逐字节一致）
bash tmp/_mutate_skew_yzoom.sh                                → 对照组 RC=0 / PASS 19
  变异 1 滚轮绑回图表容器（复现原缺陷）        → RC=1，PASS 12 / FAIL 7
  变异 2 AXES 只留 [0]（右轴不缩）             → RC=1，PASS 12 / FAIL 7
  变异 3 zoomOnMouseWheel 改回 true            → RC=1，PASS 18 / FAIL 1（X 被带偏那条抓到）
  变异 4 锚点改回量程中心                      → RC=1，PASS 16 / FAIL 3

# 项目门禁 / 语法
venv/Scripts/python.exe run.py --check                        → 16/16 项全部通过，RC=0
node --check web/*.js（13 个文件）                             → 全部通过，无输出
```

VALIDATION-SUMMARY

- `tmp/_probe_skew_yzoom.js`（真机真帧）→ `RC=0`，19/19
- `tmp/_mutate_skew_yzoom.sh` → 对照组 `RC=0`；4 处变异各 `RC=1`；4/4 逐字节还原
- `run.py --check` → `RC=0`，16/16
- `node --check web/*.js` → 全部通过
- `web/skew.js` 321 / `web/skew_zoom.js` 347 / `web/skew_helpers.js` 230 /
  `web/skew_option.js` 137 —— 全部 **< 400 行**

NOTES-PATHS

- `notes/sessions/2026-09-17/skew-dual-axis-zoom/startup.md`
- `notes/sessions/2026-09-17/skew-dual-axis-zoom/project_state.md`
- `notes/sessions/2026-09-17/skew-dual-axis-zoom/handoff.md`
- `notes/context/handoff.md` · `notes/context/project_state.md` · `notes/context/open_tasks.md`
- `.workbuddy-ai/memory/2026-09-17.md`

---

## Closed in session

- **2026-09-15 遗留的"纵轴滚轮缩放"死代码** —— 不是"没做完"，是**从未生效**。
  根因：监听绑在图表容器上，而 zrender 在自己的 viewport root 里
  `stopPropagation()`。实测计数 `zr=1 / 容器=0 / document=0`。
- **右轴（IV）不参与缩放** —— 本次扩成两条轴同步，并明确"一次缩放锁两条轴"。
- **`skew_helpers.js::FALLBACK_YCFG`** —— 配置的第二份真相，已删；缺键即抛错。
- **`resetY()` / `yLocked()` 两个无调用方的公开方法** —— 已删（`yLocked()` 保留为
  面板对 `SkewZoom.locked(0)` 的转发）。
- **面板上没有任何纵轴缩放的手势提示** —— 已加一行文字（`index.html`）。

## OPEN-RISKS

- **两条轴共用一组 `minSpan/maxSpan` ⇒ 下限会先后触底**：左轴自然量程小（约 4.4），
  先夹到 0.05；此后继续放大只有右轴在动。极端缩放下"同步"名不副实。
  要严格同步得改成"按比例缩放"。**未改，属设计取舍**，见 `project_state.md §5`。
- **探针留在 `tmp/`，无回归保护**：按 KAI 2026-09-15 明令"不额外搭检查/校验模块"，
  没有落成 `tools/` 常驻检查器。代价：日后改 `skew_zoom.js` 不会被自动跑到。
  要纳入 `tools/` 需先申请。
- **本轮未做浏览器像素级核对**（只读了 ECharts 的 extent 与 dataZoom 百分比，
  没有截图比像素）。判据覆盖的是"数值与窗口"，不是"肉眼观感"。
- **未在盘中 RTH 段复验**：本轮是 GTH 段（现价不动），Skew 曲线基本平；
  缩放对"移动中的曲线"的观感（是否闪、是否跳）**未观察**。
- `notes/context/*` 三件套已同步本轮；`notes/context/handoff.md` 顶部原先指向
  `heatmap-two-window`（已提交 `130acdc`），本轮改为指向本会话。
