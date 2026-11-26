import type { InjectionKey, Ref } from 'vue'
import type { LayerStatus } from '@guiyi/quant-chart'
import type { BarData, MainIndicatorId, MarketFrequency, SeriesKind } from '../types/market.ts'
import { previewInstant } from './candidatePreviewInstant.ts'

const EMA_STUDIES = { ema_10: 'ema10', ema_21: 'ema21', ema_60: 'ema60' } as const
const STUDIES = { ...EMA_STUDIES, boll: 'boll' } as const
export const MARKET_CHART_STUDY_BAR_LIMIT = 2_000
export type EmaIndicatorId = keyof typeof EMA_STUDIES
type ChartStudyId = keyof typeof STUDIES
type StudyPointStatus = 'READY' | 'WARMING' | 'UNKNOWN' | 'INVALID' | 'ERROR'
export type MarketChartStudyPoints = Partial<Record<ChartStudyId, Record<string, MarketChartStudyPoint>>>
export interface MarketChartStudyDisplay {
  points: MarketChartStudyPoints
  sourceRevision: string
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

export function marketStudyLayerStatus(fact?: MarketChartStudyPoint): LayerStatus {
  switch (fact?.status) {
    case 'READY': return 'ready'
    case 'WARMING': return 'warming'
    case 'ERROR': return 'compute_error'
    case 'INVALID': return fact.diagnostic === 'OUTPUT_NONFINITE' ? 'compute_error' : 'invalid_source'
    default: return 'missing_input'
  }
}

interface MarketChartStudyIdentity {
  symbol: string
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract?: string
}

export interface MarketChartStudyQuery {
  symbol: string
  series_kind: SeriesKind
  frequency: MarketFrequency
  contract?: string
  first: string
  last: string
  count: number
  studies: string
}

export const MARKET_CHART_STUDY_IDENTITY: InjectionKey<Ref<MarketChartStudyIdentity | null>> = Symbol('market-chart-study-identity')

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
      const response = (error as { response?: { status?: number; data?: { detail?: { code?: string } } } })?.response
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
  identity: MarketChartStudyIdentity, indicators: readonly MainIndicatorId[], bars: readonly BarData[],
): { query: MarketChartStudyQuery; ids: ChartStudyId[]; bars: BarData[]; key: string; truncatedBefore: boolean } | null {
  const ids = [...new Set(indicators.filter((id): id is ChartStudyId => Object.hasOwn(STUDIES, id)))].sort()
  if (!ids.length) return null
  const completed = bars.filter(bar => bar.confirmed !== false)
  const historical = completed.slice(-MARKET_CHART_STUDY_BAR_LIMIT)
  if (!historical.length || (identity.seriesKind !== 'continuous' && historical.some(
    bar => !bar.physicalContract || !bar.calculationSegmentId,
  ))) return null
  const query: MarketChartStudyQuery = {
    symbol: identity.symbol, series_kind: identity.seriesKind, frequency: identity.frequency,
    contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
    first: historical[0]!.time, last: historical.at(-1)!.time,
    count: historical.length, studies: ids.map(id => STUDIES[id]).join(','),
  }
  return {
    query, ids, bars: historical, truncatedBefore: completed.length > MARKET_CHART_STUDY_BAR_LIMIT,
    key: JSON.stringify([query, historical.map(bar => [
      bar.time, bar.physicalContract, bar.calculationSegmentId, bar.close, bar.sourceBarSha256,
    ])]),
  }
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('MARKET_CHART_STUDY_INVALID')
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
    const keys = id === 'boll' ? ['upper', 'middle', 'lower'] : ['value']
    if (Object.keys(values).length === keys.length && keys.every(key => typeof values[key] === 'number' && Number.isFinite(values[key]))) {
      return { status, values: values as Record<string, number>, diagnostic: null }
    }
  }
  if (['WARMING', 'UNKNOWN', 'INVALID', 'ERROR'].includes(status) && point.values === null
    && typeof point.diagnostic === 'string' && point.diagnostic.length > 0) {
    return { status, values: null, diagnostic: point.diagnostic }
  }
  throw new Error('MARKET_CHART_STUDY_POINT_INVALID')
}

/** Bind every projected value to the requested completed chart Bar and owner. */
export function projectMarketChartStudyDisplay(payload: unknown, request: NonNullable<ReturnType<typeof marketChartStudyRequest>>): MarketChartStudyDisplay | null {
  const { query, ids, bars } = request
  const body = record(payload)
  if (body.schema_version !== 'guiyi_market_chart_studies_v1' || body.result_schema_version !== 'guiyi_feature_result_v1'
    || body.symbol !== query.symbol || body.series_kind !== query.series_kind || body.frequency !== query.frequency
    || body.contract !== (query.contract?.toUpperCase() ?? null) || !sameInstant(body.as_of, query.last)
    || !Array.isArray(body.segments)) throw new Error('MARKET_CHART_STUDY_IDENTITY_MISMATCH')
  if (query.series_kind === 'continuous' && body.unavailable_reason === 'PHYSICAL_OWNER_REQUIRED'
    && body.source_revision === null && !body.segments.length) return null
  if (query.series_kind === 'continuous' || body.unavailable_reason !== null || typeof body.source_revision !== 'string'
    || !/^[0-9a-f]{64}$/.test(body.source_revision)) throw new Error('MARKET_CHART_STUDY_SOURCE_INVALID')
  const projected: MarketChartStudyPoints = {}
  const features: MarketChartStudyDisplay['features'] = {}
  ids.forEach(id => { projected[id] = {} })
  let offset = 0
  const seen = new Set<string>()
  for (const raw of body.segments) {
    const segment = record(raw)
    if (typeof segment.segment_id !== 'string' || !segment.segment_id || seen.has(segment.segment_id)
      || !Array.isArray(segment.bars) || !segment.bars.length
      || !Array.isArray(segment.features) || segment.features.length !== ids.length) throw new Error('MARKET_CHART_STUDY_SEGMENT_INVALID')
    seen.add(segment.segment_id)
    const owner = bars[offset]?.calculationSegmentId
    if (offset > 0 && owner === bars[offset - 1]?.calculationSegmentId
      && segment.physical_contract === bars[offset - 1]?.physicalContract) throw new Error('MARKET_CHART_STUDY_OWNER_MISMATCH')
    const times = segment.bars.map((rawBar, index) => {
      const bar = record(rawBar)
      const expected = bars[offset + index]
      if (!expected || segment.physical_contract !== expected.physicalContract || owner !== expected.calculationSegmentId
        || !sameInstant(bar.bar_end, expected.time) || typeof bar.close !== 'string' || !bar.close.trim()
        || !Number.isFinite(Number(bar.close)) || Number(bar.close) !== expected.close
        || typeof bar.source_bar_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(bar.source_bar_sha256)
        || (expected.sourceBarSha256 !== undefined && bar.source_bar_sha256 !== expected.sourceBarSha256)) {
        throw new Error('MARKET_CHART_STUDY_BAR_MISMATCH')
      }
      return expected.time
    })
    segment.features.forEach((rawFeature, index) => {
      const id = ids[index]!
      const feature = record(rawFeature)
      if (feature.study !== STUDIES[id] || feature.formula_version !== `talib_${STUDIES[id]}_v1`
        || typeof feature.backend_version !== 'string' || !feature.backend_version.startsWith('ta-lib:')
        || typeof feature.parameters_hash !== 'string' || !/^[0-9a-f]{16}$/.test(feature.parameters_hash)
        || !Array.isArray(feature.points) || feature.points.length !== times.length) throw new Error('MARKET_CHART_STUDY_FEATURE_INVALID')
      const previous = features[id]
      if (previous && (previous.backendVersion !== feature.backend_version || previous.parametersHash !== feature.parameters_hash)) {
        throw new Error('MARKET_CHART_STUDY_FEATURE_IDENTITY_MISMATCH')
      }
      features[id] = {
        formulaVersion: feature.formula_version, backendVersion: feature.backend_version, parametersHash: feature.parameters_hash,
      }
      feature.points.forEach((point, pointIndex) => { projected[id]![times[pointIndex]!] = pointValue(point, id) })
    })
    offset += times.length
  }
  if (offset !== bars.length) throw new Error('MARKET_CHART_STUDY_WINDOW_MISMATCH')
  return { points: projected, sourceRevision: body.source_revision, features }
}
