export type ContractViewMode = 'actual' | 'continuous'

export const LIVE_SUPPORTED_PERIODS = new Set(['1m', '5m', '15m', '30m', '60m'])

export const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])

export const CHART_PERIOD_OPEN_ORDER = ['15m', '5m', '1d', '1w', '1m', '30m', '60m'] as const

export function continuousContractFor(product: string): string {
  return `${product.trim().toLowerCase()}.MAIN`
}

export function defaultContractViewForPeriod(period: string): ContractViewMode {
  return DAILY_WEEKLY_PERIODS.has(period) ? 'continuous' : 'actual'
}

export function resolveContractForView(
  product: string,
  actualContract: string,
  viewMode: ContractViewMode,
): string {
  if (viewMode === 'continuous') return continuousContractFor(product)
  return actualContract
}

export function isLivePeriodSupported(period: string): boolean {
  return LIVE_SUPPORTED_PERIODS.has(period)
}

export function preferredOpenPeriod(coverage: Record<string, { available?: boolean }>): string {
  const available = new Set(
    Object.entries(coverage)
      .filter(([, item]) => item.available)
      .map(([period]) => period),
  )
  for (const period of CHART_PERIOD_OPEN_ORDER) {
    if (available.has(period)) return period
  }
  return '15m'
}

export function defaultDateRangeMs(
  period: string,
  coverageStart: number,
  coverageEnd: number,
): [number, number] {
  const day = 24 * 60 * 60 * 1000
  const end = coverageEnd
  let windowDays: number
  switch (period) {
    case '1m':
      windowDays = 7
      break
    case '5m':
      windowDays = 30
      break
    case '15m':
      windowDays = 60
      break
    case '30m':
    case '60m':
      windowDays = 90
      break
    case '1d':
      windowDays = 365 * 3
      break
    case '1w':
      windowDays = 365 * 5
      break
    default:
      windowDays = 90
  }
  const start = Math.max(coverageStart, end - windowDays * day)
  return [start, end]
}

export function formatAvailablePeriodTags(coverage: Record<string, { available?: boolean }>): string[] {
  const available = new Set(
    Object.entries(coverage)
      .filter(([, item]) => item.available)
      .map(([period]) => period),
  )
  return CHART_PERIOD_OPEN_ORDER.filter((period) => available.has(period))
}
