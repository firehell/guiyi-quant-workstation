import type { BacktestReport } from '@/types/backtest'
import type {
  BacktestMarketBarsQueryDebug,
  BacktestMarketBarsResult,
  MarketBarsRequestParams,
  MarketBarsResponse,
} from '@/types/market'
import { parseCanonicalInputIdentity } from './dataCoreV2Consumer.ts'
import type { MainIndicatorRequestParams } from './mainIndicators.ts'

export interface CanonicalBarsRequestParams {
  dataset_kind: 'continuous' | 'actual_dominant'
  symbol: string
  contract_or_series: string | null
  frequency: string
  start: string
  end: string
}

export interface CanonicalIndicatorsRequestParams extends CanonicalBarsRequestParams {
  indicator_codes: string
  display_bar_count: number
}

function exactWindow(start?: string, end?: string): { start: string; end: string } {
  if (!start?.trim() || !end?.trim()) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: exact_start_end_required')
  }
  const normalized = { start: start.trim(), end: end.trim() }
  for (const [field, value] of Object.entries(normalized)) {
    if (
      !/T/.test(value) ||
      !/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
      Number.isNaN(Date.parse(value))
    ) {
      throw new Error(`DATA_CORE_V2_REQUEST_INVALID: ${field}_rfc3339_timezone_required`)
    }
  }
  return normalized
}

function canonicalIdentity(input: {
  dataset_kind?: 'continuous' | 'actual_dominant'
  symbol: string
  contract: string | null
  period: string
}): Omit<CanonicalBarsRequestParams, 'start' | 'end'> {
  if (!input.dataset_kind) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: dataset_kind_required')
  }
  const symbol = input.symbol.trim().toLowerCase()
  if (!symbol) throw new Error('DATA_CORE_V2_REQUEST_INVALID: symbol_required')
  if (input.contract !== null && !input.contract.trim()) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: contract_or_series_required')
  }
  if (input.dataset_kind === 'continuous' && input.contract === null) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: contract_or_series_required')
  }
  return {
    dataset_kind: input.dataset_kind,
    symbol,
    contract_or_series: input.contract?.trim() || null,
    frequency: input.period,
  }
}

/** Remove every legacy Profile/Binding/tail selector from a V2 bars request. */
export function toCanonicalBarsRequest(
  input: MarketBarsRequestParams,
): CanonicalBarsRequestParams {
  return {
    ...canonicalIdentity(input),
    ...exactWindow(input.start, input.end),
  }
}

/** Bind public indicators to the exact canonical bars window and identity. */
export function toCanonicalIndicatorsRequest(
  input: MainIndicatorRequestParams,
): CanonicalIndicatorsRequestParams {
  return {
    ...canonicalIdentity(input),
    ...exactWindow(input.display_start, input.display_end),
    indicator_codes: input.indicator_codes,
    display_bar_count: input.display_bar_count,
  }
}

/** Replay a formal report only from its immutable canonical input identity. */
export function toCanonicalReportBarsQuery(
  report: Pick<BacktestReport, 'input_identity' | 'input_identity_attestation'>,
): BacktestMarketBarsQueryDebug {
  const parsed = parseCanonicalInputIdentity(report.input_identity)
  if (parsed.identity === null) {
    throw new Error(
      `DATA_CORE_V2_REQUEST_INVALID: canonical_report_input_identity_required (${parsed.reason})`,
    )
  }
  const attestation = report.input_identity_attestation
  if (attestation?.schema_version !== 'canonical_consumer_input_attestation_v1'
    || attestation.status !== 'server_verified'
    || attestation.digest !== parsed.identity.digest) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: canonical_report_input_identity_attestation_required')
  }
  const request = parsed.identity.request
  const candidate: MarketBarsRequestParams = {
    dataset_kind: request.dataset_kind as 'continuous' | 'actual_dominant',
    symbol: request.symbol,
    contract: request.contract_or_series,
    period: request.frequency,
    start: request.start,
    end: request.end,
  }
  return {
    dataset_kind: candidate.dataset_kind,
    symbol: candidate.symbol,
    contract: candidate.contract,
    interval: candidate.period,
    start: candidate.start,
    end: candidate.end,
    attempted: [candidate],
  }
}

type CanonicalReportBarsRequester = (
  path: '/market/bars/canonical',
  params: CanonicalBarsRequestParams,
) => Promise<MarketBarsResponse>

/** Execute the report's server-attested canonical request exactly once. */
export async function getMarketBarsForBacktestReport(
  report: Pick<BacktestReport, 'input_identity' | 'input_identity_attestation'>,
  requester: CanonicalReportBarsRequester,
): Promise<BacktestMarketBarsResult> {
  const query = toCanonicalReportBarsQuery(report)
  const params = toCanonicalBarsRequest(query.attempted[0])
  const response = await requester('/market/bars/canonical', params)
  return { response, query }
}
