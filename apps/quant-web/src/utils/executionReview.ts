import type {
  Episode,
  DispositionCorrectionRequest,
  Execution,
  ExecutionReviewState,
  ManualExecutionType,
  ReconstructionMode,
  ReviewItemFilters,
  ReviewRequest,
  StatsFilters,
} from '@/types/executionReview'

export const NOT_EXECUTED_REASONS = [
  'WORK_MISSED', 'TOO_LATE', 'PRICE_ACTION_REJECTED', 'POOR_LOCATION',
  'POOR_RISK_REWARD', 'EXISTING_SAME_DIRECTION_TRADE',
  'EXISTING_OPPOSITE_DIRECTION_TRADE', 'RISK_CAPACITY', 'HESITATION', 'OTHER',
] as const

export const EXECUTION_REASONS = [
  'HIGHER_TIMEFRAME_ALIGNED', 'KEY_LEVEL_BREAKOUT', 'PULLBACK_RECONFIRMED',
  'VOLUME_CONFIRMED', 'MULTITF_STRUCTURE_ALIGNED', 'LOCATION_ACCEPTABLE', 'OTHER',
] as const

export const STOP_BASES = ['EMA', 'PREVIOUS_BAR_EXTREME', 'RANGE_BOUNDARY', 'MOVE_ORIGIN', 'OTHER'] as const
export const MANUAL_EXECUTION_TYPES = ['ADD', 'REDUCE', 'CLOSE'] as const
export const SIGNAL_ADHERENCE = ['ALIGNED', 'DEVIATED'] as const
export const ENTRY_TAGS = ['REASONABLE', 'TOO_EARLY', 'TOO_LATE', 'CHASED', 'BREAKOUT_CONFIRMATION_INSUFFICIENT'] as const
export const HOLDING_TAGS = ['NORMAL', 'COULD_NOT_HOLD', 'REDUCED_TOO_EARLY', 'UNPLANNED_ADD', 'MISSED_VALID_ADD'] as const
export const EXIT_TAGS = ['NORMAL', 'STOP_DELAYED', 'STOP_MOVED', 'PROFIT_TO_LOSS', 'EXIT_TOO_EARLY', 'MISSED_PROFIT_REDUCTION'] as const
export const MARKET_CONTEXT_TAGS = ['WITH_HIGHER_TIMEFRAME', 'AGAINST_HIGHER_TIMEFRAME', 'VALID_BREAKOUT', 'FALSE_BREAKOUT', 'RANGE', 'TREND'] as const
export const PSYCHOLOGY_TAGS = ['NONE', 'HESITATION', 'LOSS_AVERSION', 'FOMO', 'REVENGE', 'PREDICTION_BIAS', 'OVERTRADING'] as const

export function executionReviewActionLabel(state: ExecutionReviewState): string {
  return {
    pending_decision: '记录执行',
    open: '查看交易',
    pending_review: '去复盘',
    done: '查看记录',
  }[state]
}

export function initialReconstructionMode(): ReconstructionMode {
  return 'signal'
}

export interface ReviewFilterDraft {
  symbol: string
  direction: ReviewItemFilters['direction'] | null
  frequency: ReviewItemFilters['frequency'] | null
  start_trading_day: string
  end_trading_day: string
}

export function buildReviewItemFilters(
  state: ExecutionReviewState,
  filters: ReviewFilterDraft,
): ReviewItemFilters {
  const result: ReviewItemFilters = {
    state,
    symbol: filters.symbol.trim() || undefined,
    direction: filters.direction || undefined,
    frequency: filters.frequency || undefined,
  }
  if (state === 'done' && filters.start_trading_day) result.start_trading_day = filters.start_trading_day
  if (state === 'done' && filters.end_trading_day) result.end_trading_day = filters.end_trading_day
  return result
}

export function buildStatsFilters(
  state: ExecutionReviewState,
  filters: ReviewFilterDraft,
): StatsFilters {
  const result: StatsFilters = {
    symbol: filters.symbol.trim() || undefined,
    direction: filters.direction || undefined,
    frequency: filters.frequency || undefined,
  }
  if (state === 'done' && filters.start_trading_day) {
    result.trading_day_from = filters.start_trading_day
  }
  if (state === 'done' && filters.end_trading_day) {
    result.trading_day_to = filters.end_trading_day
  }
  return result
}

export interface NotExecutedDraft {
  primary_reason: string
  secondary_reasons: string[]
  note: string
}

export interface ExecutedDraft {
  executed_at: string
  price: string
  quantity: number | null
  execution_reason_tags: string[]
  planned_stop_price: string | null
  stop_basis: string | null
  note: string
}

export interface ExecutedDispositionCorrectionFacts {
  executed_at: string
  price: string
  quantity: number
  execution_reason_tags: string[]
  planned_stop_price: string | null
  stop_basis: string | null
  note: string | null
}

export function buildExecutedDispositionCorrectionRequest(
  facts: ExecutedDispositionCorrectionFacts,
): DispositionCorrectionRequest {
  return {
    target_disposition: 'EXECUTED',
    executed_at: facts.executed_at,
    price: facts.price,
    quantity: facts.quantity,
    execution_reason_tags: facts.execution_reason_tags,
    planned_stop_price: facts.planned_stop_price,
    stop_basis: facts.stop_basis,
    note: facts.note,
  }
}

export function validateNotExecutedDraft(draft: NotExecutedDraft): string[] {
  return draft.primary_reason ? [] : ['请选择主要原因']
}

export function validateExecutedDraft(draft: ExecutedDraft): string[] {
  const errors: string[] = []
  if (!draft.executed_at) errors.push('请填写成交时间')
  if (!isPositiveDecimal(draft.price)) errors.push('请填写有效成交价')
  if (!Number.isInteger(draft.quantity) || (draft.quantity ?? 0) <= 0) errors.push('请填写有效手数')
  if (draft.execution_reason_tags.length === 0) errors.push('请至少选择一个执行原因')
  if (draft.planned_stop_price && !draft.stop_basis) errors.push('请选择止损依据')
  return errors
}

export function defaultExecutionQuantity(
  executionType: ManualExecutionType,
  remainingQuantity: number,
  currentQuantity: number | null,
): number | null {
  return executionType === 'CLOSE' ? remainingQuantity : currentQuantity
}

export function applyNeutralSelection(
  current: string[],
  selected: string,
  neutral: string,
): string[] {
  if (selected === neutral) return [neutral]
  const withoutNeutral = current.filter((value) => value !== neutral)
  return withoutNeutral.includes(selected)
    ? withoutNeutral.filter((value) => value !== selected)
    : [...withoutNeutral, selected]
}

export function validateReviewDraft(draft: ReviewRequest): string[] {
  const missing: string[] = []
  if (!draft.signal_execution_adherence) missing.push('请选择信号执行一致性')
  if (draft.entry_tags.length === 0) missing.push('请选择 Entry 标签')
  if (draft.holding_tags.length === 0) missing.push('请选择 Holding 标签')
  if (draft.exit_tags.length === 0) missing.push('请选择 Exit / Risk 标签')
  if (draft.market_context_tags.length === 0) missing.push('请选择 Market Context 标签')
  if (draft.psychology_tags.length === 0) missing.push('请选择 Psychology 标签')
  return missing
}

export function timelineForDisplay<T extends Pick<Execution, 'execution_type'>>(
  executions: T[],
  _episode: Pick<Episode, 'close_reason' | 'roll_reference_exit_price' | 'roll_reference_bar_end'>,
): T[] {
  return executions
}

export function isPositiveDecimal(value: string): boolean {
  if (!/^\d+(?:\.\d+)?$/.test(value)) return false
  const normalized = value.replace(/^0+/, '').replace(/^\./, '0.')
  return normalized !== '' && !/^0(?:\.0+)?$/.test(normalized)
}
