import type { EChartsOption } from 'echarts'
import { HISTORICAL_BAR_FREQUENCIES } from '../types/historicalBarFrequency'

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
  '1分钟', '5分钟', '15分钟', '30分钟', '60分钟', '日线', '周线',
].map((label, index) => ({ label, value: HISTORICAL_BAR_FREQUENCIES[index] }))

/** 行情图表周期工具栏（TradingView 风格短标签） */
export const CHART_PERIOD_OPTIONS = [
  '1m', '5m', '15m', '30m', '1h', '1D', '1W',
].map((label, index) => ({ label, value: HISTORICAL_BAR_FREQUENCIES[index] }))
