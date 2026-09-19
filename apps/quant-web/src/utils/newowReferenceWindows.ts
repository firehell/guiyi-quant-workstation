export type NewowReferencePreset = 'three_months' | 'one_year' | 'ytd'

export interface NewowReferenceWindow {
  readonly performanceSince: string
  readonly performanceThrough: string
}

/**
 * Calendar-only convenience windows.  The accepted server cutoff is the sole
 * anchor: this helper deliberately does not inspect the browser clock or data
 * coverage.
 */
export function newowReferenceWindow(anchor: string, preset: NewowReferencePreset): NewowReferenceWindow {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(anchor)) throw new Error('NEWOW_REFERENCE_ANCHOR_INVALID')
  const [year, month, day] = anchor.split('-').map(Number)
  const probe = new Date(Date.UTC(year!, month! - 1, day!))
  if (probe.getUTCFullYear() !== year || probe.getUTCMonth() !== month! - 1 || probe.getUTCDate() !== day) {
    throw new Error('NEWOW_REFERENCE_ANCHOR_INVALID')
  }
  const through = anchor
  if (preset === 'ytd') return { performanceSince: `${year}-01-01`, performanceThrough: through }
  const targetYear = preset === 'one_year' ? year! - 1 : year!
  const targetMonth = preset === 'three_months' ? month! - 4 : month! - 1
  const normalized = new Date(Date.UTC(targetYear, targetMonth, 1))
  const lastDay = new Date(Date.UTC(normalized.getUTCFullYear(), normalized.getUTCMonth() + 1, 0)).getUTCDate()
  const start = new Date(Date.UTC(normalized.getUTCFullYear(), normalized.getUTCMonth(), Math.min(day!, lastDay)))
  return { performanceSince: start.toISOString().slice(0, 10), performanceThrough: through }
}
