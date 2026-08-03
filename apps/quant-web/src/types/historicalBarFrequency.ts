export const HISTORICAL_BAR_FREQUENCIES = [
  '1m',
  '5m',
  '15m',
  '30m',
  '60m',
  '1d',
  '1w',
] as const

export type HistoricalBarFrequency = typeof HISTORICAL_BAR_FREQUENCIES[number]

const HISTORICAL_BAR_FREQUENCY_SET = new Set<string>(HISTORICAL_BAR_FREQUENCIES)

export function isHistoricalBarFrequency(value: unknown): value is HistoricalBarFrequency {
  return typeof value === 'string' && HISTORICAL_BAR_FREQUENCY_SET.has(value)
}
