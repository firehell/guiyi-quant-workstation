import type {
  FoundationField,
  ReviewDeepLinkQuery,
  ReviewFoundationContext,
  ReviewFoundationInput,
  ReviewFoundationReportLike,
} from '../types/reviewFoundation.ts'

function unavailable<T = string>(reason: string): FoundationField<T> {
  return { status: 'unavailable', value: null, reason }
}

function available<T = string>(value: T): FoundationField<T> {
  return { status: 'available', value, reason: null }
}

function warning<T = string>(value: T | null, reason: string): FoundationField<T> {
  return { status: 'warning', value, reason }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function readString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  }
  return null
}

function compactJson(value: unknown): string | null {
  if (value == null) return null
  try {
    return JSON.stringify(value)
  } catch {
    return null
  }
}

function metadataOf(report: ReviewFoundationReportLike | null | undefined): Record<string, unknown> {
  const summary = asRecord(report?.summary)
  return asRecord(summary?.report_metadata) || {}
}

function passThrough(
  report: ReviewFoundationReportLike | null | undefined,
  key: keyof ReviewFoundationReportLike,
  metaKeys: string[] = [],
): string | null {
  const top = report?.[key]
  if (typeof top === 'string' && top.trim()) return top.trim()
  const meta = metadataOf(report)
  for (const metaKey of metaKeys) {
    const value = readString(meta[metaKey])
    if (value) return value
  }
  const summary = asRecord(report?.summary)
  if (summary) {
    for (const metaKey of [String(key), ...metaKeys]) {
      const value = readString(summary[metaKey])
      if (value) return value
    }
  }
  return null
}

/**
 * 构建仅用于展示的复盘基础上下文。
 * 缺失字段保持 unavailable，不虚构数据。
 */
export function buildReviewFoundationContext(input: ReviewFoundationInput = {}): ReviewFoundationContext {
  const report = input.report || null
  const trade = input.trade || null
  const lineage = input.lineage || null
  const meta = metadataOf(report)
  const validation = input.validation_context || null

  const strategyCode = readString(report?.strategy_code, meta.strategy_code)
  const strategyVersion = readString(report?.strategy_version, meta.strategy_version)
  const profileId = readString(report?.profile_id, lineage?.primary?.profile_id, meta.profile_id)

  const policyStatus = readString(report?.indicator_policy_status)
  const policySnapshot = report?.indicator_policy_snapshot
  const policyReason = readString(report?.indicator_policy_reason)
  let indicatorPolicyStatus: FoundationField
  let indicatorPolicySummary: FoundationField
  if (policyStatus === 'available' && policySnapshot) {
    const ids = Array.isArray(policySnapshot.formal_policy_ids)
      ? policySnapshot.formal_policy_ids.map(String).join(',')
      : readString(policySnapshot.schema_version) || 'snapshot'
    indicatorPolicyStatus = available(policyStatus)
    indicatorPolicySummary = available(ids)
  } else if (policyStatus === 'legacy_policy_unavailable') {
    indicatorPolicyStatus = warning(policyStatus, policyReason || 'legacy_policy_unavailable')
    indicatorPolicySummary = unavailable(policyReason || 'no indicator policy snapshot')
  } else if (policyStatus) {
    indicatorPolicyStatus = warning(policyStatus, policyReason || 'indicator policy not available')
    indicatorPolicySummary = unavailable(policyReason || 'indicator policy snapshot missing')
  } else {
    indicatorPolicyStatus = unavailable('indicator_policy_status missing')
    indicatorPolicySummary = unavailable('indicator_policy_snapshot missing')
  }

  const binding = report?.binding_snapshot
  const bindingPresent =
    binding && typeof binding === 'object' && Object.keys(binding).length > 0
      ? available<'yes' | 'no'>('yes')
      : unavailable<'yes' | 'no'>('binding_snapshot missing')

  const signalBar = readString(trade?.entry_signal_time)
  const fillTime = readString(trade?.open_time)
  const fillPolicy = readString(meta.fill_policy)
  const executionTiming = readString(meta.execution_timing)
  const executionTimingField = executionTiming
    ? available(executionTiming)
    : unavailable('execution_timing missing')
  const nextBarFill = fillTime
    ? available(fillTime)
    : fillPolicy
      ? warning(fillPolicy, 'fill time missing; policy label only')
      : unavailable('next bar fill / fill_policy missing')

  const costModel = readString(meta.cost_model_version)

  const validationFolds = validation?.rolling_oos?.folds || []
  const oosWindow = readString(validation?.oos?.window_id) || passThrough(report, 'oos_window_id', ['oos_window_id'])
  const foldId = validation
    ? validationFolds.map((fold) => fold.fold_id).filter(Boolean).join(',') || null
    : passThrough(report, 'walk_forward_fold_id', ['walk_forward_fold_id'])
  const candidateStatus = readString(validation?.candidate_status) || passThrough(report, 'candidate_status', ['candidate_status', 'research_status'])
  const validationHardReject = [
    ...(validation?.oos?.hard_reject?.structural_reasons || []),
    ...(validation?.oos?.hard_reject?.numeric_reasons || []),
  ].join('; ')
  const hardReject = readString(validation?.hard_reject_reason, validationHardReject) || passThrough(report, 'hard_reject_reason', ['hard_reject_reason'])
  const skipStatus = readString(validation?.review_skip_status) || passThrough(report, 'review_skip_status', ['review_skip_status'])
  const oosGate = readString(validation?.oos?.gate)
  const oosMetrics = compactJson(validation?.oos?.metrics)
  const rollingProposal = readString(validation?.rolling_oos?.proposal_label)
  const foldSummary = validation
    ? validationFolds
        .map((fold) => `${fold.fold_id}:${fold.trade_count ?? '-'} trades`)
        .join(' | ') || null
    : null
  const costSensitivity = validation
    ? validationFolds
        .map((fold) => `${fold.fold_id}:${fold.overlay_scenario_count ?? 0} overlays`)
        .join(' | ') || null
    : null
  const evidenceHash = readString(validation?.context_hash)

  let lineageField: FoundationField<'ready' | 'unavailable' | 'warning'>
  if (input.lineage_error) {
    lineageField = unavailable(input.lineage_error)
  } else if (input.lineage_status_hint === 'warning') {
    lineageField = warning('warning', 'lineage warning')
  } else if (input.lineage_status_hint === 'unavailable') {
    lineageField = unavailable('lineage unavailable')
  } else if (lineage?.primary?.market_data_file_id) {
    lineageField = available('ready')
  } else if (input.lineage_status_hint === 'ready') {
    lineageField = available('ready')
  } else {
    lineageField = unavailable('lineage unavailable')
  }

  return {
    strategy_code: strategyCode ? available(strategyCode) : unavailable('strategy_code missing'),
    strategy_version: strategyVersion ? available(strategyVersion) : unavailable('strategy_version missing'),
    indicator_policy_status: indicatorPolicyStatus,
    indicator_policy_summary: indicatorPolicySummary,
    profile_id: profileId ? available(profileId) : unavailable('profile_id missing'),
    binding_snapshot_present: bindingPresent,
    signal_bar: signalBar ? available(signalBar) : unavailable('entry_signal_time missing'),
    next_bar_fill: nextBarFill,
    cost_model: costModel ? available(costModel) : unavailable('cost_model_version missing'),
    execution_timing: executionTimingField,
    oos_window_id: oosWindow ? available(oosWindow) : unavailable('oos_window_id missing'),
    walk_forward_fold_id: foldId ? available(foldId) : unavailable('walk_forward_fold_id missing'),
    candidate_status: candidateStatus ? available(candidateStatus) : unavailable('candidate_status missing'),
    hard_reject_reason: hardReject ? available(hardReject) : unavailable('hard_reject_reason missing'),
    review_skip_status: skipStatus ? available(skipStatus) : unavailable('review_skip_status missing'),
    oos_gate: oosGate
      ? available(oosGate)
      : unavailable(input.validation_error || 'validation context missing'),
    oos_metrics: oosMetrics
      ? available(oosMetrics)
      : unavailable(input.validation_error || 'validation context missing'),
    rolling_proposal: rollingProposal
      ? available(rollingProposal)
      : unavailable(input.validation_error || 'validation context missing'),
    fold_summary: foldSummary
      ? available(foldSummary)
      : unavailable(input.validation_error || 'validation context missing'),
    cost_sensitivity: costSensitivity
      ? available(costSensitivity)
      : unavailable(input.validation_error || 'validation context missing'),
    evidence_hash: evidenceHash
      ? available(evidenceHash)
      : unavailable(input.validation_error || 'validation context missing'),
    lineage_status: lineageField,
  }
}

export function reviewSourceIdentity(review: {
  source_type?: string | null
  source_id?: number | null
  report_id?: number | null
  trade_id?: number | null
}): string {
  const sourceType = review.source_type || 'unknown_source'
  if (sourceType === 'backtest_trade') {
    const parts = [sourceType]
    if (review.report_id) parts.push(`report #${review.report_id}`)
    if (review.trade_id || review.source_id) parts.push(`trade #${review.trade_id || review.source_id}`)
    if (parts.length === 1) parts.push('source unavailable')
    return parts.join(' · ')
  }
  if (review.source_id) return `${sourceType} #${review.source_id}`
  return `${sourceType} · source unavailable`
}

function numericQueryValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return Math.trunc(value)
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value.trim())
    if (Number.isFinite(parsed) && parsed > 0) return Math.trunc(parsed)
  }
  if (Array.isArray(value) && value.length > 0) return numericQueryValue(value[0])
  return null
}

/**
 * 解析复盘深链 query 参数，不虚构 id。
 */
export function parseReviewDeepLinkQuery(
  query: Record<string, unknown> | { [key: string]: unknown },
): ReviewDeepLinkQuery {
  return {
    review_id: numericQueryValue(query.review_id),
    trade_id: numericQueryValue(query.trade_id),
    report_id: numericQueryValue(query.report_id),
  }
}

/**
 * 将基础字段格式化为可读标签（含 unavailable / warning 原因）。
 */
export function foundationFieldLabel(field: FoundationField): string {
  if (field.status === 'unavailable') return `unavailable${field.reason ? ` (${field.reason})` : ''}`
  if (field.status === 'warning') {
    const base = field.value == null ? 'warning' : String(field.value)
    return field.reason ? `${base} — ${field.reason}` : base
  }
  return field.value == null ? '-' : String(field.value)
}
