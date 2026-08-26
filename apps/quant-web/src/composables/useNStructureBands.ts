import { ref } from 'vue'
import type {
  BarData,
  MarketBarsPageResponse,
  MarketFrequency,
  NStructureBand,
  NStructureBandRequest,
  NStructureBandResponse,
  SeriesKind,
} from '../types/market.ts'
import { nStructureBandCapability } from '../utils/mainIndicators.ts'

export interface NStructureBandIdentity {
  enabled: boolean
  seriesKind: SeriesKind
  symbol: string
  frequency: MarketFrequency
}

interface Dependencies {
  fetchBands: (request: NStructureBandRequest) => Promise<NStructureBandResponse>
}

export function useNStructureBands(dependencies: Dependencies) {
  const bands = ref<NStructureBand[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const bandsById = new Map<string, NStructureBand>()
  let generation = 0
  let activeIdentity: NStructureBandIdentity | null = null
  let loadedSince: string | null = null

  async function sync(
    identity: NStructureBandIdentity,
    bars: BarData[],
    canonicalCoverage: MarketBarsPageResponse['canonical_coverage'],
    mutation: 'replace' | 'prepend' | 'live',
  ): Promise<void> {
    const changed = identityKey(identity) !== identityKey(activeIdentity)
    if (changed || mutation === 'replace') reset(identity)
    if (mutation === 'live') return
    if (
      !identity.enabled
      || !identity.symbol
      || !nStructureBandCapability(identity.seriesKind, identity.frequency)
    ) {
      clearVisible()
      return
    }

    const range = confirmedRange(bars, canonicalCoverage)
    if (range === null) {
      if (mutation === 'replace') clearVisible()
      return
    }
    if (mutation === 'prepend' && loadedSince !== null && range.since >= loadedSince) return
    const through = mutation === 'prepend' && loadedSince !== null ? loadedSince : range.through
    const request: NStructureBandRequest = {
      series_kind: 'actual_dominant',
      symbol: identity.symbol,
      frequency: '5m',
      since: range.since,
      through,
    }
    const requestGeneration = generation
    loading.value = true
    error.value = null
    try {
      const response = await dependencies.fetchBands(request)
      if (requestGeneration !== generation || identityKey(identity) !== identityKey(activeIdentity)) return
      assertResponse(response, request)
      for (const band of response.bands) {
        const existing = bandsById.get(band.band_id)
        bandsById.set(
          band.band_id,
          existing ? mergeBandLifecycle(existing, band) : band,
        )
      }
      bands.value = [...bandsById.values()].sort(
        (left, right) => Date.parse(left.completed_at) - Date.parse(right.completed_at),
      )
      if (loadedSince === null || range.since < loadedSince) loadedSince = range.since
    } catch {
      if (requestGeneration === generation && identityKey(identity) === identityKey(activeIdentity)) {
        bandsById.clear()
        bands.value = []
        loadedSince = null
        error.value = 'N_STRUCTURE_BANDS_UNAVAILABLE'
      }
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function reset(identity: NStructureBandIdentity) {
    generation += 1
    activeIdentity = { ...identity }
    clearVisible()
    loading.value = false
    loadedSince = null
  }

  function clearVisible() {
    bandsById.clear()
    bands.value = []
    error.value = null
  }

  function dispose() {
    generation += 1
    activeIdentity = null
    clearVisible()
    loading.value = false
    loadedSince = null
  }

  return { bands, loading, error, sync, dispose }
}

function assertResponse(response: NStructureBandResponse, request: NStructureBandRequest): void {
  const actual = response.request
  if (
    actual.series_kind !== request.series_kind
    || actual.symbol !== request.symbol
    || actual.frequency !== request.frequency
    || actual.since !== request.since
    || actual.through !== request.through
    || response.policy.policy_id !== 'n_structure_5m_v1'
    || response.policy.formula_version !== 'n_structure_v1'
    || response.policy.source_timeframe !== '5m'
    || response.policy.research_only !== true
    || !Array.isArray(response.bands)
    || response.bands.some((band) => !validBandLifecycle(band))
  ) throw new Error('N_STRUCTURE_BAND_IDENTITY_MISMATCH')
}

function validBandLifecycle(band: NStructureBand): boolean {
  const n1At = Date.parse(band.n1_at)
  const completedAt = Date.parse(band.completed_at)
  const expandedUntil = Date.parse(band.expanded_until)
  const firstReenteredAt = band.first_reentered_at === null
    ? null
    : Date.parse(band.first_reentered_at)
  const invalidatedAt = band.invalidated_at === null
    ? null
    : Date.parse(band.invalidated_at)
  return (
    typeof band.band_id === 'string'
    && band.band_id.length > 0
    && typeof band.contract === 'string'
    && band.contract.length > 0
    && (band.direction === 'up' || band.direction === 'down')
    && (band.role === 'support_reference' || band.role === 'resistance_reference')
    && (
      (band.direction === 'up' && band.role === 'support_reference')
      || (band.direction === 'down' && band.role === 'resistance_reference')
    )
    && validTradingDay(band.segment_start_trading_day)
    && validTradingDay(band.completion_trading_day)
    && band.segment_start_trading_day <= band.completion_trading_day
    && Number.isFinite(n1At)
    && Number.isFinite(completedAt)
    && Number.isFinite(expandedUntil)
    && n1At < completedAt
    && completedAt <= expandedUntil
    && (firstReenteredAt === null || (
      Number.isFinite(firstReenteredAt)
      && completedAt < firstReenteredAt
      && firstReenteredAt <= expandedUntil
    ))
    && (invalidatedAt === null || (
      Number.isFinite(invalidatedAt)
      && completedAt <= invalidatedAt
      && invalidatedAt === expandedUntil
    ))
    && Number.isFinite(band.completion_level)
    && Number.isFinite(band.lower)
    && Number.isFinite(band.upper)
    && band.lower > 0
    && band.lower <= band.completion_level
    && band.completion_level <= band.upper
  )
}

function validTradingDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const timestamp = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value
}

function confirmedRange(
  bars: BarData[],
  coverage: MarketBarsPageResponse['canonical_coverage'],
): { since: string; through: string } | null {
  if (!coverage) return null
  const start = Date.parse(coverage.start)
  const end = Date.parse(coverage.end)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) return null
  const confirmed = bars.filter((bar) => {
    const time = Date.parse(bar.time)
    return Number.isFinite(time) && start <= time && time <= end
  })
  if (!confirmed.length) return null
  const first = confirmed[0]
  const last = confirmed[confirmed.length - 1]
  return {
    since: first.trading_day ?? first.time.slice(0, 10),
    through: last.trading_day ?? last.time.slice(0, 10),
  }
}

function identityKey(identity: NStructureBandIdentity | null): string {
  if (!identity) return ''
  return [identity.enabled, identity.seriesKind, identity.symbol, identity.frequency].join('|')
}

function mergeBandLifecycle(
  existing: NStructureBand,
  incoming: NStructureBand,
): NStructureBand {
  assertSameBandIdentity(existing, incoming)
  const wider = Date.parse(incoming.expanded_until) > Date.parse(existing.expanded_until)
    ? incoming
    : existing
  const firstReenteredAt = mergeOptionalLifecycleFact(
    existing.first_reentered_at,
    existing.expanded_until,
    incoming.first_reentered_at,
    incoming.expanded_until,
  )
  const invalidatedAt = mergeOptionalLifecycleFact(
    existing.invalidated_at,
    existing.expanded_until,
    incoming.invalidated_at,
    incoming.expanded_until,
  )
  const merged = {
    ...wider,
    first_reentered_at: firstReenteredAt,
    invalidated_at: invalidatedAt,
    expanded_until: invalidatedAt ?? wider.expanded_until,
  }
  if (!validBandLifecycle(merged)) throw new Error('N_STRUCTURE_BAND_LIFECYCLE_CONFLICT')
  return merged
}

function assertSameBandIdentity(left: NStructureBand, right: NStructureBand): void {
  const fields = [
    'band_id',
    'contract',
    'segment_start_trading_day',
    'completion_trading_day',
    'direction',
    'role',
    'n1_at',
    'completed_at',
    'completion_level',
    'lower',
    'upper',
  ] as const
  if (fields.some((field) => left[field] !== right[field])) {
    throw new Error('N_STRUCTURE_BAND_IDENTITY_CONFLICT')
  }
}

function mergeOptionalLifecycleFact(
  left: string | null,
  leftObservedUntil: string,
  right: string | null,
  rightObservedUntil: string,
): string | null {
  if (left !== null && right !== null) {
    if (left !== right) throw new Error('N_STRUCTURE_BAND_LIFECYCLE_CONFLICT')
    return left
  }
  if (left === null && right === null) return null
  const fact = left ?? right!
  const missingObservedUntil = left === null ? leftObservedUntil : rightObservedUntil
  if (Date.parse(missingObservedUntil) >= Date.parse(fact)) {
    throw new Error('N_STRUCTURE_BAND_LIFECYCLE_CONFLICT')
  }
  return fact
}
