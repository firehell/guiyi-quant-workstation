import type { ReferenceTradeView } from './referenceTrading'
export interface HtdyHistoricalSignal {
  bar_end: string; trading_day: string; physical_contract: string; segment_id: string
  calculation_segment_id: string; observation_types: ('buy' | 'sell')[]; reference_price: string; action_ids: string[]
}
export interface HtdyHistoricalResponse {
  schema_version: 'htdy_historical_reference_v1'; recording_mode: 'historical_replay'
  product: string; frequency: string; source_token: string; computed_through: string
  since: string; through: string; trades: ReferenceTradeView[]; signals: HtdyHistoricalSignal[]
  summary: { total: number; closed: number; open: number; wins?: number; losses?: number; flat?: number; interrupted?: number; win_rate_pct?: string | null; mean_return_pct?: string | null; sum_return_percentage_points?: string | null }; next_cursor: string | null
}
