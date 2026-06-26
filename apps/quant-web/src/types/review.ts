export interface ReviewSourceTrade {
  id: number
  source_type: 'backtest_trade'
  source_id: number
  review_id?: number | null
  reviewed: boolean
  report_id: number
  symbol: string
  contract: string
  period?: string | null
  direction: 'long' | 'short'
  open_time: string
  close_time: string
  open_price: number
  close_price: number
  volume: number
  net_pnl: number
  commission: number
  slippage: number
  holding_bars: number
  entry_reason: string
  exit_reason: string
}

export interface ReviewNote {
  id: number
  source_type: string
  review_object_type?: 'backtest_trade' | 'manual_trade' | string
  source_id?: number | null
  symbol?: string | null
  contract?: string | null
  period?: string | null
  direction?: 'long' | 'short' | null
  strategy_name?: string | null
  strategy_version?: string | null
  open_time?: string | null
  close_time?: string | null
  open_price?: number | null
  close_price?: number | null
  volume?: number | null
  net_pnl?: number | null
  entry_reason?: string | null
  exit_reason?: string | null
  market_phase?: string | null
  is_system_compliant?: boolean | null
  mistake_tags: string[]
  setup_tags: string[]
  rule_tags: string[]
  emotion_tags: string[]
  execution_note?: string | null
  improvement_note?: string | null
  lesson?: string | null
  screenshot_path?: string | null
  screenshot_paths: string[]
  kline_focus_time?: string | null
  kline_window_start?: string | null
  kline_window_end?: string | null
  review_score?: number | null
  ai_summary?: string | null
  ai_status: string
  ai_model?: string | null
  ai_generated_at?: string | null
  extra: Record<string, unknown>
  source?: ReviewSourceTrade | null
}

export interface ReviewTag {
  id: number
  tag_type: 'mistake' | 'market_phase' | 'entry_rule' | 'exit_rule' | 'emotion'
  name: string
  description?: string | null
  sort_order: number
  is_active: boolean
}

export interface ReviewUpdateRequest {
  entry_reason?: string | null
  exit_reason?: string | null
  market_phase?: string | null
  is_system_compliant?: boolean | null
  mistake_tags?: string[]
  setup_tags?: string[]
  rule_tags?: string[]
  emotion_tags?: string[]
  execution_note?: string | null
  improvement_note?: string | null
  lesson?: string | null
  screenshot_path?: string | null
  screenshot_paths?: string[]
  review_score?: number | null
  ai_summary?: string | null
}

export interface ReviewStats {
  total_reviews: number
  mistake_tags: Array<{ name: string; count: number }>
  rule_effectiveness: Array<{ name: string; count: number; net_pnl: number; win_rate: number }>
  market_phase: Array<{ name: string; count: number; net_pnl: number; win_rate: number }>
  system_compliance: Array<{ name: string; count: number; net_pnl: number }>
}
