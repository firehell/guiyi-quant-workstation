/** C5-06A 复盘基础上下文 — 仅展示用，不做策略计算 */

import type { BacktestValidationContext } from './backtestValidation'
import type { CanonicalInputIdentity } from './backtest'

/** 基础字段可用性状态 */
export type FoundationFieldStatus = 'available' | 'unavailable' | 'warning'

/** 复盘跳过状态（如 OOS 硬拒绝后冻结） */
export type ReviewSkipStatus =
  | 'SKIPPED_BY_FROZEN_HARD_REJECT'
  | 'none'
  | string

/** 研究候选状态 */
export type CandidateStatusValue =
  | 'validated_research_candidate'
  | 'rejected_research_candidate'
  | 'oos_hard_rejected'
  | string

/** 数据溯源展示状态 */
export type LineageDisplayStatus = 'ready' | 'unavailable' | 'warning'

/** 带状态与原因的展示字段 */
export interface FoundationField<T = string> {
  status: FoundationFieldStatus
  value: T | null
  reason?: string | null
}

/** 复盘页基础上下文（策略绑定、OOS、成本模型等只读展示） */
export interface ReviewFoundationContext {
  strategy_code: FoundationField
  strategy_version: FoundationField
  indicator_policy_status: FoundationField
  indicator_policy_summary: FoundationField
  canonical_input_identity: FoundationField
  canonical_input_digest: FoundationField
  signal_bar: FoundationField
  next_bar_fill: FoundationField
  cost_model: FoundationField
  execution_timing: FoundationField
  oos_window_id: FoundationField
  walk_forward_fold_id: FoundationField
  candidate_status: FoundationField<CandidateStatusValue>
  hard_reject_reason: FoundationField
  review_skip_status: FoundationField<ReviewSkipStatus>
  oos_gate: FoundationField
  oos_metrics: FoundationField
  rolling_proposal: FoundationField
  fold_summary: FoundationField
  cost_sensitivity: FoundationField
  evidence_hash: FoundationField
  lineage_status: FoundationField<LineageDisplayStatus>
}

/** 构建复盘基础上下文所需的报告字段子集 */
export interface ReviewFoundationReportLike {
  strategy_code?: string | null
  strategy_version?: string | null
  input_identity?: CanonicalInputIdentity | null
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

/** 构建复盘基础上下文所需的成交字段子集 */
export interface ReviewFoundationTradeLike {
  entry_signal_time?: string | null
  open_time?: string | null
  exit_signal_time?: string | null
  close_time?: string | null
}

/** 构建复盘基础上下文所需的 lineage 字段子集 */
export interface ReviewFoundationLineageLike {
  schema_version?: string
  input_identity?: CanonicalInputIdentity | null
  input_digest?: string | null
}

/** 复盘基础上下文组装输入 */
export interface ReviewFoundationInput {
  report?: ReviewFoundationReportLike | null
  trade?: ReviewFoundationTradeLike | null
  lineage?: ReviewFoundationLineageLike | null
  lineage_error?: string | null
  lineage_status_hint?: LineageDisplayStatus | null
  validation_context?: BacktestValidationContext | null
  validation_error?: string | null
}

/** 复盘页深链接 query 参数 */
export interface ReviewDeepLinkQuery {
  review_id: number | null
  trade_id: number | null
  report_id: number | null
}
