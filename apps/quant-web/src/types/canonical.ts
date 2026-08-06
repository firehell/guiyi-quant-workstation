import type { HistoricalBarFrequency } from './historicalBarFrequency'

/** Immutable DatasetKey shared by canonical Signal and Review consumers. */
export interface CanonicalDatasetKey {
  provider: string
  dataset_kind: 'continuous' | 'actual_dominant' | string
  symbol: string
  contract_or_series: string
  frequency: HistoricalBarFrequency
  adjustment: string
  schema_version: string
}

/** Exact canonical read identity persisted by non-backtest research consumers. */
export interface CanonicalInputIdentity {
  schema_version: 'canonical_consumer_input_v1' | string
  request: {
    dataset_kind: 'continuous' | 'actual_dominant' | string
    symbol: string
    contract_or_series: string | null
    frequency: HistoricalBarFrequency
    start: string
    end: string
    strict: boolean
  }
  source_datasets: CanonicalDatasetKey[]
  manifest_digests: string[]
  source_data_versions: string[]
  derived_frequency: null
  strategy_input_version: string
  digest: string
}
