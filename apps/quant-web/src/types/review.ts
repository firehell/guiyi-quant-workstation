import type { CanonicalDatasetKey, CanonicalInputIdentity } from './canonical'
import type { BarData } from './market'

export type ReviewSourceType = 'strategy_signal' | 'signal_event' | 'signal_decision' | 'manual_trade' | string

/** 单笔复盘笔记；来源仅使用独立 source_type/source_id 合同。 */
export interface ReviewNote {
  id: number
  source_type: ReviewSourceType
  source_id?: number | null
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

export type ReviewFormalLineage = ReviewCanonicalLineage | ReviewObservationLineage

export interface ReviewBarsResponse {
  lineage: ReviewFormalLineage
  bars: BarData[]
}
