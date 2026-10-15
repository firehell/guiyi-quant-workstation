import { capabilityContract } from '../generated/newowCapabilityContracts.ts'
import { newowSessionResources, newowResourceIdentity } from '../utils/newowSessionResources.ts'
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
  if (!isRecord(value) || typeof value.schema_version !== 'string') return false
  const contract = capabilityContract(value.schema_version)
  if (!contract) return false
  const keys = [...Object.keys(contract.response), ...(contract.intradayScope ? ['intraday_products'] : [])]
  if (!sameCapabilityValue(Object.keys(value).sort(), keys.sort())) return false
  if (!Object.entries(contract.response).every(([key, expected]) => sameCapabilityValue(value[key], expected))) return false
  const scope = contract.intradayScope
  if (scope) {
    const products = value.intraday_products
    if (!Array.isArray(products) || products.length === 0 || (scope.single && products.length !== 1)
      || !products.every(product => typeof product === 'string' && scope.allowed.includes(product))
      || !sameCapabilityValue(products, [...new Set(products)].sort())) return false
  }
  return true
}

function sameCapabilityValue(value: unknown, expected: unknown): boolean {
  if (Array.isArray(expected)) {
    return Array.isArray(value) && value.length === expected.length
      && expected.every((item, index) => sameCapabilityValue(value[index], item))
  }
  if (isRecord(expected)) {
    return isRecord(value) && sameCapabilityValue(Object.keys(value).sort(), Object.keys(expected).sort())
      && Object.entries(expected).every(([key, item]) => sameCapabilityValue(value[key], item))
  }
  return value === expected
}

function freezeProductCapabilities(
  value: NewowProductCapabilities,
): NewowProductCapabilities {
  for (const item of value.deferred_frequencies) Object.freeze(item)
  for (const item of value.deferred_sections) Object.freeze(item)
  Object.freeze(value.open_frequencies)
  if (value.weekly_products) Object.freeze(value.weekly_products)
  if (value.intraday_products) Object.freeze(value.intraday_products)
  if (value.latest_completed_frequencies) Object.freeze(value.latest_completed_frequencies)
  if (value.strategy_frequencies) {
    for (const frequencies of Object.values(value.strategy_frequencies)) Object.freeze(frequencies)
    Object.freeze(value.strategy_frequencies)
  }
  Object.freeze(value.deferred_frequencies)
  Object.freeze(value.open_sections)
  Object.freeze(value.deferred_sections)
  return Object.freeze(value)
}

export async function getNewowHistoricalSnapshot(
  identity: NewowProductRequest['identity'],
  options: NewowProductRequestOptions = {},
): Promise<NewowHistoricalSnapshot> {
  if (options.request === undefined) return newowSessionResources.load(snapshotResourceKey('historical-snapshot', identity), signal => getNewowHistoricalSnapshot(identity, { ...options, signal, request: defaultRequest }), newowResourceIdentity, options.signal)
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
  if (options.request === undefined && !options.signal?.aborted) { const context = homeSnapshot(identity); if (context?.frequency === '1d') return context }
  if (options.request === undefined) return newowSessionResources.load(snapshotResourceKey('daily-snapshot', identity), signal => getNewowDailySnapshot(identity, { ...options, signal, request: defaultRequest }), newowResourceIdentity, options.signal)
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
  if (options.request === undefined && !options.signal?.aborted) { const context = homeSnapshot(identity); if (context?.frequency === '1w') return context }
  if (options.request === undefined) return newowSessionResources.load(snapshotResourceKey('weekly-snapshot', identity), signal => getNewowWeeklySnapshot(identity, { ...options, signal, request: defaultRequest }), newowResourceIdentity, options.signal)
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
  readonly timeout?: number
  readonly params: Record<string, unknown>
  readonly signal?: AbortSignal
}

type ProductTransport = (path: string, config: ProductRequestConfig) => Promise<unknown>

export interface NewowProductRequestOptions {
  readonly timeout?: number
  readonly signal?: AbortSignal
  readonly request?: ProductTransport
}

export async function getNewowProductSection(
  request: NewowProductRequest,
  options: NewowProductRequestOptions = {},
): Promise<NewowProductSectionResponse> {
  if (options.request === undefined) return newowSessionResources.load(`newow:${request.identity.product}:section:${JSON.stringify(buildNewowProductQuery(request))}`, signal => getNewowProductSection(request, { ...options, signal, request: defaultRequest }), newowResourceIdentity, options.signal)
  const transport = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await transport('/market/newow/strategy-detail', {
      params: buildNewowProductQuery(request),
      signal: options.signal,
      timeout: options.timeout ?? 60000,
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
  if (String(request.identity.frequency) === '1m') throw new NewowProductRequestError('NEWOW_FREQUENCY_NOT_OPEN', 'unavailable')
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
    if (request.fusionBefore !== undefined) common.fusion_before = request.fusionBefore
    if ((request.performanceSince === undefined) !== (request.performanceThrough === undefined)) throw new NewowProductRequestError('NEWOW_INVALID_PERFORMANCE_WINDOW', 'invalid')
    if (request.performanceSince !== undefined) {
      common.performance_since = request.performanceSince
      common.performance_through = request.performanceThrough
    }
    if (request.historyLimit !== undefined) common.history_limit = request.historyLimit
    if (request.historyBefore !== undefined) common.history_before = request.historyBefore
  }
  if (request.section === 'explanation' && request.decisionV2) common.decision_v2 = true
  if (request.snapshotToken !== undefined) common.snapshot_token = request.snapshotToken
  return common
}

function addWindow(target: Record<string, unknown>, from: string | undefined, through: string | undefined): void {
  if ((from === undefined) !== (through === undefined)) throw new NewowProductRequestError('NEWOW_INVALID_RANGE', 'invalid')
  if (from !== undefined) { target.from = from; target.through = through }
}

async function defaultRequest(path: string, config: ProductRequestConfig): Promise<unknown> {
  if (import.meta.env?.DEV) console.debug('Newow HTTP detail', path, config.params.product, config.params.section ?? 'snapshot')
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

function snapshotResourceKey(kind: string, identity: NewowProductRequest['identity']) {
  return `newow:${identity.product}:${kind}:${JSON.stringify(identity)}`
}

/** Context is read from the bounded home entry, not duplicated four times per product. */
function homeSnapshot(identity: NewowProductRequest['identity']): NewowDailySnapshot | NewowWeeklySnapshot | undefined {
  return newowSessionResources.find(value => {
    const response = value as { schema_version?: string; items?: Array<{ product: string; strategies: Record<string, Record<string, { snapshot_context?: unknown }>> }> }
    if (response?.schema_version !== 'newow_home_cards_v2') return undefined
    const context = response.items?.find(item => item.product === identity.product)?.strategies[identity.strategy]?.[identity.frequency]?.snapshot_context
    if (identity.frequency === '1d' && isDailySnapshot(context, identity)) return context
    if (identity.frequency === '1w' && isWeeklySnapshot(context, identity)) return context
    return undefined
  })
}
