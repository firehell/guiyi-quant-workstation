import { previewInstant } from './candidatePreviewInstant.ts'
import { comparePositiveDecimalText } from './marketDisplay.ts'
import type { HomePeriodFact } from './newowHomeCards.ts'
import type { NewowProductSectionResponse } from '../types/newowProduct.ts'
import type { CrossPeriodPrices } from '../types/newowDecisionV2.ts'

export interface PriceProvenance {
  raw: string; display_value: string; frequency: string; bar_end: string; as_of: string
  physical_contract: string; segment_id: string; calculation_segment_id: string
  formula_version: string; branch: string; source_category: string; input_sha256?: string; support_cap_applied?: boolean
}
export interface PriceSourceRow { label: string; available: boolean; reason: string; source: PriceProvenance | null }
const unavailable = (label: string, reason = '来源信息不可用'): PriceSourceRow => ({ label, available: false, reason, source: null })
function row(label: string, candidate: unknown, owner?: { physical_contract?: string; as_of?: string }): PriceSourceRow {
  if (!candidate || typeof candidate !== 'object') return unavailable(label)
  const value = candidate as PriceProvenance
  const required = ['raw','display_value','frequency','bar_end','as_of','physical_contract','segment_id','calculation_segment_id','formula_version','branch','source_category'] as const
  if (required.some(key => typeof value[key] !== 'string' || !value[key].trim()) || !['1d','1w','60m','5m','15m','30m','1M'].includes(value.frequency)
    || comparePositiveDecimalText(value.raw, value.raw) === null || comparePositiveDecimalText(value.display_value, value.display_value) === null
    || previewInstant(value.bar_end) === null || previewInstant(value.as_of) === null || previewInstant(value.bar_end)! > previewInstant(value.as_of)!
    || owner?.physical_contract && value.physical_contract !== owner.physical_contract
    || owner?.as_of && previewInstant(owner.as_of) !== previewInstant(value.as_of)) return unavailable(label, '价格来源身份或时间不一致')
  return { label, available: true, reason: '', source: value }
}
export function homePriceSources(fact?: HomePeriodFact, period: '1d' | '1w' = '1d'): PriceSourceRow[] {
  return (['target','absorb'] as const).map(kind => {
    const label = `首页当前周期通道 · ${kind === 'target' ? '目标' : '吸筹'}`
    const candidate = fact?.price_sources?.[kind]
    if (fact?.status !== 'ready' || !candidate) return unavailable(label)
    if (candidate.frequency !== period || candidate.segment_id !== fact.segment_id || candidate.calculation_segment_id !== fact.calculation_segment_id
      || previewInstant(candidate.bar_end) !== previewInstant(fact.bar_end ?? '') || candidate.formula_version !== fact.price_formula_version
      || candidate.input_sha256 !== fact.price_input_sha256 || !/^[a-f0-9]{64}$/.test(candidate.input_sha256 ?? '') || comparePositiveDecimalText(candidate.raw, fact[kind]) !== 0) return unavailable(label, '价格来源身份或数值不一致')
    return row(label,candidate,fact)
  })
}
export function chartPriceSources(chart: NewowProductSectionResponse<'chart'> | null, summary: { target: {display_value: string} | null; absorb: {display_value: string} | null }): PriceSourceRow[] {
  const direct = chart?.value?.price_reference, anchor = chart?.value?.bars.at(-1)
  return (['target','absorb'] as const).map(kind => {
    const label = `主图当前周期通道 · ${kind === 'target' ? '目标' : '吸筹'}`
    const value = direct?.[kind]
    if (!direct || !anchor || !summary[kind] || value?.status.status !== 'ready') return unavailable(label)
    if (direct.frequency !== chart?.meta.identity?.frequency || direct.segment_id !== anchor.segment_id || direct.calculation_segment_id !== anchor.calculation_segment_id
      || previewInstant(direct.anchor_bar_end) !== previewInstant(anchor.bar_end) || comparePositiveDecimalText(value.display, summary[kind]!.display_value) !== 0) return unavailable(label, '价格来源身份或数值不一致')
    return row(label,{...direct,raw:value.raw,display_value:value.display,bar_end:direct.anchor_bar_end,branch:kind === 'target' ? 'chart_hhv10' : 'chart_llv10',source_category:'canonical_channel'}, {physical_contract:anchor.physical_contract,as_of:chart!.meta.as_of})
  })
}
export function decisionPriceSources(prices: CrossPeriodPrices | null | undefined): PriceSourceRow[] {
  const selected = (['shared','status_card'] as const).flatMap(surface => (['target','absorb'] as const).map(kind => {
    const label = `${surface === 'shared' ? '跨周期共享选择' : '状态卡价格'} · ${kind === 'target' ? '目标' : '吸筹'}`
    const value = prices?.[surface][kind]
    if (value && value.frequency === prices?.current_price.frequency && (value.segment_id !== prices.current_price.segment_id || value.calculation_segment_id !== prices.current_price.calculation_segment_id)) return unavailable(label, '价格来源计算段不一致')
    return row(label, value ? {...value, display_value:value.display_value ?? value.raw, as_of:prices!.as_of, formula_version:prices!.formula_version} : null, {physical_contract:prices?.current_price.physical_contract,as_of:prices?.as_of})
  }))
  const context = (['current_price','previous_close'] as const).map(kind => {
    const value = prices?.[kind]
    return row(`守卫输入 · ${kind === 'current_price' ? '现价' : '同合约前一有效日线昨收'}`, value ? {...value,display_value:value.raw,as_of:prices!.as_of,formula_version:prices!.formula_version,branch:kind} : null, {physical_contract:prices?.current_price.physical_contract,as_of:prices?.as_of})
  })
  return [...selected,...context]
}
