import type {
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
} from 'lightweight-charts'
import type { InjectionKey } from 'vue'

import type { KlineReferenceCallout } from '../../../../types/referenceCallout.ts'
import type {
  NewowAuxiliaryComponent,
  NewowAuxiliaryData,
  NewowAuxiliaryValue,
  NewowProductFrequency,
  NewowProductAction,
  NewowProductSectionResponse,
  NewowResourceLifecycle,
} from '../../../../types/newowProduct.ts'
import { chartCoordinate } from '../../../../utils/newowProductTypes.ts'
import { formatDecimalText } from '../../../../utils/marketDisplay.ts'

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
  readonly calculationSegmentId: string
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
  readonly tradeEligibility: NewowProductAction['trade_eligibility']
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
  readonly tone: NewowHintTone
}

export type NewowHintTone = 'risk' | 'entry' | 'cycle' | 'neutral'

export interface NewowProductChartModel {
  readonly identity: {
    readonly product: string
    readonly strategy: NewowProductSectionResponse<'chart'>['meta']['identity']['strategy']
    readonly frequency: NewowProductFrequency
  }
  readonly bars: readonly NewowProductChartBar[]
  readonly bandAreas: readonly NewowProductBandArea[]
  readonly channelPoints: readonly NewowPriceChannelChartPoint[]
  readonly mainLines: readonly NewowProductMainLine[]
  readonly actions: readonly NewowProductActionMarker[]
  readonly hints: readonly NewowProductHintMarker[]
  readonly nextBefore: string | null
}

export interface NewowPriceChannelChartPoint {
  readonly barEnd: string
  readonly tradingDay: string
  readonly upper: number
  readonly lower: number
}

export interface NewowProductBandArea {
  readonly time: Time
  readonly a: number
  readonly b: number
  readonly color: string
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
      bars: [], bandAreas: [], channelPoints: [], mainLines: [], actions: [], hints: [], nextBefore: null,
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
    calculationSegmentId: bar.calculation_segment_id,
    sourceIdentity: bar.source_identity,
  }))
  const barByEnd = new Map(bars.map((bar) => [bar.barEnd, bar]))
  const mainLines: NewowProductMainLine[] = []
  const frameByEnd = new Map(value.frames.map(frame => [frame.bar_end, frame]))
  for (const [key, label] of MAIN_LAYER_DEFINITIONS[response.meta.identity.strategy]) {
    let line: { id: string; key: string; label: string; segmentId: string; points: NewowProductLinePoint[] } | null = null
    let owner = ''
    let run = 0
    for (const bar of bars) {
      const frame = frameByEnd.get(bar.barEnd)
      const text = frame?.main_values[key]
      const nextOwner = `${bar.physicalContract}:${bar.calculationSegmentId}`
      if (text == null || frame?.status.status !== 'ready') { line = null; continue }
      if (line === null || owner !== nextOwner) {
        line = { id: `${key}:${nextOwner}:${run++}`, key, label, segmentId: bar.calculationSegmentId, points: [] }
        mainLines.push(line)
      }
      line.points.push({ barEnd: bar.barEnd, tradingDay: bar.tradingDay, value: chartCoordinate(text) })
      owner = nextOwner
    }
  }
  const bandAreas: NewowProductBandArea[] = []
  const bandKeys = response.meta.identity.strategy === 'trend' ? ['a', 'b'] as const
    : response.meta.identity.strategy === 'main_rise' ? ['ma35', 'ma45'] as const : null
  if (bandKeys !== null) {
    for (const bar of bars) {
      const frame = frameByEnd.get(bar.barEnd)
      const [firstKey, secondKey] = bandKeys
      if (frame?.status.status !== 'ready'
        || frame.main_values[firstKey] == null || frame.main_values[secondKey] == null
        || !['BUILD', 'HOLD', 'CLEAR', 'FLAT'].includes(frame.main_state)) continue
      bandAreas.push({
        time: chartMarkerTime(bar.barEnd, response.meta.identity.frequency, bar.tradingDay),
        a: chartCoordinate(frame.main_values[firstKey]),
        b: chartCoordinate(frame.main_values[secondKey]),
        color: ['BUILD', 'HOLD'].includes(frame.main_state) ? 'rgba(245, 183, 38, 0.35)' : 'rgba(54, 90, 245, 0.35)',
      })
    }
  }
  const channelPoints: NewowPriceChannelChartPoint[] = []
  if (response.meta.identity.strategy === 'trend') {
    for (const point of value.trend_channel?.points ?? []) {
      if (point.status.status !== 'ready' || point.upper === null || point.lower === null) continue
      const bar = barByEnd.get(point.bar_end)
      if (bar === undefined) continue
      channelPoints.push({
        barEnd: point.bar_end,
        tradingDay: bar.tradingDay,
        upper: chartCoordinate(point.upper),
        lower: chartCoordinate(point.lower),
      })
    }
  } else if (response.meta.identity.strategy === 'oscillation') {
    for (const bar of bars) {
      const frame = frameByEnd.get(bar.barEnd)
      if (frame?.status.status !== 'ready' || frame.main_values.upper == null || frame.main_values.lower == null) continue
      channelPoints.push({
        barEnd: bar.barEnd,
        tradingDay: bar.tradingDay,
        upper: chartCoordinate(frame.main_values.upper),
        lower: chartCoordinate(frame.main_values.lower),
      })
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
    tradeEligibility: action.trade_eligibility,
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
    tone: classifyNewowHintTone(hint.kind),
  }))
  return {
    identity: {
      product: response.meta.identity.product,
      strategy: response.meta.identity.strategy,
      frequency: response.meta.identity.frequency,
    },
    bars, bandAreas, channelPoints, mainLines, actions, hints, nextBefore: value.next_before,
  }
}

/** Display-only classification of server-owned Hint kinds. */
export function classifyNewowHintTone(kind: string): NewowHintTone {
  if (kind === 'J' || /^D[1-3]$/.test(kind) || /^NEWOW_ESCAPE_D[1-3]$/.test(kind)) return 'risk'
  if (/^D[4-6]$/.test(kind)) return 'entry'
  if (kind.startsWith('MAGIC11:')) return 'cycle'
  return 'neutral'
}

/** Keeps zoom only when both strategy snapshots describe the exact same product time axis. */
export function preserveNewowViewport(
  previous: Pick<NewowProductChartModel, 'identity' | 'bars'>,
  next: Pick<NewowProductChartModel, 'identity' | 'bars'>,
): boolean {
  return previous.identity.product === next.identity.product
    && previous.identity.frequency === next.identity.frequency
    && previous.bars.length === next.bars.length
    && previous.bars.every((bar, index) => bar.barEnd === next.bars[index]?.barEnd)
}

/** Keeps the action label bound to the server's exact time, owner, and Decimal price. */
export function buildNewowActionCallouts(
  model: Pick<NewowProductChartModel, 'actions'>,
): KlineReferenceCallout[] {
  return model.actions.map(action => ({
    id: action.id,
    time: action.barEnd,
    physicalContract: action.physicalContract,
    price: action.referencePrice,
    title: newowInitialClearLabel(action.tradeEligibility) ?? (action.kind === 'BUILD' ? '建仓' : '清仓'),
    detail: `参考价 ${formatDecimalText(action.referencePrice, { maximumFractionDigits: 0 })}`,
    tone: action.kind === 'BUILD' ? 'gain' : 'loss',
    above: action.kind === 'CLEAR',
  }))
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
  trend_reversal: [['bias', '偏离'], ['rebound', '反弹'], ['adjust', '调整'], ['wr1', 'WR1'], ['wr2', 'WR2']],
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
  if (value.component === 'macd') {
    const series: NewowAuxiliaryChartSeries[] = []
    let offset = 0
    for (const segment of value.segments) {
      for (const [key, label] of [['dif', 'DIF'], ['dea', 'DEA'], ['histogram', 'MACD']] as const) {
        const byTime = new Map(segment.data[key].map(point => [point.bar_end, point]))
        let points: NewowAuxiliaryChartPoint[] = []
        let run = 0
        const flush = () => {
          if (points.length) series.push({ id: `${key}:${segment.segment_id}:${run++}`, key, label, points })
          points = []
        }
        segment.bar_ends.forEach((barEnd, index) => {
          const point = byTime.get(barEnd)
          if (!point?.ready || !point.valid || point.value === null || !Number.isFinite(point.value)) { flush(); return }
          points.push({ barEnd, index: offset + index, value: point.value, physicalContract: segment.physical_contract, segmentId: segment.segment_id })
        })
        flush()
      }
      offset += segment.bar_ends.length
    }
    return { component: value.component, totalPoints: offset, series }
  }
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
          if (item === null || !Number.isFinite(item)) { flush(); continue }
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
  readinessMessage: string | null = null,
): NewowAuxiliaryRenderState {
  if (lifecycle === 'loading') return {
    mode: 'loading', showRetainedValue: hasRetainedValue,
    message: hasRetainedValue ? '正在刷新；以下为上次成功的预览。' : '正在加载辅助资源…',
  }
  if (lifecycle === 'stale') return {
    mode: 'stale', showRetainedValue: hasRetainedValue,
    message: `刷新失败${error === null ? '' : `（${error}）`}；以下为上次成功的 stale 预览。`,
  }
  if (lifecycle === 'ready') return { mode: 'ready', showRetainedValue: hasRetainedValue, message: readinessMessage }
  if (lifecycle === 'warming') return {
    mode: 'warming', showRetainedValue: hasRetainedValue,
    message: readinessMessage ?? (hasRetainedValue ? '辅助资源仍在预热；显示已验证的部分序列。' : '辅助资源仍在预热。'),
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
  trend_reversal: '趋势转折',
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
    color: item.id === selectedSignalId ? '#7C3AED' : action ? (build ? '#FF403A' : '#22B95D') : '#64748B',
    text: action
      ? newowInitialClearLabel(item.tradeEligibility) ?? ''
      : item.kind,
    size: 1,
  }
}

export function newowInitialClearLabel(
  tradeEligibility: NewowProductAction['trade_eligibility'],
): '清仓（无入场）' | null {
  return tradeEligibility === 'INITIAL_CLEAR_NO_ENTRY' || tradeEligibility === 'NO_ELIGIBLE_ENTRY' ? '清仓（无入场）' : null
}

export function describeNewowProductAction(item: NewowProductActionMarker): {
  readonly label: string
  readonly explanation: string
} {
  const initialClearLabel = newowInitialClearLabel(item.tradeEligibility)
  if (initialClearLabel !== null) {
    return {
      label: initialClearLabel,
      explanation: '初始无入场：未观察到可配对 BUILD，不生成参考交易。',
    }
  }
  return {
    label: item.kind === 'BUILD' ? '参考建仓' : '参考清仓',
    explanation: '仅为所选历史主动作事实，不代表账户成交。',
  }
}


/** Same server proof across display windows; the content hash may differ between sections. */
export function newowChartSnapshotKey(response: NewowProductSectionResponse | null): string | null {
  if (!response?.meta.snapshot_token) return null
  const meta = response.meta
  return JSON.stringify([meta.schema_version, meta.snapshot_token,
    meta.identity.product, meta.identity.strategy, meta.identity.frequency, meta.identity.series_kind,
    meta.identity.profile_id, meta.identity.formula_versions, meta.as_of, meta.data_revision_identity,
    meta.reference_model_version, meta.futures_adaptation_version])
}

export interface NewowAlignedAuxiliaryChartModel {
  readonly component: NewowAuxiliaryComponent
  readonly series: readonly (Omit<NewowAuxiliaryChartSeries, 'points'> & {
    readonly points: readonly (NewowAuxiliaryChartPoint & { readonly time: Time })[]
  })[]
}

/** Intersect with chart authority, splitting runs when a chart Bar has no matching point. */
export function alignNewowAuxiliaryChartModel(
  chart: NewowProductSectionResponse<'chart'> | null,
  auxiliary: NewowProductSectionResponse<'auxiliary'> | null,
): NewowAlignedAuxiliaryChartModel | null {
  const proof = newowChartSnapshotKey(chart)
  if (proof === null || proof !== newowChartSnapshotKey(auxiliary) || !chart?.value || !auxiliary?.value) return null
  const raw = buildNewowAuxiliaryChartModel(auxiliary.value)
  const series: NewowAlignedAuxiliaryChartModel['series'][number][] = []
  for (const source of raw.series) {
    const pointsByOwnerTime = new Map(source.points.map(point => [`${point.physicalContract}:${point.segmentId}:${point.barEnd}`, point]))
    let points: Array<NewowAuxiliaryChartPoint & { time: Time }> = []
    let run = 0
    const flush = () => {
      if (points.length) series.push({ ...source, id: `${source.id}:visible:${run++}`, points })
      points = []
    }
    for (const bar of chart.value.bars) {
      const point = pointsByOwnerTime.get(`${bar.physical_contract}:${bar.segment_id}:${bar.bar_end}`)
      if (!point) { flush(); continue }
      points.push({ ...point, time: chartMarkerTime(bar.bar_end, chart.meta.identity.frequency, bar.trading_day) })
    }
    flush()
  }
  return { component: raw.component, series }
}
