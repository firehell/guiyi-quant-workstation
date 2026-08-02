import type { BacktestTaskCreateRequest, CanonicalInputIdentity } from '@/types/backtest'
import type { SignalScanRequest } from '@/types/signal'

function compact(value: string) {
  return value.trim()
}

const SHA256 = /^[0-9a-f]{64}$/
const DATASET_KINDS = new Set(['continuous', 'actual_dominant'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonBlankString(value: unknown) {
  return typeof value === 'string' && Boolean(value.trim())
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
  const request = value.request
  if (!isRecord(request)) return unavailableIdentity('canonical request is missing')
  const requestFields = ['dataset_kind', 'symbol', 'contract_or_series', 'frequency', 'start', 'end']
  if (requestFields.some((field) => !nonBlankString(request[field])) || typeof request.strict !== 'boolean') {
    return unavailableIdentity('canonical request fields are malformed')
  }
  if (!DATASET_KINDS.has(String(request.dataset_kind))) {
    return unavailableIdentity('canonical request dataset_kind is unsupported')
  }
  if (options.expectedDatasetKind && request.dataset_kind !== options.expectedDatasetKind) {
    return unavailableIdentity(`expected ${options.expectedDatasetKind} canonical dataset_kind`)
  }
  if (!Array.isArray(value.source_datasets) || value.source_datasets.length === 0) {
    return unavailableIdentity('canonical source_datasets are missing')
  }
  const sourceFields = ['provider', 'dataset_kind', 'symbol', 'contract_or_series', 'frequency', 'adjustment', 'schema_version']
  if (value.source_datasets.some((item) =>
    !isRecord(item)
    || sourceFields.some((field) => !nonBlankString(item[field]))
    || !DATASET_KINDS.has(String(item.dataset_kind))
    || item.dataset_kind !== request.dataset_kind,
  )) {
    return unavailableIdentity('canonical source_datasets are malformed')
  }
  if (!Array.isArray(value.manifest_digests) || value.manifest_digests.length === 0 || value.manifest_digests.some((item) => typeof item !== 'string' || !SHA256.test(item))) {
    return unavailableIdentity('canonical manifest digests are malformed')
  }
  if (!Array.isArray(value.source_data_versions) || value.source_data_versions.some((item) => !nonBlankString(item))) {
    return unavailableIdentity('canonical source_data_versions are malformed')
  }
  if (value.derived_frequency !== null && !nonBlankString(value.derived_frequency)) {
    return unavailableIdentity('canonical derived_frequency is malformed')
  }
  if (!nonBlankString(value.strategy_input_version) || !nonBlankString(value.digest) || !SHA256.test(String(value.digest))) {
    return unavailableIdentity('canonical input digest is malformed')
  }
  return {
    status: 'unverified' as const,
    reason: 'canonical input structure is valid; browser digest recomputation is not performed',
    identity: value as unknown as CanonicalInputIdentity,
  }
}

/** Serialize only the backend's formal canonical backtest contract. */
export function buildFormalBacktestRequest(input: BacktestTaskCreateRequest): BacktestTaskCreateRequest {
  return {
    engine_type: input.engine_type,
    task_type: input.task_type,
    dataset_kind: input.dataset_kind,
    instrument_symbol: compact(input.instrument_symbol).toLowerCase(),
    contract_or_series: compact(input.contract_or_series).toUpperCase(),
    exchange: compact(input.exchange).toUpperCase(),
    interval: compact(input.interval),
    ...(input.auxiliary_periods ? { auxiliary_periods: input.auxiliary_periods.map(compact) } : {}),
    start: input.start,
    end: input.end,
    strategy_class_path: compact(input.strategy_class_path),
    strategy_code: input.strategy_code,
    strategy_version: input.strategy_version,
    strategy_parameters: input.strategy_parameters,
    rate: input.rate,
    slippage: input.slippage,
    size: input.size,
    pricetick: input.pricetick,
    capital: input.capital,
    ...(input.execution_timing ? { execution_timing: input.execution_timing } : {}),
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
  startMs: number
  endMs: number
  riskPerTradePercent: number
  maxMarginUsagePercent: number
}): string | null {
  if (!input.contractOrSeries.trim() || input.contractOrSeries.trim().toUpperCase().endsWith('.MAIN')) {
    return '必须填写具体实际主力合约（例如 JM2609），不能使用 JM.MAIN；未提交扫描请求。'
  }
  if (!input.periods.length || input.periods.some((period) => !period.trim())) {
    return '必须选择至少一个有效周期；未提交扫描请求。'
  }
  if (input.periods.some((period) => period.trim() === '1w')) {
    return 'actual_dominant 正式 Signal 暂不支持 1w 周期；未提交扫描请求。'
  }
  if (!Number.isFinite(input.startMs) || !Number.isFinite(input.endMs) || input.startMs >= input.endMs) {
    return '请求时间窗口必须有效且开始时间早于结束时间；未提交扫描请求。'
  }
  return validateFormalSignalRiskPercentages(input.riskPerTradePercent, input.maxMarginUsagePercent)
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
