import type { BarData, KlineMarker } from '../types/market.ts'
import type { HistoricalChartAction } from '../types/historicalChartAction.ts'
import type { OwnedSignalMarker } from './historicalSignalMerge.ts'
export type HtdyObservedMarker = OwnedSignalMarker & { historicalSignalId?: string }
export interface HtdyReplayMarker extends KlineMarker { physicalContract: string; actionId: string; signalId: string }
export function htdyReplayMarkers(actions: readonly HistoricalChartAction[], bars: readonly BarData[], snapshotId: string): HtdyReplayMarker[] {
 return actions.filter(a => bars.some(b => Date.parse(b.time) === Date.parse(a.bar_end) && b.physicalContract?.toUpperCase() === a.physical_contract.toUpperCase()
  && (!b.calculationSegmentId || b.calculationSegmentId === a.calculation_segment_id))).map(a => {
  const buying = a.role === 'BUILD' ? a.side === 'LONG' : a.side === 'SHORT'
  const label = a.role === 'BUILD' ? a.side === 'LONG' ? '建多' : '建空' : a.side === 'LONG' ? '平多' : '平空'
  return {id:`replay:${snapshotId}:${a.action_id}`,time:a.bar_end,label:`${label} · 回放补充`,tooltip:`历史回放参考 · ${label} ${a.reference_price} · ${a.physical_contract} · 快照 ${snapshotId} · 动作 ${a.action_id} · 不是实际成交`,tone:buying?'up':'down',position:buying?'belowBar':'aboveBar',shape:buying?'arrowUp':'arrowDown',physicalContract:a.physical_contract,actionId:a.action_id,signalId:a.signal_id}
 })
}
export function htdyUnifiedMarkers(
 replay: readonly HtdyReplayMarker[], observations: readonly HtdyObservedMarker[], formulaVersions: readonly string[],
): KlineMarker[] {
 const own = observations.filter(o => o.strategy === 'htdy' && o.frequency === '60m' && o.source === 'actual_observation')
 const same = (r: HtdyReplayMarker, o: HtdyObservedMarker) => Date.parse(r.time) === Date.parse(o.barEnd)
  && r.physicalContract.toUpperCase() === o.physicalContract.toUpperCase() && r.signalId === o.historicalSignalId
 const verified = (o: HtdyObservedMarker) => Boolean(o.marker.id && o.formulaVersion && formulaVersions.includes(o.formulaVersion)
  && o.historicalSignalId && replay.some(r => same(r, o)))
 const conflict = (r: HtdyReplayMarker) => own.some(o => verified(o) && same(r, o) && r.tone !== o.marker.tone)
 const retained = replay.filter(r => conflict(r) || !own.some(o => verified(o) && same(r, o) && r.tone === o.marker.tone))
 return [...retained, ...own.map(o => {
  const association = verified(o)
   ? replay.some(r => same(r, o) && conflict(r)) ? '与回放方向不同，分别保留' : '实际记录优先展示'
   : !o.formulaVersion ? '公式版本未确认，未覆盖回放' : '稳定信号关联未确认，未覆盖回放'
  return {...o.marker, tooltip: `${o.marker.tooltip ?? '实际首次观察'} · ${association}`}
 })]
}
