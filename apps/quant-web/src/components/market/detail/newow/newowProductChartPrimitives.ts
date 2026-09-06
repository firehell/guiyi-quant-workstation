import type {
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
} from 'lightweight-charts'
import type { InjectionKey } from 'vue'

import type {
  NewowAuxiliaryComponent,
  NewowProductFrequency,
  NewowProductSectionResponse,
  NewowResourceLifecycle,
} from '../../../../types/newowProduct.ts'
import { chartCoordinate } from '../../../../utils/newowProductTypes.ts'

export interface NewowProductChartBar {
  readonly barEnd: string
  readonly tradingDay: string
  readonly open: number
  readonly high: number
  readonly low: number
  readonly close: number
  readonly volume: number
  readonly physicalContract: string
  readonly segmentId: string
}

export interface NewowProductLinePoint {
  readonly barEnd: string
  readonly tradingDay: string
  readonly value: number
}

export interface NewowProductMainLine {
  readonly id: string
  readonly key: string
  readonly label: string
  readonly segmentId: string
  readonly points: readonly NewowProductLinePoint[]
}

export interface NewowProductActionMarker {
  readonly id: string
  readonly kind: 'BUILD' | 'CLEAR'
  readonly barEnd: string
  readonly tradingDay: string
  readonly value: number
  readonly referencePrice: string
  readonly physicalContract: string
  readonly segmentId: string
  readonly sequence: number
}

export interface NewowProductHintMarker {
  readonly id: string
  readonly kind: string
  readonly barEnd: string
  readonly tradingDay: string
  readonly value: number | null
  readonly anchorPrice: string | null
  readonly confirmedAt: string
  readonly source: string
  readonly sequence: number | null
}

export interface NewowProductChartModel {
  readonly identity: {
    readonly product: string
    readonly strategy: NewowProductSectionResponse<'chart'>['meta']['identity']['strategy']
    readonly frequency: NewowProductFrequency
  }
  readonly bars: readonly NewowProductChartBar[]
  readonly mainLines: readonly NewowProductMainLine[]
  readonly actions: readonly NewowProductActionMarker[]
  readonly hints: readonly NewowProductHintMarker[]
  readonly nextBefore: string | null
}

const MAIN_LAYER_DEFINITIONS = {
  trend: [['b', 'B'], ['a', 'A']],
  oscillation: [['upper', 'HHV'], ['lower', 'LLV']],
  main_rise: [['ma35', 'MA35'], ['ma45', 'MA45']],
} as const

/** Projects only validated P4 facts. It never calculates a strategy value. */
export function buildNewowProductChartModel(
  response: NewowProductSectionResponse<'chart'>,
): NewowProductChartModel {
  if (response.value === null) {
    return {
      identity: {
        product: response.meta.identity.product,
        strategy: response.meta.identity.strategy,
        frequency: response.meta.identity.frequency,
      },
      bars: [], mainLines: [], actions: [], hints: [], nextBefore: null,
    }
  }
  const value = response.value
  const bars = value.bars.map((bar): NewowProductChartBar => ({
    barEnd: bar.bar_end,
    tradingDay: bar.trading_day,
    open: chartCoordinate(bar.open),
    high: chartCoordinate(bar.high),
    low: chartCoordinate(bar.low),
    close: chartCoordinate(bar.close),
    volume: bar.volume,
    physicalContract: bar.physical_contract,
    segmentId: bar.segment_id,
  }))
  const barByEnd = new Map(bars.map((bar) => [bar.barEnd, bar]))
  const mainLines: NewowProductMainLine[] = []
  for (const [key, label] of MAIN_LAYER_DEFINITIONS[response.meta.identity.strategy]) {
    const bySegment = new Map<string, NewowProductLinePoint[]>()
    for (const frame of value.frames) {
      const text = frame.main_values[key]
      const bar = barByEnd.get(frame.bar_end)
      if (text === null || text === undefined || bar === undefined) continue
      const points = bySegment.get(bar.segmentId) ?? []
      points.push({ barEnd: bar.barEnd, tradingDay: bar.tradingDay, value: chartCoordinate(text) })
      bySegment.set(bar.segmentId, points)
    }
    for (const [segmentId, points] of bySegment) {
      mainLines.push({ id: `${key}:${segmentId}`, key, label, segmentId, points })
    }
  }
  const actions = value.actions.map((action): NewowProductActionMarker => ({
    id: action.signal_id,
    kind: action.kind,
    barEnd: action.bar_end,
    tradingDay: action.trading_day,
    value: chartCoordinate(action.reference_price),
    referencePrice: action.reference_price,
    physicalContract: action.physical_contract,
    segmentId: action.segment_id,
    sequence: action.sequence,
  }))
  const hints = value.hints.map((hint): NewowProductHintMarker => ({
    id: hint.hint_id,
    kind: hint.kind,
    barEnd: hint.bar_end,
    tradingDay: barByEnd.get(hint.bar_end)?.tradingDay ?? hint.bar_end.slice(0, 10),
    value: hint.anchor_price === null ? null : chartCoordinate(hint.anchor_price),
    anchorPrice: hint.anchor_price,
    confirmedAt: hint.known_at,
    source: `${hint.physical_contract} · ${hint.segment_id}`,
    sequence: hint.sequence,
  }))
  return {
    identity: {
      product: response.meta.identity.product,
      strategy: response.meta.identity.strategy,
      frequency: response.meta.identity.frequency,
    },
    bars, mainLines, actions, hints, nextBefore: value.next_before,
  }
}

export interface NewowAuxiliaryDisclosure {
  readonly component: NewowAuxiliaryComponent
  readonly title: string
  readonly applicability: NewowResourceLifecycle
  readonly disclosure: string
}

const AUXILIARY_TITLES: Readonly<Record<NewowAuxiliaryComponent, string>> = {
  main_force_control: '主力控盘',
  up_down_energy: '涨跌动能',
  zhaoyao_mirror: '主力照妖镜',
  cup_handle: '杯柄',
}

/** Keeps applicability/evidence wording separate from signal presence. */
export function buildNewowAuxiliaryDisclosure(
  component: NewowAuxiliaryComponent,
  frequency: NewowProductFrequency,
  lifecycle: NewowResourceLifecycle,
): NewowAuxiliaryDisclosure {
  if (component === 'cup_handle' && frequency !== '1d') {
    return { component, title: AUXILIARY_TITLES[component], applicability: 'not_applicable', disclosure: '该周期不适用：杯柄 clean-room 形态仅适用于 D1。' }
  }
  if (component === 'zhaoyao_mirror') {
    return { component, title: AUXILIARY_TITLES[component], applicability: lifecycle, disclosure: '仅供历史回看，会重绘；不进入主动作、Hint 或参考交易。' }
  }
  if (component === 'cup_handle') {
    return { component, title: AUXILIARY_TITLES[component], applicability: lifecycle, disclosure: 'Clean-room 杯柄仅显示已确认见证；pivot 时间不是首次可知时间，以确认时间为准。' }
  }
  const state = lifecycle === 'ready' ? '已加载' : lifecycle === 'warming' || lifecycle === 'loading' ? '正在准备' : lifecycle === 'not_requested' ? '尚未请求' : '不可用'
  return { component, title: AUXILIARY_TITLES[component], applicability: lifecycle, disclosure: `${AUXILIARY_TITLES[component]}${state}；仅展示服务端事实。` }
}

export interface NewowProductResizeObserver {
  observe(target: Element): void
  disconnect(): void
}

export interface NewowProductChartAdapter {
  createChart: typeof import('lightweight-charts')['createChart']
  createSeriesMarkers: <T extends Time>(series: never) => ISeriesMarkersPluginApi<T>
  createResizeObserver: (callback: ResizeObserverCallback) => NewowProductResizeObserver
}

export const NEWOW_PRODUCT_CHART_ADAPTER_KEY: InjectionKey<NewowProductChartAdapter> = Symbol('newow-product-chart-adapter')

export interface NewowProductChartResources {
  unsubscribeRange: () => void
  unsubscribeClick: () => void
  disconnectResizeObserver: () => void
  removeChart: () => void
}

export function createNewowProductChartDisposer(resources: NewowProductChartResources): () => void {
  let disposed = false
  return () => {
    if (disposed) return
    disposed = true
    resources.unsubscribeRange()
    resources.unsubscribeClick()
    resources.disconnectResizeObserver()
    resources.removeChart()
  }
}

export function chartMarkerTime(
  barEnd: string,
  frequency: NewowProductFrequency,
  tradingDay: string,
): Time {
  if (frequency === '60m') return Math.floor(Date.parse(barEnd) / 1000) as Time
  const [year, month, day] = tradingDay.split('-').map(Number)
  return { year: year!, month: month!, day: day! }
}

export function productChartMarker(
  item: NewowProductActionMarker | NewowProductHintMarker,
  selectedSignalId: string | null,
  time: Time,
): SeriesMarker<Time> {
  const action = 'referencePrice' in item
  const build = action && item.kind === 'BUILD'
  return {
    id: item.id,
    time,
    position: action ? (build ? 'belowBar' : 'aboveBar') : 'inBar',
    shape: action ? (build ? 'arrowUp' : 'arrowDown') : 'circle',
    color: item.id === selectedSignalId ? '#7C3AED' : action ? (build ? '#D97706' : '#2563EB') : '#64748B',
    text: action ? (build ? '建仓' : '清仓') : item.kind,
    size: action ? 1.5 : 1,
  }
}
