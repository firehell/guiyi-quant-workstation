import { ref } from 'vue'
import type { AlertEventListResponse } from '../api/alerts.ts'
import type { BarData, KlineMarker, MarketFrequency, SeriesKind } from '../types/market.ts'
import { alertEventsToMarkers, isPersistentAlertIdentity } from '../utils/alertMarkers.ts'


const REFRESH_INTERVAL_MS = 30_000
const RECENT_WINDOW_MS = 2 * 60 * 60 * 1000

export interface AlertMarkerIdentity {
  seriesKind: SeriesKind
  symbol: string
  frequency: MarketFrequency
}

interface AlertEventRequest {
  symbol: string
  ruleCode: string
  start: string
  end: string
}

interface Dependencies {
  fetchEvents: (params: AlertEventRequest) => Promise<AlertEventListResponse>
  scheduleInterval?: (callback: () => void | Promise<void>, delayMs: number) => unknown
  clearInterval?: (handle: unknown) => void
}

export function usePersistentAlertMarkers(dependencies: Dependencies) {
  const markers = ref<KlineMarker[]>([])
  const events = new Map<string, AlertEventListResponse['items'][number]>()
  const fetchEvents = dependencies.fetchEvents
  const scheduleInterval = dependencies.scheduleInterval
    ?? ((callback, delay) => setInterval(() => void callback(), delay))
  const clearScheduledInterval = dependencies.clearInterval
    ?? ((handle) => clearInterval(handle as ReturnType<typeof setInterval>))
  let generation = 0
  let timer: unknown = null
  let activeIdentity: AlertMarkerIdentity | null = null
  let loadedStart: string | null = null
  let loadedEnd: string | null = null

  async function sync(
    identity: AlertMarkerIdentity,
    bars: BarData[],
    mutation: 'replace' | 'prepend' | 'live',
  ): Promise<void> {
    const identityChanged = identityKey(identity) !== identityKey(activeIdentity)
    if (identityChanged || mutation === 'replace') {
      generation += 1
      stopTimer()
      events.clear()
      markers.value = []
      activeIdentity = { ...identity }
      loadedStart = null
      loadedEnd = null
    }
    if (!isPersistentAlertIdentity(identity.seriesKind, identity.frequency) || !bars.length) {
      generation += 1
      stopTimer()
      events.clear()
      markers.value = []
      activeIdentity = { ...identity }
      loadedStart = null
      loadedEnd = null
      return
    }

    const range = barRange(bars)
    const requestGeneration = generation
    if (loadedStart === null || loadedEnd === null) {
      loadedStart = range.start
      loadedEnd = range.end
      await fetchRange(identity, range.start, range.end, requestGeneration)
      startTimer(requestGeneration)
      return
    }
    if (mutation === 'prepend' && Date.parse(range.start) < Date.parse(loadedStart)) {
      const previousStart = loadedStart
      loadedStart = range.start
      await fetchRange(identity, range.start, previousStart, requestGeneration)
    }
    if (Date.parse(range.end) > Date.parse(loadedEnd)) loadedEnd = range.end
  }

  function startTimer(requestGeneration: number) {
    if (timer !== null) return
    timer = scheduleInterval(() => refreshRecent(requestGeneration), REFRESH_INTERVAL_MS)
  }

  async function refreshRecent(requestGeneration: number) {
    if (
      requestGeneration !== generation
      || !activeIdentity
      || loadedStart === null
      || loadedEnd === null
      || !isPersistentAlertIdentity(activeIdentity.seriesKind, activeIdentity.frequency)
    ) return
    const recentStart = new Date(Math.max(
      Date.parse(loadedStart),
      Date.parse(loadedEnd) - RECENT_WINDOW_MS,
    )).toISOString()
    await fetchRange(activeIdentity, recentStart, loadedEnd, requestGeneration)
  }

  async function fetchRange(
    identity: AlertMarkerIdentity,
    start: string,
    end: string,
    requestGeneration: number,
  ) {
    const normalizedEnd = Date.parse(end) > Date.parse(start)
      ? end
      : new Date(Date.parse(start) + 1).toISOString()
    try {
      const response = await fetchEvents({
        symbol: identity.symbol,
        ruleCode: 'htdy_original_15m',
        start,
        end: normalizedEnd,
      })
      if (requestGeneration !== generation || identityKey(identity) !== identityKey(activeIdentity)) return
      for (const event of response.items) {
        if (
          event.rule_code !== 'htdy_original_15m'
          || event.symbol !== identity.symbol
          || event.frequency !== '15m'
        ) continue
        events.set(eventKey(event), event)
      }
      markers.value = alertEventsToMarkers([...events.values()])
    } catch {
      // Presentation refresh is optional; keep the last persistent marker snapshot.
    }
  }

  function stopTimer() {
    if (timer === null) return
    clearScheduledInterval(timer)
    timer = null
  }

  function dispose() {
    generation += 1
    stopTimer()
    events.clear()
    markers.value = []
  }

  return { markers, sync, dispose }
}

function identityKey(identity: AlertMarkerIdentity | null): string {
  return identity
    ? `${identity.seriesKind}:${identity.symbol}:${identity.frequency}`
    : ''
}

function eventKey(event: AlertEventListResponse['items'][number]): string {
  return `${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
}

function barRange(bars: BarData[]): { start: string; end: string } {
  const times = bars.map((bar) => bar.time).sort((left, right) => Date.parse(left) - Date.parse(right))
  return { start: times[0], end: times.at(-1)! }
}
