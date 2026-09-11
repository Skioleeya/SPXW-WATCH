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
       上限 400 是刻意取的：1 分钟粒度整个会话只有 390 列，所以这个截断只对
       30 秒粒度生效（780 列），更粗的周期一个像素都不变。 */
    maxColumns: 400
  },

  /* Skew 曲线 */
  skew: {
    showAtm: true,
    showPut25: true,
    showCall25: true,
    zeroLine: true,
    /* 纵轴留白比例 */
    padRatio: 0.18
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
