import { computed, readonly, shallowRef, watch, type Ref, type ShallowRef } from 'vue'

import { getNewowProductSection, NewowProductRequestError } from '../api/newowProduct.ts'
import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import {
  NEWOW_PRODUCT_FREQUENCIES,
  NEWOW_PRODUCT_STRATEGIES,
} from '../types/newowProduct.ts'
import type {
  NewowAuxiliaryComponent,
  NewowChartValue,
  NewowProductIdentity,
  NewowProductRequest,
  NewowProductSection,
  NewowProductSectionResponse,
  NewowReferenceValue,
  NewowResourceLifecycle,
} from '../types/newowProduct.ts'
import { sharedChartBarsAgree } from '../utils/newowProductTypes.ts'

type FetchSection = (request: NewowProductRequest, signal: AbortSignal) => Promise<NewowProductSectionResponse>

const MAX_ACCUMULATED_CHART_ROWS = 3000
const MAX_ACCUMULATED_REFERENCE_TRADES = 300
const NEWOW_STRATEGY_SET = new Set<string>(NEWOW_PRODUCT_STRATEGIES)
const NEWOW_FREQUENCY_SET = new Set<string>(NEWOW_PRODUCT_FREQUENCIES)

export interface UseNewowProductOptions {
  readonly identity: Readonly<Ref<MarketDetailIdentity | null>>
  readonly fetchSection?: FetchSection
  readonly now?: () => Date
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
  const now = options.now ?? (() => new Date())
  const currentIdentity = shallowRef<NewowProductIdentity | null>(null)
  const asOf = shallowRef<string | null>(null)
  const resources = Object.fromEntries(
    (['chart', 'auxiliary', 'reference', 'explanation', 'comparator'] as const)
      .map((section) => [section, createResource()]),
  ) as Record<NewowProductSection, SectionResource>
  const controllers = new Map<NewowProductSection, AbortController>()
  const inFlightSnapshotTokens = new Map<NewowProductSection, string | undefined>()
  const sectionGenerations = new Map<NewowProductSection, number>()
  const auxiliaryCache = new Map<string, NewowProductSectionResponse<'auxiliary'>>()
  let generation = 0
  let disposed = false
  let chartWindow: { from: string; through: string } | null = null
  let chartFingerprint: string | null = null
  let acceptedChartGenerationSignature: string | null = null
  let chartPageLimit: number | null = null
  let referenceWindow: { since: string; through: string } | null = null
  let referenceFingerprint: string | null = null
  let referencePageLimit: number | null = null

  const identityKey = computed(() => {
    const identity = options.identity.value
    return identity === null ? '' : [identity.view, identity.symbol, identity.strategy ?? '', identity.seriesKind, identity.frequency, identity.contract ?? ''].join('|')
  })

  const stopWatch = watch(identityKey, () => replaceIdentity(), { immediate: true, flush: 'sync' })

  function replaceIdentity(): void {
    generation += 1
    abortAll()
    resetAll()
    currentIdentity.value = validatedIdentity(options.identity.value)
    asOf.value = currentIdentity.value === null ? null : validNow(now())
    if (!disposed && currentIdentity.value !== null) void loadChart()
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
      restoreCachedAuxiliary(cached)
      return
    }
    await run(request)
  }

  async function loadNextChartPage(): Promise<void> {
    const current = resources.chart.data.value
    if (current?.section !== 'chart' || current.value === null || current.value.next_before === null || chartWindow === null) return
    const common = requestCommon('chart')
    if (common === null) return
    await run({ ...common, section: 'chart', from: chartWindow.from, through: chartWindow.through, chartLimit: chartPageLimit ?? 500, chartBefore: current.value.next_before })
  }

  async function loadReference(load: ReferenceLoadOptions = {}): Promise<void> {
    const common = requestCommon('reference')
    if (common === null) return
    const requestedWindow = load.performanceSince === undefined && load.performanceThrough === undefined
      ? referenceWindow
      : { since: load.performanceSince ?? '', through: load.performanceThrough ?? '' }
    if (referenceWindow !== null && requestedWindow !== null && (referenceWindow.since !== requestedWindow.since || referenceWindow.through !== requestedWindow.through)) {
      clearResource('reference')
      referenceFingerprint = null
      referenceWindow = null
      referencePageLimit = null
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
            invalidateAuxiliaryCache()
            invalidateTokenDependents(rejectedToken, section)
            if (section === 'reference' || section === 'chart' || section === 'auxiliary') {
              clearResource(section)
              if (section === 'reference' || section === 'chart') resetPagination(section)
              resources[section].state.value = 'loading'
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
      resource.data.value = accepted
      acceptedChartGenerationSignature = nextGeneration
    } else if (section === 'reference' && response.section === 'reference' && response.value !== null) {
      const accepted = acceptReference(response, request)
      if (accepted === null) return
      resource.data.value = accepted
    } else {
      resource.data.value = response
    }
    resource.state.value = response.status.status
    resource.error.value = null
    if (section === 'auxiliary' && request.section === 'auxiliary' && response.section === 'auxiliary' && response.status.status === 'ready' && response.value !== null) {
      cacheAuxiliary(response, request)
    }
  }

  function acceptChart(response: NewowProductSectionResponse<'chart'>, request: NewowProductRequest): NewowProductSectionResponse<'chart'> | null {
    const value = response.value!
    const fingerprint = chartIdentity(response.meta, value)
    const existing = resources.chart.data.value
    const prior = existing?.section === 'chart' ? existing : null
    const priorValue = prior?.value ?? null
    const isPage = request.section === 'chart' && request.chartBefore !== undefined
    if (isPage && chartFingerprint !== fingerprint) {
      failConflict('chart', 'NEWOW_CHART_FINGERPRINT_CONFLICT')
      return null
    }
    chartWindow = { from: value.chart_from, through: value.chart_through }
    chartFingerprint = fingerprint
    if (!isPage || priorValue === null) {
      chartPageLimit = request.section === 'chart' ? request.chartLimit ?? 500 : 500
      return response
    }
    const bars = mergeUnique(value.bars, priorValue.bars, (item) => item.bar_end, 'chart bars')
    const frames = mergeUnique(value.frames, priorValue.frames, (item) => item.bar_end, 'chart frames')
    const actions = mergeUnique(value.actions, priorValue.actions, (item) => item.signal_id, 'chart actions')
    const hints = mergeUnique(value.hints, priorValue.hints, (item) => item.hint_id, 'chart hints')
    if ([bars, frames, actions, hints].some((items) => items === null)) {
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
    return {
      meta: response.meta,
      section: 'chart',
      status: prior!.status,
      value: {
        ...value,
        bars: boundedBars, frames: boundedFrames, actions: boundedActions, hints: boundedHints,
        diagnostics: [...new Set([...priorValue.diagnostics, ...value.diagnostics])],
        next_before: bars!.length >= MAX_ACCUMULATED_CHART_ROWS ? null : value.next_before,
      },
    }
  }

  function acceptReference(response: NewowProductSectionResponse<'reference'>, request: NewowProductRequest): NewowProductSectionResponse | null {
    const value = response.value!
    const fingerprint = referenceIdentity(response.meta, value)
    const existing = resources.reference.data.value
    const isPage = request.section === 'reference' && request.historyBefore !== undefined
    if (isPage && referenceFingerprint !== fingerprint) {
      failConflict('reference', 'NEWOW_REFERENCE_FINGERPRINT_CONFLICT')
      return null
    }
    if (!isPage && referenceFingerprint !== null && referenceFingerprint !== fingerprint) clearResource('reference')
    const priorValue = existing?.section === 'reference' ? existing.value : null
    if (priorValue !== null && referenceFingerprint === fingerprint) {
      const duplicateConflict = duplicateReferenceConflict(priorValue.items, value.items)
      if (duplicateConflict || JSON.stringify(priorValue.summary) !== JSON.stringify(value.summary)) {
        failConflict('reference', 'NEWOW_REFERENCE_INPUT_CONFLICT')
        return null
      }
    }
    referenceWindow = { since: value.performance_since, through: value.performance_through }
    referenceFingerprint = fingerprint
    if (!isPage || priorValue === null) {
      referencePageLimit = request.section === 'reference' ? request.historyLimit ?? 50 : 50
      return response
    }
    const ids = new Set(priorValue.items.map((item) => item.reference_trade_id))
    const appended = value.items.filter((item) => !ids.has(item.reference_trade_id))
    const mergedItems = [...priorValue.items, ...appended]
    return {
      ...response,
      value: {
        ...value,
        summary: priorValue.summary,
        items: mergedItems.slice(0, MAX_ACCUMULATED_REFERENCE_TRADES),
        next_before: mergedItems.length >= MAX_ACCUMULATED_REFERENCE_TRADES ? null : value.next_before,
      },
    }
  }

  function fail(section: NewowProductSection, error: unknown): void {
    const resource = resources[section]
    const requestError = error instanceof NewowProductRequestError
      ? error
      : new NewowProductRequestError('NEWOW_API_UNAVAILABLE', 'unavailable')
    resource.error.value = requestError.code
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
      ? (['chart', 'reference', 'explanation'] as const)
      : ([section] as const)
    for (const candidate of dependent) {
      clearResource(candidate)
      resources[candidate].state.value = 'input_conflict'
      resources[candidate].error.value = code
    }
    if (dependent.some((candidate) => candidate === 'reference')) { referenceWindow = null; referenceFingerprint = null; referencePageLimit = null }
    if (dependent.some((candidate) => candidate === 'chart')) { chartWindow = null; chartFingerprint = null; chartPageLimit = null }
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
    invalidateAuxiliaryCache()
    if (currentSection !== 'auxiliary') {
      controllers.get('auxiliary')?.abort()
      sectionGenerations.set('auxiliary', (sectionGenerations.get('auxiliary') ?? 0) + 1)
      controllers.delete('auxiliary')
      inFlightSnapshotTokens.delete('auxiliary')
      clearResource('auxiliary')
    }
    if (token === undefined) return
    for (const section of ['chart', 'reference', 'explanation', 'auxiliary', 'comparator'] as const) {
      const inFlightMatches = section !== currentSection && inFlightSnapshotTokens.get(section) === token
      const loadedMatches = resources[section].data.value?.meta.snapshot_token === token
      if (!inFlightMatches && !loadedMatches) continue
      if (inFlightMatches) {
        controllers.get(section)?.abort()
        sectionGenerations.set(section, (sectionGenerations.get(section) ?? 0) + 1)
        controllers.delete(section)
        inFlightSnapshotTokens.delete(section)
      }
      clearResource(section)
      if (section === 'chart' || section === 'reference') resetPagination(section)
    }
  }

  function invalidateChartDependents(): void {
    invalidateAuxiliaryCache()
    for (const section of ['auxiliary', 'reference', 'explanation', 'comparator'] as const) {
      controllers.get(section)?.abort()
      sectionGenerations.set(section, (sectionGenerations.get(section) ?? 0) + 1)
      controllers.delete(section)
      inFlightSnapshotTokens.delete(section)
      clearResource(section)
    }
    resetPagination('reference')
  }

  function resetPagination(section: 'chart' | 'reference'): void {
    if (section === 'chart') {
      chartWindow = null
      chartFingerprint = null
      acceptedChartGenerationSignature = null
      chartPageLimit = null
      return
    }
    referenceWindow = null
    referenceFingerprint = null
    referencePageLimit = null
  }

  function isCurrent(section: NewowProductSection, requestGeneration: number, sectionGeneration: number, controller: AbortController): boolean {
    return !disposed && requestGeneration === generation && sectionGenerations.get(section) === sectionGeneration && controllers.get(section) === controller && !controller.signal.aborted
  }

  function dispose(): void {
    if (disposed) return
    disposed = true
    generation += 1
    abortAll()
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

  return {
    identity: readonly(currentIdentity),
    asOf: readonly(asOf),
    sections: resources,
    referenceChartCompatible: readonly(referenceChartCompatible),
    loadChart, loadNextChartPage, loadAuxiliary, loadReference, loadNextReferencePage, loadExplanation, loadComparator, dispose,
  }

  function abortAll(): void { for (const controller of controllers.values()) controller.abort(); controllers.clear(); inFlightSnapshotTokens.clear() }
  function resetAll(): void { for (const section of ['chart', 'auxiliary', 'reference', 'explanation', 'comparator'] as const) clearResource(section); invalidateAuxiliaryCache(); chartWindow = null; chartFingerprint = null; acceptedChartGenerationSignature = null; chartPageLimit = null; referenceWindow = null; referenceFingerprint = null; referencePageLimit = null }
  function clearResource(section: NewowProductSection): void { resources[section].data.value = null; resources[section].state.value = 'not_requested'; resources[section].error.value = null }
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
  function restoreCachedAuxiliary(response: NewowProductSectionResponse<'auxiliary'>): void {
    const section = 'auxiliary' as const
    sectionGenerations.set(section, (sectionGenerations.get(section) ?? 0) + 1)
    controllers.get(section)?.abort()
    controllers.delete(section)
    inFlightSnapshotTokens.delete(section)
    resources[section].data.value = response
    resources[section].state.value = response.status.status
    resources[section].error.value = null
  }
  function invalidateAuxiliaryCache(): void { auxiliaryCache.clear() }
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

function validNow(value: Date): string {
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

function mergeUnique<T>(left: readonly T[], right: readonly T[], key: (item: T) => string, field: string): T[] | null {
  const byKey = new Map<string, T>()
  for (const item of [...left, ...right]) {
    const identity = key(item)
    const existing = byKey.get(identity)
    if (existing !== undefined && JSON.stringify(existing) !== JSON.stringify(item)) return null
    byKey.set(identity, item)
  }
  const result = [...byKey.values()]
  if (field === 'chart bars' || field === 'chart frames') result.sort((a, b) => Date.parse(key(a)) - Date.parse(key(b)))
  return result
}

function referenceIdentity(meta: NewowProductSectionResponse['meta'], value: NewowReferenceValue): string {
  return JSON.stringify([
    meta.identity.product, meta.identity.strategy, meta.identity.frequency, meta.identity.series_kind,
    meta.identity.profile_id, meta.identity.formula_versions, meta.as_of, meta.data_revision_identity, meta.reference_model_version,
    meta.futures_adaptation_version, value.performance_since, value.performance_through,
    value.actual_available_through, value.reference_cutoff, value.reference_input_sha256,
  ])
}

function duplicateReferenceConflict(left: NewowReferenceValue['items'], right: NewowReferenceValue['items']): boolean {
  const known = new Map(left.map((item) => [item.reference_trade_id, JSON.stringify(item)]))
  return right.some((item) => known.has(item.reference_trade_id) && known.get(item.reference_trade_id) !== JSON.stringify(item))
}
