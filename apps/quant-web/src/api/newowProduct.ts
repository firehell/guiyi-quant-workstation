import type {
  NewowHistoricalSnapshot,
  NewowDailySnapshot,
  NewowWeeklySnapshot,
  NewowProductCapabilities,
  NewowProductRequest,
  NewowProductSectionResponse,
} from '../types/newowProduct.ts'
import { normalizeNewowProductResponse } from '../utils/newowProductTypes.ts'
import { formatNewowDataDiagnostic, parseNewowDataDiagnostic, type NewowDataDiagnostic } from '../utils/newowDataDiagnostics.ts'

export type NewowProductErrorClassification = 'invalid' | 'conflict' | 'busy' | 'cancelled' | 'unavailable' | 'response_invalid'

const INVALID_CODES = new Set([
  'NEWOW_INVALID_QUERY', 'NEWOW_INVALID_PRODUCT', 'NEWOW_INVALID_RANGE', 'NEWOW_INVALID_PERFORMANCE_WINDOW',
  'NEWOW_INVALID_CHART_LIMIT', 'NEWOW_INVALID_HISTORY_LIMIT', 'NEWOW_AUXILIARY_COMPONENT_REQUIRED',
  'NEWOW_SECTION_PARAMETER_INVALID', 'NEWOW_COMPLETE_PERIOD_MISSING',
])
const CONFLICT_CODES = new Set([
  'NEWOW_DATA_IDENTITY_INVALID', 'NEWOW_DATA_OUT_OF_ORDER',
  'NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'NEWOW_CURSOR_GENERATION_CONFLICT', 'NEWOW_CURSOR_INVALID',
  'NEWOW_REFERENCE_PAIRING_CONFLICT', 'NEWOW_PAGE_COMPARATOR_CONFLICTING_FACT',
])
const UNAVAILABLE_CODES = new Set([
  'NEWOW_DATA_UNAVAILABLE', 'NEWOW_SOURCE_NONPOSITIVE_PRICE', 'NEWOW_COMPLETE_TRADING_DAY_MISSING',
  'NEWOW_COMPLETE_PERIOD_MISSING', 'NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE',
  'NEWOW_FREQUENCY_NOT_OPEN', 'NEWOW_SECTION_NOT_OPEN',
  'NEWOW_WEEKLY_UNKNOWN', 'NEWOW_WEEKLY_FAILED', 'NEWOW_WEEKLY_STALE',
])
const WEEKLY_PRODUCTS_V8 = 'a ag al ao ap au bu c cf cu ec fg fu hc i jd jm l lc lh m ma ni p pb pd pp ps pt rb rm ru sa sc sn ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V10 = 'a ag al ao ap au b bu bz c cf cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V11 = 'a ag al ao ap au b bu bz c cf cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V12 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V13 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V14 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V15 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pk pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V16 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V17 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V18 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V19 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V20 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V21 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V22 = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sm sn sr ss ta ur v y zn'.split(' ')
const WEEKLY_PRODUCTS_V9 = [...WEEKLY_PRODUCTS_V10, ...'cj oi pf pk pl pr px rs sf sh sm sr'.split(' ')]

export class NewowProductRequestError extends Error {
  readonly code: string
  readonly classification: NewowProductErrorClassification
  readonly diagnostic: NewowDataDiagnostic | null

  constructor(code: string, classification: NewowProductErrorClassification, diagnostic: NewowDataDiagnostic | null = null) {
    super(diagnostic === null ? code : formatNewowDataDiagnostic(diagnostic))
    this.name = 'NewowProductRequestError'
    this.code = code
    this.classification = classification
    this.diagnostic = diagnostic
  }
}

export async function getNewowProductCapabilities(
  options: NewowProductRequestOptions = {},
): Promise<NewowProductCapabilities> {
  const transport = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await transport('/market/newow/product-capabilities', {
      params: {},
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof NewowProductRequestError) throw error
    throw classifyTransportError(error)
  }
  if (!isProductCapabilities(payload)) {
    throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid')
  }
  return freezeProductCapabilities(payload)
}

function isProductCapabilities(value: unknown): value is NewowProductCapabilities {
  if (!isRecord(value)) return false
  const daily = value.schema_version === 'newow_product_capabilities_v3'
    && value.release_stage === 'daily'
    && sameLiteralArray(value.open_frequencies, ['1d'])
  const legacyCandidate = value.schema_version === 'newow_product_capabilities_v4'
    && value.release_stage === 'daily_weekly_candidate'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const remaining19Candidate = value.schema_version === 'newow_product_capabilities_v9'
    && value.release_stage === 'daily_weekly_candidate'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const candidate = legacyCandidate || remaining19Candidate
  const formalWeeklyV8 = value.schema_version === 'newow_product_capabilities_v8'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV10 = value.schema_version === 'newow_product_capabilities_v10'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV11 = value.schema_version === 'newow_product_capabilities_v11'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV12 = value.schema_version === 'newow_product_capabilities_v12'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV13 = value.schema_version === 'newow_product_capabilities_v13'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV14 = value.schema_version === 'newow_product_capabilities_v14'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV15 = value.schema_version === 'newow_product_capabilities_v15'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV16 = value.schema_version === 'newow_product_capabilities_v16'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV17 = value.schema_version === 'newow_product_capabilities_v17'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV18 = value.schema_version === 'newow_product_capabilities_v18'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV19 = value.schema_version === 'newow_product_capabilities_v19'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV20 = value.schema_version === 'newow_product_capabilities_v20'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV21 = value.schema_version === 'newow_product_capabilities_v21'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeeklyV22 = value.schema_version === 'newow_product_capabilities_v22'
    && value.release_stage === 'daily_weekly'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w'])
  const formalWeekly = formalWeeklyV22 || formalWeeklyV8 || formalWeeklyV10 || formalWeeklyV11 || formalWeeklyV12 || formalWeeklyV13 || formalWeeklyV14 || formalWeeklyV15 || formalWeeklyV16 || formalWeeklyV17 || formalWeeklyV18 || formalWeeklyV19 || formalWeeklyV20 || formalWeeklyV21
  const expectedKeys = [
    'deferred_frequencies', 'deferred_sections', 'open_frequencies', 'open_sections',
    'release_stage', 'schema_version', ...(candidate || formalWeekly ? ['weekly_products'] : []),
  ]
  if (Object.keys(value).sort().join(',') !== expectedKeys.join(',')) return false
  const auPreview = value.schema_version === 'newow_product_capabilities_v5'
    && value.release_stage === 'au_daily_weekly_hourly_candidate'
    && sameLiteralArray(value.open_frequencies, ['1d', '1w', '60m'])
  const hourlyPreview = (
    (value.schema_version === 'newow_product_capabilities_v6' && value.release_stage === 'pd_pt_hourly_candidate')
    || (value.schema_version === 'newow_product_capabilities_v7' && value.release_stage === 'ap_hourly_candidate')
  )
    && sameLiteralArray(value.open_frequencies, ['1d', '60m'])
  if ((!daily && !candidate && !formalWeekly && !auPreview && !hourlyPreview)
    || !sameLiteralArray(value.open_sections, ['chart', 'auxiliary', 'reference', 'comparator'])
  ) return false
  const expectedWeeklyProducts = remaining19Candidate
    ? WEEKLY_PRODUCTS_V9
    : formalWeeklyV22 ? WEEKLY_PRODUCTS_V22
    : formalWeeklyV21 ? WEEKLY_PRODUCTS_V21
    : formalWeeklyV20 ? WEEKLY_PRODUCTS_V20
    : formalWeeklyV19 ? WEEKLY_PRODUCTS_V19
    : formalWeeklyV18 ? WEEKLY_PRODUCTS_V18
    : formalWeeklyV17 ? WEEKLY_PRODUCTS_V17
    : formalWeeklyV16 ? WEEKLY_PRODUCTS_V16
    : formalWeeklyV15 ? WEEKLY_PRODUCTS_V15
    : formalWeeklyV14 ? WEEKLY_PRODUCTS_V14
    : formalWeeklyV13 ? WEEKLY_PRODUCTS_V13
    : formalWeeklyV12 ? WEEKLY_PRODUCTS_V12
    : formalWeeklyV11 ? WEEKLY_PRODUCTS_V11
    : formalWeeklyV10 ? WEEKLY_PRODUCTS_V10 : WEEKLY_PRODUCTS_V8
  if ((candidate || formalWeekly) && !sameLiteralArray(value.weekly_products, expectedWeeklyProducts)) return false
  if (!Array.isArray(value.deferred_frequencies)
    || value.deferred_frequencies.length !== (daily ? 2 : (candidate || formalWeekly || hourlyPreview) ? 1 : 0)) return false
  if (!Array.isArray(value.deferred_sections) || value.deferred_sections.length !== 1) return false
  return (daily
    ? isDeferred(value.deferred_frequencies[0], '1w', 'NEWOW_WEEKLY_RELEASE_PENDING')
      && isDeferred(value.deferred_frequencies[1], '60m', 'NEWOW_HOURLY_RELEASE_PENDING')
    : candidate || formalWeekly ? isDeferred(value.deferred_frequencies[0], '60m', 'NEWOW_HOURLY_RELEASE_PENDING')
    : hourlyPreview ? isDeferred(value.deferred_frequencies[0], '1w', 'NEWOW_WEEKLY_RELEASE_PENDING')
    : true)
    && isDeferred(value.deferred_sections[0], 'explanation', 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN')
}

function sameLiteralArray(value: unknown, expected: readonly string[]): boolean {
  return Array.isArray(value)
    && value.length === expected.length
    && value.every((item, index) => item === expected[index])
}

function isDeferred(value: unknown, identity: string, reason: string): boolean {
  if (!isRecord(value)) return false
  const keys = Object.keys(value).sort().join(',')
  if (keys === 'frequency,reason_code') {
    return value.frequency === identity && value.reason_code === reason
  }
  if (keys === 'reason_code,section') {
    return value.section === identity && value.reason_code === reason
  }
  return false
}

function freezeProductCapabilities(
  value: NewowProductCapabilities,
): NewowProductCapabilities {
  for (const item of value.deferred_frequencies) Object.freeze(item)
  for (const item of value.deferred_sections) Object.freeze(item)
  Object.freeze(value.open_frequencies)
  if (value.weekly_products) Object.freeze(value.weekly_products)
  Object.freeze(value.deferred_frequencies)
  Object.freeze(value.open_sections)
  Object.freeze(value.deferred_sections)
  return Object.freeze(value)
}

export async function getNewowHistoricalSnapshot(
  identity: NewowProductRequest['identity'],
  options: NewowProductRequestOptions = {},
): Promise<NewowHistoricalSnapshot> {
  const transport = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await transport('/market/newow/historical-snapshot', {
      params: { product: identity.product, strategy: identity.strategy, frequency: identity.frequency },
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof NewowProductRequestError) throw error
    throw classifyTransportError(error)
  }
  if (!isHistoricalSnapshot(payload, identity)) throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid')
  return payload
}

export async function getNewowDailySnapshot(
  identity: NewowProductRequest['identity'],
  options: NewowProductRequestOptions = {},
): Promise<NewowDailySnapshot> {
  const transport = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await transport('/market/newow/daily-snapshot', {
      params: { product: identity.product, strategy: identity.strategy, frequency: identity.frequency },
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof NewowProductRequestError) throw error
    throw classifyTransportError(error)
  }
  if (!isDailySnapshot(payload, identity)) throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid')
  return payload
}

export async function getNewowWeeklySnapshot(
  identity: NewowProductRequest['identity'],
  options: NewowProductRequestOptions = {},
): Promise<NewowWeeklySnapshot> {
  const transport = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await transport('/market/newow/weekly-snapshot', {
      params: { product: identity.product, strategy: identity.strategy, frequency: identity.frequency },
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof NewowProductRequestError) throw error
    throw classifyTransportError(error)
  }
  if (!isWeeklySnapshot(payload, identity)) throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid')
  return payload
}

function isWeeklySnapshot(value: unknown, identity: NewowProductRequest['identity']): value is NewowWeeklySnapshot {
  if (!isRecord(value) || value.schema_version !== 'newow_weekly_snapshot_v1'
    || value.product !== identity.product || value.strategy !== identity.strategy
    || value.frequency !== '1w' || value.frequency !== identity.frequency
    || value.series_kind !== 'actual_dominant'
    || !isRecord(value.current_context)
    || (value.current_context.status !== 'known' && value.current_context.status !== 'unknown')
    || (value.current_context.status === 'known'
      ? typeof value.current_context.physical_contract !== 'string' || value.current_context.physical_contract.length === 0
      : value.current_context.physical_contract !== null)
    || !validInstant(value.requested_at) || !validInstant(value.expected_period_end)
    || !validInstant(value.available_period_end) || !validInstant(value.as_of)) return false
  return value.as_of === value.available_period_end
    && Date.parse(value.available_period_end) <= Date.parse(value.expected_period_end)
    && Date.parse(value.expected_period_end) <= Date.parse(value.requested_at)
    && (value.freshness === 'current'
      ? value.available_period_end === value.expected_period_end
      : value.freshness === 'pending_update' && value.available_period_end < value.expected_period_end)
}

function validInstant(value: unknown): value is string {
  return typeof value === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))
}

function isDailySnapshot(value: unknown, identity: NewowProductRequest['identity']): value is NewowDailySnapshot {
  if (!isRecord(value) || value.schema_version !== 'newow_daily_snapshot_v1'
    || value.product !== identity.product || value.strategy !== identity.strategy
    || value.frequency !== '1d' || value.frequency !== identity.frequency
    || value.series_kind !== 'actual_dominant'
    || !validCalendarDate(value.expected_trading_day as string)
    || !validCalendarDate(value.available_trading_day as string)
    || typeof value.requested_at !== 'string' || !Number.isFinite(Date.parse(value.requested_at))
    || typeof value.as_of !== 'string' || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value.as_of)
    || !Number.isFinite(Date.parse(value.as_of))) return false
  const expected = value.expected_trading_day as string
  const available = value.available_trading_day as string
  return available <= expected
    && (value.freshness === 'current' ? available === expected : value.freshness === 'pending_update' && available < expected)
    && Date.parse(value.as_of) <= Date.parse(value.requested_at)
}

function isHistoricalSnapshot(value: unknown, identity: NewowProductRequest['identity']): value is NewowHistoricalSnapshot {
  return isRecord(value) && value.schema_version === 'newow_historical_snapshot_v1'
    && value.product === identity.product && value.strategy === identity.strategy
    && value.frequency === identity.frequency && value.series_kind === 'actual_dominant'
    && typeof value.trading_day === 'string' && validCalendarDate(value.trading_day)
    && typeof value.as_of === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value.as_of) && Number.isFinite(Date.parse(value.as_of))
    && Array.isArray(value.validated_sections) && value.validated_sections.length === 2
    && value.validated_sections[0] === 'chart' && value.validated_sections[1] === 'zhaoyao_mirror'
}

function validCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (match === null) return false
  const year = Number(match[1]); const month = Number(match[2]); const day = Number(match[3])
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day
}

interface ProductRequestConfig {
  readonly params: Record<string, unknown>
  readonly signal?: AbortSignal
}

type ProductTransport = (path: string, config: ProductRequestConfig) => Promise<unknown>

export interface NewowProductRequestOptions {
  readonly signal?: AbortSignal
  readonly request?: ProductTransport
}

export async function getNewowProductSection(
  request: NewowProductRequest,
  options: NewowProductRequestOptions = {},
): Promise<NewowProductSectionResponse> {
  const transport = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await transport('/market/newow/strategy-detail', {
      params: buildNewowProductQuery(request),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof NewowProductRequestError) throw error
    throw classifyTransportError(error)
  }
  try {
    return normalizeNewowProductResponse(payload, request)
  } catch {
    throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid')
  }
}

export function buildNewowProductQuery(request: NewowProductRequest): Record<string, unknown> {
  const common: Record<string, unknown> = {
    product: request.identity.product,
    strategy: request.identity.strategy,
    frequency: request.identity.frequency,
    series_kind: request.identity.seriesKind,
    section: request.section,
    as_of: request.asOf,
  }
  if (request.section === 'chart') {
    addWindow(common, request.from, request.through)
    if (request.chartLimit !== undefined) common.chart_limit = request.chartLimit
    if (request.chartBefore !== undefined) common.chart_before = request.chartBefore
    if (request.chartOlderWindow !== undefined) {
      if (request.chartBefore !== undefined || request.from !== undefined || request.snapshotToken === undefined) throw new NewowProductRequestError('NEWOW_SECTION_PARAMETER_INVALID', 'invalid')
      common.chart_older_window = request.chartOlderWindow
    }
  } else if (request.section === 'auxiliary') {
    common.component = request.component
    addWindow(common, request.from, request.through)
  } else if (request.section === 'reference') {
    if (request.includeFusion) common.include_fusion = true
    if ((request.performanceSince === undefined) !== (request.performanceThrough === undefined)) throw new NewowProductRequestError('NEWOW_INVALID_PERFORMANCE_WINDOW', 'invalid')
    if (request.performanceSince !== undefined) {
      common.performance_since = request.performanceSince
      common.performance_through = request.performanceThrough
    }
    if (request.historyLimit !== undefined) common.history_limit = request.historyLimit
    if (request.historyBefore !== undefined) common.history_before = request.historyBefore
  }
  if (request.snapshotToken !== undefined) common.snapshot_token = request.snapshotToken
  return common
}

function addWindow(target: Record<string, unknown>, from: string | undefined, through: string | undefined): void {
  if ((from === undefined) !== (through === undefined)) throw new NewowProductRequestError('NEWOW_INVALID_RANGE', 'invalid')
  if (from !== undefined) { target.from = from; target.through = through }
}

async function defaultRequest(path: string, config: ProductRequestConfig): Promise<unknown> {
  const { default: request } = await import('./request.ts')
  return request.get<never, unknown>(path, config)
}

function classifyTransportError(error: unknown): NewowProductRequestError {
  if (isAbort(error)) return new NewowProductRequestError('NEWOW_REQUEST_CANCELLED', 'cancelled')
  const detail = httpDetail(error)
  if (detail?.status === 429 && detail.code === 'NEWOW_RESOURCE_BUSY') return new NewowProductRequestError(detail.code, 'busy')
  if (detail?.status === 429 && detail.code === 'NEWOW_REQUEST_CANCELLED') return new NewowProductRequestError(detail.code, 'cancelled')
  if (detail?.status === 409 && UNAVAILABLE_CODES.has(detail.code)) return new NewowProductRequestError(detail.code, 'unavailable', detail.diagnostic)
  if (detail?.status === 409 && CONFLICT_CODES.has(detail.code)) return new NewowProductRequestError(detail.code, 'conflict')
  if (detail?.status === 422 && INVALID_CODES.has(detail.code)) return new NewowProductRequestError(detail.code, 'invalid')
  return new NewowProductRequestError('NEWOW_API_UNAVAILABLE', 'unavailable')
}

function httpDetail(error: unknown): { status: number; code: string; diagnostic: NewowDataDiagnostic | null } | null {
  try {
    if (!isRecord(error) || !isRecord(error.response) || typeof error.response.status !== 'number' || !isRecord(error.response.data) || !isRecord(error.response.data.detail) || typeof error.response.data.detail.code !== 'string') return null
    return { status: error.response.status, code: error.response.data.detail.code, diagnostic: parseNewowDataDiagnostic(error.response.data.detail.diagnostic) }
  } catch { return null }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
