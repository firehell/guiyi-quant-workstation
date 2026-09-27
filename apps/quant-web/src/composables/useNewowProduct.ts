import { computed, readonly, shallowRef, watch, type Ref, type ShallowRef } from 'vue'

import { getNewowDailySnapshot, getNewowWeeklySnapshot, getNewowHistoricalSnapshot, getNewowProductSection, NewowProductRequestError } from '../api/newowProduct.ts'
import { candidatePreview } from '../utils/candidatePreview.ts'
import { previewInstant } from '../utils/candidatePreviewInstant.ts'
import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import {
  NEWOW_PRODUCT_FREQUENCIES,
  NEWOW_PRODUCT_STRATEGIES,
} from '../types/newowProduct.ts'
import type {
  NewowAuxiliaryComponent,
  NewowHistoricalSnapshot,
  NewowDailySnapshot,
  NewowWeeklySnapshot,
  NewowChartValue,
  NewowProductIdentity,
  NewowProductRequest,
  NewowProductSection,
  NewowProductSectionResponse,
  NewowReferenceValue,
  NewowResourceLifecycle,
} from '../types/newowProduct.ts'
import { sharedChartBarsAgree } from '../utils/newowProductTypes.ts'
import { createReferencePageState } from './referencePageState.ts'

type FetchSection = (request: NewowProductRequest, signal: AbortSignal) => Promise<NewowProductSectionResponse>

const MAX_ACCUMULATED_CHART_ROWS = 3000
const MAX_ACCUMULATED_REFERENCE_TRADES = 300
const NEWOW_STRATEGY_SET = new Set<string>(NEWOW_PRODUCT_STRATEGIES)
const NEWOW_FREQUENCY_SET = new Set<string>(NEWOW_PRODUCT_FREQUENCIES)

export interface UseNewowProductOptions {
  readonly identity: Readonly<Ref<MarketDetailIdentity | null>>
  readonly fetchSection?: FetchSection
  readonly now?: () => Date | string
  readonly fetchHistoricalSnapshot?: (identity: NewowProductIdentity, signal: AbortSignal) => Promise<NewowHistoricalSnapshot>
  readonly fetchDailySnapshot?: (identity: NewowProductIdentity, signal: AbortSignal) => Promise<NewowDailySnapshot>
  readonly fetchWeeklySnapshot?: (identity: NewowProductIdentity, signal: AbortSignal) => Promise<NewowWeeklySnapshot>
}

interface SectionResource {
  readonly data: ShallowRef<NewowProductSectionResponse | null>
  readonly state: ShallowRef<NewowResourceLifecycle>
  readonly error: ShallowRef<string | null>
}

interface ReferenceLoadOptions {
  readonly performanceSince?: string
  readonly performanceThrough?: string
  readonly historyLimit?: number
}

interface ChartLoadOptions {
  readonly from?: string
  readonly through?: string
  readonly chartLimit?: number
  readonly chartBefore?: string
}

export function useNewowProduct(options: UseNewowProductOptions) {
  const fetchSection: FetchSection = options.fetchSection
    ?? ((request, signal) => getNewowProductSection(request, { signal }))
  const now = options.now ?? (() => candidatePreview.enabled && !candidatePreview.defaultWeekly
    ? candidatePreview.asOf : new Date())
  const currentIdentity = shallowRef<NewowProductIdentity | null>(null)
  const asOf = shallowRef<string | null>(null)
  const historicalSnapshot = shallowRef<NewowHistoricalSnapshot | null>(null)
  const dailySnapshot = shallowRef<NewowDailySnapshot | null>(null)
  const weeklySnapshot = shallowRef<NewowWeeklySnapshot | null>(null)
  const dailyError = shallowRef<string | null>(null)
  const dailyLoading = shallowRef(false)
  const historicalError = shallowRef<string | null>(null)
  const historicalLoading = shallowRef(false)
  let resolverController: AbortController | null = null
  let dailyController: AbortController | null = null
  const resources = Object.fromEntries(
    (['chart', 'auxiliary', 'reference', 'explanation', 'comparator'] as const)
      .map((section) => [section, createResource()]),
  ) as Record<NewowProductSection, SectionResource>
  const controllers = new Map<NewowProductSection, AbortController>()
  const inFlightSnapshotTokens = new Map<NewowProductSection, string | undefined>()
  const sectionGenerations = new Map<NewowProductSection, number>()
  const auxiliaryCache = new Map<string, NewowProductSectionResponse<'auxiliary'>>()
  const auxiliaryRebuildAttempts = new Set<string>()
  let generation = 0
  let disposed = false
  let preservingCurrentChart = false
  const acceptedCurrentChartWindow = shallowRef(false)
  const acceptedHistoricalChartWindow = shallowRef(false)
  const acceptedAuxiliaryWindow = shallowRef<{ from: string; through: string } | null>(null)
  let chartWindow: { from: string; through: string } | null = null
  let chartFingerprint: string | null = null
  let acceptedChartGenerationSignature: string | null = null
  let chartPageLimit: number | null = null
  // Main-chart labels retain their accepted reference snapshot independently of performance tabs.
  const chartReference = shallowRef<NewowProductSectionResponse<'reference'> | null>(null)
  let referenceWindow: { since: string; through: string } | null = null
  let referenceFingerprint: string | null = null
  const referencePages = createReferencePageState<NewowReferenceValue['items'][number]>(item => item.reference_trade_id, MAX_ACCUMULATED_REFERENCE_TRADES, true)
  let referencePageLimit: number | null = null

  const identityKey = computed(() => {
    const identity = options.identity.value
    return identity === null ? '' : [identity.view, identity.symbol, identity.strategy ?? '', identity.seriesKind, identity.frequency, identity.contract ?? ''].join('|')
  })

  const stopWatch = watch(identityKey, () => replaceIdentity(), { immediate: true, flush: 'sync' })

  function replaceIdentity(): void {
    generation += 1
    preservingCurrentChart = false
    resolverController?.abort()
    resolverController = null
    dailyController?.abort()
    dailyController = null
    dailySnapshot.value = null
    weeklySnapshot.value = null
    dailyError.value = null
    dailyLoading.value = false
    historicalLoading.value = false
    resetAll()
    historicalSnapshot.value = null
    historicalError.value = null
    currentIdentity.value = validatedIdentity(options.identity.value)
    asOf.value = currentIdentity.value === null ? null : validNow(now())
    if (!disposed && currentIdentity.value !== null) void loadCurrent()
  }

  function loadCurrent(): void {
    const current = currentIdentity.value
    if (current === null) return
    // Injected section transports retain direct fixture mode unless the
    // matching resolver is injected. Production resolves D1 and W1 first.
    const resolveDaily = current.frequency === '1d'
      && (options.fetchSection === undefined || options.fetchDailySnapshot !== undefined)
    const resolveWeekly = current.frequency === '1w'
      && (options.fetchSection === undefined || options.fetchWeeklySnapshot !== undefined)
    if (!resolveDaily && !resolveWeekly) {
      void loadChart()
      return
    }
    const controller = new AbortController()
    dailyController = controller
    const requestedGeneration = generation
    dailyLoading.value = true
    const fetchSnapshot = resolveWeekly
      ? (options.fetchWeeklySnapshot ?? ((identity: NewowProductIdentity, signal: AbortSignal) => getNewowWeeklySnapshot(identity, { signal })))
      : (options.fetchDailySnapshot ?? ((identity: NewowProductIdentity, signal: AbortSignal) => getNewowDailySnapshot(identity, { signal })))
    void fetchSnapshot(current, controller.signal).then(snapshot => {
      if (disposed || controller.signal.aborted || dailyController !== controller || generation !== requestedGeneration || currentIdentity.value !== current) return
      if (preservingCurrentChart) resetAll()
      preservingCurrentChart = false
      if (snapshot.frequency === '1w') weeklySnapshot.value = snapshot
      else dailySnapshot.value = snapshot
      asOf.value = snapshot.as_of
      void loadChart()
    }).catch(error => {
      if (disposed || controller.signal.aborted || dailyController !== controller || generation !== requestedGeneration) return
      dailyError.value = error instanceof NewowProductRequestError ? error.message : 'NEWOW_API_UNAVAILABLE'
      if (!preservingCurrentChart) {
        resources.chart.state.value = 'unavailable'
        resources.chart.error.value = dailyError.value
      }
      preservingCurrentChart = false
    }).finally(() => {
      if (dailyController === controller) { dailyController = null; dailyLoading.value = false }
    })
  }

  async function switchToHistorical(): Promise<void> {
    if (disposed || currentIdentity.value === null) return
    dailyController?.abort()
    dailyController = null
    resolverController?.abort()
    const controller = new AbortController()
    resolverController = controller
    const requestedIdentity = currentIdentity.value
    const resolverGeneration = generation
    historicalLoading.value = true
    historicalError.value = null
    try {
      const fetchHistorical = options.fetchHistoricalSnapshot ?? ((identity, signal) => getNewowHistoricalSnapshot(identity, { signal }))
      const resolved = await fetchHistorical(requestedIdentity, controller.signal)
      if (disposed || controller.signal.aborted || resolverController !== controller || generation !== resolverGeneration || currentIdentity.value !== requestedIdentity) return
      generation += 1
      resetAll()
      dailySnapshot.value = null
      weeklySnapshot.value = null
      historicalSnapshot.value = resolved
      // Preserve the server's exact microsecond cutoff; Date.toISOString() truncates it.
      asOf.value = resolved.as_of
      await loadChart()
    } catch (error) {
      if (!controller.signal.aborted && resolverController === controller && generation === resolverGeneration) historicalError.value = error instanceof NewowProductRequestError ? error.message : 'NEWOW_API_UNAVAILABLE'
    } finally {
      if (resolverController === controller) { resolverController = null; historicalLoading.value = false }
    }
  }

  function returnToCurrent(): void {
    resetCurrentGeneration(false)
  }

  function refreshCurrent(): void {
    resetCurrentGeneration(true)
  }

  function resetCurrentGeneration(preserveChart: boolean): void {
    resolverController?.abort()
    resolverController = null
    dailyController?.abort()
    dailyController = null
    generation += 1
    preservingCurrentChart = preserveChart && (dailySnapshot.value !== null || weeklySnapshot.value !== null)
      && resources.chart.data.value !== null
      && historicalSnapshot.value === null
    if (preservingCurrentChart) {
      for (const controller of controllers.values()) controller.abort()
      controllers.clear()
    } else {
      resetAll()
      dailySnapshot.value = null
      weeklySnapshot.value = null
    }
    dailyError.value = null
    dailyLoading.value = false
    historicalSnapshot.value = null
    historicalError.value = null
    historicalLoading.value = false
    if (!preservingCurrentChart) asOf.value = currentIdentity.value === null ? null : validNow(now())
    if (!disposed && currentIdentity.value !== null) loadCurrent()
  }

  async function loadChart(load: ChartLoadOptions = {}): Promise<void> {
    const common = requestCommon('chart')
    if (common === null) return
    await run({ ...common, section: 'chart', ...load })
  }

  async function loadAuxiliary(component: NewowAuxiliaryComponent, load: Pick<ChartLoadOptions, 'from' | 'through'> = {}): Promise<void> {
    const common = requestCommon('auxiliary')
    if (common === null) return
    const request = { ...common, section: 'auxiliary' as const, component, ...load }
    const cacheKey = auxiliaryCacheKey(request)
    const cached = auxiliaryCache.get(cacheKey)
    if (cached !== undefined) {
      auxiliaryCache.delete(cacheKey)
      auxiliaryCache.set(cacheKey, cached)
      restoreCachedAuxiliary(cached, request)
      return
    }
    await run(request)
  }

  async function loadNextChartPage(): Promise<void> {
    const current = resources.chart.data.value
    if (current?.section !== 'chart' || current.value === null || chartWindow === null || current.value.bars.length >= MAX_ACCUMULATED_CHART_ROWS) return
    const common = requestCommon('chart')
    if (common === null) return
    if (current.value.next_before !== null) {
      await run({ ...common, section: 'chart', from: chartWindow.from, through: chartWindow.through, chartLimit: chartPageLimit ?? 500, chartBefore: current.value.next_before })
    } else if (current.value.next_older_window != null && current.meta.snapshot_token !== null) {
      await run({ ...common, section: 'chart', snapshotToken: current.meta.snapshot_token, chartLimit: chartPageLimit ?? 500, chartOlderWindow: current.value.next_older_window })
    }
  }

  async function loadReference(load: ReferenceLoadOptions = {}): Promise<void> {
    const common = requestCommon('reference')
    if (common === null) return
    const requestedWindow = load.performanceSince === undefined && load.performanceThrough === undefined
      ? referenceWindow
      : { since: load.performanceSince ?? '', through: load.performanceThrough ?? '' }
    if (referenceWindow !== null && requestedWindow !== null && (referenceWindow.since !== requestedWindow.since || referenceWindow.through !== requestedWindow.through)) {
      invalidateSection('reference')
    }
    await run({
      ...common,
      section: 'reference',
      ...(requestedWindow === null ? {} : { performanceSince: requestedWindow.since, performanceThrough: requestedWindow.through }),
      ...(load.historyLimit === undefined ? {} : { historyLimit: load.historyLimit }),
    })
  }

  async function loadNextReferencePage(): Promise<void> {
    const current = resources.reference.data.value
    if (current?.section !== 'reference' || current.value === null || current.value.next_before === null || referenceWindow === null) return
    const common = requestCommon('reference')
    if (common === null) return
    await run({
      ...common,
      section: 'reference',
      performanceSince: referenceWindow.since,
      performanceThrough: referenceWindow.through,
      historyLimit: referencePageLimit ?? 50,
      historyBefore: current.value.next_before,
    })
  }

  async function loadExplanation(): Promise<void> {
    const common = requestCommon('explanation')
    if (common !== null) await run({ ...common, section: 'explanation' })
  }

  async function loadComparator(): Promise<void> {
    const common = requestCommon('comparator')
    if (common !== null) await run({ ...common, section: 'comparator' })
  }

  function requestCommon(section: NewowProductSection): Pick<NewowProductRequest, 'identity' | 'asOf' | 'snapshotToken'> | null {
    if (disposed || currentIdentity.value === null || asOf.value === null) return null
    const snapshotToken = compatibleToken(section)
    return {
      identity: currentIdentity.value,
      asOf: asOf.value,
      ...(snapshotToken === null ? {} : { snapshotToken }),
    }
  }

  async function run(initialRequest: NewowProductRequest): Promise<void> {
    const section = initialRequest.section
    const requestGeneration = generation
    const sectionGeneration = (sectionGenerations.get(section) ?? 0) + 1
    sectionGenerations.set(section, sectionGeneration)
    controllers.get(section)?.abort()
    const controller = new AbortController()
    controllers.set(section, controller)
    const resource = resources[section]
    resource.state.value = 'loading'
    resource.error.value = null
    let request = initialRequest
    let rebuilt = false
    try {
      while (true) {
        inFlightSnapshotTokens.set(section, request.snapshotToken ?? resource.data.value?.meta.snapshot_token ?? undefined)
        try {
          const response = await fetchSection(request, controller.signal)
          if (!isCurrent(section, requestGeneration, sectionGeneration, controller)) return
          accept(section, response, request)
          return
        } catch (error) {
          if (!isCurrent(section, requestGeneration, sectionGeneration, controller)) return
          if (!rebuilt && isRebuildable(error)) {
            rebuilt = true
            const rejectedToken = request.snapshotToken ?? resource.data.value?.meta.snapshot_token ?? undefined
            const auxiliaryRebuild = request.section === 'auxiliary' ? auxiliaryRebuildKey(request) : null
            const rebuildExhausted = auxiliaryRebuild !== null && auxiliaryRebuildAttempts.has(auxiliaryRebuild)
            const rebuildChartWindow = request.section !== 'auxiliary' || acceptedCurrentChartWindow.value
              ? {}
              : request.from !== undefined && request.through !== undefined
                ? { from: request.from, through: request.through }
                : null
            invalidateTokenDependents(rejectedToken, section)
            if (section === 'auxiliary') {
              if (rebuildExhausted || rebuildChartWindow === null) {
                failConflict(section, error instanceof NewowProductRequestError ? error.code : 'NEWOW_SNAPSHOT_GENERATION_CONFLICT')
                return
              }
              // Auxiliary responses are never retried without chart proof. Rebuild the
              // chart generation; the chart-window consumer may then issue one proven request.
              auxiliaryRebuildAttempts.add(auxiliaryRebuild!)
              invalidateSection('auxiliary')
              await loadChart(rebuildChartWindow)
              return
            }
            request = withoutGenerationBindings(request)
            continue
          }
          fail(section, error)
          return
        }
      }
    } finally {
      if (isCurrent(section, requestGeneration, sectionGeneration, controller)) {
        controllers.delete(section)
        inFlightSnapshotTokens.delete(section)
      }
    }
  }

  function accept(section: NewowProductSection, response: NewowProductSectionResponse, request: NewowProductRequest): void {
    if (response.section !== section) { failConflict(section, 'NEWOW_RESPONSE_INVALID'); return }
    if (section === 'auxiliary' && request.section === 'auxiliary') {
      const auxiliaryResponse = response as NewowProductSectionResponse<'auxiliary'>
      if (auxiliaryResponse.value !== null && auxiliaryResponse.value.component !== request.component) {
        failConflict(section, 'NEWOW_AUXILIARY_IDENTITY_CONFLICT')
        return
      }
    }
    const resource = resources[section]
    if (section === 'chart' && resource.data.value !== null && !sharedChartBarsAgree(resource.data.value, response)) {
      failConflict(section, 'NEWOW_SHARED_BAR_CONFLICT')
      return
    }
    if (section === 'chart' && response.section === 'chart' && response.value !== null) {
      const accepted = acceptChart(response, request)
      if (accepted === null) return
      const nextGeneration = chartGenerationSignature(response.meta)
      if (acceptedChartGenerationSignature !== null && acceptedChartGenerationSignature !== nextGeneration) invalidateChartDependents()
      // Only accepted request provenance can identify the current completed-day viewport.
      // Paging within it preserves provenance; explicit/older windows cannot claim current.
      if (request.section === 'chart' && request.chartBefore === undefined) {
        acceptedCurrentChartWindow.value = request.from === undefined && request.through === undefined
          && request.chartOlderWindow === undefined && historicalSnapshot.value === null
          && dailySnapshot.value?.freshness !== 'pending_update'
          && weeklySnapshot.value?.freshness !== 'pending_update'
        acceptedHistoricalChartWindow.value = !acceptedCurrentChartWindow.value
      }
      resource.data.value = accepted
      acceptedChartGenerationSignature = nextGeneration
    } else if (section === 'reference' && response.section === 'reference' && response.value !== null) {
      const accepted = acceptReference(response, request)
      if (accepted === null) return
      resource.data.value = accepted
      if (chartReference.value === null) chartReference.value = accepted
    } else {
      resource.data.value = response
    }
    resource.state.value = response.status.status
    resource.error.value = null
    if (section === 'auxiliary' && request.section === 'auxiliary') {
      auxiliaryRebuildAttempts.delete(auxiliaryRebuildKey(request))
    }
    if (section === 'auxiliary' && request.section === 'auxiliary' && response.section === 'auxiliary' && response.value !== null) {
      acceptedAuxiliaryWindow.value = request.from !== undefined && request.through !== undefined
        ? { from: request.from, through: request.through }
        : null
      if (response.status.status === 'ready') cacheAuxiliary(response, request)
    }
  }

  function acceptChart(response: NewowProductSectionResponse<'chart'>, request: NewowProductRequest): NewowProductSectionResponse<'chart'> | null {
    const value = response.value!
    const fingerprint = chartIdentity(response.meta, value)
    const existing = resources.chart.data.value
    const prior = existing?.section === 'chart' ? existing : null
    const priorValue = prior?.value ?? null
    const isPage = request.section === 'chart' && request.chartBefore !== undefined
    const isOlder = request.section === 'chart' && request.chartOlderWindow !== undefined
    if (isPage && chartFingerprint !== fingerprint) {
      failConflict('chart', 'NEWOW_CHART_FINGERPRINT_CONFLICT')
      return null
    }
    if (isOlder && (prior === null || priorValue === null || priorValue.next_before !== null
      || priorValue.next_older_window !== request.chartOlderWindow
      || request.snapshotToken !== prior.meta.snapshot_token || prior.meta.snapshot_token === null
      || chartGenerationSignature(prior.meta) !== chartGenerationSignature(response.meta)
      || value.chart_through >= priorValue.chart_from
      || (value.frames.length > 0 && priorValue.frames.length > 0
        && Date.parse(value.frames.at(-1)!.bar_end) >= Date.parse(priorValue.frames[0]!.bar_end)))) {
      failConflict('chart', 'NEWOW_CHART_WINDOW_CONFLICT')
      return null
    }
    chartWindow = { from: value.chart_from, through: value.chart_through }
    chartFingerprint = fingerprint
    if ((!isPage && !isOlder) || priorValue === null) {
      chartPageLimit = request.section === 'chart' ? request.chartLimit ?? 500 : 500
      return response
    }
    const bars = mergeTimelineUnique(value.bars, priorValue.bars, (item) => item.bar_end)
    const frames = mergeTimelineUnique(value.frames, priorValue.frames, (item) => item.bar_end)
    const actions = mergeUnique(value.actions, priorValue.actions, (item) => item.signal_id)
    const hints = mergeUnique(value.hints, priorValue.hints, (item) => item.hint_id)
    let trendChannel: NewowChartValue['trend_channel'] = null
    let trendChannelConflict = false
    if (value.trend_channel === null || priorValue.trend_channel === null) {
      trendChannelConflict = value.trend_channel !== priorValue.trend_channel
    } else if (
      value.trend_channel.kind !== priorValue.trend_channel.kind
      || value.trend_channel.period !== priorValue.trend_channel.period
      || value.trend_channel.formula_version !== priorValue.trend_channel.formula_version
    ) {
      trendChannelConflict = true
    } else {
      const points = mergeTimelineUnique(
        value.trend_channel.points,
        priorValue.trend_channel.points,
        (item) => item.bar_end,
      )
      if (points === null) trendChannelConflict = true
      else trendChannel = { ...value.trend_channel, points }
    }
    if ([bars, frames, actions, hints].some((items) => items === null) || trendChannelConflict) {
      failConflict('chart', 'NEWOW_CHART_PAGE_CONFLICT')
      return null
    }
    actions!.sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end) || left.sequence - right.sequence)
    hints!.sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end) || (left.sequence ?? -1) - (right.sequence ?? -1))
    const boundedBars = bars!.slice(-MAX_ACCUMULATED_CHART_ROWS)
    const retainedEnds = new Set(boundedBars.map((item) => item.bar_end))
    const boundedFrames = frames!.filter((item) => retainedEnds.has(item.bar_end))
    const boundedActions = actions!.filter((item) => retainedEnds.has(item.bar_end))
    const boundedHints = hints!.filter((item) => retainedEnds.has(item.bar_end))
    const boundedTrendChannel = trendChannel === null ? null : {
      ...trendChannel,
      points: trendChannel.points.filter((item) => retainedEnds.has(item.bar_end)),
    }
    if (boundedTrendChannel !== null && boundedTrendChannel.points.length !== boundedBars.length) {
      failConflict('chart', 'NEWOW_CHART_PAGE_CONFLICT')
      return null
    }
    return {
      meta: response.meta,
      section: 'chart',
      status: prior!.status,
      value: {
        ...value,
        bars: boundedBars, frames: boundedFrames, trend_channel: boundedTrendChannel,
        actions: boundedActions, hints: boundedHints,
        diagnostics: [...new Set([...priorValue.diagnostics, ...value.diagnostics])],
        next_before: bars!.length >= MAX_ACCUMULATED_CHART_ROWS ? null : value.next_before,
        next_older_window: bars!.length >= MAX_ACCUMULATED_CHART_ROWS ? null : value.next_older_window,
      },
    }
  }

  function acceptReference(response: NewowProductSectionResponse<'reference'>, request: NewowProductRequest): NewowProductSectionResponse<'reference'> | null {
    const value = response.value!
    const fingerprint = referenceIdentity(response.meta, value)
    const existing = resources.reference.data.value
    const isPage = request.section === 'reference' && request.historyBefore !== undefined
    if (isPage && referenceFingerprint !== fingerprint) {
      failConflict('reference', 'NEWOW_REFERENCE_FINGERPRINT_CONFLICT')
      return null
    }
    const priorValue = existing?.section === 'reference' ? existing.value : null
    if (priorValue !== null && referenceFingerprint === fingerprint) {
      if (duplicateReferenceConflict(priorValue.items, value.items) || JSON.stringify(priorValue.summary) !== JSON.stringify(value.summary)
        || JSON.stringify(priorValue.curve_trades) !== JSON.stringify(value.curve_trades)) {
        failConflict('reference', 'NEWOW_REFERENCE_INPUT_CONFLICT')
        return null
      }
    }
    referenceWindow = { since: value.performance_since, through: value.performance_through }
    referenceFingerprint = fingerprint
    if (!isPage || priorValue === null) {
      try { referencePages.first(fingerprint, value.items, value.next_before) }
      catch { failConflict('reference', 'NEWOW_REFERENCE_INPUT_CONFLICT'); return null }
      referencePageLimit = request.section === 'reference' ? request.historyLimit ?? 50 : 50
      return response
    }
    let mergedItems: NewowReferenceValue['items']
    try { mergedItems = referencePages.append(fingerprint, request.historyBefore!, value.items, value.next_before) }
    catch { failConflict('reference', 'NEWOW_REFERENCE_FINGERPRINT_CONFLICT'); return null }
    return {
      ...response,
      value: {
        ...value,
        summary: priorValue.summary,
        items: mergedItems,
        next_before: referencePages.cursor,
      },
    }
  }

  function fail(section: NewowProductSection, error: unknown): void {
    const resource = resources[section]
    const requestError = error instanceof NewowProductRequestError
      ? error
      : new NewowProductRequestError('NEWOW_API_UNAVAILABLE', 'unavailable')
    resource.error.value = requestError.message
    if (requestError.classification === 'conflict' || requestError.classification === 'response_invalid') {
      failConflict(section, requestError.code)
      return
    }
    if (requestError.classification === 'busy' || requestError.classification === 'cancelled') {
      resource.state.value = resource.data.value === null ? requestError.classification : 'stale'
      return
    }
    resource.state.value = resource.data.value === null ? 'unavailable' : 'stale'
  }

  function failConflict(section: NewowProductSection, code: string): void {
    invalidateAuxiliaryCache()
    const dependent = section === 'chart' || section === 'reference' || section === 'explanation'
      ? (['chart', 'reference', 'explanation', 'auxiliary', 'comparator'] as const)
      : ([section] as const)
    for (const candidate of dependent) invalidateSection(candidate, { state: 'input_conflict', error: code })
  }

  function compatibleToken(section: NewowProductSection): string | null {
    for (const candidate of ['chart', 'reference', 'explanation', 'auxiliary', 'comparator'] as const) {
      if (candidate === section) continue
      const token = resources[candidate].data.value?.meta.snapshot_token
      if (token) return token
    }
    return null
  }

  function invalidateTokenDependents(token: string | undefined, currentSection: NewowProductSection): void {
    // Collect before clearing tokens/data: a loaded match invalidates the whole section,
    // including a replacement request that may already carry a different token.
    const affected = new Set<NewowProductSection>([currentSection, 'auxiliary'])
    if (token !== undefined) {
      for (const section of ['chart', 'reference', 'explanation', 'auxiliary', 'comparator'] as const) {
        if (inFlightSnapshotTokens.get(section) === token || resources[section].data.value?.meta.snapshot_token === token) affected.add(section)
      }
    }
    invalidateAuxiliaryCache()
    for (const section of affected) {
      invalidateSection(section, section === currentSection ? { state: 'loading', preserveRebuildRequest: true } : {})
    }
  }

  function invalidateChartDependents(): void {
    chartReference.value = null
    invalidateAuxiliaryCache()
    for (const section of ['auxiliary', 'reference', 'explanation', 'comparator'] as const) invalidateSection(section)
  }

  function invalidateSection(section: NewowProductSection, options: {
    state?: NewowResourceLifecycle
    error?: string
    preserveRebuildRequest?: boolean
  } = {}): void {
    // Only the current, once-only 409 rebuild may retain its request identity.
    // Generation and controller identity also guard fetch implementations that ignore abort.
    if (!options.preserveRebuildRequest) {
      sectionGenerations.set(section, (sectionGenerations.get(section) ?? 0) + 1)
      controllers.get(section)?.abort()
      controllers.delete(section)
    }
    inFlightSnapshotTokens.delete(section)
    resources[section].data.value = null
    if (section === 'auxiliary') acceptedAuxiliaryWindow.value = null
    if (section === 'chart' || section === 'reference') resetPagination(section)
    resources[section].state.value = options.state ?? 'not_requested'
    resources[section].error.value = options.error ?? null
  }

  function resetPagination(section: 'chart' | 'reference'): void {
    if (section === 'chart') {
      chartReference.value = null
      acceptedCurrentChartWindow.value = false
      acceptedHistoricalChartWindow.value = false
      chartWindow = null
      chartFingerprint = null
      acceptedChartGenerationSignature = null
      chartPageLimit = null
      return
    }
    referenceWindow = null
    referenceFingerprint = null
    referencePages.reset()
    referencePageLimit = null
  }

  function isCurrent(section: NewowProductSection, requestGeneration: number, sectionGeneration: number, controller: AbortController): boolean {
    return !disposed && requestGeneration === generation && sectionGenerations.get(section) === sectionGeneration && controllers.get(section) === controller && !controller.signal.aborted
  }

  function dispose(): void {
    if (disposed) return
    disposed = true
    generation += 1
    resolverController?.abort()
    resolverController = null
    dailyController?.abort()
    dailyController = null
    stopWatch()
    resetAll()
    currentIdentity.value = null
    asOf.value = null
  }

  const referenceChartCompatible = computed(() => {
    const chart = resources.chart.data.value
    const reference = resources.reference.data.value
    const token = chart?.meta.snapshot_token
    return chart !== null && reference !== null && token !== null && token !== undefined
      && reference.meta.snapshot_token === token
  })

  const explanationChartCompatible = computed(() => {
    const chart = resources.chart.data.value
    const explanation = resources.explanation.data.value
    return chart !== null && explanation !== null && chart.meta.snapshot_token !== null
      && chartGenerationSignature(chart.meta) === chartGenerationSignature(explanation.meta)
  })

  const currentChartWindow = computed(() => acceptedCurrentChartWindow.value
    && historicalSnapshot.value === null && resources.chart.state.value === 'ready'
    && resources.chart.data.value?.section === 'chart' && resources.chart.data.value.value !== null)
  const historicalChartWindow = computed(() => acceptedHistoricalChartWindow.value
    && resources.chart.data.value?.section === 'chart' && resources.chart.data.value.value !== null)

  return {
    chartReference: readonly(chartReference),
    acceptedAuxiliaryWindow: readonly(acceptedAuxiliaryWindow),
    currentChartWindow: readonly(currentChartWindow),
    historicalChartWindow: readonly(historicalChartWindow),
    explanationChartCompatible: readonly(explanationChartCompatible),
    identity: readonly(currentIdentity),
    asOf: readonly(asOf),
    historicalSnapshot: readonly(historicalSnapshot),
    dailySnapshot: readonly(dailySnapshot),
    weeklySnapshot: readonly(weeklySnapshot),
    dailyError: readonly(dailyError),
    dailyLoading: readonly(dailyLoading),
    historicalError: readonly(historicalError),
    historicalLoading: readonly(historicalLoading),
    sections: resources,
    referenceChartCompatible: readonly(referenceChartCompatible),
    loadChart, loadNextChartPage, loadAuxiliary, loadReference, loadNextReferencePage, loadExplanation, loadComparator, switchToHistorical, returnToCurrent, refreshCurrent, dispose,
  }

  function resetAll(): void {
    for (const section of ['chart', 'auxiliary', 'reference', 'explanation', 'comparator'] as const) invalidateSection(section)
    invalidateAuxiliaryCache()
    auxiliaryRebuildAttempts.clear()
  }
  function cacheAuxiliary(response: NewowProductSectionResponse<'auxiliary'>, request: Extract<NewowProductRequest, { section: 'auxiliary' }>): void {
    if (response.value?.component === undefined) return
    const key = auxiliaryCacheKey(request)
    auxiliaryCache.delete(key)
    if (auxiliaryCache.size >= 4) {
      const oldest = auxiliaryCache.keys().next().value
      if (oldest !== undefined) auxiliaryCache.delete(oldest)
    }
    auxiliaryCache.set(key, response)
  }
  function restoreCachedAuxiliary(response: NewowProductSectionResponse<'auxiliary'>, request: Extract<NewowProductRequest, { section: 'auxiliary' }>): void {
    const section = 'auxiliary' as const
    invalidateSection(section)
    resources[section].data.value = response
    resources[section].state.value = response.status.status
    resources[section].error.value = null
    acceptedAuxiliaryWindow.value = request.from !== undefined && request.through !== undefined
      ? { from: request.from, through: request.through }
      : null
  }
  function invalidateAuxiliaryCache(): void { auxiliaryCache.clear() }
  function auxiliaryRebuildKey(request: Extract<NewowProductRequest, { section: 'auxiliary' }>): string {
    return JSON.stringify([generation, request.identity.product, request.identity.strategy,
      request.identity.frequency, request.identity.seriesKind, request.asOf, request.component])
  }
}

function auxiliaryCacheKey(request: Extract<NewowProductRequest, { section: 'auxiliary' }>): string {
  return JSON.stringify([request.component, request.from ?? null, request.through ?? null, request.snapshotToken ?? null])
}

function createResource(): SectionResource {
  return { data: shallowRef<NewowProductSectionResponse | null>(null), state: shallowRef<NewowResourceLifecycle>('not_requested'), error: shallowRef<string | null>(null) }
}

function validatedIdentity(identity: MarketDetailIdentity | null): NewowProductIdentity | null {
  if (identity === null || identity.view !== 'newow' || !/^[a-z]+$/.test(identity.symbol) || identity.seriesKind !== 'actual_dominant' || identity.contract !== undefined || identity.strategy === undefined || !NEWOW_STRATEGY_SET.has(identity.strategy) || !NEWOW_FREQUENCY_SET.has(identity.frequency)) return null
  return { product: identity.symbol, strategy: identity.strategy, frequency: identity.frequency as NewowProductIdentity['frequency'], seriesKind: 'actual_dominant' }
}

function validNow(value: Date | string): string {
  if (typeof value === 'string' && previewInstant(value) !== null) return value
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) throw new Error('Newow generation clock is invalid')
  return value.toISOString()
}

function isRebuildable(error: unknown): boolean {
  return error instanceof NewowProductRequestError
    && error.classification === 'conflict'
    && (error.code.includes('SNAPSHOT_GENERATION') || error.code.includes('CURSOR'))
}

function withoutGenerationBindings(request: NewowProductRequest): NewowProductRequest {
  const copy = { ...request } as Record<string, unknown>
  delete copy.snapshotToken
  delete copy.historyBefore
  delete copy.chartBefore
  delete copy.chartOlderWindow
  return copy as unknown as NewowProductRequest
}

function chartIdentity(meta: NewowProductSectionResponse['meta'], value: NewowChartValue): string {
  return JSON.stringify([
    meta.identity.product, meta.identity.strategy, meta.identity.frequency, meta.identity.series_kind,
    meta.identity.profile_id, meta.identity.formula_versions, meta.as_of, meta.input_content_sha256, meta.data_revision_identity,
    value.chart_from, value.chart_through, value.page_identity,
  ])
}

function chartGenerationSignature(meta: NewowProductSectionResponse['meta']): string {
  // A server-validated token spans section/display windows; their input hashes
  // legitimately differ. Without that proof retain strict fingerprint isolation.
  return JSON.stringify([
    meta.schema_version, meta.snapshot_token,
    meta.identity.product, meta.identity.strategy, meta.identity.frequency, meta.identity.series_kind,
    meta.identity.profile_id, meta.identity.formula_versions,
    meta.as_of, meta.snapshot_token === null ? meta.input_content_sha256 : null, meta.data_revision_identity,
    meta.reference_model_version, meta.futures_adaptation_version,
  ])
}

function mergeUnique<T>(left: readonly T[], right: readonly T[], key: (item: T) => string): T[] | null {
  const byKey = new Map<string, T>()
  for (const item of [...left, ...right]) {
    const identity = key(item)
    const existing = byKey.get(identity)
    if (existing !== undefined && JSON.stringify(existing) !== JSON.stringify(item)) return null
    byKey.set(identity, item)
  }
  return [...byKey.values()]
}

function mergeTimelineUnique<T>(left: readonly T[], right: readonly T[], key: (item: T) => string): T[] | null {
  const merged = mergeUnique(left, right, key)
  if (merged === null) return null
  return merged.sort((a, b) => Date.parse(key(a)) - Date.parse(key(b)))
}

function referenceIdentity(meta: NewowProductSectionResponse['meta'], value: NewowReferenceValue): string {
  return JSON.stringify([
    meta.identity.product, meta.identity.strategy, meta.identity.frequency, meta.identity.series_kind,
    meta.identity.profile_id, meta.identity.formula_versions, meta.as_of, meta.data_revision_identity, meta.reference_model_version,
    meta.futures_adaptation_version, value.performance_since, value.performance_through,
    value.actual_available_through, value.reference_cutoff, value.reference_input_sha256,
    value.storage_mode ?? 'legacy',
  ])
}

function duplicateReferenceConflict(left: NewowReferenceValue['items'], right: NewowReferenceValue['items']): boolean {
  const known = new Map(left.map((item) => [item.reference_trade_id, JSON.stringify(item)]))
  return right.some((item) => known.has(item.reference_trade_id) && known.get(item.reference_trade_id) !== JSON.stringify(item))
}
