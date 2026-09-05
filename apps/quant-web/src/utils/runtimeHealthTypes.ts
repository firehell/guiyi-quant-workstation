import { ALERT_RULE_CODES } from './alertRules.ts'

export type RuntimeAlertRuleErrorType = null | 'evaluation_input_invalid' | 'evaluation_warming_up' | 'evaluation_failed'

export interface RuntimeAlertRuleStatus {
  last_evaluated_bar_at: string | null
  last_event_at: string | null
  last_failure_at: string | null
  error_type: RuntimeAlertRuleErrorType
}

export interface RuntimeAlertProjection {
  status: string
  enabled_rule_count: number
  rule_status: Record<typeof ALERT_RULE_CODES.HTDY | typeof ALERT_RULE_CODES.SUBING_THS, RuntimeAlertRuleStatus>
}

const RULE_KEYS = [ALERT_RULE_CODES.HTDY, ALERT_RULE_CODES.SUBING_THS] as const
const STATUS_KEYS = ['last_evaluated_bar_at', 'last_event_at', 'last_failure_at', 'error_type'] as const
const ERROR_TYPES = new Set<RuntimeAlertRuleErrorType>([null, 'evaluation_input_invalid', 'evaluation_warming_up', 'evaluation_failed'])

/** Strictly projects Alert Runtime v6; a global heartbeat never substitutes a Rule evaluation. */
export function normalizeRuntimeAlertProjection(value: unknown): RuntimeAlertProjection {
  if (!isRecord(value) || typeof value.status !== 'string' || !isNonNegativeInteger(value.enabled_rule_count) || !isRecord(value.rule_status)) throw new Error('runtime alert projection is invalid')
  const keys = Object.keys(value.rule_status).sort()
  if (keys.length !== RULE_KEYS.length || keys.some((key, index) => key !== [...RULE_KEYS].sort()[index])) throw new Error('runtime rule keys are invalid')
  return {
    status: value.status,
    enabled_rule_count: value.enabled_rule_count,
    rule_status: {
      [ALERT_RULE_CODES.HTDY]: normalizeRuleStatus(value.rule_status[ALERT_RULE_CODES.HTDY]),
      [ALERT_RULE_CODES.SUBING_THS]: normalizeRuleStatus(value.rule_status[ALERT_RULE_CODES.SUBING_THS]),
    },
  }
}

function normalizeRuleStatus(value: unknown): RuntimeAlertRuleStatus {
  if (!isRecord(value) || Object.keys(value).length !== STATUS_KEYS.length || STATUS_KEYS.some((key) => !(key in value))) throw new Error('runtime rule status is invalid')
  for (const key of ['last_evaluated_bar_at', 'last_event_at', 'last_failure_at'] as const) {
    if (value[key] !== null && !isAwareIso(value[key])) throw new Error('runtime timestamp is invalid')
  }
  if (!ERROR_TYPES.has(value.error_type as RuntimeAlertRuleErrorType)) throw new Error('runtime error type is invalid')
  return value as unknown as RuntimeAlertRuleStatus
}

function isAwareIso(value: unknown): value is string {
  return typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}
