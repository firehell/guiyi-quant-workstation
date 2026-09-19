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
      if (query.frequency && result.frequency !== query.frequency || query.since && result.performance_since !== query.since || query.through && result.performance_through !== query.through || query.as_of && Date.parse(result.as_of) !== Date.parse(query.as_of)) throw new Error('identity')
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
      const result = normalizeSubingReference(await fetch(expected, { ...(previous.frequency === '15m' ? {} : { frequency: previous.frequency }), since: previous.performance_since, through: previous.performance_through, as_of: previous.as_of, before: previous.next_before }), expected)
      if (current !== generation) return
      if (result.frequency !== previous.frequency || result.input_snapshot_hash !== previous.input_snapshot_hash || result.as_of !== previous.as_of || result.performance_since !== previous.performance_since || result.performance_through !== previous.performance_through || JSON.stringify(result.summary) !== JSON.stringify(previous.summary) || JSON.stringify(result.signals) !== JSON.stringify(previous.signals) || JSON.stringify(result.indicators) !== JSON.stringify(previous.indicators)) throw new Error('snapshot')
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
  const response = (reason as { response?: { status?: unknown; data?: unknown } } | null)?.response
  const status = response?.status
  if (status === 422) return '参考日期无效：结束日须为已完成交易日，窗口不超过 365 个日历日。请调整后重新读取。'
  if (status === 503) return '历史参考服务暂忙或已达本次读取预算，请稍后手动重新读取。'
  const diagnostic = subingDiagnosticText(response?.data)
  if (diagnostic) return diagnostic
  return '历史参考不可用，请核查数据覆盖或重新读取。实际预警记录独立展示。'
}

function subingDiagnosticText(value: unknown): string | null {
  const root = record(value)
  const detail = record(root?.detail)
  const diagnostic = record(detail?.diagnostic)
  const context = record(diagnostic?.context)
  if (detail?.code !== 'SUBING_REFERENCE_DATA_UNAVAILABLE' || !diagnostic || !context) return null
  const stages: Readonly<Record<string, string>> = {
    calendar: '交易日历解析',
    session: '交易时段解析',
    actual_dominant_replay: '真实主力回放',
    physical_contract_replay: '物理合约回放',
  }
  const reasons: Readonly<Record<string, string>> = {
    TRADING_CALENDAR_MISSING: '交易日历缺失',
    TRADING_SESSION_MISSING: '交易时段缺失',
    MAIN_CONTRACT_MAP_MISSING: '主力合约映射缺失',
    DATASET_OR_PARTITION_MISSING: '行情数据集或分区缺失',
    REPLAY_ENDPOINTS_MISSING: '权威交易端点缺失',
    DATA_INTEGRITY_INVALID: '行情完整性校验失败',
  }
  const stage = typeof diagnostic.stage === 'string' ? stages[diagnostic.stage] : null
  const reason = typeof diagnostic.reason === 'string' ? reasons[diagnostic.reason] : null
  if (!stage || !reason) return null
  const locations: string[] = []
  if (typeof context.symbol === 'string' && /^[a-z]{1,8}$/.test(context.symbol)) locations.push(context.symbol.toUpperCase())
  if (typeof context.contract === 'string' && /^[A-Za-z]{1,8}\d{3,4}$/.test(context.contract)) locations.push(context.contract.toUpperCase())
  if (typeof context.frequency === 'string' && ['1m', '5m', '15m', '30m', '60m', '1d', '1w'].includes(context.frequency)) locations.push(context.frequency)
  if (typeof context.expected_count === 'number' && Number.isSafeInteger(context.expected_count) && context.expected_count >= 0) locations.push(`预期 ${context.expected_count} 个端点`)
  return `${stage}失败：${reason}${locations.length ? `（${locations.join(' · ')}）` : ''}。数据修复需单独授权；实际预警记录独立展示。`
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}
