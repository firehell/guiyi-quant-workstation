import { previewInstant } from './candidatePreviewInstant.ts'
import type { NewowDecisionV2 } from '../types/newowDecisionV2'
import type { NewowProductSectionResponse } from '../types/newowProduct'

export interface NewowDisplayOwner { asOf: string; physicalContract: string | null; segmentId: string | null; calculationSegmentId?: string | null; frequency?: string }

export function sharedChartForOwner(chart: NewowProductSectionResponse<'chart'> | null, owner: NewowDisplayOwner | null): NewowProductSectionResponse<'chart'> | null {
  if (!owner?.physicalContract || !owner.segmentId || !chart?.value || previewInstant(chart.meta.as_of) === null || previewInstant(chart.meta.as_of) !== previewInstant(owner.asOf)) return null
  const bars = chart.value.bars.filter(bar => bar.physical_contract === owner.physicalContract && (bar.segment_id === owner.segmentId || bar.calculation_segment_id === owner.segmentId))
  if (!bars.length || new Set(bars.map(bar => bar.segment_id)).size !== 1) return null
  const times = new Set(bars.map(bar => bar.bar_end))
  return { ...chart, value: { ...chart.value, bars, frames: chart.value.frames.filter(frame => times.has(frame.bar_end)) } }
}

export function sharedDecisionForOwner(value: NewowDecisionV2 | null, owner: NewowDisplayOwner | null, axis: 'trend' | 'oscillation'): boolean {
  if (!value || !owner?.physicalContract || !owner.segmentId || previewInstant(value.cdv2.as_of) === null || previewInstant(value.cdv2.as_of) !== previewInstant(owner.asOf)) return false
  const day = value.cdv2.facts.find(fact => fact.role === `${axis}_day`)
  if (day?.status !== 'ready' || day.physical_contract !== owner.physicalContract || day.segment_id !== owner.segmentId) return false
  const current = value.prices?.current_price
  if (current && owner.calculationSegmentId && current.frequency === owner.frequency && current.calculation_segment_id !== owner.calculationSegmentId) return false
  return !current || (current.physical_contract === owner.physicalContract && current.segment_id === owner.segmentId)
}
