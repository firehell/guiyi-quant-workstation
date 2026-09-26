import { formatChartTimeInShanghai } from './barTime.ts'
import { formatMarketPercent } from './marketDisplay.ts'
import type { NewowAuxiliaryValue, NewowProductBar, NewowProductSectionResponse, NewowResourceLifecycle } from '../types/newowProduct.ts'

export function priceDirection(value: number | null): 'neutral' | 'up' | 'down' {
  return value === null || !Number.isFinite(value) || value === 0 ? 'neutral' : value > 0 ? 'up' : 'down'
}
const labels = { BUILD: '策略建仓', HOLD: '策略持有', CLEAR: '策略清仓', FLAT: '策略空仓', UNAVAILABLE: '状态不可用' }
export function projectNewowDetail(
  chart: NewowProductSectionResponse<'chart'> | null,
  lifecycle: NewowResourceLifecycle,
  explanation: NewowProductSectionResponse<'explanation'> | null = null,
  explanationLifecycle: NewowResourceLifecycle = 'not_requested',
  explanationCompatible = false,
  reference: NewowProductSectionResponse<'reference'> | null = null,
  referenceLifecycle: NewowResourceLifecycle = 'not_requested',
  referenceCompatible = false,
  currentChartWindow = false,
  historicalChartWindow = false,
) {
  const value = chart?.value
  const latestBar = value?.bars.at(-1)
  const frame = value?.frames.find(item => item.bar_end === latestBar?.bar_end)
  // “当前”来自 loader 已接受的请求 provenance；日历日不能定义最新已完成 D1/W1。
  const historical = !!chart && !!value && historicalChartWindow
  const ready = lifecycle === 'ready' && latestBar?.observation_eligible && frame?.status.status === 'ready'
  const state = ready ? frame!.main_state : 'UNAVAILABLE'
  const result = explanation?.value?.target_absorb
  const direct = value?.price_reference
  const compatible = explanationCompatible && chart && explanation && JSON.stringify(chart.meta.identity) === JSON.stringify(explanation.meta.identity) && chart.meta.as_of === explanation.meta.as_of
  const targetValid = currentChartWindow && ready && compatible && explanationLifecycle === 'ready' && result?.status === 'ready' && result.evidence_status === 'ACTIVE_CODE_VERIFIED' && result.as_of === chart.meta.as_of
  const targetPrice = (kind: 'target' | 'absorb') => {
    const priceDirect = direct?.[kind]
    if (currentChartWindow && ready && priceDirect?.status.status === 'ready' && priceDirect.raw !== null && priceDirect.display !== null && direct?.anchor_bar_end === latestBar?.bar_end && direct.physical_contract === latestBar?.physical_contract && direct.segment_id === latestBar?.segment_id && direct.calculation_segment_id === latestBar?.calculation_segment_id && direct.as_of === chart?.meta.as_of) return { display: priceDirect.display, display_value: priceDirect.display, bar_end: direct.anchor_bar_end }
    const price = result?.value?.[kind]
    return targetValid && price && /^\d+(\.\d+)?$/.test(price.display_value) && Number.isFinite(Number(price.display_value)) && price.physical_contract === latestBar?.physical_contract && price.segment_id === latestBar?.segment_id && Date.parse(price.bar_end) <= Date.parse(chart!.meta.as_of) ? price : null
  }
  const openReference = currentChartWindow && ready && referenceCompatible && referenceLifecycle === 'ready' && reference?.meta.as_of === chart?.meta.as_of
    ? reference?.value?.items.find(item => item.status === 'OPEN' && item.physical_contract === latestBar?.physical_contract && item.segment_id === latestBar?.segment_id) ?? null : null
  return {
    status: { label: labels[state], state, barEnd: latestBar?.bar_end ?? null, historical },
    target: targetPrice('target'), absorb: targetPrice('absorb'), openReference,
    latestAction: lifecycle === 'ready' ? value?.actions.at(-1) ?? null : null,
  }
}

/** Display-only vocabulary; unknown server tokens are disclosed, never diagnosed. */
export function newowDisplayLabel(value: string): string {
  const labels: Record<string, string> = { trend: '趋势', oscillation: '震荡', main_rise: '主升浪', BUILD: '参考建仓', HOLD: '策略持有', CLEAR: '参考清仓', FLAT: '策略空仓', UNAVAILABLE: '状态不可用', LONG_BIAS: '偏多', SHORT_BIAS: '偏空', NEUTRAL: '中性', WAIT_CONFIRM: '等待确认', D1: 'D1 逃顶提示', D2: 'D2 逃顶提示', D3: 'D3 逃顶提示', D4: 'D4 低位修复提示', D5: 'D5 低位修复提示', D6: 'D6 低位修复提示', NEWOW_ESCAPE_D1: 'D1 逃顶提示', NEWOW_ESCAPE_D2: 'D2 逃顶提示', NEWOW_ESCAPE_D3: 'D3 逃顶提示', low: '低', medium: '中等', high: '高' }
  return labels[value] ?? (value === '—' ? '—' : '未确认')
}
export function describeNewowState(value: string, historical = false): string {
  const descriptions: Record<string, string> = {
    BUILD: '策略当前为建仓状态，仅作页面参考，不代表已成交。',
    HOLD: '策略当前为持有状态，仅作页面参考，不代表账户持仓。',
    CLEAR: '策略当前为清仓状态，仅作页面参考，不代表已成交。',
    FLAT: '策略当前为空仓状态，仅作页面参考，不代表账户持仓。',
  }
  const description = descriptions[value] ?? '当前状态不可用，等待可核实的已完成行情与策略事实。'
  return historical ? description.replace('策略当前为', '所示历史 Bar 的策略状态为').replace('当前状态不可用', '所示历史 Bar 状态不可用') : description
}

export function shortNewowTime(value: string | null | undefined): string {
  return value ? formatChartTimeInShanghai(value).slice(5) || '—' : '—'
}

/** Decoration of server-provided Decimal text only; no return calculation. */
export function referencePercentDisplay(value: string | null | undefined): { text: string; direction: 'up' | 'down' | 'neutral' } {
  if (value == null || !/^-?\d+(\.\d+)?$/.test(value)) return { text: '—', direction: 'neutral' }
  const zero = /^-?0+(\.0+)?$/.test(value)
  const direction = zero ? 'neutral' : value.startsWith('-') ? 'down' : 'up'
  return { text: formatMarketPercent(value, 'percentage_points', true), direction }
}
export function referenceInterruptionLabel(reason: string | null): string {
  if (reason === 'SOURCE_PRICE_UNAVAILABLE') return '源日线价格不可用，交易参考中断；不计入完整收益'
  if (reason === 'OWNER_BOUNDARY') return '物理合约区段结束'
  if (reason === 'OWNER_BOUNDARY_MARK_UNAVAILABLE') return '物理合约区段结束时缺少可验证估值'
  return '原因未识别（原始码见技术详情）'
}

/** Reference-card labels only. Raw timestamps remain available in title/details. */
export function referenceTimeDisplay(
  value: string | null | undefined,
  frequency: string,
  relatedTimes: readonly (string | null | undefined)[],
): string {
  if (!value) return '—'
  const full = formatChartTimeInShanghai(value)
  if (!full) return '—'
  if (frequency === '1d' || frequency === '1w') return full.slice(0, 10)
  const crossYear = relatedTimes.some(time => time && formatChartTimeInShanghai(time).slice(0, 4) !== full.slice(0, 4))
  return crossYear ? full : full.slice(5)
}

/** Projects server segment readiness at the last displayed Bar, without recomputing indicators. */
export function projectNewowAuxiliaryReadiness(value: NewowAuxiliaryValue | null | undefined, latestBar: Pick<NewowProductBar, 'bar_end' | 'physical_contract' | 'calculation_segment_id'> | null | undefined) {
  if (!value || !latestBar) return null
  // Auxiliary segment_id is the backend calculation segment identity, including price-gap resets.
  const latest = value.segments.find(segment => segment.physical_contract === latestBar.physical_contract && segment.segment_id === latestBar.calculation_segment_id && segment.bar_ends.includes(latestBar.bar_end))
  if (!latest) return null
  const historicalWarming = value.segments.filter(segment => segment !== latest && segment.status.status === 'warming').length
  const currentLabel = latest.status.status === 'ready' ? '当前可计算'
    : latest.status.status === 'warming' ? '当前数据不足，待每日增量积累' : '当前指标不可用'
  return { currentStatus: latest.status.status, historicalWarming,
    message: `${currentLabel}${historicalWarming ? `；历史部分仍在预热（${historicalWarming} 个区段）` : ''}` }
}

/** A readable old snapshot is useful for charts but cannot make the current quote fresh. */
export function newowQuoteFreshness(hasQuote: boolean, dailyPendingUpdate: boolean): 'fresh' | 'unavailable' {
  return hasQuote && !dailyPendingUpdate ? 'fresh' : 'unavailable'
}
