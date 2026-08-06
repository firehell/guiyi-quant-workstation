import type { CanonicalInputIdentity } from '@/types/canonical'
import { isHistoricalBarFrequency } from '../types/historicalBarFrequency.ts'
import type { SignalScanRequest } from '@/types/signal'

function compact(value: string) {
  return value.trim()
}

const SHA256 = /^[0-9a-f]{64}$/
const DATASET_KINDS = new Set(['continuous', 'actual_dominant'])
export const FORMAL_SIGNAL_HISTORICAL_FREQUENCIES = [
  '5m', '15m', '30m', '60m', '1d',
] as const
const FORMAL_SIGNAL_FREQUENCY_SET = new Set<string>(FORMAL_SIGNAL_HISTORICAL_FREQUENCIES)

export function isFormalSignalHistoricalFrequency(value: string): boolean {
  return FORMAL_SIGNAL_FREQUENCY_SET.has(value)
}
const CANONICAL_INPUT_FIELDS = [
  'schema_version',
  'request',
  'source_datasets',
  'manifest_digests',
  'source_data_versions',
  'derived_frequency',
  'strategy_input_version',
  'digest',
]
const CANONICAL_REQUEST_FIELDS = [
  'dataset_kind',
  'symbol',
  'contract_or_series',
  'frequency',
  'start',
  'end',
  'strict',
]
const CANONICAL_DATASET_FIELDS = [
  'provider',
  'dataset_kind',
  'symbol',
  'contract_or_series',
  'frequency',
  'adjustment',
  'schema_version',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exactText(value: unknown, transform?: (text: string) => string): value is string {
  return typeof value === 'string'
    && Boolean(value.trim())
    && value === (transform ? transform(value.trim()) : value.trim())
}

function exactFields(value: Record<string, unknown>, expected: string[]) {
  const fields = Object.keys(value)
  return fields.length === expected.length
    && fields.every((field) => expected.includes(field))
}

function canonicalUtcDatetimeParts(value: unknown): number[] | null {
  if (typeof value !== 'string') return null
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{6}))?\+00:00$/.exec(value)
  if (!match) return null
  const [year, month, day, hour, minute, second, microsecond = 0] = match.slice(1).map(Number)
  if (year < 1) return null
  const parsed = new Date(0)
  parsed.setUTCFullYear(year, month - 1, day)
  parsed.setUTCHours(hour, minute, second, 0)
  if (!Number.isFinite(parsed.getTime())) return null
  if (parsed.getUTCFullYear() !== year
    || parsed.getUTCMonth() !== month - 1
    || parsed.getUTCDate() !== day
    || parsed.getUTCHours() !== hour
    || parsed.getUTCMinutes() !== minute
    || parsed.getUTCSeconds() !== second) return null
  return [year, month, day, hour, minute, second, microsecond]
}

function canonicalUtcDatetime(value: unknown): value is string {
  return canonicalUtcDatetimeParts(value) !== null
}

function precedesCanonicalUtcDatetime(start: string, end: string) {
  const startParts = canonicalUtcDatetimeParts(start)
  const endParts = canonicalUtcDatetimeParts(end)
  if (!startParts || !endParts) return false
  for (let index = 0; index < startParts.length; index += 1) {
    if (startParts[index] !== endParts[index]) return startParts[index] < endParts[index]
  }
  return false
}

function validRequestContract(datasetKind: string, symbol: string, contractOrSeries: unknown): contractOrSeries is string | null {
  if (datasetKind === 'continuous') return contractOrSeries === `${symbol.toUpperCase()}.MAIN`
  return contractOrSeries === null || (
    exactText(contractOrSeries, (value) => value.toUpperCase())
    && new RegExp(`^${symbol.toUpperCase()}\\d{3,4}$`).test(contractOrSeries)
  )
}

function validDatasetContract(datasetKind: string, symbol: string, contractOrSeries: unknown) {
  return typeof contractOrSeries === 'string'
    && validRequestContract(datasetKind, symbol, contractOrSeries)
}

function canonicalStringArray(value: unknown, predicate: (item: string) => boolean): value is string[] {
  return Array.isArray(value)
    && value.every((item) => typeof item === 'string' && predicate(item))
    && value.every((item, index) => index === 0 || value[index - 1] < item)
}

function datasetSortKey(item: CanonicalInputIdentity['source_datasets'][number]) {
  return [
    item.provider,
    item.dataset_kind,
    item.symbol,
    item.contract_or_series,
    item.frequency,
    item.adjustment,
    item.schema_version,
  ].join('\u0000')
}

function isCanonicalDataset(value: unknown): value is CanonicalInputIdentity['source_datasets'][number] {
  if (!isRecord(value) || !exactFields(value, CANONICAL_DATASET_FIELDS)) return false
  if (value.provider !== 'rqdata'
    || !DATASET_KINDS.has(String(value.dataset_kind))
    || !exactText(value.symbol, (text) => text.toLowerCase())
    || !exactText(value.adjustment, (text) => text.toLowerCase())
    || !exactText(value.schema_version)
    || !isHistoricalBarFrequency(value.frequency)
    || !validDatasetContract(String(value.dataset_kind), String(value.symbol), value.contract_or_series)) {
    return false
  }
  return true
}

function unavailableIdentity(reason: string) {
  return { status: 'unavailable' as const, reason, identity: null }
}

/**
 * Structural validation for untyped API/DB feature payloads. SHA-256 values are
 * format-checked here but not browser-recomputed, so valid payloads stay
 * explicitly `unverified` rather than being promoted to a cryptographic proof.
 */
export function parseCanonicalInputIdentity(
  value: unknown,
  options: { expectedDatasetKind?: 'continuous' | 'actual_dominant' } = {},
) {
  if (!isRecord(value) || value.schema_version !== 'canonical_consumer_input_v1') {
    return unavailableIdentity('unsupported or missing canonical input schema')
  }
  if (!exactFields(value, CANONICAL_INPUT_FIELDS)) return unavailableIdentity('canonical input fields are malformed')
  const request = value.request
  if (!isRecord(request) || !exactFields(request, CANONICAL_REQUEST_FIELDS)) {
    return unavailableIdentity('canonical request is missing or malformed')
  }
  const requestDatasetKind = request.dataset_kind
  const requestSymbol = request.symbol
  const requestContract = request.contract_or_series
  const requestFrequency = request.frequency
  const requestStart = request.start
  const requestEnd = request.end
  const requestStrict = request.strict
  if (typeof requestDatasetKind !== 'string'
    || !DATASET_KINDS.has(requestDatasetKind)
    || !exactText(requestSymbol, (text) => text.toLowerCase())
    || typeof requestFrequency !== 'string'
    || !isHistoricalBarFrequency(requestFrequency)
    || !canonicalUtcDatetime(requestStart)
    || !canonicalUtcDatetime(requestEnd)
    || typeof requestStrict !== 'boolean') {
    return unavailableIdentity('canonical request fields are malformed')
  }
  if (!validRequestContract(requestDatasetKind, requestSymbol, requestContract)) {
    return unavailableIdentity('canonical request contract is malformed')
  }
  if (!precedesCanonicalUtcDatetime(requestStart, requestEnd)) {
    return unavailableIdentity('canonical request window is malformed')
  }
  if (options.expectedDatasetKind && requestDatasetKind !== options.expectedDatasetKind) {
    return unavailableIdentity(`expected ${options.expectedDatasetKind} canonical dataset_kind`)
  }
  const sourceDatasetsRaw = value.source_datasets
  if (!Array.isArray(sourceDatasetsRaw) || sourceDatasetsRaw.length === 0) {
    return unavailableIdentity('canonical source_datasets are missing')
  }
  const sourceDatasets: CanonicalInputIdentity['source_datasets'] = []
  for (const sourceDataset of sourceDatasetsRaw) {
    if (!isCanonicalDataset(sourceDataset)) return unavailableIdentity('canonical source_datasets are malformed')
    sourceDatasets.push(sourceDataset)
  }
  if (!sourceDatasets.every((item, index) => index === 0 || datasetSortKey(sourceDatasets[index - 1]) < datasetSortKey(item))
    || sourceDatasets.some((item) => item.dataset_kind !== requestDatasetKind
      || item.symbol !== requestSymbol
      || (requestContract !== null && item.contract_or_series !== requestContract))) {
    return unavailableIdentity('canonical source_datasets are malformed')
  }
  const manifestDigests = value.manifest_digests
  if (!canonicalStringArray(manifestDigests, (item) => SHA256.test(item)) || manifestDigests.length === 0) {
    return unavailableIdentity('canonical manifest digests are malformed')
  }
  const sourceDataVersions = value.source_data_versions
  if (!canonicalStringArray(sourceDataVersions, (item) => exactText(item))) {
    return unavailableIdentity('canonical source_data_versions are malformed')
  }
  const derivedFrequency = value.derived_frequency
  if (derivedFrequency !== null) {
    return unavailableIdentity('historical derived lineage cannot drive an active canonical read')
  }
  if (sourceDatasets.some((item) => item.frequency !== requestFrequency)) {
    return unavailableIdentity('canonical same-frequency relationship is malformed')
  }
  const strategyInputVersion = value.strategy_input_version
  const digest = value.digest
  if (!exactText(strategyInputVersion) || typeof digest !== 'string' || !SHA256.test(digest)) {
    return unavailableIdentity('canonical input digest is malformed')
  }
  const identity: CanonicalInputIdentity = {
    schema_version: 'canonical_consumer_input_v1',
    request: {
      dataset_kind: requestDatasetKind,
      symbol: requestSymbol,
      contract_or_series: requestContract,
      frequency: requestFrequency,
      start: requestStart,
      end: requestEnd,
      strict: requestStrict,
    },
    source_datasets: sourceDatasets.map((item) => ({ ...item })),
    manifest_digests: [...manifestDigests],
    source_data_versions: [...sourceDataVersions],
    derived_frequency: derivedFrequency,
    strategy_input_version: strategyInputVersion,
    digest,
  }
  return {
    status: 'unverified' as const,
    reason: 'valid canonical shape; digest unverified because the browser does not recompute it',
    identity,
  }
}

/** Serialize the canonical signal contract; non-scan modes remain zero-write server previews. */
export function buildFormalSignalScanRequest(input: SignalScanRequest): SignalScanRequest {
  return {
    dataset_kind: input.dataset_kind,
    instrument_symbol: compact(input.instrument_symbol).toLowerCase(),
    contract_or_series: compact(input.contract_or_series).toUpperCase(),
    periods: input.periods.map(compact),
    start: input.start,
    end: input.end,
    mode: input.mode,
    watchlist_code: compact(input.watchlist_code),
    account_equity: input.account_equity,
    risk_per_trade_pct: input.risk_per_trade_pct,
    max_margin_usage_pct: input.max_margin_usage_pct,
    min_score_bucket: input.min_score_bucket,
    ...(input.strategy_params ? { strategy_params: input.strategy_params } : {}),
  }
}

/** Validate the percentage controls before they are converted to backend fractions. */
export function validateFormalSignalRiskPercentages(
  riskPerTradePercent: number,
  maxMarginUsagePercent: number,
): string | null {
  if (!Number.isFinite(riskPerTradePercent) || riskPerTradePercent <= 0 || riskPerTradePercent > 1) {
    return '单笔风险必须大于 0% 且不超过 1%；未提交扫描请求。'
  }
  if (!Number.isFinite(maxMarginUsagePercent) || maxMarginUsagePercent <= 0 || maxMarginUsagePercent > 35) {
    return '保证金上限必须大于 0% 且不超过 35%；未提交扫描请求。'
  }
  return null
}

/** Fail closed before posting a formal actual-dominant Signal request. */
export function validateFormalSignalScanInput(input: {
  contractOrSeries: string
  periods: string[]
  startMs: number | null
  endMs: number | null
  riskPerTradePercent: number
  maxMarginUsagePercent: number
}): string | null {
  if (!/^JM\d{3,4}$/.test(input.contractOrSeries)) {
    return '必须填写大写且规范的 JM 实际主力合约（例如 JM2609，格式 JM\\d{3,4}）；未提交扫描请求。'
  }
  if (!input.periods.length || input.periods.some((period) => !period.trim())) {
    return '必须选择至少一个有效周期；未提交扫描请求。'
  }
  if (input.periods.some((period) => !isHistoricalBarFrequency(period))) {
    return '周期仅支持 1m/5m/15m/30m/60m/1d/1w，且不接受别名或大小写转换；未提交扫描请求。'
  }
  if (input.periods.some((period) => !isFormalSignalHistoricalFrequency(period))) {
    return '当前正式信号策略仅支持 5m/15m/30m/60m/1d；历史数据合同仍支持全部七种周期。'
  }
  if (input.startMs === null || input.endMs === null
    || !Number.isFinite(input.startMs) || !Number.isFinite(input.endMs)
    || input.startMs >= input.endMs) {
    return '请求时间窗口必须有效且开始时间早于结束时间；未提交扫描请求。'
  }
  return validateFormalSignalRiskPercentages(input.riskPerTradePercent, input.maxMarginUsagePercent)
}

/** Preserve an intentionally cleared Naive UI date range as an invalid form state. */
export function normalizeFormalSignalDateRange(value: readonly number[] | null) {
  if (!value || value.length !== 2 || !Number.isFinite(value[0]) || !Number.isFinite(value[1])) {
    return { startMs: null, endMs: null }
  }
  return { startMs: value[0], endMs: value[1] }
}

export function presentCanonicalInputIdentity(
  value: unknown,
  options: { expectedDatasetKind?: 'continuous' | 'actual_dominant' } = {},
) {
  const parsed = parseCanonicalInputIdentity(value, options)
  const identity = parsed.identity
  const request = identity?.request
  const datasets = identity?.source_datasets || []
  return {
    status: parsed.status,
    warning: parsed.reason,
    request: request
      ? [request.dataset_kind, request.symbol, request.contract_or_series || '-', request.frequency].join(' · ')
      : 'unavailable',
    sourceDatasets: datasets.length
      ? datasets
          .map((item) => [item.provider, item.dataset_kind, item.symbol, item.contract_or_series, item.frequency].join(' · '))
          .join(' | ')
      : 'unavailable',
    manifestDigests: identity?.manifest_digests?.join(' | ') || 'unavailable',
    requestedWindow: request ? `${request.start} → ${request.end}` : 'unavailable',
    digest: identity?.digest || 'unavailable',
  }
}
