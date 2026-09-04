import { ref } from 'vue'
import type { AlertEventListResponse } from '../api/alerts.ts'
import type { AlertRuleCode, BarData, KlineMarker, MarketFrequency, SeriesKind } from '../types/market.ts'
import { alertEventsToMarkers, isPersistentAlertIdentity, markerRuleCodes } from '../utils/alertMarkers.ts'
import { alertEventIdentityKey, matchesAlertRuleCode } from '../utils/alertRules.ts'

const REFRESH_INTERVAL_MS = 30_000
const RECENT_WINDOW_MS = 2 * 60 * 60 * 1000

export interface AlertMarkerIdentity {
  seriesKind: SeriesKind
  symbol: string
  frequency: MarketFrequency
}

export interface PersistentAlertMarkerOptions {
  /** A workspace may narrow the existing read-only AlertEvent authority without changing global policy. */
  resolveRuleCodes?: (identity: AlertMarkerIdentity) => readonly AlertRuleCode[]
}

interface AlertEventRequest {
  symbol: string
  ruleCode: AlertRuleCode
  start: string
  end: string
}

interface Dependencies {
  fetchEvents: (params: AlertEventRequest) => Promise<AlertEventListResponse>
  scheduleInterval?: (callback: () => void | Promise<void>, delayMs: number) => unknown
  clearInterval?: (handle: unknown) => void
}

export function usePersistentAlertMarkers(dependencies: Dependencies, options: PersistentAlertMarkerOptions = {}) {
  const markers = ref<KlineMarker[]>([])
  const eventMap = new Map<string, AlertEventListResponse['items'][number]>()
  const events = ref<AlertEventListResponse['items']>([])
  const unavailable = ref(false)
  const fetchEvents = dependencies.fetchEvents
  const scheduleInterval = dependencies.scheduleInterval
    ?? ((callback, delay) => setInterval(() => void callback(), delay))
  const clearScheduledInterval = dependencies.clearInterval
    ?? ((handle) => clearInterval(handle as ReturnType<typeof setInterval>))
  let generation = 0
  let requestRevision = 0
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
    if (identityChanged) {
      generation += 1
      requestRevision += 1
      stopTimer()
      eventMap.clear()
      events.value = []
      markers.value = []
      unavailable.value = false
      activeIdentity = { ...identity }
      loadedStart = null
      loadedEnd = null
    }
    if (!isPersistentAlertIdentity(identity.seriesKind, identity.frequency) || !bars.length) {
      generation += 1
      requestRevision += 1
      stopTimer()
      eventMap.clear()
      events.value = []
      markers.value = []
      unavailable.value = false
      activeIdentity = { ...identity }
      loadedStart = null
      loadedEnd = null
      return
    }

    const range = barRange(bars)
    const requestGeneration = generation
    const requestRevisionAtStart = ++requestRevision
    if (loadedStart === null || loadedEnd === null) {
      loadedStart = range.start
      loadedEnd = range.end
      await fetchRange(identity, range.start, range.end, requestGeneration, requestRevisionAtStart)
      startTimer(requestGeneration)
      return
    }
    if (mutation === 'replace') {
      loadedStart = range.start
      loadedEnd = range.end
      await fetchRange(identity, range.start, range.end, requestGeneration, requestRevisionAtStart, true)
      return
    }
    if (mutation === 'prepend' && Date.parse(range.start) < Date.parse(loadedStart)) {
      const previousStart = loadedStart
      loadedStart = range.start
      await fetchRange(identity, range.start, previousStart, requestGeneration, requestRevisionAtStart)
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
    await fetchRange(activeIdentity, recentStart, loadedEnd, requestGeneration, ++requestRevision)
  }

  async function fetchRange(
    identity: AlertMarkerIdentity,
    start: string,
    end: string,
    requestGeneration: number,
    requestRevisionAtStart: number,
    replaceSnapshot = false,
  ) {
    const ruleCodes = options.resolveRuleCodes?.(identity) ?? markerRuleCodes(identity.seriesKind, identity.frequency)
    if (!ruleCodes.length) return
    const normalizedEnd = Date.parse(end) > Date.parse(start)
      ? end
      : new Date(Date.parse(start) + 1).toISOString()
    try {
      const responses = await Promise.all(ruleCodes.map((ruleCode) => fetchEvents({
        symbol: identity.symbol,
        ruleCode,
        start,
        end: normalizedEnd,
      })))
      if (requestGeneration !== generation || requestRevisionAtStart !== requestRevision || identityKey(identity) !== identityKey(activeIdentity)) return
      const nextEvents = new Map<string, AlertEventListResponse['items'][number]>()
      let responseMismatch = false
      for (const [index, response] of responses.entries()) {
        const ruleCode = ruleCodes[index]
        for (const event of response.items) {
          if (
            !matchesAlertRuleCode(event, ruleCode)
            || event.symbol !== identity.symbol
            || event.frequency !== identity.frequency
          ) {
            responseMismatch = true
            continue
          }
          nextEvents.set(eventKey(event), event)
        }
      }
      if (responseMismatch) throw new Error('AlertEvent identity mismatch')
      if (replaceSnapshot) eventMap.clear()
      for (const [key, event] of nextEvents) eventMap.set(key, event)
      events.value = [...eventMap.values()].sort((left, right) => Date.parse(left.detected_at) - Date.parse(right.detected_at))
      markers.value = alertEventsToMarkers(events.value)
      unavailable.value = false
    } catch {
      // Presentation refresh is optional; keep the last persistent marker snapshot.
      if (requestGeneration !== generation || requestRevisionAtStart !== requestRevision || identityKey(identity) !== identityKey(activeIdentity)) return
      unavailable.value = true
    }
  }

  function stopTimer() {
    if (timer === null) return
    clearScheduledInterval(timer)
    timer = null
  }

  function dispose() {
    generation += 1
    requestRevision += 1
    stopTimer()
    eventMap.clear()
    events.value = []
    markers.value = []
    unavailable.value = false
  }

  return { markers, events, unavailable, sync, dispose }
}

function identityKey(identity: AlertMarkerIdentity | null): string {
  return identity
    ? `${identity.seriesKind}:${identity.symbol}:${identity.frequency}`
    : ''
}

function eventKey(event: AlertEventListResponse['items'][number]): string {
  return alertEventIdentityKey(event)
}

function barRange(bars: BarData[]): { start: string; end: string } {
  const times = bars.map((bar) => bar.time).sort((left, right) => Date.parse(left) - Date.parse(right))
  return { start: times[0], end: times.at(-1)! }
}
