import type { SignalEventRecord, StrategySignalRecord } from '@/types/signal'

export function signalMarkerId(signal: Pick<StrategySignalRecord, 'id'>) {
  return `signal-${signal.id}`
}

export function signalIdFromMarkerId(markerId: string) {
  const match = /^signal-(\d+)$/.exec(markerId)
  if (!match) return null
  const value = Number(match[1])
  return Number.isFinite(value) ? value : null
}

export function eventMatchesSignalChart(
  event: SignalEventRecord,
  signal: StrategySignalRecord,
  chart: { product?: string | null; contract?: string | null; period?: string | null },
) {
  const product = event.product || event.symbol
  const eventContract = event.actual_contract || event.contract
  const signalContract = signal.actual_contract || signal.contract
  const eventPeriod = event.period
  const signalPeriod = signal.entry_interval || signal.interval || signal.period
  return (
    product === (chart.product || signal.product || signal.symbol) &&
    eventContract === (chart.contract || signalContract) &&
    eventPeriod === (chart.period || signalPeriod)
  )
}

export function selectSignalEventForChart(
  events: SignalEventRecord[],
  signal: StrategySignalRecord,
  chart: { product?: string | null; contract?: string | null; period?: string | null } = {},
) {
  const preferredTypes = new Set(['signal_created', 'signal_changed'])
  const sorted = [...events].sort((first, second) => {
    const firstTime = new Date(first.created_at || first.signal_time || first.bar_end || '').getTime()
    const secondTime = new Date(second.created_at || second.signal_time || second.bar_end || '').getTime()
    return (Number.isFinite(secondTime) ? secondTime : 0) - (Number.isFinite(firstTime) ? firstTime : 0)
  })
  return (
    sorted.find((event) => preferredTypes.has(event.event_type) && eventMatchesSignalChart(event, signal, chart)) ||
    sorted.find((event) => preferredTypes.has(event.event_type)) ||
    sorted[0] ||
    null
  )
}
