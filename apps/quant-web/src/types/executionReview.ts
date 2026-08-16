import type { CanonicalBarDto } from '@/types/market'

export type DecimalValue = string
export type ExecutionReviewState = 'pending_decision' | 'open' | 'pending_review' | 'done'
export type Direction = 'LONG' | 'SHORT'
export type ExecutionReviewFrequency = '5m' | '15m'
export type ReconstructionMode = 'signal' | 'full'
export type ReconstructionStatus = 'READY' | 'UNAVAILABLE'
export type ReconstructionReason =
  | 'MARKET_HISTORY_NOT_READY'
  | 'MARKET_IDENTITY_CONFLICT'
  | 'MARKET_PARTITION_UNAVAILABLE'
export type DecisionDisposition = 'EXECUTED' | 'NOT_EXECUTED'
export type ExecutionType = 'OPEN' | 'ADD' | 'REDUCE' | 'CLOSE'
export type ManualExecutionType = Exclude<ExecutionType, 'OPEN'>

export interface ReviewItem {
  item_kind: 'decision' | 'episode'
  state: ExecutionReviewState
  event_id: number
  decision_id: number | null
  episode_id: number | null
  symbol: string
  contract: string
  direction: Direction
  trading_day: string
}

export interface ReviewItemsResponse { items: ReviewItem[] }

export interface EventState {
  event_id: number
  state: ExecutionReviewState
  decision_id: number | null
  episode_id: number | null
}

export interface EventStatesResponse { items: EventState[] }

export interface EventContext {
  id: number
  rule_code: string
  symbol: string
  contract: string
  trading_day: string
  frequency: ExecutionReviewFrequency
  bar_end: string
  result_codes: Array<'buy' | 'sell'>
  lower_tf_confirmation: boolean
  detected_at: string
  notification_attempted_at: string | null
}

export interface Decision {
  id: number
  alert_event_id: number
  disposition: DecisionDisposition
  first_viewed_at: string | null
  decided_at: string
  primary_not_execute_reason: string | null
  secondary_not_execute_reasons: string[]
  note: string | null
  execution_reason_tags: string[]
  planned_stop_price: DecimalValue | null
  stop_basis: string | null
}

export interface Episode {
  id: number
  origin_decision_id: number
  symbol: string
  contract: string
  direction: Direction
  opened_at: string
  closed_at: string | null
  close_reason: 'EXECUTION_NET_ZERO' | 'DOMINANT_ROLL' | null
  roll_reference_exit_price: DecimalValue | null
  roll_reference_bar_end: string | null
  contract_multiplier_snapshot: DecimalValue | null
  multiplier_policy_id: string | null
}

export interface Execution {
  id: number
  episode_id: number
  trigger_decision_id: number | null
  sequence_no: number
  execution_type: ExecutionType
  executed_at: string
  price: DecimalValue
  quantity: number
  note: string | null
}

export interface Review {
  id: number
  episode_id: number
  signal_execution_adherence: string
  entry_tags: string[]
  holding_tags: string[]
  exit_tags: string[]
  market_context_tags: string[]
  psychology_tags: string[]
  summary: string | null
  submitted_at: string
  updated_at: string
}

export interface Position {
  remaining_quantity: number
  average_cost: DecimalValue | null
  realized_points: DecimalValue
  estimated_gross_pnl: DecimalValue | null
}

export interface ExecutedResponse {
  decision: Decision
  episode: Episode
  execution: Execution
  position: Position
}

export interface ExecutionResponse {
  episode: Episode
  execution: Execution
  position: Position
}

export interface TimelineResponse {
  episode: Episode
  executions: Execution[]
  position: Position
}

export interface DispositionCorrectionResponse {
  decision: Decision
  episode: Episode | null
  execution: Execution | null
  position: Position | null
}

export interface EpisodeDetailResponse {
  episode: Episode
  origin_event: EventContext
  decisions: Decision[]
  executions: Execution[]
  review: Review | null
  position: Position
}

export interface ReconstructionSegment {
  contract: string
  start_trading_day: string
  end_trading_day: string
}

export interface ReconstructionWindow {
  start_trading_day: string
  end_trading_day: string
  bar_end_cutoff: string | null
}

export interface EventReconstructionResponse {
  status: ReconstructionStatus
  reason: ReconstructionReason | null
  mode: ReconstructionMode
  post_hoc_reconstruction: boolean
  event: EventContext
  segment: ReconstructionSegment | null
  window: ReconstructionWindow | null
  bars_5m: CanonicalBarDto[]
  bars_15m: CanonicalBarDto[]
}

export interface OpportunityStats {
  eligible_events: number
  processed_events: number
  pending_events: number
  executed_decisions: number
  not_executed_decisions: number
  decision_completion_rate: DecimalValue | null
  execution_rate: DecimalValue | null
  primary_reason_counts: Record<string, number>
}

export interface ExecutionReviewStatsResponse {
  opportunities: OpportunityStats
  episode_states: {
    open_episodes: number
    pending_review_episodes: number
    done_episodes: number
  }
  review_issue_top: {
    entry: Record<string, number>
    holding: Record<string, number>
    exit_risk: Record<string, number>
    psychology: Record<string, number>
  }
}

export interface ReviewItemFilters {
  state: ExecutionReviewState
  symbol?: string
  direction?: Direction
  frequency?: ExecutionReviewFrequency
  start_trading_day?: string
  end_trading_day?: string
}

export interface StatsFilters {
  trading_day_from?: string
  trading_day_to?: string
  symbol?: string
  direction?: Direction
  frequency?: ExecutionReviewFrequency
}

export interface NotExecutedRequest {
  primary_reason: string
  secondary_reasons: string[]
  first_viewed_at?: string | null
  decided_at?: string | null
  note?: string | null
}

export interface ExecutedRequest {
  executed_at: string
  price: DecimalValue
  quantity: number
  execution_reason_tags: string[]
  first_viewed_at?: string | null
  decided_at?: string | null
  planned_stop_price?: DecimalValue | null
  stop_basis?: string | null
  note?: string | null
}

export interface ExecutionCreateRequest {
  execution_type: ManualExecutionType
  executed_at: string
  price: DecimalValue
  quantity: number
  note?: string | null
}

export interface ExecutionUpdateRequest {
  executed_at: string
  price: DecimalValue
  note?: string | null
}

export interface TimelineExecutionRequest {
  execution_id?: number | null
  execution_type: ExecutionType
  executed_at: string
  price: DecimalValue
  quantity: number
  note?: string | null
}

export interface TimelineReplaceRequest { items: TimelineExecutionRequest[] }

export interface DecisionUpdateRequest {
  first_viewed_at: string | null
  decided_at: string
  primary_not_execute_reason: string | null
  secondary_not_execute_reasons: string[]
  note: string | null
  execution_reason_tags: string[]
  planned_stop_price: DecimalValue | null
  stop_basis: string | null
}

export interface DispositionCorrectionRequest {
  target_disposition: DecisionDisposition
  primary_reason?: string | null
  secondary_reasons?: string[]
  execution_reason_tags?: string[]
  executed_at?: string | null
  price?: DecimalValue | null
  quantity?: number | null
  first_viewed_at?: string | null
  decided_at?: string | null
  planned_stop_price?: DecimalValue | null
  stop_basis?: string | null
  note?: string | null
}

export interface ReviewRequest {
  signal_execution_adherence: string
  entry_tags: string[]
  holding_tags: string[]
  exit_tags: string[]
  market_context_tags: string[]
  psychology_tags: string[]
  summary?: string | null
}
