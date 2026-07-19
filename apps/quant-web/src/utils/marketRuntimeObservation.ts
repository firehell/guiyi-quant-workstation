import type {
  MarketDataMode,
  MarketRuntimeObservationContext,
  MarketRuntimeObservationInput,
  ObservationField,
} from '../types/marketRuntimeObservation.ts'

const SENSITIVE_KEY_RE =
  /^(file_path|file_paths|password|passwd|secret|token|api_key|apikey|credential|license|private_key)$/i

function unavailable<T = string>(reason: string): ObservationField<T> {
  return { status: 'unavailable', value: null, reason }
}

function available<T>(value: T): ObservationField<T> {
  return { status: 'available', value, reason: null }
}

function warning<T>(value: T | null, reason: string): ObservationField<T> {
  return { status: 'warning', value, reason }
}

function readString(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return null
}

function readNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/**
 * Build display-only observation context.
 * Never invents runtime facts; degraded/failed must not map to healthy.
 * Confirmed and partial counts stay separate (same-bar display must not double-count).
 */
export function buildMarketRuntimeObservation(
  input: MarketRuntimeObservationInput = {},
): MarketRuntimeObservationContext {
  const mode = input.data_mode === 'live' || input.data_mode === 'historical' ? input.data_mode : null
  const conflict =
    mode &&
    input.conflicting_data_mode &&
    (input.conflicting_data_mode === 'live' || input.conflicting_data_mode === 'historical') &&
    input.conflicting_data_mode !== mode

  const dataModeField: ObservationField<MarketDataMode> = !mode
    ? unavailable('data_mode missing')
    : conflict
      ? warning(mode, 'historical/live must not silently mix')
      : available(mode)

  const sourceBadge = mode
    ? conflict
      ? warning(mode, 'historical/live must not silently mix')
      : available(mode === 'live' ? 'live' : 'historical')
    : unavailable('source badge requires data_mode')

  const blocked = Array.isArray(input.target_blocked_reasons)
    ? input.target_blocked_reasons.filter(Boolean)
    : []
  const actual = readString(input.actual_contract)
  let actualField: ObservationField
  if (actual) {
    actualField = available(actual)
  } else if (blocked.length || (input.readiness_status && input.readiness_status !== 'ready')) {
    actualField = unavailable(blocked.join(',') || `readiness=${input.readiness_status}`)
  } else {
    actualField = unavailable('actual_contract missing')
  }

  const latest1m = readString(input.latest_live_1m)
  const confirmed = readNumber(input.confirmed_count)
  const partial = readNumber(input.partial_count)
  const chartRows = readNumber(input.chart_row_count)

  // Same-bar rule: chart_row_count (confirmed-only) must not silently equal confirmed+partial.
  let confirmedField: ObservationField<number>
  if (confirmed == null) {
    confirmedField = unavailable('confirmed_count missing')
  } else if (
    chartRows != null &&
    partial != null &&
    partial > 0 &&
    chartRows === confirmed + partial
  ) {
    confirmedField = warning(confirmed, 'same-bar display must not merge partial into confirmed')
  } else {
    confirmedField = available(confirmed)
  }

  const runtimeStatus = readString(input.runtime_health_status)?.toLowerCase() || null
  let runtimeField: ObservationField
  if (!runtimeStatus) {
    runtimeField = unavailable('runtime_health_status missing')
  } else if (runtimeStatus === 'ok') {
    runtimeField = available('ok')
  } else if (runtimeStatus === 'degraded' || runtimeStatus === 'failed') {
    // Never map degraded/failed to healthy.
    runtimeField = warning(runtimeStatus, 'not healthy')
  } else {
    runtimeField = warning(runtimeStatus, 'unknown runtime status')
  }

  const checkpointStatus = readString(input.checkpoint_status)
  const lag = readNumber(input.checkpoint_lag_seconds)
  const latency = readNumber(input.latency_ms)

  const archivedDay = readString(input.archived_trading_day)
  const dataVersion = readString(input.active_data_version)
  let dataVersionField: ObservationField
  if (dataVersion) {
    dataVersionField = available(dataVersion)
  } else if (mode === 'live') {
    dataVersionField = unavailable('live mode has no active data_version by design')
  } else {
    dataVersionField = unavailable('active_data_version missing')
  }

  const quality = readString(input.quality_status)
  const profileId = readString(input.profile_id)
  let profileField: ObservationField
  if (profileId) {
    profileField = available(profileId)
  } else if (mode === 'live') {
    profileField = unavailable('live mode does not bind research profile')
  } else {
    profileField = unavailable('profile_id missing')
  }

  return {
    data_mode: dataModeField,
    source_badge: sourceBadge,
    actual_contract: actualField,
    latest_live_1m: latest1m ? available(latest1m) : unavailable('latest_live_1m missing'),
    confirmed_count: confirmedField,
    partial_count: partial == null ? unavailable('partial_count missing') : available(partial),
    checkpoint_status: checkpointStatus
      ? available(checkpointStatus)
      : unavailable('checkpoint_status missing'),
    checkpoint_lag_seconds: lag == null ? unavailable('checkpoint_lag_seconds missing') : available(lag),
    latency_ms: latency == null ? unavailable('latency_ms missing') : available(latency),
    runtime_health_status: runtimeField,
    archived_trading_day: archivedDay
      ? available(archivedDay)
      : unavailable('archived_trading_day missing'),
    active_data_version: dataVersionField,
    quality_status: quality ? available(quality) : unavailable('quality_status missing'),
    profile_id: profileField,
  }
}

export function observationFieldLabel(field: ObservationField): string {
  if (field.status === 'unavailable') return `unavailable${field.reason ? ` (${field.reason})` : ''}`
  if (field.status === 'warning') {
    const base = field.value == null ? 'warning' : String(field.value)
    return field.reason ? `${base} — ${field.reason}` : base
  }
  return field.value == null ? '-' : String(field.value)
}

/** Static check: payload must not leak paths or credentials. */
export function assertNoSensitivePayload(value: unknown, path = '$'): string[] {
  const leaks: string[] = []
  if (value == null) return leaks
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      leaks.push(...assertNoSensitivePayload(item, `${path}[${index}]`))
    })
    return leaks
  }
  if (typeof value !== 'object') return leaks
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (SENSITIVE_KEY_RE.test(key) && child != null && child !== '') {
      leaks.push(`${path}.${key}`)
    }
    leaks.push(...assertNoSensitivePayload(child, `${path}.${key}`))
  }
  return leaks
}

export function normalizeRuntimeHealthDisplay(status: string | null | undefined): 'ok' | 'degraded' | 'failed' | 'other' {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'ok') return 'ok'
  if (normalized === 'degraded') return 'degraded'
  if (normalized === 'failed') return 'failed'
  return 'other'
}
