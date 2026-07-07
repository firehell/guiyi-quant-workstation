import type { EChartsOption } from 'echarts'

/** A股配色：涨红跌绿 */
export const STOCK_COLORS = {
  up: '#ef4444',
  down: '#22c55e',
  flat: '#999999',
} as const

/** ECharts 通用网格配置 */
export const defaultGrid: EChartsOption['grid'] = {
  left: '3%',
  right: '3%',
  bottom: '3%',
  containLabel: true,
}

/** ECharts 通用 tooltip 配置 */
export const defaultTooltip: EChartsOption['tooltip'] = {
  trigger: 'axis',
  axisPointer: { type: 'cross' },
}

/** 期货交易所列表 */
export const EXCHANGES = [
  { label: '上期所 (SHFE)', value: 'SHFE' },
  { label: '中金所 (CFFEX)', value: 'CFFEX' },
  { label: '大商所 (DCE)', value: 'DCE' },
  { label: '郑商所 (CZCE)', value: 'CZCE' },
  { label: '上海能源 (INE)', value: 'INE' },
] as const

/** K线周期选项 */
export const PERIODS = [
  { label: '1分钟', value: '1m' },
  { label: '5分钟', value: '5m' },
  { label: '15分钟', value: '15m' },
  { label: '30分钟', value: '30m' },
  { label: '60分钟', value: '60m' },
  { label: '日线', value: '1d' },
] as const

/** 行情图表周期工具栏（TradingView 风格短标签） */
export const CHART_PERIOD_OPTIONS = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '30m', value: '30m' },
  { label: '1h', value: '60m' },
  { label: '1D', value: '1d' },
] as const
