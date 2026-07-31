import type { MarketBarsRequestParams } from '@/types/market'
import type { MainIndicatorRequestParams } from './mainIndicators.ts'

export interface CanonicalBarsRequestParams {
  dataset_kind: 'continuous' | 'actual_dominant'
  symbol: string
  contract_or_series: string
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

function jmIdentity(input: {
  dataset_kind?: 'continuous' | 'actual_dominant'
  symbol: string
  contract: string
  period: string
}): Omit<CanonicalBarsRequestParams, 'start' | 'end'> {
  if (!input.dataset_kind) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: dataset_kind_required')
  }
  if (input.symbol.trim().toLowerCase() !== 'jm') {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: jm_only')
  }
  if (!input.contract.trim()) {
    throw new Error('DATA_CORE_V2_REQUEST_INVALID: contract_or_series_required')
  }
  return {
    dataset_kind: input.dataset_kind,
    symbol: 'jm',
    contract_or_series: input.contract.trim(),
    frequency: input.period,
  }
}

/** Remove every legacy Profile/Binding/tail selector from a V2 bars request. */
export function toCanonicalBarsRequest(
  input: MarketBarsRequestParams,
): CanonicalBarsRequestParams {
  return {
    ...jmIdentity(input),
    ...exactWindow(input.start, input.end),
  }
}

/** Bind public indicators to the exact canonical bars window and identity. */
export function toCanonicalIndicatorsRequest(
  input: MainIndicatorRequestParams,
): CanonicalIndicatorsRequestParams {
  return {
    ...jmIdentity(input),
    ...exactWindow(input.display_start, input.display_end),
    indicator_codes: input.indicator_codes,
    display_bar_count: input.display_bar_count,
  }
}
