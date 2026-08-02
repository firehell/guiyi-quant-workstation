import type { BacktestTaskCreateRequest, CanonicalInputIdentity } from '@/types/backtest'
import type { SignalScanRequest } from '@/types/signal'

function compact(value: string) {
  return value.trim()
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

export function presentCanonicalInputIdentity(identity: CanonicalInputIdentity | null | undefined) {
  const request = identity?.request
  const datasets = identity?.source_datasets || []
  return {
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
