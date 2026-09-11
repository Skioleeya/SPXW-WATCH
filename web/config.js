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
    /* 发散色标：冷 = IV 下行，暖 = IV 上行 */
    palette: [
      "#0b3a6f", "#155ea8", "#3d8fd1", "#8ec9ee",
      "#1a1f26", "#1a1f26",
      "#f6c98a", "#f4a259", "#ef6f4c", "#d63b2f", "#a81f1c"
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
    showSpotLine: true
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
    panel: "#11151a",
    accent: "#00e5ff",
    hot: "#ff5a5a",
    cool: "#4ea8ff",
    warn: "#ffb020"
  }
};
