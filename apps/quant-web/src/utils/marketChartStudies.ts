import type { InjectionKey, Ref } from 'vue'
import { DISPLAY_CATALOG, type LayerStatus } from '@guiyi/quant-chart'
import type { BarData, MainIndicatorId, MarketFrequency, MarketStudyActivity, SeriesKind } from '../types/market.ts'
import { previewInstant } from './candidatePreviewInstant.ts'

const EMA_STUDIES = { ema_10: 'ema10', ema_21: 'ema21', ema_60: 'ema60' } as const
const STUDIES = { ...EMA_STUDIES, boll: 'boll', macd: 'macd' } as const
export const MARKET_CHART_STUDY_BAR_LIMIT = 2_000
export type EmaIndicatorId = keyof typeof EMA_STUDIES
export type ChartStudyId = keyof typeof STUDIES
export type GenericChartProfile = 'free' | 'htdy' | 'subing'
export type MarketStudySelection = MainIndicatorId | 'macd'
export const isGenericChartProfile = (profile: unknown): profile is GenericChartProfile =>
  profile === 'free' || profile === 'htdy' || profile === 'subing'
// Registry defaults, hashed with guiyi_quant.compute.contracts.hash_parameters.
const WORKSTATION_PARAMETERS: Record<ChartStudyId, string> = {
  ema_10: '98f49abca86eb526', ema_21: '92210fca093bfe8c', ema_60: '94d0f49990074e0a',
  boll: 'bcc734b77616a3e9', macd: 'f9b4b4b0b4d0678d',
}
const SHA256 = /^[0-9a-f]{64}$/
type StudyPointStatus = 'READY' | 'WARMING' | 'UNKNOWN' | 'INVALID' | 'ERROR'
const STUDY_POINT_REASONS = new Set([
  'LOOKBACK_REQUIRED', 'INPUT_QUALITY_INVALID', 'INPUT_MISSING', 'INPUT_NONFINITE',
  'INPUT_PREFIX_INTERRUPTED', 'OUTPUT_NONFINITE', 'COMPUTE_FAILED',
])
export type MarketChartStudyPoints = Partial<Record<ChartStudyId, Record<string, MarketChartStudyPoint>>>
export interface MarketChartStudyDisplay {
  points: MarketChartStudyPoints
  sourceRevision: string
  segmentsByTime: Record<string, { calculationAnchor: string; segmentId: string; physicalContract: string }>
  features: Partial<Record<ChartStudyId, {
    formulaVersion: string
    backendVersion: string
    parametersHash: string
  }>>
}

export interface MarketChartStudyPoint {
  values: Record<string, number> | null
  status: StudyPointStatus
  diagnostic: string | null
}

export interface MarketChartStudyIssue {
  status: Extract<LayerStatus, 'catalog_mismatch' | 'invalid_source' | 'compute_error' | 'missing_input'>
  reason: string
}

class MarketChartStudyProjectionError extends Error {
  readonly issue: MarketChartStudyIssue

  constructor(issue: MarketChartStudyIssue) {
    super(issue.reason)
    this.issue = issue
  }
}

function rejectStudy(reason: string, status: MarketChartStudyIssue['status'] = 'invalid_source'): never {
  throw new MarketChartStudyProjectionError({ status, reason })
}

export function marketChartStudyIssue(error: unknown): MarketChartStudyIssue {
  if (error instanceof MarketChartStudyProjectionError) return error.issue
  const response = chartStudyResponse(error)
  const code = response?.data?.detail?.code
  if (response?.status === 409 && (code === 'MARKET_CHART_STUDY_PHYSICAL_OWNER_INVALID' || code === 'MARKET_CHART_STUDY_WINDOW_MISMATCH' || code === 'MARKET_CHART_STUDY_BASE_EXPIRED' || code === 'MARKET_CHART_STUDY_LIVE_REVISION_CONFLICT')) {
    return { status: 'invalid_source', reason: code }
  }
  return { status: 'missing_input', reason: 'MARKET_CHART_STUDY_REQUEST_FAILED' }
}

export function marketChartStudyBaseExpired(error: unknown): boolean {
  const response = chartStudyResponse(error)
  return response?.status === 409 && ['MARKET_CHART_STUDY_BASE_EXPIRED', 'MARKET_CHART_STUDY_WINDOW_MISMATCH']
    .includes(response.data?.detail?.code ?? '')
}

function chartStudyResponse(error: unknown) {
  return (error as { response?: { status?: number; data?: { detail?: { code?: string } } } })?.response
}

export function marketStudyLayerStatus(fact?: MarketChartStudyPoint): LayerStatus {
  switch (fact?.status) {
    case 'READY': return 'ready'
    case 'WARMING': return 'warming'
    case 'ERROR': return 'compute_error'
    case 'INVALID': return fact.diagnostic === 'OUTPUT_NONFINITE' ? 'compute_error' : 'invalid_source'
    default: return 'missing_input'
  }
}

export interface MarketChartStudyIdentity {
  symbol: string
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract?: string
  profile?: GenericChartProfile | 'newow'
}

export interface MarketChartStudyQuery {
  symbol: string
  series_kind: SeriesKind
  frequency: MarketFrequency
  contract?: string
  profile: GenericChartProfile | 'newow'
  first: string
  last: string
  count: number
  studies: string
}

export interface MarketChartStudyContext {
  identity: MarketChartStudyIdentity
  active: Readonly<Ref<MarketStudyActivity | null>>
  allowCompleted: Readonly<Ref<boolean>>
  revision: Readonly<Ref<string | null>>
  revisionPending: Readonly<Ref<boolean>>
  allowTail: boolean
  talibMacd: boolean
  toggleMacd(): void
}
export const MARKET_CHART_STUDY_CONTEXT: InjectionKey<Ref<MarketChartStudyContext | null>> = Symbol('market-chart-study-context')

// The superseded request can occupy the server's 8-second worker even after
// its browser request was aborted. Only the still-current generation retries.
const CHART_STUDY_BUSY_DELAYS_MS = [100, 300, 600, 1200, 2000, 2000, 2000]

export async function retryMarketStudyWhenBusy<T>(read: () => Promise<T>, signal: AbortSignal): Promise<T> {
  let retries = 0
  for (;;) {
    signal.throwIfAborted()
    try {
      const result = await read()
      signal.throwIfAborted()
      return result
    } catch (error) {
      const response = chartStudyResponse(error)
      const delay = CHART_STUDY_BUSY_DELAYS_MS[retries++]
      if (signal.aborted || delay === undefined || response?.status !== 503
        || response.data?.detail?.code !== 'MARKET_CHART_STUDY_BUSY') throw error
      await new Promise<void>(resolve => {
        const finished = () => {
          clearTimeout(timer)
          signal.removeEventListener('abort', finished)
          resolve()
        }
        const timer = setTimeout(finished, delay)
        signal.addEventListener('abort', finished, { once: true })
      })
    }
  }
}

export function isEmaIndicator(id: MainIndicatorId): id is EmaIndicatorId {
  return Object.hasOwn(EMA_STUDIES, id)
}

export function marketChartStudyRequest(
  identity: MarketChartStudyIdentity, indicators: readonly MarketStudySelection[], bars: readonly BarData[],
  canonicalRevision: string | null = null,
): { query: MarketChartStudyQuery; ids: ChartStudyId[]; bars: BarData[]; key: string; truncatedBefore: boolean } | null {
  const ids = [...new Set(indicators.filter((id): id is ChartStudyId => Object.hasOwn(STUDIES, id)))].sort()
  if (!ids.length) return null
  const completed = bars.filter(bar => bar.confirmed !== false && (!bar.marketSource || bar.marketSource === 'canonical'))
  const historical = completed.slice(-MARKET_CHART_STUDY_BAR_LIMIT)
  if (!historical.length || (identity.seriesKind !== 'continuous' && historical.some(
    bar => !bar.physicalContract || !bar.calculationSegmentId,
  ))) return null
  if (identity.profile === 'newow' && historical.some(bar =>
    bar.marketSource !== 'canonical' || !bar.sourceBarSha256 || !SHA256.test(bar.sourceBarSha256))) return null
  const query: MarketChartStudyQuery = {
    symbol: identity.symbol, series_kind: identity.seriesKind, frequency: identity.frequency,
    contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
    profile: identity.profile ?? 'free',
    first: historical[0]!.time, last: historical.at(-1)!.time,
    count: historical.length, studies: ids.map(id => STUDIES[id]).join(','),
  }
  return {
    query, ids, bars: historical, truncatedBefore: completed.length > MARKET_CHART_STUDY_BAR_LIMIT,
    key: JSON.stringify([query, canonicalRevision, historical.map(bar => [
      bar.time, bar.trading_day, bar.physicalContract, bar.calculationSegmentId, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.sourceBarSha256,
    ])]),
  }
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) rejectStudy('MARKET_CHART_STUDY_INVALID')
  return value as Record<string, unknown>
}

function sameInstant(value: unknown, expected: string): boolean {
  return typeof value === 'string' && previewInstant(value) !== null && previewInstant(value) === previewInstant(expected)
}

function pointValue(value: unknown, id: ChartStudyId): MarketChartStudyPoint {
  const point = record(value)
  const status = point.status as StudyPointStatus
  if (status === 'READY' && point.diagnostic === null) {
    const values = record(point.values)
    const source = DISPLAY_CATALOG[id]?.source
    if (source?.type !== 'quant_feature' || source.featureId !== STUDIES[id]) {
      rejectStudy('MARKET_CHART_STUDY_FEATURE_INVALID', 'catalog_mismatch')
    }
    const keys = source.outputs
    if (Object.keys(values).length !== keys.length || !keys.every(key => Object.hasOwn(values, key))) {
      rejectStudy('MARKET_CHART_STUDY_OUTPUT_MISMATCH', 'catalog_mismatch')
    }
    if (keys.every(key => typeof values[key] === 'number' && Number.isFinite(values[key]))) {
      return { status, values: values as Record<string, number>, diagnostic: null }
    }
    rejectStudy('MARKET_CHART_STUDY_POINT_INVALID', 'compute_error')
  }
  if (['WARMING', 'UNKNOWN', 'INVALID', 'ERROR'].includes(status) && point.values === null
    && typeof point.diagnostic === 'string' && point.diagnostic.length > 0) {
    return {
      status, values: null,
      diagnostic: STUDY_POINT_REASONS.has(point.diagnostic) ? point.diagnostic : 'MARKET_CHART_STUDY_POINT_UNAVAILABLE',
    }
  }
  return rejectStudy('MARKET_CHART_STUDY_POINT_INVALID')
}

export type MarketChartStudyDemand = NonNullable<ReturnType<typeof marketChartStudyRequest>>
export interface MarketChartStudyTailQuery extends Omit<MarketChartStudyQuery, 'first' | 'last' | 'count'> {
  canonical_end: string
  source_revision: string
  completed_through?: string
  include_preview: boolean
}

export function marketChartStudyTailRequest(
  history: MarketChartStudyDemand, display: MarketChartStudyDisplay, bars: readonly BarData[],
  allowCompleted: boolean, activity: MarketStudyActivity | null,
) {
  const { symbol, series_kind, frequency, contract, profile, studies, last } = history.query
  if (profile === 'newow') return null
  const completed = allowCompleted ? bars.filter(bar => bar.marketSource === 'completed_live') : []
  const preview = activity?.bar.marketSource === 'active_preview' ? activity : null
  if (!completed.length && !preview) return null
  const query: MarketChartStudyTailQuery = {
    symbol, series_kind, frequency, contract, profile, studies, canonical_end: last, source_revision: display.sourceRevision,
    completed_through: completed.at(-1)?.time, include_preview: preview !== null,
  }
  const baseKey = JSON.stringify([history.query, display.sourceRevision])
  const barKeys = completed.map(bar => JSON.stringify([
    bar.time, bar.trading_day, bar.physicalContract, bar.calculationSegmentId, bar.open, bar.high, bar.low, bar.close, bar.volume,
    bar.turnover, bar.openInterest, bar.sourceBarSha256,
  ]))
  const completedKey = JSON.stringify([baseKey, barKeys])
  const key = JSON.stringify([completedKey, preview])
  return { query, history, display, completed, preview, key, completedKey, baseKey, barKeys }
}

export type MarketChartStudyTailDemand = NonNullable<ReturnType<typeof marketChartStudyTailRequest>>
export interface MarketChartStudyPreview {
  bar: BarData
  generation: string
  data: MarketChartStudyDisplay
}

function emptyDisplay(ids: readonly ChartStudyId[], sourceRevision: string): MarketChartStudyDisplay {
  const points: MarketChartStudyPoints = {}
  ids.forEach(id => { points[id] = {} })
  return { points, sourceRevision, features: {}, segmentsByTime: {} }
}

function matchingBody(payload: unknown, query: MarketChartStudyQuery | MarketChartStudyTailQuery) {
  const body = record(payload)
  if (body.schema_version !== 'guiyi_market_chart_studies_v1' || body.result_schema_version !== 'guiyi_feature_result_v1') {
    rejectStudy('MARKET_CHART_STUDY_SCHEMA_MISMATCH', 'catalog_mismatch')
  }
  const asOf = 'last' in query ? query.last : query.canonical_end
  if (body.symbol !== query.symbol || body.series_kind !== query.series_kind || body.frequency !== query.frequency
    || body.contract !== (query.contract?.toUpperCase() ?? null) || !sameInstant(body.as_of, asOf)
    || !Array.isArray(body.segments)) rejectStudy('MARKET_CHART_STUDY_IDENTITY_MISMATCH')
  return { body, segments: body.segments as unknown[] }
}

function matchingDecimal(wire: unknown, expected: number): boolean {
  return typeof wire === 'string' && !!wire.trim() && Number.isFinite(Number(wire)) && Number(wire) === expected
}

function projectSegments(
  segments: readonly unknown[], bars: readonly BarData[], ids: readonly ChartStudyId[],
  output: MarketChartStudyDisplay, source: NonNullable<BarData['marketSource']>,
  expectedFeatures = output.features,
): void {
  let offset = 0
  const seen = new Set<string>()
  for (const raw of segments) {
    const segment = record(raw)
    const segmentId = segment.segment_id
    const calculationAnchor = segment.calculation_anchor
    const contract = segment.physical_contract
    if (typeof segmentId !== 'string' || !segmentId.trim() || seen.has(segmentId)
      || typeof contract !== 'string' || !/^[A-Z]+[0-9]+$/.test(contract)
      || typeof calculationAnchor !== 'string' || !Array.isArray(segment.bars) || !segment.bars.length) {
      rejectStudy('MARKET_CHART_STUDY_SEGMENT_INVALID')
    }
    const anchor = previewInstant(calculationAnchor)
    const first = bars[offset] && previewInstant(bars[offset]!.time)
    if (anchor === null || first == null || anchor > first) rejectStudy('MARKET_CHART_STUDY_SEGMENT_INVALID')
    if (!Array.isArray(segment.features) || segment.features.length !== ids.length) rejectStudy('MARKET_CHART_STUDY_FEATURE_INVALID', 'catalog_mismatch')
    seen.add(segmentId)
    const owner = bars[offset]?.calculationSegmentId
    const times = segment.bars.map((rawBar, index) => {
      const bar = record(rawBar)
      const expected = bars[offset + index]
      if (!expected || contract !== expected.physicalContract || owner !== expected.calculationSegmentId
        || bar.source !== source || !sameInstant(bar.bar_end, expected.time)
        || (expected.trading_day !== undefined && bar.trading_day !== expected.trading_day)
        || !matchingDecimal(bar.close, expected.close) || !matchingDecimal(bar.open, expected.open)
        || !matchingDecimal(bar.high, expected.high) || !matchingDecimal(bar.low, expected.low)
        || !matchingDecimal(bar.volume, expected.volume)
        || typeof bar.source_bar_sha256 !== 'string' || !SHA256.test(bar.source_bar_sha256)
        || (expected.sourceBarSha256 !== undefined && bar.source_bar_sha256 !== expected.sourceBarSha256)) {
        rejectStudy('MARKET_CHART_STUDY_BAR_MISMATCH')
      }
      output.segmentsByTime[expected.time] = { calculationAnchor, segmentId, physicalContract: contract }
      return expected.time
    })
    segment.features.forEach((rawFeature, index) => {
      const id = ids[index]!
      const feature = record(rawFeature)
      const formula = id === 'macd' ? 'talib_macd_12_26_9_v1' : `talib_${STUDIES[id]}_v1`
      if (feature.study !== STUDIES[id] || feature.formula_version !== formula
        || typeof feature.backend_version !== 'string' || !feature.backend_version.startsWith('ta-lib:')) {
        rejectStudy('MARKET_CHART_STUDY_FEATURE_INVALID', 'catalog_mismatch')
      }
      if (typeof feature.parameters_hash !== 'string' || !/^[0-9a-f]{16}$/.test(feature.parameters_hash)
        || !Array.isArray(feature.points) || feature.points.length !== times.length) rejectStudy('MARKET_CHART_STUDY_FEATURE_INVALID')
      const previous = expectedFeatures[id]
      if (previous && (previous.backendVersion !== feature.backend_version || previous.parametersHash !== feature.parameters_hash)) {
        rejectStudy('MARKET_CHART_STUDY_FEATURE_IDENTITY_MISMATCH')
      }
      output.features[id] = {
        formulaVersion: feature.formula_version, backendVersion: feature.backend_version, parametersHash: feature.parameters_hash,
      }
      feature.points.forEach((point, pointIndex) => { output.points[id]![times[pointIndex]!] = pointValue(point, id) })
    })
    offset += times.length
  }
  if (offset !== bars.length) rejectStudy('MARKET_CHART_STUDY_WINDOW_MISMATCH')
}

/** Bind every projected value to the requested Canonical chart Bar and owner. */
export function projectMarketChartStudyDisplay(payload: unknown, request: MarketChartStudyDemand): MarketChartStudyDisplay | null {
  const { query, ids, bars } = request
  const { body, segments } = matchingBody(payload, query)
  if (query.series_kind === 'continuous' && body.unavailable_reason === 'PHYSICAL_OWNER_REQUIRED'
    && body.source_revision === null && !segments.length) return null
  if (query.series_kind === 'continuous' || body.unavailable_reason !== null || typeof body.source_revision !== 'string'
    || !SHA256.test(body.source_revision)) rejectStudy('MARKET_CHART_STUDY_SOURCE_INVALID')
  const output = emptyDisplay(ids, body.source_revision)
  projectSegments(segments, bars, ids, output, 'canonical')
  if (query.profile === 'newow' && ids.some(id => output.features[id]?.parametersHash !== WORKSTATION_PARAMETERS[id])) {
    rejectStudy('MARKET_CHART_STUDY_FEATURE_IDENTITY_MISMATCH', 'catalog_mismatch')
  }
  return output
}

export function projectMarketChartStudyTail(payload: unknown, demand: MarketChartStudyTailDemand) {
  const { query, history: { ids }, display, completed, preview } = demand
  const { body, segments } = matchingBody(payload, query)
  if (body.source_revision !== query.source_revision || body.unavailable_reason !== null) {
    rejectStudy('MARKET_CHART_STUDY_SOURCE_INVALID')
  }
  const completedDisplay = emptyDisplay(ids, query.source_revision)
  const reason = body.tail_unavailable_reason
  if (reason != null && typeof reason !== 'string') rejectStudy('MARKET_CHART_STUDY_SOURCE_INVALID')
  if (segments.length || reason == null) projectSegments(segments, completed, ids, completedDisplay, 'completed_live', display.features)

  let previewDisplay: MarketChartStudyPreview | null = null
  let issue: MarketChartStudyIssue | null = null
  if (body.preview != null && reason == null && preview) {
    try {
      const observation = record(body.preview)
      if (observation.generation === preview.generation && sameInstant(observation.observed_at, preview.observedAt)
        && sameInstant(observation.received_at, preview.receivedAt)) {
        const output = emptyDisplay(ids, query.source_revision)
        projectSegments([observation.segment], [preview.bar], ids, output, 'active_preview', display.features)
        previewDisplay = { bar: preview.bar, generation: preview.generation, data: output }
      }
    } catch (error) {
      issue = marketChartStudyIssue(error)
    }
  }
  const publicReason = reason === 'MARKET_CHART_STUDY_LIVE_GAP' || reason === 'MARKET_CHART_STUDY_LIVE_IDENTITY_UNAVAILABLE'
    || reason === 'MARKET_CHART_STUDY_PREVIEW_UNAVAILABLE' ? reason : 'MARKET_CHART_STUDY_TAIL_UNAVAILABLE'
  if (!issue && (reason != null || (preview && !previewDisplay))) issue = { status: 'missing_input', reason: publicReason }
  return { completed: segments.length ? completedDisplay : null, preview: previewDisplay, issue }
}
