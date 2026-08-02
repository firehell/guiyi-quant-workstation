import type { CanonicalInputIdentity } from '@/types/backtest'
import { presentCanonicalInputIdentity } from './dataCoreV2Consumer.ts'

type ReportLike = {
  id: number
  report_no: string
  input_identity?: CanonicalInputIdentity | null
  candidate_status?: string | null
  hard_reject_reason?: string | null
  summary?: Record<string, unknown>
}

type ValidationObservationLike = {
  available: boolean
  context?: {
    candidate?: Record<string, unknown>
    candidate_status?: string | null
    hard_reject_reason?: string | null
    oos?: { window_id?: string | null; gate?: string | null }
  } | null
  error_type?: string | null
  error_message?: string | null
} | null

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function buildBacktestReportPresentation(
  report: ReportLike,
  observation: ValidationObservationLike,
) {
  const context = observation?.available ? observation.context : null
  const candidate = context?.candidate || {}
  const metadata =
    report.summary?.report_metadata &&
    typeof report.summary.report_metadata === 'object' &&
    !Array.isArray(report.summary.report_metadata)
      ? (report.summary.report_metadata as Record<string, unknown>)
      : {}
  const trustAudit =
    stringValue(candidate.candidate_trust_audit) ||
    stringValue(candidate.report14_trust_audit) ||
    'unavailable'
  const inputIdentity = presentCanonicalInputIdentity(report.input_identity)

  return {
    identity: `${report.report_no} · report #${report.id}`,
    canonicalInput: inputIdentity,
    costModel: stringValue(metadata.cost_model_version) || 'unavailable',
    trustAudit,
    validationEvidence: observation?.available
      ? 'available'
      : observation?.error_type || observation?.error_message || 'unavailable',
    candidateStatus: context?.candidate_status || report.candidate_status || 'unavailable',
    oosWindow: context?.oos?.window_id || 'unavailable',
    oosGate: context?.oos?.gate || 'unavailable',
    hardReject: context?.hard_reject_reason || report.hard_reject_reason || 'none recorded',
    boundary: '可信审计仅说明报告口径与证据可核对，不等于策略有效或可盈利。',
  }
}
