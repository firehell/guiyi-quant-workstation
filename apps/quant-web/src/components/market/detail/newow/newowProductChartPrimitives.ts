import type {
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
} from 'lightweight-charts'
import type { InjectionKey } from 'vue'

import type {
  NewowAuxiliaryComponent,
  NewowAuxiliaryData,
  NewowAuxiliaryValue,
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
  readonly sourceIdentity: string
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
  readonly sourceIdentity: string | null
  readonly formulaVersions: readonly string[]
  readonly physicalContract: string
  readonly segmentId: string
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
    sourceIdentity: bar.source_identity,
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
    sourceIdentity: barByEnd.get(hint.bar_end)?.sourceIdentity ?? null,
    formulaVersions: response.meta.identity.formula_versions,
    physicalContract: hint.physical_contract,
    segmentId: hint.segment_id,
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

export interface NewowAuxiliaryChartPoint {
  readonly barEnd: string
  readonly index: number
  readonly value: number
  readonly physicalContract: string
  readonly segmentId: string
}

export interface NewowAuxiliaryChartSeries {
  readonly id: string
  readonly key: string
  readonly label: string
  readonly points: readonly NewowAuxiliaryChartPoint[]
}

export interface NewowAuxiliaryChartModel {
  readonly component: NewowAuxiliaryComponent
  readonly totalPoints: number
  readonly series: readonly NewowAuxiliaryChartSeries[]
}

const AUXILIARY_SERIES_LABELS = {
  main_force_control: [['kongpan', '主力控盘']],
  up_down_energy: [
    ['var4', 'VAR4'], ['ma10', 'MA10'], ['band_entry', '波段介入'],
    ['rebound_entry', '反弹介入'], ['oversold_entry', '超跌介入'], ['var3', 'VAR3'], ['ma120', 'MA120'],
  ],
  zhaoyao_mirror: [
    ['entry', '进场'], ['wash', '洗盘'], ['distribution', '派发'], ['markup', '拉升'],
    ['exit', '离场'], ['inducement', '诱多'], ['peaks', '峰值'], ['caution', '风险'],
  ],
  cup_handle: [],
} as const

/** Maps aligned P4 arrays to visible series; it never derives an indicator. */
export function buildNewowAuxiliaryChartModel(value: NewowAuxiliaryValue): NewowAuxiliaryChartModel {
  // Point objects are excluded from this legacy scalar-array renderer.
  if (value.component === 'macd') return { component: 'macd', totalPoints: value.segments.reduce((size, segment) => size + segment.bar_ends.length, 0), series: [] }
  const series: NewowAuxiliaryChartSeries[] = []
  let offset = 0
  for (const segment of value.segments) {
    if (segment.data !== null && isAuxiliarySequenceData(segment.data)) {
      for (const [key, label] of AUXILIARY_SERIES_LABELS[value.component]) {
        const sequence = auxiliarySequence(segment.data, key)
        if (sequence === null) continue
        let points: NewowAuxiliaryChartPoint[] = []
        let run = 0
        const flush = () => {
          if (points.length === 0) return
          series.push({ id: `${key}:${segment.segment_id}:${run}`, key, label, points })
          points = []
          run += 1
        }
        for (let index = 0; index < sequence.length; index += 1) {
          const item = sequence[index]
          if (item === null) { flush(); continue }
          points.push({
            barEnd: segment.bar_ends[index]!, index: offset + index, value: item,
            physicalContract: segment.physical_contract, segmentId: segment.segment_id,
          })
        }
        flush()
      }
    }
    offset += segment.bar_ends.length
  }
  return { component: value.component, totalPoints: offset, series }
}

function isAuxiliarySequenceData(data: NewowAuxiliaryData): data is Exclude<NewowAuxiliaryData, readonly unknown[]> {
  return !Array.isArray(data)
}

function auxiliarySequence(data: Exclude<NewowAuxiliaryValue['segments'][number]['data'], null | readonly unknown[]>, key: string): readonly (number | null)[] | null {
  if (!(key in data)) return null
  const value = data[key as keyof typeof data]
  if (!Array.isArray(value)) return null
  return value as readonly (number | null)[]
}

export interface NewowAuxiliaryRenderState {
  readonly mode: 'idle' | 'loading' | 'ready' | 'warming' | 'stale' | 'error'
  readonly showRetainedValue: boolean
  readonly message: string | null
}

/** Makes request lifecycle visible before any retained same-component payload. */
export function resolveNewowAuxiliaryRenderState(
  lifecycle: NewowResourceLifecycle,
  hasRetainedValue: boolean,
  error: string | null,
): NewowAuxiliaryRenderState {
  if (lifecycle === 'loading') return {
    mode: 'loading', showRetainedValue: hasRetainedValue,
    message: hasRetainedValue ? '正在刷新；以下为上次成功的预览。' : '正在加载辅助资源…',
  }
  if (lifecycle === 'stale') return {
    mode: 'stale', showRetainedValue: hasRetainedValue,
    message: `刷新失败${error === null ? '' : `（${error}）`}；以下为上次成功的 stale 预览。`,
  }
  if (lifecycle === 'ready') return { mode: 'ready', showRetainedValue: hasRetainedValue, message: null }
  if (lifecycle === 'warming') return {
    mode: 'warming', showRetainedValue: hasRetainedValue,
    message: hasRetainedValue ? '辅助资源仍在 warming；显示已验证的部分序列。' : '辅助资源仍在 warming。',
  }
  if (lifecycle === 'not_requested') return { mode: 'idle', showRetainedValue: false, message: null }
  return {
    mode: 'error', showRetainedValue: hasRetainedValue,
    message: `加载失败${error === null ? '' : `（${error}）`}。${hasRetainedValue ? '以下为上次成功的 stale 预览。' : ''}`,
  }
}

export interface NewowAuxiliaryDisclosure {
  readonly component: NewowAuxiliaryComponent
  readonly title: string
  readonly applicability: NewowResourceLifecycle
  readonly disclosure: string
}

const AUXILIARY_TITLES: Readonly<Record<NewowAuxiliaryComponent, string>> = {
  macd: 'MACD',
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
