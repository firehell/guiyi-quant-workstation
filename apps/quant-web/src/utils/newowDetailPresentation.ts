import { formatChartTimeInShanghai } from './barTime.ts'
import type { NewowProductSectionResponse, NewowResourceLifecycle } from '../types/newowProduct.ts'

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
) {
  const value = chart?.value
  const latestBar = value?.bars.at(-1)
  const frame = value?.frames.find(item => item.bar_end === latestBar?.bar_end)
  const historical = !!chart && !!value && value.chart_through.slice(0, 10) < chart.meta.as_of.slice(0, 10)
  const ready = lifecycle === 'ready' && latestBar?.observation_eligible && frame?.status.status === 'ready'
  const state = ready ? frame!.main_state : 'UNAVAILABLE'
  const result = explanation?.value?.target_absorb
  const compatible = explanationCompatible && chart && explanation && JSON.stringify(chart.meta.identity) === JSON.stringify(explanation.meta.identity) && chart.meta.as_of === explanation.meta.as_of
  const targetValid = !historical && ready && compatible && explanationLifecycle === 'ready' && result?.status === 'ready' && result.evidence_status === 'ACTIVE_CODE_VERIFIED' && result.as_of === chart.meta.as_of
  const targetPrice = (kind: 'target' | 'absorb') => {
    const price = result?.value?.[kind]
    return targetValid && price && /^\d+(\.\d+)?$/.test(price.display_value) && Number.isFinite(Number(price.display_value)) && price.physical_contract === latestBar?.physical_contract && price.segment_id === latestBar?.segment_id && Date.parse(price.bar_end) <= Date.parse(chart!.meta.as_of) ? price : null
  }
  const openReference = !historical && ready && referenceCompatible && referenceLifecycle === 'ready' && reference?.meta.as_of === chart?.meta.as_of
    ? reference?.value?.items.find(item => item.status === 'OPEN' && item.physical_contract === latestBar?.physical_contract && item.segment_id === latestBar?.segment_id) ?? null : null
  return {
    status: { label: labels[state], state, barEnd: latestBar?.bar_end ?? null, historical },
    target: targetPrice('target'), absorb: targetPrice('absorb'), openReference,
    latestAction: lifecycle === 'ready' ? value?.actions.at(-1) ?? null : null,
  }
}

/** Display-only vocabulary; unknown server tokens are disclosed, never diagnosed. */
export function newowDisplayLabel(value: string): string {
  const labels: Record<string, string> = { trend: '趋势', oscillation: '震荡', main_rise: '主升浪', BUILD: '参考建仓', HOLD: '策略持有', CLEAR: '参考清仓', FLAT: '策略空仓', UNAVAILABLE: '状态不可用', LONG_BIAS: '偏多', SHORT_BIAS: '偏空', NEUTRAL: '中性', WAIT_CONFIRM: '等待确认', low: '低', medium: '中等', high: '高' }
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
  return { text: `${direction === 'up' ? '+' : ''}${value}%`, direction }
}
export function referenceInterruptionLabel(reason: string | null): string {
  return reason === 'OWNER_BOUNDARY' ? '物理合约区段结束' : '中断原因待确认（见详情）'
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
