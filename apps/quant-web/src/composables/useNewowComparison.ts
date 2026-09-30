import { computed, shallowRef, watch, type Ref } from 'vue'
import { getNewowProductSection, NewowProductRequestError } from '../api/newowProduct.ts'
import type { NewowProductRequest, NewowProductSectionResponse, NewowResourceLifecycle } from '../types/newowProduct.ts'
import { newowChartSnapshotKey } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
import { sharedChartBarsAgree } from '../utils/newowProductTypes.ts'
import { newowComparisonCompatible, newowComparisonWindow } from '../utils/newowComparison.ts'

type Chart = NewowProductSectionResponse<'chart'>
type FetchChart = (request: NewowProductRequest, signal: AbortSignal) => Promise<NewowProductSectionResponse>
export function useNewowComparison(base: Readonly<Ref<Chart | null>>, enabled: Readonly<Ref<boolean>>, fetch: FetchChart = (request, signal) => getNewowProductSection(request, { signal })) {
  const response = shallowRef<Chart | null>(null)
  const reference = shallowRef<NewowProductSectionResponse<'reference'> | null>(null)
  const referenceError = shallowRef<string | null>(null)
  const state = shallowRef<NewowResourceLifecycle>('not_requested')
  const error = shallowRef<string | null>(null)
  // Chart readiness precedes the partner reference request; fusion must wait for both.
  const referenceSettled = computed(() => enabled.value && (state.value === 'unavailable' || state.value === 'input_conflict'
    || (state.value === 'ready' && (reference.value !== null || referenceError.value !== null))))
  let controller: AbortController | null = null
  let generation = 0
  let disposed = false
  async function reload() {
    const current = ++generation
    controller?.abort(); controller = null; response.value = null; reference.value = null; referenceError.value = null; error.value = null
    const accepted = base.value
    if (disposed || !enabled.value || !accepted?.value || !newowChartSnapshotKey(accepted) || accepted.status.status !== 'ready'
      || !['trend', 'oscillation'].includes(accepted.meta.identity.strategy)) { state.value = 'not_requested'; return }
    const acceptedChart: Chart = accepted
    const active = new AbortController(); controller = active; state.value = 'loading'
    const identity = accepted.meta.identity
    const window = newowComparisonWindow(accepted)
    if (!window) { state.value = 'unavailable'; return }
    const request: Extract<NewowProductRequest, { section: 'chart' }> = { identity: { product: identity.product, strategy: identity.strategy === 'trend' ? 'oscillation' : 'trend', frequency: identity.frequency, seriesKind: 'actual_dominant' },
      asOf: accepted.meta.as_of, section: 'chart', from: window.from, through: window.through, chartLimit: 500 }
    const isCurrent = () => !active.signal.aborted && current === generation && !disposed && base.value === acceptedChart
    async function loadPartnerChart() {
      let result = await fetch(request, active.signal)
      if (!isCurrent()) return null
      // Bound display pagination to the existing chart cap, with partner-owned cursors/tokens.
      for (let pages = 1; result.section === 'chart' && result.value && result.value.bars.length < acceptedChart.value!.bars.length && result.value.next_before && pages < 6; pages++) {
        const next = await fetch({ ...request, chartBefore: result.value.next_before, snapshotToken: result.meta.snapshot_token ?? undefined }, active.signal)
        if (!isCurrent()) return null
        if (next.section !== 'chart' || !next.value || next.status.status !== 'ready' || newowChartSnapshotKey(next) !== newowChartSnapshotKey(result) || !sharedChartBarsAgree(result, next)) throw new Error('comparison conflict')
        const previous = result.value
        const merge = <T,>(older: readonly T[], newer: readonly T[], key: (item: T) => string): T[] => [...new Map([...older, ...newer].map(item => [key(item), item])).values()]
        result = { ...result, value: { ...previous,
          bars: merge(next.value.bars, previous.bars, item => item.bar_end), frames: merge(next.value.frames, previous.frames, item => item.bar_end), actions: merge(next.value.actions, previous.actions, item => item.signal_id), hints: merge(next.value.hints, previous.hints, item => item.hint_id), next_before: next.value.next_before,
          trend_channel: previous.trend_channel && next.value.trend_channel ? { ...previous.trend_channel, points: merge(next.value.trend_channel.points, previous.trend_channel.points, item => item.bar_end) } : previous.trend_channel,
        } }
      }
      return isCurrent() ? result : null
    }
    try {
      // A partner reference snapshot conflict revokes that chart's token. Rebuild
      // the same accepted window once, then bind its fresh token to reference.
      for (let rebuild = 0; rebuild < 2; rebuild++) {
        const result = await loadPartnerChart()
        if (!result) return
        if (result.section !== 'chart' || !newowComparisonCompatible(accepted, result)) {
          state.value = 'input_conflict'; error.value = '两策略的窗口、时间或物理合约事实无法对齐，已停止叠加。'; return
        }
        response.value = result; state.value = 'ready'
        try {
          const records = await fetch({ identity: request.identity, section: 'reference', asOf: request.asOf,
            snapshotToken: result.meta.snapshot_token ?? undefined, historyLimit: 200 }, active.signal)
          if (!isCurrent()) return
          if (records.section !== 'reference' || records.status.status !== 'ready' || records.meta.snapshot_token !== result.meta.snapshot_token
            || records.meta.identity.strategy !== result.meta.identity.strategy || records.meta.identity.product !== result.meta.identity.product
            || records.meta.identity.frequency !== result.meta.identity.frequency || records.meta.as_of !== result.meta.as_of) throw new Error('reference conflict')
          reference.value = records
          return
        } catch (cause) {
          if (!isCurrent()) return
          if (rebuild === 0 && cause instanceof NewowProductRequestError && cause.classification === 'conflict'
            && cause.code === 'NEWOW_SNAPSHOT_GENERATION_CONFLICT') {
            response.value = null; reference.value = null; state.value = 'loading'
            continue
          }
          referenceError.value = '另一策略参考收益暂不可用，未计算缺失样本。'
          return
        }
      }
    } catch {
      if (!isCurrent()) return
      state.value = 'unavailable'; error.value = '双策略对照读取失败；单策略结果保持独立，可手动重试。'
    } finally { if (controller === active) controller = null }
  }
  const stop = watch(() => [enabled.value, base.value], () => { void reload() }, { immediate: true, flush: 'sync' })
  function dispose() { disposed = true; ++generation; controller?.abort(); state.value = 'not_requested'; stop() }
  return { response, reference, referenceError, referenceSettled, state, error, reload, dispose }
}
