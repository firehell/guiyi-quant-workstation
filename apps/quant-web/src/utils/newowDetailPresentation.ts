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
