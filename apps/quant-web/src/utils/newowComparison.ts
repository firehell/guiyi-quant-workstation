import type { NewowProductSectionResponse } from '../types/newowProduct.ts'
import { sharedChartBarsAgree } from './newowProductTypes.ts'
import { newowChartSnapshotKey } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
type Chart = NewowProductSectionResponse<'chart'>
/** A loaded older window can coexist with previously loaded newer Bars. */
export function newowComparisonWindow(base: Chart): { from: string; through: string } | null {
  if (!base.value?.bars.length) return null
  const dates = base.value.bars.map(bar => bar.trading_day)
  return { from: [base.value.chart_from, ...dates].sort()[0]!, through: [base.value.chart_through, ...dates].sort().at(-1)! }
}
/** Two independent strategy snapshots may have different tokens and input hashes.
 * Compare their accepted visible market facts, never pretend the tokens are interchangeable. */
export function newowComparisonCompatible(base: Chart | null, partner: Chart | null): boolean {
  if (!base?.value || !partner?.value || !newowChartSnapshotKey(base) || !newowChartSnapshotKey(partner)
    || base.status.status !== 'ready' || partner.status.status !== 'ready') return false
  const a = base.meta, b = partner.meta
  if (!['trend', 'oscillation'].includes(a.identity.strategy) || b.identity.strategy !== (a.identity.strategy === 'trend' ? 'oscillation' : 'trend')
    || a.identity.product !== b.identity.product || a.identity.frequency !== b.identity.frequency
    || a.identity.series_kind !== b.identity.series_kind || a.as_of !== b.as_of
    || a.identity.input_quality_policy !== b.identity.input_quality_policy
    || a.futures_adaptation_version !== b.futures_adaptation_version
    || a.reference_model_version !== b.reference_model_version || a.data_revision_identity !== b.data_revision_identity
    || !base.value.bars.length
    || partner.value.chart_from > base.value.bars[0]!.trading_day || partner.value.chart_through < base.value.bars.at(-1)!.trading_day
    || !sharedChartBarsAgree(base, partner)) return false
  const bars = new Map(partner.value.bars.map(bar => [bar.bar_end, bar]))
  return base.value.bars.every(bar => {
    const other = bars.get(bar.bar_end)
    return other?.calculation_segment_id === bar.calculation_segment_id
  })
}
