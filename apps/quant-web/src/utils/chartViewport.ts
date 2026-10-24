const DEFAULT_INITIAL_CHART_BAR_COUNT = 300

// Newow opens on recent candles at a readable density, with the latest at the right.
export function initialNewowChartLogicalRange(barCount: number, width: number) {
  if (!Number.isInteger(barCount) || barCount <= 0) return null
  const count = Math.min(barCount, Math.max(40, Math.min(100, Math.floor(width / 14))))
  return { from: Math.max(-0.5, barCount - count - 0.5), to: barCount - 0.5 }
}

export function initialChartLogicalRange(barCount: number) {
  if (!Number.isInteger(barCount) || barCount <= 0) return null
  return {
    from: Math.max(0, barCount - DEFAULT_INITIAL_CHART_BAR_COUNT),
    to: barCount - 1,
  }
}

/** Keep a pending stabilization target tied to the same candles after a prepend. */
export function prependChartLogicalRange(range: { from: number; to: number } | null, added: number) {
  if (!range) return null
  if (!Number.isSafeInteger(added) || added < 0) throw new Error('invalid prepend count')
  return { from: range.from + added, to: range.to + added }
}
