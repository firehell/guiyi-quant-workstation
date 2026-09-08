import { ref } from 'vue'
import type { SubingReferenceQuery, SubingReferenceResponse } from '../types/subingReference.ts'
import { normalizeSubingReference } from '../utils/subingReference.ts'

export function useSubingReference(fetch: (symbol: string, query: SubingReferenceQuery) => Promise<unknown>) {
  const data = ref<SubingReferenceResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0
  let symbol = ''
  async function refresh(nextSymbol: string, query: SubingReferenceQuery = {}) {
    const current = ++generation
    symbol = nextSymbol.toLowerCase(); const expected = symbol
    data.value = null; error.value = null; loading.value = true
    try {
      const result = normalizeSubingReference(await fetch(expected, query), expected)
      if (query.since && result.performance_since !== query.since || query.through && result.performance_through !== query.through || query.as_of && Date.parse(result.as_of) !== Date.parse(query.as_of)) throw new Error('identity')
      if (current === generation) data.value = result
    } catch (reason) { if (current === generation) error.value = referenceReadError(reason) }
    finally { if (current === generation) loading.value = false }
  }
  async function loadMore() {
    const previous = data.value
    if (!previous?.next_before || loading.value) return
    const current = generation; const expected = symbol
    loading.value = true; error.value = null
    try {
      const result = normalizeSubingReference(await fetch(expected, { since: previous.performance_since, through: previous.performance_through, as_of: previous.as_of, before: previous.next_before }), expected)
      if (current !== generation) return
      if (result.input_snapshot_hash !== previous.input_snapshot_hash || result.as_of !== previous.as_of || result.performance_since !== previous.performance_since || result.performance_through !== previous.performance_through || JSON.stringify(result.summary) !== JSON.stringify(previous.summary) || JSON.stringify(result.signals) !== JSON.stringify(previous.signals)) throw new Error('snapshot')
      const ids = new Set(previous.items.map((item) => item.reference_trade_id))
      if (result.items.some((item) => ids.has(item.reference_trade_id))) throw new Error('duplicate')
      data.value = { ...result, items: [...previous.items, ...result.items] }
    } catch { if (current === generation) { data.value = null; error.value = '历史参考快照已变化或分页不可用，请重新读取。' } }
    finally { if (current === generation) loading.value = false }
  }
  function dispose() { generation += 1 }
  return { data, loading, error, refresh, loadMore, dispose }
}

function referenceReadError(reason: unknown): string {
  const status = (reason as { response?: { status?: unknown } } | null)?.response?.status
  if (status === 422) return '参考日期无效：结束日须为已完成交易日，窗口不超过 365 个日历日。请调整后重新读取。'
  if (status === 503) return '历史参考服务暂忙或已达本次读取预算，请稍后手动重新读取。'
  return '历史参考不可用，请核查数据覆盖或重新读取。实际预警记录独立展示。'
}
