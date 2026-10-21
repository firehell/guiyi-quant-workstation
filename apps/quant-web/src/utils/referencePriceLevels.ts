import type { BarData } from '../types/market.ts'
import type { KlineReferenceIndicator } from '../types/referenceCallout.ts'
/** Price overlay geometry only: separate series enforce gaps and physical-owner boundaries. */
export function referencePriceLevelSegments(bars: readonly BarData[], points: readonly KlineReferenceIndicator[]) {
  const indexed=new Map(points.map(point=>[`${point.bar_end}:${point.physical_contract}`,point]))
  const result:Array<{kind:'target'|'stop';points:Array<{time:string;value:number}>}>=[]
  for(const kind of ['target','stop'] as const){
    let active:typeof result[number]|null=null, owner=''
    for(const bar of bars){
      const point=indexed.get(`${bar.time}:${bar.physicalContract??''}`)
      const raw=point?.[kind==='target'?'target_reference_price':'stop_reference_price']
      const identity=`${bar.physicalContract}:${bar.calculationSegmentId}`
      const valid=point && ['LONG','SHORT'].includes(point.reference_side??'') && typeof raw==='string' && Number.isFinite(Number(raw)) && Number(raw)>0
        && (!point.owner_segment_id || point.owner_segment_id===bar.calculationSegmentId)
      if(!valid){active=null;owner='';continue}
      if(!active||owner!==identity){active={kind,points:[]};result.push(active);owner=identity}
      active.points.push({time:bar.time,value:Number(raw)})
    }
  }
  return result
}
