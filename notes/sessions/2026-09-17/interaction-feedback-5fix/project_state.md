# Project State — interaction-feedback-5fix（2026-09-17）

## 一句话

KAI 点的五项交互缺陷（2 / 4 / 5 / 6 / 7）已全部修完并全绿：全宽横拖会响、
Skew 锁定侧变色、两图有复位按钮与快捷键、Skew 四区有游标和高亮框、
热力图有十字线与跨重建存活的提示框。工作区**脏且未提交**。

## 仓库状态

- `HEAD = 390ac6e`（已推送远端）
- 工作区**脏**：本轮 3 个新增 `web/` 文件 + 9 个修改的 `web/` 文件 + 3 个 `tmp/` 探针
  + `notes/`，**外加上一会话** `skew-drag-interaction` 未提交的 `web/skew*.js`、
  `heatmap-pan-drag` 未提交的 `web/heatmap*.js`、`skew-dual-axis-zoom`
  —— **四轮改动混在同一工作区**，引用时注意区分。
- 未跟踪：`notes/analysis/`（上一轮新建的目录，归属待 KAI 裁）

## 文件行数（`run.py --check [1]`，上限 400 严格小于）

| 文件 | 行数 | 说明 |
|---|---|---|
| web/style.css | **394** | 本轮新增 `.chip` / `.vbtn` / `.xhair` / `.region-hint` |
| web/skew_zoom.js | **394** | 本轮减 5 行（`leftHeld` 迁出），**距上限只剩 6 行** |
| web/skew_helpers.js | 390 | 本轮 +42（`regionsOf` / `leftHeld`） |
| web/heatmap.js | 383 | 悬停块迁出后回落 |
| web/heatmap_option.js | 378 | |
| web/skew.js | 357 | |
| web/config.js | 310 | 本轮 +40（新增 5 组配置键） |
| web/app_render.js | 215 | |
| web/app.js | 214 | |
| web/heatmap_hover.js | 185 | **新增** |
| web/skew_regions.js | 155 | **新增** |
| web/view_chips.js | 85 | **新增** |

⚠️ **`style.css` 与 `skew_zoom.js` 都到 394 行** —— 下一次动这两个文件
几乎必然要先拆分（`skew_zoom.js` 可拆的缝：手势状态机 / 视图状态导出；
`style.css` 可拆的缝：按面板分文件）。

## 服务状态（2026-09-17 07:5x EDT 实测）

- `:8060` 后端**在跑** —— 本轮四个 Playwright 探针 + 在线契约检查全部连上
- `:4002` IB Gateway **在跑**
- 需要服务的检查（`check_web_contract` 在线 / `[13]` 活链路段 / Playwright 探针）**现在都能跑**
- 重启后端：`venv/Scripts/python.exe run.py`

## 已验证 / 未验证

**已验证**
- `run.py --check` 16/16（**最终字节上重跑**）
- `check_web_contract` 离线 + 在线 全通过
- `tmp/_probe_feedback.js` 四模式：prod 49/0 · nofb 43/0 · nohover 41/0 · nohint 48/0（均 `RC=0`）
- 探针模式守卫：故意传 `nofbb` 会抛错（`exit 1`）
- `tmp/_probe_skew_drag.js`：prod 26/0
- 两张截图肉眼复核 + 面板头 `metaClipped: false`、1662px 无溢出

**未验证 / 未做**
- **A1 热力图纵轴仍不可交互**（诊断里最大的功能缺口，本轮**没做**）
- 触摸（E1）未接；两图不联动（C3）是 KAI 的明确取舍
- 像素级复核、真实物理鼠标验证 —— 都没有
- 三个探针在 `tmp/` **无回归保护**（按 KAI 明令不建常驻检查器）

## 设计取舍与已否决的选项（**理由留在这里，别在别处复述**）

1. **常驻反馈一律走 DOM 覆盖层，不用 ECharts 内部状态。**
   否决"调 `emphasis` / 挂 `axisPointer` / 开 `moveOnMouseMove`"三条路：
   实测在每 ≤400ms 的 `notMerge` 重建下全部失效（见 `handoff.md` 的不变量）。
2. **提示框补位按像素，不按 `dataIndex`。**
   列每帧在追加，索引会漂 —— 只有像素坐标是稳定的。
3. **锁定色必须"显式写回"才能解锁。**
   `setOption` 是 merge 语义，不把默认色写回去就会留色。
   同理 `_applyDecimals` 要把 formatter **合并进既有 `axisLabel`**，否则会连锁定色一起抹掉。
4. **区域矩形只定义一次**（`skew_helpers.js::regionsOf()`），
   手势层与反馈层共用 —— 否决"反馈层再算一遍"，那是重复真相。
5. **游标表达"动作"而不是"对象"**：左右两个纵轴区共用 `ns-resize`
   （左右之别由高亮框和徽标承载），否决"用两个不同游标区分左右"。
6. **状态文本从 meta 行迁到徽标** —— 一个事实只有一个归属；
   否决"meta 与徽标都写一份"。
7. **第 2 项只加"响"，不改语义**：全宽横拖**仍然不生成窗口**。
   否决"顺手让它也能平移" —— 那不是 KAI 要的，会改掉既有设计。

## 本轮踩的坑（含两个"差点写成错结论"的）

1. **`zr.handler.findHover(x, y, null)` 返回对象 `{target, topTarget}`，不是数组**
   —— 按数组写 `.slice` 会 `TypeError`，并让人误判"找不到图元"。
2. **取样点必须先确认有数据**：热力图**左侧约 2/3 是空的**（还没数据桶），
   在网格中心取样必然"什么都查不到"。连续 6 次诊断给出假的"无悬停"结论，
   最后**靠看截图**才发现是取样点错 ⇒ **否定结论之前，先证明取样点有数据**。
   之前的结论已全部撤回。
3. **可见性判据要统一**：探针查 `style.display`、实现用 `on` class ⇒ 4 条假 FAIL。
   现统一到 `on` class（与 `skew_regions.js` 一致）。
4. **状态文本归属变更后要同步探针**：`窗口 / 锁定` 移到徽标后，
   探针还在 meta 里找 `全宽` ⇒ 三个模式全 FAIL。
5. **⚠️ 探针模式参数会静默失效**：模式原只读环境变量 `SWATCH_MODE`，
   按位置参数传会**静默退回 prod** —— 三次"单开关翻转"跑的是同一份代码，
   差点把假绿当非空转证据。**已加守卫**（未知模式抛错）。
6. **断言用"最短间隙"而非"边对边"**：ECharts 贴近容器下沿会**自动把提示框
   翻到指针上方**，拿 `top` 比格子顶边会在翻转那次运行里**误报 1 条 FAIL**。
   `rectGap()` 单测：翻转上方 gap=0、压住 gap=0、飘走 gap=149.5 ⇒ 断言仍能报 FAIL。
