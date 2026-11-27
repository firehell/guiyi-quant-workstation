import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { candidatePreview } from '../utils/candidatePreview.ts'
import {
  marketChartStudyBaseExpired, marketChartStudyIssue, marketChartStudyRequest, marketChartStudyTailRequest,
  projectMarketChartStudyDisplay, projectMarketChartStudyTail,
  type MarketChartStudyContext, type MarketChartStudyDisplay, type MarketChartStudyIssue,
  type MarketChartStudyPreview, type MarketChartStudyTailDemand, type MarketStudySelection,
} from '../utils/marketChartStudies.ts'
import type { BarData } from '../types/market.ts'

const MIN_TAIL_INTERVAL_MS = 250

export function useMarketChartStudies(
  context: () => MarketChartStudyContext | null,
  bars: () => readonly BarData[],
  selection: () => readonly MarketStudySelection[],
) {
  const visible = ref(typeof document === 'undefined' || document.visibilityState !== 'hidden')
  const syncVisibility = () => { visible.value = document.visibilityState !== 'hidden' }
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', syncVisibility)
    onScopeDispose(() => document.removeEventListener('visibilitychange', syncVisibility))
  }
  const demand = computed(() => {
    const market = context()
    if (!market || candidatePreview.enabled || market.revisionPending.value) return null
    return marketChartStudyRequest(market.identity, selection(), bars(), market.revision.value)
  })
  const history = shallowRef<{ key: string; display: MarketChartStudyDisplay } | null>(null)
  const canonical = computed(() => history.value?.key === demand.value?.key ? history.value?.display ?? null : null)
  const canonicalIssue = shallowRef<MarketChartStudyIssue | null>(null)
  const baseRefresh = ref(0)
  const baseLoading = ref(false)
  let recoveredBase: string | null = null

  watch([() => demand.value?.key, visible, baseRefresh], async ([_key, isVisible], _old, onCleanup) => {
    const current = demand.value
    canonicalIssue.value = null
    baseLoading.value = false
    if (!current) {
      history.value = null
      recoveredBase = null
      return
    }
    if (history.value?.key !== current.key) history.value = null
    if (!isVisible || current.query.series_kind === 'continuous') return
    const controller = new AbortController()
    const isCurrent = () => !controller.signal.aborted && visible.value && demand.value?.key === current.key
    onCleanup(() => controller.abort())
    baseLoading.value = true
    try {
      const { getMarketChartStudyDisplay } = await import('../api/market')
      if (!isCurrent()) return
      const payload = await getMarketChartStudyDisplay(current.query, controller.signal)
      if (!isCurrent()) return
      const display = projectMarketChartStudyDisplay(payload, current)
      history.value = display ? { key: current.key, display } : null
    } catch (error) {
      if (isCurrent()) {
        canonicalIssue.value = marketChartStudyIssue(error)
        if (history.value?.key !== current.key) history.value = null
      }
    } finally {
      if (isCurrent()) baseLoading.value = false
    }
  }, { immediate: true })

  const wanted = computed(() => {
    const market = context()
    if (!demand.value || !canonical.value || !market?.allowTail || !visible.value || baseLoading.value) return null
    return marketChartStudyTailRequest(demand.value, canonical.value, bars(), market.allowCompleted.value, market.active.value)
  })
  const completedResult = shallowRef<{ demand: MarketChartStudyTailDemand; display: MarketChartStudyDisplay } | null>(null)
  const previewResult = shallowRef<{ key: string; value: MarketChartStudyPreview } | null>(null)
  const tailIssue = shallowRef<MarketChartStudyIssue | null>(null)
  const completed = computed(() => {
    const current = wanted.value
    const result = completedResult.value
    if (!current || !result || current.baseKey !== result.demand.baseKey
      || !result.demand.barKeys.every((key, index) => key === current.barKeys[index])) return null
    return result.display
  })
  const preview = computed(() => previewResult.value?.key === wanted.value?.key ? previewResult.value?.value ?? null : null)

  let pending: { controller: AbortController; baseKey: string } | null = null
  let sentKey: string | null = null
  let nextReadAt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false

  function readLatest() {
    if (disposed || pending || timer || !wanted.value || wanted.value.key === sentKey) return
    const delay = nextReadAt - performance.now()
    if (delay > 0) {
      timer = setTimeout(() => { timer = undefined; readLatest() }, delay)
      return
    }
    const requested = wanted.value
    const controller = new AbortController()
    const flight = { controller, baseKey: requested.baseKey }
    pending = flight
    sentKey = requested.key
    nextReadAt = performance.now() + MIN_TAIL_INTERVAL_MS
    void (async () => {
      try {
        const { getMarketChartStudyTail } = await import('../api/market')
        if (controller.signal.aborted) return
        const payload = await getMarketChartStudyTail(requested.query, controller.signal)
        const current = wanted.value
        if (controller.signal.aborted || !current || current.completedKey !== requested.completedKey) return
        const result = projectMarketChartStudyTail(payload, current)
        if (result.completed || result.preview || result.issue === null) recoveredBase = null
        if (result.completed && completedResult.value?.demand.completedKey !== current.completedKey) {
          completedResult.value = { demand: current, display: result.completed }
        } else if (!result.completed && requested.key === current.key) {
          completedResult.value = null
        }
        previewResult.value = result.preview ? { key: current.key, value: result.preview } : null
        tailIssue.value = requested.key === current.key ? result.issue : null
      } catch (error) {
        const current = wanted.value
        if (controller.signal.aborted || !current || current.completedKey !== requested.completedKey) return
        completedResult.value = null
        previewResult.value = null
        tailIssue.value = marketChartStudyIssue(error)
        if (marketChartStudyBaseExpired(error) && recoveredBase !== current.baseKey) {
          recoveredBase = current.baseKey
          baseLoading.value = true
          baseRefresh.value++
        }
      } finally {
        if (pending === flight) pending = null
        readLatest()
      }
    })()
  }

  watch(() => wanted.value?.key, (_key, previous) => {
    const current = wanted.value
    if (!current || previous === undefined) tailIssue.value = null
    if (!current || pending?.baseKey !== current.baseKey) pending?.controller.abort()
    if (!current) {
      clearTimeout(timer)
      timer = undefined
      sentKey = null
      completedResult.value = null
      previewResult.value = null
    }
    readLatest()
  }, { immediate: true })
  onScopeDispose(() => {
    disposed = true
    pending?.controller.abort()
    clearTimeout(timer)
  })

  const historyUnavailable = computed(() => demand.value?.query.series_kind === 'continuous' || (canonical.value === null && canonicalIssue.value !== null))
  return { demand, canonical, canonicalIssue, historyUnavailable, completed, preview, tailIssue }
}
