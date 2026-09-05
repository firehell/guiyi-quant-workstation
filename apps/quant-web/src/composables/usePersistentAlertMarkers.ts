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

interface AcceptedRange {
  revision: number
  start: string
  end: string
}

export function usePersistentAlertMarkers(dependencies: Dependencies, options: PersistentAlertMarkerOptions = {}) {
  const markers = ref<KlineMarker[]>([])
  const eventMap = new Map<string, AlertEventListResponse['items'][number]>()
  const eventAcceptedAt = new Map<string, number>()
  const events = ref<AlertEventListResponse['items']>([])
  const unavailable = ref(false)
  const fetchEvents = dependencies.fetchEvents
  const scheduleInterval = dependencies.scheduleInterval
    ?? ((callback, delay) => setInterval(() => void callback(), delay))
  const clearScheduledInterval = dependencies.clearInterval
    ?? ((handle) => clearInterval(handle as ReturnType<typeof setInterval>))
  let generation = 0
  let replacementRevision = 0
  let requestSequence = 0
  let lastAvailabilitySequence = 0
  let acceptedRevision = 0
  let rangesAcceptedAfterReplacement: AcceptedRange[] = []
  let timer: unknown = null
  let activeIdentity: AlertMarkerIdentity | null = null
  let loadedStart: string | null = null
  let loadedEnd: string | null = null
  let visibleStart: string | null = null
  let visibleEnd: string | null = null
  let initialLoadPending = false

  async function sync(
    identity: AlertMarkerIdentity,
    bars: BarData[],
    mutation: 'replace' | 'prepend' | 'live',
  ): Promise<void> {
    const identityChanged = identityKey(identity) !== identityKey(activeIdentity)
    if (identityChanged) {
      generation += 1
      replacementRevision += 1
      stopTimer()
      eventMap.clear()
      eventAcceptedAt.clear()
      events.value = []
      markers.value = []
      unavailable.value = false
      activeIdentity = { ...identity }
      loadedStart = null
      loadedEnd = null
      visibleStart = null
      visibleEnd = null
      initialLoadPending = false
      lastAvailabilitySequence = 0
      acceptedRevision = 0
      rangesAcceptedAfterReplacement = []
    }
    if (!isPersistentAlertIdentity(identity.seriesKind, identity.frequency) || !bars.length) {
      generation += 1
      replacementRevision += 1
      stopTimer()
      eventMap.clear()
      eventAcceptedAt.clear()
      events.value = []
      markers.value = []
      unavailable.value = false
      activeIdentity = { ...identity }
      loadedStart = null
      loadedEnd = null
      visibleStart = null
      visibleEnd = null
      initialLoadPending = false
      lastAvailabilitySequence = 0
      acceptedRevision = 0
      rangesAcceptedAfterReplacement = []
      return
    }

    const range = barRange(bars)
    visibleStart = range.start
    visibleEnd = range.end
    const requestGeneration = generation
    if (mutation === 'live' && initialLoadPending) return
    if (loadedStart === null || loadedEnd === null) {
      const replacementRevisionAtStart = ++replacementRevision
      initialLoadPending = true
      const accepted = await fetchRange(
        identity,
        range.start,
        range.end,
        requestGeneration,
        replacementRevisionAtStart,
        true,
      )
      if (replacementRevisionAtStart === replacementRevision) initialLoadPending = false
      if (accepted) {
        startTimer(requestGeneration)
      }
      return
    }
    if (mutation === 'replace') {
      const replacementRevisionAtStart = ++replacementRevision
      await fetchRange(
        identity,
        range.start,
        range.end,
        requestGeneration,
        replacementRevisionAtStart,
        true,
      )
      return
    }
    if (mutation === 'prepend' && Date.parse(range.start) < Date.parse(loadedStart)) {
      const previousStart = loadedStart
      await fetchRange(
        identity,
        range.start,
        previousStart,
        requestGeneration,
        replacementRevision,
      )
    }
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
      || visibleStart === null
      || visibleEnd === null
      || !isPersistentAlertIdentity(activeIdentity.seriesKind, activeIdentity.frequency)
    ) return
    const recentStart = new Date(Math.max(
      Date.parse(loadedStart),
      Date.parse(visibleEnd) - RECENT_WINDOW_MS,
    )).toISOString()
    const refreshEnd = visibleEnd
    await fetchRange(
      activeIdentity,
      recentStart,
      refreshEnd,
      requestGeneration,
      replacementRevision,
    )
  }

  async function fetchRange(
    identity: AlertMarkerIdentity,
    start: string,
    end: string,
    requestGeneration: number,
    replacementRevisionAtStart: number,
    replaceSnapshot = false,
  ): Promise<boolean> {
    const ruleCodes = options.resolveRuleCodes?.(identity) ?? markerRuleCodes(identity.seriesKind, identity.frequency)
    if (!ruleCodes.length) return false
    const requestSequenceAtStart = ++requestSequence
    const snapshotAcceptedRevision = acceptedRevision
    if (replaceSnapshot) rangesAcceptedAfterReplacement = []
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
      if (!requestIsCurrent(identity, requestGeneration, replacementRevisionAtStart, replaceSnapshot)) return false
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
      const commitRevision = ++acceptedRevision
      if (replaceSnapshot) {
        for (const [key, revision] of eventAcceptedAt) {
          if (revision <= snapshotAcceptedRevision) {
            eventAcceptedAt.delete(key)
            eventMap.delete(key)
          }
        }
      }
      for (const [key, event] of nextEvents) {
        if (replaceSnapshot && (eventAcceptedAt.get(key) ?? 0) > snapshotAcceptedRevision) continue
        eventMap.set(key, event)
        eventAcceptedAt.set(key, commitRevision)
      }
      commitAcceptedRange({
        revision: commitRevision,
        start,
        end,
      }, replaceSnapshot, snapshotAcceptedRevision)
      events.value = [...eventMap.values()].sort((left, right) => Date.parse(left.detected_at) - Date.parse(right.detected_at))
      markers.value = alertEventsToMarkers(events.value)
      commitAvailability(false, requestSequenceAtStart)
      return true
    } catch {
      // Presentation refresh is optional; keep the last persistent marker snapshot.
      if (!requestIsCurrent(identity, requestGeneration, replacementRevisionAtStart, replaceSnapshot)) return false
      commitAvailability(true, requestSequenceAtStart)
      return false
    }
  }

  function requestIsCurrent(
    identity: AlertMarkerIdentity,
    requestGeneration: number,
    replacementRevisionAtStart: number,
    replaceSnapshot: boolean,
  ): boolean {
    return requestGeneration === generation
      && identityKey(identity) === identityKey(activeIdentity)
      && (!replaceSnapshot || replacementRevisionAtStart === replacementRevision)
  }

  function commitAcceptedRange(
    range: AcceptedRange,
    replaceSnapshot: boolean,
    snapshotAcceptedRevision: number,
  ) {
    if (replaceSnapshot) {
      rangesAcceptedAfterReplacement = rangesAcceptedAfterReplacement
        .filter((accepted) => accepted.revision > snapshotAcceptedRevision)
      const acceptedRanges = [range, ...rangesAcceptedAfterReplacement]
      loadedStart = acceptedRanges.reduce(
        (earliest, accepted) => Date.parse(accepted.start) < Date.parse(earliest) ? accepted.start : earliest,
        range.start,
      )
      loadedEnd = acceptedRanges.reduce(
        (latest, accepted) => Date.parse(accepted.end) > Date.parse(latest) ? accepted.end : latest,
        range.end,
      )
      return
    }
    rangesAcceptedAfterReplacement.push(range)
    if (loadedStart === null || Date.parse(range.start) < Date.parse(loadedStart)) loadedStart = range.start
    if (loadedEnd === null || Date.parse(range.end) > Date.parse(loadedEnd)) loadedEnd = range.end
  }

  function commitAvailability(nextUnavailable: boolean, requestSequenceAtStart: number) {
    if (requestSequenceAtStart < lastAvailabilitySequence) return
    lastAvailabilitySequence = requestSequenceAtStart
    unavailable.value = nextUnavailable
  }

  function stopTimer() {
    if (timer === null) return
    clearScheduledInterval(timer)
    timer = null
  }

  function dispose() {
    generation += 1
    replacementRevision += 1
    stopTimer()
    eventMap.clear()
    eventAcceptedAt.clear()
    events.value = []
    markers.value = []
    unavailable.value = false
    loadedStart = null
    loadedEnd = null
    visibleStart = null
    visibleEnd = null
    initialLoadPending = false
    lastAvailabilitySequence = 0
    acceptedRevision = 0
    rangesAcceptedAfterReplacement = []
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
