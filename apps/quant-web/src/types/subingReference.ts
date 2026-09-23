import type { KlineReferenceIndicator } from './referenceCallout'

export interface SubingReferenceSignal {
  signal_id: string; bar_end: string; trading_day: string; physical_contract: string; segment_id: string
  calculation_segment_id?: string
  direction: 'buy' | 'sell'; reference_price: string
  action: 'OPEN_LONG' | 'OPEN_SHORT' | 'REVERSE_TO_LONG' | 'REVERSE_TO_SHORT' | 'SAME_DIRECTION'
  entry_trade_id: string | null; closed_trade_id: string | null; closed_return_pct: string | null
  dif?: string | null; dea?: string | null; macd?: string | null; ema21?: string | null
}
export interface SubingReferenceTrade {
  reference_trade_id: string; side: 'LONG' | 'SHORT'; physical_contract: string; segment_id: string
  calculation_segment_id?: string
  entry_signal_id: string; entry_bar_end: string; entry_trading_day: string; entry_reference_price: string
  exit_signal_id: string | null; exit_bar_end: string | null; exit_trading_day: string | null; exit_reference_price: string | null
  status: 'OPEN' | 'CLOSED' | 'ROLLOVER_INTERRUPTED' | 'DATA_INTERRUPTED'; holding_bars: number; reference_return_pct: string | null
  mark_bar_end: string | null; mark_reference_price: string | null; mark_change_pct: string | null
  interrupted_at: string | null; interruption_reason?: 'PRICE_UNAVAILABLE' | 'NONPOSITIVE_CLOSE' | null; interruption_trading_day?: string | null; initial: boolean
}
export interface SubingCoverageInterval { since: string; through: string; status: 'WARMING' | 'INDICATOR_READY_CROSS_UNEVALUABLE' | 'CROSS_EVALUATED' | 'PRICE_UNAVAILABLE' | 'NONPOSITIVE_CLOSE'; physical_contract: string; segment_id: string; calculation_segment_id: string | null }
export interface SubingQualityInterruption { bar_end: string; trading_day: string; physical_contract: string; segment_id: string; classification: 'PRICE_UNAVAILABLE' | 'NONPOSITIVE_CLOSE'; classification_version: 'rqdata-d1-zero-ohl-v1' | 'rqdata-d1-nonpositive-close-v1'; request_sha256: string; response_sha256: string }
export interface SubingQualityChartBar { bar_end: string; trading_day: string; open: string; high: string; low: string; close: string; volume: string; turnover: string | null; open_interest: string | null; physical_contract: string; segment_id: string; calculation_segment_id: string }
export interface SubingReferenceResponse {
  symbol: string; frequency: '15m' | '30m' | '60m' | '1d'; series_kind: 'actual_dominant'; formula_version: 'subing_ths_15m_v3' | 'subing_ths_30m_v1' | 'subing_ths_60m_v1' | 'subing_ths_1d_v1'
  reference_model_version: 'subing_reference_reverse_close_v1' | 'subing_reference_reverse_close_quality_segment_v2'; as_of: string; performance_since: string; performance_through: string
  reference_cutoff: string; input_snapshot_hash: string; executable: false; auto_order: false; source: 'historical_replay'; research_status: 'ready' | 'warming' | 'WARMING' | 'INDICATOR_READY_CROSS_UNEVALUABLE' | 'CROSS_EVALUATED'
  storage_mode?: 'persisted'
  summary: { closed_count: number; win_count: number; loss_count: number; flat_count: number; open_count: number; interrupted_count: number; rollover_interrupted_count?: number; data_interrupted_count?: number; initial_count: number; win_rate_pct: string | null; mean_return_pct: string | null; sum_return_percentage_points: string }
  signals: SubingReferenceSignal[]; indicators: SubingReferenceIndicator[]; items: SubingReferenceTrade[]; next_before: string | null
  quality_policy_version?: 'subing-d1-quality-segment-v1'; coverage_intervals?: SubingCoverageInterval[]; quality_interruptions?: SubingQualityInterruption[]; quality_chart_bars?: SubingQualityChartBar[]
}
export interface SubingReferenceIndicator extends Omit<KlineReferenceIndicator, 'calculation_segment_id'> { calculation_segment_id?: string }
export interface SubingReferenceQuery { frequency?: SubingReferenceResponse['frequency']; since?: string; through?: string; as_of?: string; before?: string; limit?: number }
