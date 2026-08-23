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
  ema10: string
  ema20: string
  ema21: string
  ema60: string
  macdDif: string
  macdDea: string
  htdy: string
  htdyZk1: string
  htdyZd1: string
  htdyZd2: string
}

/** SSR 或无 CSS 变量时的默认配色（与亮色 tokens.css 对齐） */
const FALLBACK: ChartTheme = {
  background: '#FFFFFF',
  grid: '#EDF1F7',
  axis: '#98A2B3',
  text: '#33507E',
  textMuted: '#5B718F',
  up: '#DC2626',
  down: '#16A34A',
  volumeUp: 'rgba(220, 38, 38, 0.38)',
  volumeDown: 'rgba(22, 163, 74, 0.38)',
  ema10: '#D97706',
  ema20: '#EA580C',
  ema21: '#F59E0B',
  ema60: '#7C3AED',
  macdDif: '#0284C7',
  macdDea: '#F59E0B',
  htdy: '#F79009',
  htdyZk1: '#0F766E',
  htdyZd1: '#0891B2',
  htdyZd2: '#D97706',
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
    ema10: cssValue(style, '--gy-chart-ema-10', FALLBACK.ema10),
    ema20: cssValue(style, '--gy-chart-ema-20', FALLBACK.ema20),
    ema21: cssValue(style, '--gy-chart-ema', FALLBACK.ema21),
    ema60: cssValue(style, '--gy-chart-ema-60', FALLBACK.ema60),
    macdDif: cssValue(style, '--gy-chart-macd-dif', FALLBACK.macdDif),
    macdDea: cssValue(style, '--gy-chart-macd-dea', FALLBACK.macdDea),
    htdy: cssValue(style, '--gy-status-warning', FALLBACK.htdy),
    htdyZk1: cssValue(style, '--gy-chart-htdy-zk1', FALLBACK.htdyZk1),
    htdyZd1: cssValue(style, '--gy-chart-htdy-zd1', FALLBACK.htdyZd1),
    htdyZd2: cssValue(style, '--gy-chart-htdy-zd2', FALLBACK.htdyZd2),
  }
}
