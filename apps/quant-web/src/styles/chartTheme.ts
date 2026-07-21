/** Lightweight Charts / ECharts 共用的 K 线配色主题 */
export interface ChartTheme {
  background: string
  grid: string
  axis: string
  text: string
  textMuted: string
  up: string
  down: string
  volumeUp: string
  volumeDown: string
  ema: string
  macdDif: string
  macdDea: string
  atr: string
}

/** SSR 或无 CSS 变量时的默认配色 */
const FALLBACK: ChartTheme = {
  background: '#0b111b',
  grid: '#202a3a',
  axis: '#39465b',
  text: '#9aa7b9',
  textMuted: '#8290a6',
  up: '#fa5151',
  down: '#07c160',
  volumeUp: 'rgba(250, 81, 81, 0.42)',
  volumeDown: 'rgba(7, 193, 96, 0.42)',
  ema: '#f59e0b',
  macdDif: '#38bdf8',
  macdDea: '#f59e0b',
  atr: '#a78bfa',
}

function cssValue(style: CSSStyleDeclaration, name: string, fallback: string) {
  return style.getPropertyValue(name).trim() || fallback
}

/** 从 document root 的 CSS 变量解析图表主题（优先 --gy-chart-*） */
export function resolveChartTheme(root: Element = document.documentElement): ChartTheme {
  if (typeof window === 'undefined') return FALLBACK
  const style = window.getComputedStyle(root)
  return {
    background: cssValue(style, '--gy-chart-bg', FALLBACK.background),
    grid: cssValue(style, '--gy-chart-grid', FALLBACK.grid),
    axis: cssValue(style, '--gy-chart-axis', FALLBACK.axis),
    text: cssValue(style, '--gy-chart-text', FALLBACK.text),
    textMuted: cssValue(style, '--gy-text-muted', FALLBACK.textMuted),
    up: cssValue(style, '--gy-up', FALLBACK.up),
    down: cssValue(style, '--gy-down', FALLBACK.down),
    volumeUp: cssValue(style, '--gy-chart-volume-up', FALLBACK.volumeUp),
    volumeDown: cssValue(style, '--gy-chart-volume-down', FALLBACK.volumeDown),
    ema: cssValue(style, '--gy-chart-ema', FALLBACK.ema),
    macdDif: cssValue(style, '--gy-chart-macd-dif', FALLBACK.macdDif),
    macdDea: cssValue(style, '--gy-chart-macd-dea', FALLBACK.macdDea),
    atr: cssValue(style, '--gy-chart-atr', FALLBACK.atr),
  }
}
