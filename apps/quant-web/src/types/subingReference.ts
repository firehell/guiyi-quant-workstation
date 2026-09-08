export interface SubingReferenceSignal {
  signal_id: string; bar_end: string; trading_day: string; physical_contract: string; segment_id: string
  direction: 'buy' | 'sell'; reference_price: string
  action: 'OPEN_LONG' | 'OPEN_SHORT' | 'REVERSE_TO_LONG' | 'REVERSE_TO_SHORT' | 'SAME_DIRECTION'
  entry_trade_id: string | null; closed_trade_id: string | null; closed_return_pct: string | null
}
export interface SubingReferenceTrade {
  reference_trade_id: string; side: 'LONG' | 'SHORT'; physical_contract: string; segment_id: string
  entry_signal_id: string; entry_bar_end: string; entry_trading_day: string; entry_reference_price: string
  exit_signal_id: string | null; exit_bar_end: string | null; exit_trading_day: string | null; exit_reference_price: string | null
  status: 'OPEN' | 'CLOSED' | 'ROLLOVER_INTERRUPTED'; holding_bars: number; reference_return_pct: string | null
  mark_bar_end: string | null; mark_reference_price: string | null; mark_change_pct: string | null
  interrupted_at: string | null; initial: boolean
}
export interface SubingReferenceResponse {
  symbol: string; frequency: '15m'; series_kind: 'actual_dominant'; formula_version: 'subing_ths_15m_v3'
  reference_model_version: 'subing_reference_reverse_close_v1'; as_of: string; performance_since: string; performance_through: string
  reference_cutoff: string; input_snapshot_hash: string; executable: false; auto_order: false; source: 'historical_replay'
  summary: { closed_count: number; win_count: number; loss_count: number; flat_count: number; open_count: number; interrupted_count: number; initial_count: number; win_rate_pct: string | null; mean_return_pct: string | null; sum_return_percentage_points: string }
  signals: SubingReferenceSignal[]; items: SubingReferenceTrade[]; next_before: string | null
}
export interface SubingReferenceQuery { since?: string; through?: string; as_of?: string; before?: string; limit?: number }
