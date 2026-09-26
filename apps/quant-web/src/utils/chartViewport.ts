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
