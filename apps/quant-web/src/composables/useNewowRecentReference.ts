import { shallowRef, watch, onScopeDispose, type Ref } from 'vue'
import { getNewowProductSection } from '../api/newowProduct.ts'
import { newowReferenceWindow } from '../utils/newowReferenceWindows.ts'
import type { NewowProductSectionResponse, NewowProductRequest } from '../types/newowProduct.ts'

// Records own their window and cursor; performance-tab requests never enter this resource.
export function useNewowRecentReference(source: Ref<NewowProductSectionResponse<'reference'> | null>, fetch = getNewowProductSection) {
  const response = shallowRef<NewowProductSectionResponse<'reference'> | null>(null)
  const loading = shallowRef(false)
  const error = shallowRef<string | null>(null)
  let controller: AbortController | null = null
  let generation = 0
  async function loadMore() {
    const anchor = source.value
    if (!anchor?.value || !anchor.meta.snapshot_token || loading.value) return
    const cursor = response.value?.value?.next_before
    if (response.value && !cursor) return
    const current = generation
    controller = new AbortController()
    const active = controller
    loading.value = true
    error.value = null
    const window = newowReferenceWindow(anchor.value.actual_available_through, 'three_months', anchor.value.performance_since)
    const request: NewowProductRequest = {
      identity: { product: anchor.meta.identity.product, strategy: anchor.meta.identity.strategy, frequency: anchor.meta.identity.frequency, seriesKind: 'actual_dominant' },
      section: 'reference', asOf: anchor.meta.as_of, snapshotToken: anchor.meta.snapshot_token,
      ...window, historyLimit: 200, ...(cursor ? { historyBefore: cursor } : {}),
    }
    try {
      const next = await fetch(request, { signal: active.signal })
      if (generation !== current || active.signal.aborted) return
      if (next.section !== 'reference' || next.meta.snapshot_token !== anchor.meta.snapshot_token || !next.value) throw new Error('reference identity unavailable')
      const previous = response.value?.value
      response.value = previous && cursor
        ? { ...next, value: { ...next.value, items: [...previous.items, ...next.value.items.filter(item => !previous.items.some(old => old.reference_trade_id === item.reference_trade_id))] } }
        : next
    } catch {
      if (generation === current && !active.signal.aborted) error.value = '近三个月操盘记录暂不可用，请重试。'
    } finally {
      if (generation === current) loading.value = false
    }
  }
  const stop = watch(() => [source.value?.meta.snapshot_token, source.value?.value?.actual_available_through].join('|'), () => {
    ++generation
    controller?.abort()
    response.value = null
    loading.value = false
    error.value = null
    void loadMore()
  }, { immediate: true })
  onScopeDispose(() => { ++generation; controller?.abort(); stop() }, true)
  return { response, loading, error, loadMore }
}
