export interface ReviewSourceTrade {
  id: number
  source_type: 'backtest_trade'
  source_id: number
  review_id?: number | null
  reviewed: boolean
  report_id: number
  trade_id?: number
  trade_no?: string
  symbol: string
  contract: string
  period?: string | null
  entry_interval?: string | null
  direction: 'long' | 'short'
  entry_signal_time?: string | null
  open_time: string
  close_time: string
  entry_time?: string
  exit_time?: string
  open_price: number
  close_price: number
  volume: number
  net_pnl: number
  commission: number
  slippage: number
  holding_bars: number
  hold_bars?: number
  entry_reason: string
  exit_reason: string
}

export interface ReviewNote {
  id: number
  source_type: string
  review_object_type?: 'backtest_trade' | 'manual_trade' | string
  source_id?: number | null
  report_id?: number | null
  trade_id?: number | null
  trade_no?: string | null
  symbol?: string | null
  contract?: string | null
  period?: string | null
  entry_interval?: string | null
  direction?: 'long' | 'short' | null
  strategy_name?: string | null
  strategy_version?: string | null
  open_time?: string | null
  close_time?: string | null
  entry_time?: string | null
  exit_time?: string | null
  open_price?: number | null
  close_price?: number | null
  volume?: number | null
  net_pnl?: number | null
  hold_bars?: number | null
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

export interface ReviewFormalLineage {
  schema_version: 'review_source_lineage_v1'
  source_type: string
  source_id: number
  quality_policy?: string | null
  primary: {
    profile_id?: string | null
    market_data_file_id: number
    instrument_symbol: string
    contract_code: string
    period: string
    data_version?: string | null
    provider: string
    data_role: 'primary'
    quality_status: 'passed'
  }
  bar: {
    bar_start: string
    bar_end: string
    trigger_price?: number | null
    confirmation_mode?: string | null
  }
}

export interface ReviewBarsResponse {
  lineage: ReviewFormalLineage
  bars: BarData[]
}
import type { BarData } from './market'
