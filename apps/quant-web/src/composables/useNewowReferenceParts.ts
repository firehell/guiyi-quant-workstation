import { computed, onScopeDispose, shallowRef, watch, type Ref } from 'vue'
import { getNewowReferencePart, NewowProductRequestError } from '../api/newowProduct.ts'
import { MAX_ACCUMULATED_REFERENCE_TRADES, sameNewowReferenceResult } from '../utils/newowReferenceParts.ts'
import { newowErrorDisplay } from '../utils/newowDataDiagnostics.ts'
import type {
  NewowProductSectionResponse, NewowReferenceMode, NewowReferencePartRequest,
  NewowReferencePartResponse, NewowReferenceRecord,
} from '../types/newowProduct.ts'

type FetchPart = (request: NewowReferencePartRequest, options: { signal: AbortSignal }) => Promise<NewowReferencePartResponse>
const initialMode = (fusion: boolean): NewowReferenceMode => fusion ? 'fusion_page_ordinary' : 'page_ordinary'
const isConflict = (error: unknown) => error instanceof NewowProductRequestError && error.classification === 'conflict'
const isCancelled = (error: unknown) => error instanceof NewowProductRequestError && error.classification === 'cancelled'
const failureDetail = (error: unknown) => error instanceof NewowProductRequestError ? newowErrorDisplay(error.code) : null
const partUnavailable = (part: NewowReferencePartResponse, label: string) => `${label}暂不可用${part.status.reason_code ? `：${newowErrorDisplay(part.status.reason_code)}` : ''}，请重试。`

/** One selected mode at a time; all responses must prove one frozen input. */
export function useNewowReferenceParts(
  chart: Ref<NewowProductSectionResponse<'chart'> | null>,
  visible: Ref<boolean>,
  fusion: Ref<boolean>,
  fetchPart: FetchPart = getNewowReferencePart,
) {
  const mode = shallowRef<NewowReferenceMode>(initialMode(fusion.value))
  const overview = shallowRef<NewowReferencePartResponse | null>(null)
  const curve = shallowRef<NewowReferencePartResponse | null>(null)
  const history = shallowRef<NewowReferencePartResponse | null>(null)
  const historyRows = shallowRef<readonly NewowReferenceRecord[]>([])
  const historyTruncated = shallowRef(false)
  const loading = shallowRef(false)
  const historyLoading = shallowRef(false)
  const error = shallowRef<string | null>(null)
  const historyError = shallowRef<string | null>(null)
  const requestedWindow = shallowRef<{ performanceSince: string; performanceThrough: string } | null>(null)
  let generation = 0
  let controller: AbortController | null = null
  let historyController: AbortController | null = null

  const proof = computed(() => {
    const response = chart.value
    return response?.value && response.meta.snapshot_token
      ? JSON.stringify([response.meta.identity.product, response.meta.identity.strategy, response.meta.identity.frequency,
        response.meta.as_of, response.meta.input_content_sha256, response.meta.snapshot_token, fusion.value]) : ''
  })
  const chartCompatible = computed(() => !!overview.value?.value && !!chart.value
    && chart.value.meta.snapshot_token === overview.value.meta.snapshot_token
    && chart.value.meta.as_of === overview.value.meta.as_of
    && chart.value.meta.identity.product === overview.value.meta.identity.product
    && chart.value.meta.identity.strategy === overview.value.meta.identity.strategy
    && chart.value.meta.identity.frequency === overview.value.meta.identity.frequency)
  const trades = computed(() => historyRows.value.filter((row): row is Extract<NewowReferenceRecord, { reference_trade_id: string }> => 'reference_trade_id' in row))
  const historyCapped = computed(() => historyTruncated.value || historyRows.value.length >= MAX_ACCUMULATED_REFERENCE_TRADES
    && history.value?.value?.reference_part === 'history' && history.value.value.next_before !== null)
  const complete = computed(() => {
    const selected = curve.value?.value?.reference_part === 'curve' ? curve.value.value.curve : null
    const last = history.value?.value?.reference_part === 'history' ? history.value.value : null
    return chartCompatible.value && mode.value === 'closed' && selected?.metrics != null && last != null && last.next_before === null
      && !historyTruncated.value && last.record_since <= last.performance_since
      && historyRows.value.filter(row => 'reference_trade_id' in row && row.status === 'CLOSED'
        && row.statistics_membership === 'entry_in_window_v1').length === selected.metrics.closed_count
  })

  function baseRequest(part: NewowReferencePartRequest['part'], selectedMode = mode.value): NewowReferencePartRequest | null {
    const response = chart.value
    if (!response?.value || !response.meta.snapshot_token) return null
    return {
      identity: { product: response.meta.identity.product, strategy: response.meta.identity.strategy,
        frequency: response.meta.identity.frequency, seriesKind: 'actual_dominant' },
      asOf: response.meta.as_of, snapshotToken: response.meta.snapshot_token, part, mode: selectedMode,
      ...(requestedWindow.value ?? {}),
    }
  }
  function clear() {
    generation++
    controller?.abort(); historyController?.abort()
    overview.value = null; curve.value = null; history.value = null; historyRows.value = []; historyTruncated.value = false
    loading.value = false; historyLoading.value = false; error.value = null; historyError.value = null
  }
  async function load(explicit = false) {
    if ((!visible.value && !explicit) || !proof.value) return
    clear()
    const own = generation, request = baseRequest('panel')
    if (!request) return
    controller = new AbortController()
    const active = controller
    loading.value = true
    try {
      const first = await fetchPart(request, { signal: active.signal })
      if (own !== generation || active.signal.aborted) return
      if (!first.value) { error.value = partUnavailable(first, '参考统计'); return }
      if (first.value.reference_part !== 'panel' || first.value.curve.mode !== request.mode
        || first.value.reference_mode !== request.mode) throw Error('NEWOW_REFERENCE_PART_CONFLICT')
      const { curve: selected, ...summary } = first.value
      overview.value = { ...first, value: { ...summary, reference_part: 'overview' } }
      const { summary: _summary, recent_items: _recent, page_summaries: _page,
        fusion_groups: _groups, coverage_intervals: _coverage, unavailable_days: _gaps, ...common } = summary
      curve.value = { ...first, value: { ...common, reference_part: 'curve', curve: selected } }
    } catch (cause) {
      if (own === generation && !active.signal.aborted && !isCancelled(cause)) {
        overview.value = null; curve.value = null
        error.value = isConflict(cause) ? '参考快照已变化，请刷新图表后重试。'
          : `参考曲线暂不可用${failureDetail(cause) ? `：${failureDetail(cause)}` : ''}，请重试。`
      }
    } finally { if (own === generation) loading.value = false }
  }
  async function loadHistory(own = generation, source = overview.value) {
    if (!source?.value || own !== generation || historyLoading.value) return
    const request = baseRequest('history')
    if (!request) return
    historyController?.abort(); historyController = new AbortController()
    const active = historyController
    historyLoading.value = true; historyError.value = null
    try {
      const next = await fetchPart({ ...request,
        performanceSince: source.value.performance_since, performanceThrough: source.value.performance_through,
        historyLimit: 50 }, { signal: active.signal })
      if (own !== generation || active.signal.aborted) return
      if (!next.value) { historyError.value = partUnavailable(next, '历史参考记录'); return }
      if (next.value.reference_part !== 'history' || !sameNewowReferenceResult(source, next)) throw Error('NEWOW_REFERENCE_IDENTITY_CONFLICT')
      history.value = next
      historyRows.value = next.value.items
      historyTruncated.value = false
    } catch (cause) {
      if (own === generation && !active.signal.aborted && !isCancelled(cause)) {
        history.value = null; historyRows.value = []
        historyError.value = isConflict(cause) ? '记录快照已变化，请刷新图表后重试。'
          : `历史参考记录暂不可用${failureDetail(cause) ? `：${failureDetail(cause)}` : ''}，请重试。`
      }
    } finally { if (own === generation) historyLoading.value = false }
  }
  async function loadMore() {
    const current = history.value
    if (!current?.value || current.value.reference_part !== 'history' || !current.value.next_before || historyLoading.value || historyCapped.value) return
    const request = baseRequest('history')
    if (!request) return
    const own = generation, cursor = current.value.next_before
    historyController = new AbortController()
    const active = historyController
    historyLoading.value = true; historyError.value = null
    try {
      const next = await fetchPart({ ...request,
        performanceSince: current.value.performance_since, performanceThrough: current.value.performance_through,
        historyLimit: 50, historyBefore: cursor }, { signal: active.signal })
      if (own !== generation || active.signal.aborted) return
      if (!next.value || next.value.reference_part !== 'history' || !sameNewowReferenceResult(current, next)
        || next.value.next_before === cursor) throw Error('NEWOW_REFERENCE_CURSOR_CONFLICT')
      const recordKey = (row: NewowReferenceRecord) => 'reference_trade_id' in row ? row.reference_trade_id
        : JSON.stringify([row.buyDate, row.buyPrice, row.sellDate, row.sellPrice, row.pct, row.segment_id])
      const existing = new Set(historyRows.value.map(recordKey))
      if (next.value.items.some(row => existing.has(recordKey(row)))) throw Error('NEWOW_REFERENCE_CURSOR_CONFLICT')
      const accumulated = [...historyRows.value, ...next.value.items]
      historyTruncated.value = accumulated.length > MAX_ACCUMULATED_REFERENCE_TRADES
      historyRows.value = accumulated.slice(0, MAX_ACCUMULATED_REFERENCE_TRADES)
      history.value = next
    } catch (cause) {
      if (own === generation && !active.signal.aborted && !isCancelled(cause)) {
        if (isConflict(cause)) { history.value = null; historyRows.value = [] }
        historyError.value = '记录快照已变化或读取失败，请刷新后重试。'
      }
    } finally { if (own === generation) historyLoading.value = false }
  }
  async function loadCompleteClosed(window: { performanceSince: string; performanceThrough: string }) {
    clear()
    mode.value = 'closed'
    requestedWindow.value = window
    await load(true)
    if (!curve.value || error.value) return false
    await loadHistory()
    for (let page = 0; page < 100 && history.value?.value?.reference_part === 'history'
      && history.value.value.next_before && !historyError.value && !historyCapped.value; page++) await loadMore()
    if (!complete.value) historyError.value = '完整记录未能核对，当前不显示双策略参考统计。'
    return complete.value
  }
  function select(next: NewowReferenceMode, window?: { performanceSince: string; performanceThrough: string }) {
    clear()
    mode.value = next
    if (window) requestedWindow.value = window
    void load()
  }
  let previousDisplayOwner = ''
  function reset() {
    clear()
    requestedWindow.value = null
    if (!chart.value) return
    const owner = JSON.stringify([chart.value.meta.identity.product, chart.value.meta.identity.frequency])
    const keepIdeal = owner === previousDisplayOwner && mode.value.includes('page_ideal')
    previousDisplayOwner = owner
    mode.value = keepIdeal ? (fusion.value ? 'fusion_page_ideal' : 'page_ideal') : initialMode(fusion.value)
    if (visible.value) void load()
  }
  watch(proof, reset, { immediate: true, flush: 'sync' })
  watch(visible, shown => { if (shown && overview.value === null && !loading.value && error.value === null) void load() })
  onScopeDispose(clear, true)
  return { mode, overview, curve, history, historyRows, trades, complete, historyCapped, chartCompatible, loading, historyLoading,
    error, historyError, requestedWindow, load, loadHistory, loadMore, loadCompleteClosed, select, reset, clear }
}
