import { getNewowProductSection, type NewowProductRequestOptions, NewowProductRequestError } from './newowProduct.ts'
import type { NewowProductRequest } from '@/types/newowProduct'

export interface FusionGroup {
  model: 'trend' | 'oscillation' | 'fusion'
  closed_count: number
  open_count: number
  interrupted_count: number
  sum_return_percentage_points: string | null
}
export interface FusionTrade {
  reference_trade_id: string
  entry_source: 'trend' | 'oscillation'
  exit_source: 'trend' | 'oscillation' | null
  entry_bar_end: string
  exit_bar_end: string | null
  physical_contract: string
  entry_reference_price: string
  exit_reference_price: string | null
  reference_return_pct: string | null
  mark_change_pct: string | null
  status: 'OPEN' | 'CLOSED' | 'ROLLOVER_INTERRUPTED' | 'DATA_INTERRUPTED'
  statistics_membership: 'entry_in_window_v1' | 'initial_before_window'
}
export interface FusionComparison {
  reference_model_version: string
  groups: FusionGroup[]
  items: FusionTrade[]
  records_truncated: boolean
  performance_since: string
  performance_through: string
  reference_cutoff: string
}
export async function getNewowFusion(request: Extract<NewowProductRequest, { section: 'reference' }>, options: NewowProductRequestOptions = {}): Promise<FusionComparison> {
  const response = await getNewowProductSection({ ...request, includeFusion: true }, options)
  const value = response.section === 'reference' ? response.value?.fusion_comparison : undefined
  if (!value) throw new NewowProductRequestError('NEWOW_RESPONSE_INVALID', 'response_invalid')
  return value
}
