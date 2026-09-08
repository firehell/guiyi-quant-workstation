import type {
  NewowHistoricalSnapshot,
  NewowProductRequest,
  NewowProductSectionResponse,
} from '../types/newowProduct.ts'
import { normalizeNewowProductResponse } from '../utils/newowProductTypes.ts'

export type NewowProductErrorClassification = 'invalid' | 'conflict' | 'busy' | 'cancelled' | 'unavailable' | 'response_invalid'

const INVALID_CODES = new Set([
  'NEWOW_INVALID_QUERY', 'NEWOW_INVALID_PRODUCT', 'NEWOW_INVALID_RANGE', 'NEWOW_INVALID_PERFORMANCE_WINDOW',
  'NEWOW_INVALID_CHART_LIMIT', 'NEWOW_INVALID_HISTORY_LIMIT', 'NEWOW_AUXILIARY_COMPONENT_REQUIRED',
  'NEWOW_SECTION_PARAMETER_INVALID', 'NEWOW_COMPLETE_PERIOD_MISSING',
])
const CONFLICT_CODES = new Set([
  'NEWOW_DATA_IDENTITY_INVALID', 'NEWOW_DATA_UNAVAILABLE', 'NEWOW_DATA_OUT_OF_ORDER',
  'NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'NEWOW_CURSOR_GENERATION_CONFLICT', 'NEWOW_CURSOR_INVALID',
  'NEWOW_REFERENCE_PAIRING_CONFLICT', 'NEWOW_PAGE_COMPARATOR_CONFLICTING_FACT',
])

export class NewowProductRequestError extends Error {
  readonly code: string
  readonly classification: NewowProductErrorClassification

  constructor(code: string, classification: NewowProductErrorClassification) {
    super(code)
    this.name = 'NewowProductRequestError'
    this.code = code
    this.classification = classification
  }
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
  } else if (request.section === 'auxiliary') {
    common.component = request.component
    addWindow(common, request.from, request.through)
  } else if (request.section === 'reference') {
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
  if (detail?.status === 409 && CONFLICT_CODES.has(detail.code)) return new NewowProductRequestError(detail.code, 'conflict')
  if (detail?.status === 422 && INVALID_CODES.has(detail.code)) return new NewowProductRequestError(detail.code, 'invalid')
  return new NewowProductRequestError('NEWOW_API_UNAVAILABLE', 'unavailable')
}

function httpDetail(error: unknown): { status: number; code: string } | null {
  try {
    if (!isRecord(error) || !isRecord(error.response) || typeof error.response.status !== 'number' || !isRecord(error.response.data) || !isRecord(error.response.data.detail) || typeof error.response.data.detail.code !== 'string') return null
    return { status: error.response.status, code: error.response.data.detail.code }
  } catch { return null }
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
