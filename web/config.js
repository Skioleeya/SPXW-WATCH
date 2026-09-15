/* 前端展示配置
 * ------------------------------------------------------------------
 * 这里只放【呈现】参数。任何与后端有关的取值（端口、WS 路径、推送频率、
 * 矩阵尺寸）一律不在这里硬编码，而是启动时从 /health 动态获取。
 *
 * 理由：端口和路径属于后端的 config/transport.json，前端复制一份就等于
 * 制造了"两份真相"，改一处忘一处必然导致连不上。
 * ------------------------------------------------------------------ */

window.SWATCH_CONFIG = {
  /* 断线重连退避 */
  reconnect: {
    initialMs: 400,
    maxMs: 8000,
    factor: 1.7,
    jitterMs: 200
  },

  /* 渲染节流：后端推送可能远快于屏幕刷新，按帧合并 */
  render: {
    maxFps: 5,
    staleWarnMs: 15000,
    staleErrorMs: 45000
  },

  /* 热力图 */
  heatmap: {
    /* 色标：Plotly `Turbo` 顺序色阶，逐色抄自参考项目 live-volatility-surface
       （dash_surface.py 的 IV_COLORSCALE，其 DASHBOARD_CONFIG_DEFAULTS 取 "Turbo"，
       未反转）。冷端 = IV 下行，暖端 = IV 上行。
       取位规则：ECharts 的 inRange.color 数组与 Plotly 的 list 色阶一致，都是在
       数组上等距取点，故 15 色落在 0, 1/14, …, 1 —— 与本图 visualMap 的
       [-vmax, +vmax] 对齐后，两端读数与原项目同色。
       注意：这是顺序色阶，不是发散色阶；0 值落在第 8 色（黄绿），不再是中性灰。 */
    palette: [
      "#30123b", "#4145ab", "#4675ed", "#39a2fc", "#1bcfd4",
      "#24eca6", "#61fc6c", "#a4fc3b", "#d1e834", "#f3c63a",
      "#fe9b2d", "#f36315", "#d93806", "#b11901", "#7a0402"
    ],
    /* 防除零守卫：色标量程一律采用后端下发的 vmax（后端已按配置的分位截断 +
       下限保护算好）。这里只在 vmax 缺失或为 0 时兜一个极小值，避免色标
       min==max 导致映射出 NaN 颜色。它不是"色标下限策略"，不要在这里调节
       对比度——那是 config/serialization.json 的事。 */
    boundEpsilon: 0.05,
    /* 纵轴行权价标签最多显示多少个，避免拥挤 */
    maxYLabels: 26,
    /* 横轴时间标签间隔（按列数自动调整的基准） */
    xLabelCount: 14,
    showSpotLine: true,

    /* 网格线 —— 旧版 ECharts 的 `itemStyle: {borderWidth:1, borderColor: theme.grid}`
       在 af2e2e4 的 WebGL 重写中被删除（theme.grid 一度成为**死配置**，2026-09-14 定位）。
       2026-09-14 渲染器换回 ECharts 后，恢复方式改为轴 `splitLine`：
       颜色取 `theme.grid`、宽度 1px，`cellBorderMix` 映射为线的 opacity ——
       `opacity m` 的线叠在数据色上 ≡ 旧 shader 的 `mix(color, border, m)`，数学等价。

       **网格线按最小间距抽样**：细档位列宽只有 1–2 像素（30 秒档 2370 列在
       1250px 网格里每列仅 0.53px；1 分档 630 列 ⇒ 2px），每格都画线等于把格子吃光。
       所以每 `stride` 个分类画一条，`stride = ceil(cellBorderMinPx / cellPx)` ——
       线间距恒 ≥ 本值。
       用 splitLine 而不是逐格 `itemStyle.borderWidth` 的原因：后者要给 5.7 万个矩形
       各描一次边，在 2370 列下既是性能灾难、又会把细档位糊成一片。

       取值说明（2026-09-14 由 5 调到 12，KAI 定的方案 A）：
       原值 5 在细档位下**等于没画** —— 30 秒档 1086 列 ⇒ cellPx=1.02px，
       stride=ceil(5/1.02)=5 ⇒ 线间距仅 5.12px。1px 宽、55% 不透明的深色线落在
       同样 1px 宽的彩色数据格上，被数据色吃掉；实测截图里**空白区网格清晰、
       数据密集区完全看不见**。且 `stride × cellPx` 在 cellPx < 本值时会锁死在
       本值附近（ceil 的必然结果）⇒ "无极调节"在稠密区实际失效。
       调到 12 后线间距恒 ≈ 12.3px，30 秒档线数 217 → 90，密集区可辨。
       副作用：5 分档 cellPx=10.2px < 12 ⇒ stride 由 1 变 2，间距 10.2 → 20.4px，
       网格变稀（仍够用，15 分档 cellPx=30px 不受影响，stride 仍为 1）。

       取值边界：太小（< 3）线会挨到一起变糊；太大（> 20）网格会稀到失去"格子"
       的观感、细档位的格子被抹平。单位是 CSS 像素（ECharts 坐标单位）。 */
    cellBorderMix: 0.55,
    cellBorderMinPx: 12,

    /* 成交量驱动的逐格边框 —— 行权价 × 方向那一行在某个时间桶上的成交量越大，
       该格的黑色边框越粗。**颜色统一黑，只有粗细变**。

       数据源唯一：**30 秒桶的 tick 计数**（后端 `vol_bm`/`vol_i16`，scale=1）。
       更粗的显示周期由 `web/period.js::aggregate` 在组内**求和**得到，不另取数据。

       为什么不用白色混色：旧 WebGL shader 是 `mix(color, white, 0.6)`，白边压在
       高值区的亮黄绿填充上几乎看不出边界；黑色在整条 Turbo 色阶上都对比明确。 */
    volumeBorder: {
      enabled: true,
      /* 边框颜色。所有格子统一用这一个色，粗细才是唯一的编码维度。 */
      color: "#000000",
      /* 最粗边框 = 本值 × 格子**短边**。与旧 shader 的 `border = vol*0.35` 同量级；
         调到 0.5 时成交量最大的格子会被边框吃光，只剩中间一点填充。 */
      maxRatio: 0.35,
      /* 边框宽度下限（CSS px）。0 = 允许完全无边框（成交量为 0 的格子不描边）。 */
      minPx: 0
    },

    /* 可选时间周期（秒）。这是纯呈现参数：它只决定给用户几个缩放档位。
       真正的基线桶宽由后端帧里的 heatmap.bucket_seconds 给出，前端不复制 ——
       不满足"基线桶宽整数倍"的项会被自动丢弃并告警（见 web/period.js）。 */
    periods: [
      { seconds: 30, label: "30秒" },
      { seconds: 60, label: "1分" },
      { seconds: 180, label: "3分" },
      { seconds: 300, label: "5分" },
      { seconds: 900, label: "15分" }
    ],
    /* 打开页面时默认选中的周期（秒）。不在可用列表里则回退到列表第一项。 */
    defaultPeriodSeconds: 60,
    /* 一屏最多画多少列，超出只画**最近**的若干列。
       取值必须 ≥ 整个交易日网格的桶数（2370 = 71100s ÷ 30s），也就是说：
       **在一个交易日之内这个截断永远不会生效**。这不是"忘了调小"，是刻意的。
       横轴是时间轴，从尾部截掉历史段在图上**看不出来**（只是左边少了几列、
       没有滚动条也没有提示），于是 GTH 开盘那一段会静默消失 —— 而"能在 GTH
       时段完成实盘验证"恰恰要求看得见 GTH。密度交给周期选择器：30 秒全时段
       是 2360 列（很密），想看全貌就切 5 分钟。
       tools/check_period_aggregation.py 的跨文件不变量会核对这个下限。 */
    maxColumns: 2370
  },

  /* 时段视图。
     按钮本身**不在这里声明** —— 时段真相在 config/app.json 的 sessions，
     随帧下发到 session.zones（含 id 与显示名），前端照着生成按钮。在这里抄一份
     "GTH / RTH" 就是把会话定义抄了第二遍，后端加一个时段前端不会跟着变。
     这里只放那个**合成的**"全部时段"档的显示名。 */
  sessions: {
    allId: "all",
    allLabel: "全时段"
  },

  /* Skew 曲线 */
  skew: {
    showAtm: true,
    showPut25: true,
    showCall25: true,
    zeroLine: true,
    /* 纵轴留白比例 */
    padRatio: 0.18,
    /* 纵轴**刻度标签**的小数位（左右两个纵轴共用）。这**不是数据精度** ——
       数据精度是 decimals.skew / decimals.iv（提示框与顶栏读数用）。刻度只需
       够分辨量级，位数给多了反而糊成一团。 */
    axisDecimals: 1,
    /* 横轴时间标签的目标数量。按**当前可见列数**算间隔，所以滚轮放大之后
       标签会自动变密（与 heatmap.xLabelCount 同一规则）。 */
    xLabelCount: 14,

    /* 三条 IV 曲线（右轴）的语义色。
       **必须与主序列的分段色区分开**：主序列 25Δ Skew 按正负用 hot(红)/cool(蓝)
       分段；IV 曲线若复用同样两色，图上就只剩"两条红、两条蓝"，再叠加图例里
       两个同名的 25Δ Skew，用户无法判断哪条是 IV、哪条是 Skew。三条 IV 曲线
       之间也必须互不同色。
       语义：atm = ATM 跨式（straddle）IV，put25 = 25Δ Put IV，call25 = 25Δ Call IV。
       与 style.css 的 --warn / --put / --call 同值（顶栏读数用同一套语义色）。 */
    colors: {
      atm: "#ffb020",
      put25: "#2fd07a",
      call25: "#ff5a5a"
    }
  },

  /* 小数位（仅显示用） */
  decimals: {
    spot: 1,
    iv: 2,
    skew: 2,
    impulse: 2,
    price: 2
  },

  /* 面板配色，与 style.css 的 CSS 变量保持一致 */
  theme: {
    text: "#dbe3ec",
    textDim: "#8b97a5",
    textFaint: "#5d6874",
    border: "#232b34",
    grid: "#1a2029",
    panel: "#11151a",
    accent: "#00e5ff",
    hot: "#ff5a5a",
    cool: "#4ea8ff",
    warn: "#ffb020"
  }
};
