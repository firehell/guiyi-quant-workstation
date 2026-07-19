/** C5-06A Review foundation context — display-only, no strategy computation. */

export type FoundationFieldStatus = 'available' | 'unavailable' | 'warning'

export type ReviewSkipStatus =
  | 'SKIPPED_BY_FROZEN_HARD_REJECT'
  | 'none'
  | string

export type CandidateStatusValue =
  | 'validated_research_candidate'
  | 'rejected_research_candidate'
  | 'oos_hard_rejected'
  | string

export type LineageDisplayStatus = 'ready' | 'unavailable' | 'warning'

export interface FoundationField<T = string> {
  status: FoundationFieldStatus
  value: T | null
  reason?: string | null
}

export interface ReviewFoundationContext {
  strategy_code: FoundationField
  strategy_version: FoundationField
  indicator_policy_status: FoundationField
  indicator_policy_summary: FoundationField
  profile_id: FoundationField
  binding_snapshot_present: FoundationField<'yes' | 'no'>
  signal_bar: FoundationField
  next_bar_fill: FoundationField
  cost_model: FoundationField
  execution_timing: FoundationField
  oos_window_id: FoundationField
  walk_forward_fold_id: FoundationField
  candidate_status: FoundationField<CandidateStatusValue>
  hard_reject_reason: FoundationField
  review_skip_status: FoundationField<ReviewSkipStatus>
  lineage_status: FoundationField<LineageDisplayStatus>
}

export interface ReviewFoundationReportLike {
  strategy_code?: string | null
  strategy_version?: string | null
  profile_id?: string | null
  binding_snapshot?: Record<string, unknown> | null
  indicator_policy_status?: string | null
  indicator_policy_snapshot?: Record<string, unknown> | null
  indicator_policy_reason?: string | null
  oos_window_id?: string | null
  walk_forward_fold_id?: string | null
  candidate_status?: string | null
  hard_reject_reason?: string | null
  review_skip_status?: string | null
  summary?: Record<string, unknown> | null
}

export interface ReviewFoundationTradeLike {
  entry_signal_time?: string | null
  open_time?: string | null
  exit_signal_time?: string | null
  close_time?: string | null
}

export interface ReviewFoundationLineageLike {
  primary?: {
    profile_id?: string | null
    market_data_file_id?: number
    quality_status?: string
  }
  bar?: {
    bar_start?: string
    bar_end?: string
  }
}

export interface ReviewFoundationInput {
  report?: ReviewFoundationReportLike | null
  trade?: ReviewFoundationTradeLike | null
  lineage?: ReviewFoundationLineageLike | null
  lineage_error?: string | null
  lineage_status_hint?: LineageDisplayStatus | null
}

export interface ReviewDeepLinkQuery {
  review_id: number | null
  trade_id: number | null
  report_id: number | null
}
