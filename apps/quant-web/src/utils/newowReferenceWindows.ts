export type NewowReferencePreset = 'three_months' | 'one_year' | 'three_years' | 'ytd' | 'all' | 'ideal'

export interface NewowReferenceWindow {
  readonly performanceSince: string
  readonly performanceThrough: string
}

export function acceptedNewowReferencePreset<T extends string>(pending: { readonly kind: T; readonly since: string; readonly through: string } | null, accepted: NewowReferenceWindow | null): T | null {
  return pending !== null && accepted !== null && pending.since === accepted.performanceSince && pending.through === accepted.performanceThrough ? pending.kind : null
}

/**
 * Calendar-only convenience windows.  The accepted server cutoff is the sole
 * anchor: this helper deliberately does not inspect the browser clock or data
 * coverage.
 */
export function newowReferenceWindow(anchor: string, preset: NewowReferencePreset, availableSince?: string): NewowReferenceWindow {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(anchor)) throw new Error('NEWOW_REFERENCE_ANCHOR_INVALID')
  const [year, month, day] = anchor.split('-').map(Number)
  const probe = new Date(Date.UTC(year!, month! - 1, day!))
  if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month! - 1 || probe.getUTCDate() !== day) {
    throw new Error('NEWOW_REFERENCE_ANCHOR_INVALID')
  }
  const through = anchor
  const clampStart = (since: string) => ({ performanceSince: availableSince && since < availableSince ? availableSince : since, performanceThrough: through })
  if ((preset === 'all' || preset === 'ideal')) {
    if (!availableSince) throw new Error('NEWOW_REFERENCE_START_UNAVAILABLE')
    return clampStart(availableSince)
  }
  if (preset === 'ytd') return clampStart(`${year}-01-01`)
  const targetYear = preset === 'one_year' ? year! - 1 : preset === 'three_years' ? year! - 3 : year!
  const targetMonth = preset === 'three_months' ? month! - 4 : month! - 1
  const normalized = new Date(Date.UTC(targetYear, targetMonth, 1))
  const lastDay = new Date(Date.UTC(normalized.getUTCFullYear(), normalized.getUTCMonth() + 1, 0)).getUTCDate()
  const start = new Date(Date.UTC(normalized.getUTCFullYear(), normalized.getUTCMonth(), Math.min(day!, lastDay)))
  return clampStart(start.toISOString().slice(0, 10))
}
