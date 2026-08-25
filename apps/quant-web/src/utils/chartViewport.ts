const DEFAULT_INITIAL_CHART_BAR_COUNT = 300

export function initialChartLogicalRange(barCount: number) {
  if (!Number.isInteger(barCount) || barCount <= 0) return null
  return {
    from: Math.max(0, barCount - DEFAULT_INITIAL_CHART_BAR_COUNT),
    to: barCount - 1,
  }
}
