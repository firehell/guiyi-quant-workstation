/** Display facts emitted by the existing reference projector, never account fills. */
export interface HistoricalChartAction {
  action_id: string; reference_trade_id: string; signal_id: string
  role: 'BUILD' | 'CLEAR'; side: 'LONG' | 'SHORT'
  bar_end: string; trading_day: string; physical_contract: string
  segment_id: string; calculation_segment_id: string
  reference_price: string; return_pct: string | null
  status: 'OPEN' | 'CLOSED' | 'ROLLOVER_INTERRUPTED' | 'DATA_INTERRUPTED'
  recording_mode: 'historical_replay'
}
