import type { CanonicalDatasetKey, CanonicalInputIdentity } from './backtest'

/** 复盘来源交易（回测成交明细） */
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

/** 单笔复盘笔记（含标签、截图与 AI 摘要） */
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

/** 复盘标签字典项 */
export interface ReviewTag {
  id: number
  tag_type: 'mistake' | 'market_phase' | 'entry_rule' | 'exit_rule' | 'emotion'
  name: string
  description?: string | null
  sort_order: number
  is_active: boolean
}

/** 更新复盘笔记的请求体 */
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

/** 复盘统计汇总（标签分布、规则有效性等） */
export interface ReviewStats {
  total_reviews: number
  mistake_tags: Array<{ name: string; count: number }>
  rule_effectiveness: Array<{ name: string; count: number; net_pnl: number; win_rate: number }>
  market_phase: Array<{ name: string; count: number; net_pnl: number; win_rate: number }>
  system_compliance: Array<{ name: string; count: number; net_pnl: number }>
}

/** Canonical historical review lineage with a persisted exact consumer input. */
export interface ReviewCanonicalLineage {
  schema_version: 'review_canonical_lineage_v1'
  source_type: string
  source_id: number
  strategy_version?: string | null
  input_digest: string
  dataset_keys: CanonicalDatasetKey[]
  manifest_digests: string[]
  window: { start: string; end: string }
  source_window: { start: string | null; end: string | null }
  input_identity: CanonicalInputIdentity
  auxiliary_input_identities?: Record<string, CanonicalInputIdentity>
}

/** Legacy live-observation lineage; it must not be displayed as canonical history. */
export interface ReviewObservationLineage {
  schema_version: 'review_source_lineage_v1'
  source_type: string
  source_id: number
  source_snapshot_schema_version?: string | null
  source_mode?: string | null
  bar?: {
    bar_start?: string | null
    bar_end?: string | null
    confirmation_mode?: string | null
  } | null
}

/** Backend-supported review lineage variants, discriminated by schema_version. */
export type ReviewFormalLineage = ReviewCanonicalLineage | ReviewObservationLineage

/** 复盘页 K 线响应（含 lineage） */
export interface ReviewBarsResponse {
  lineage: ReviewFormalLineage
  bars: BarData[]
}
import type { BarData } from './market'
