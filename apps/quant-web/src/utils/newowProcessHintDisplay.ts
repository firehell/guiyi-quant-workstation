import type { NewowProductChartBar, NewowProductHintMarker } from '../components/market/detail/newow/newowProductChartPrimitives.ts'

const appearances: Readonly<Record<string, { text: string; color: string; below: boolean; cycle?: boolean }>> = {
  'MAGIC11:4高': { text: '4高', color: '#4CAF50', below: false, cycle: true },
  'MAGIC11:7低': { text: '7低', color: '#F5A623', below: true, cycle: true },
  'MAGIC11:11变': { text: '11变', color: '#E91E63', below: false, cycle: true },
  'MAGIC11:4低': { text: '4低', color: '#E53935', below: true, cycle: true },
  'MAGIC11:7高': { text: '7高', color: '#4CAF50', below: false, cycle: true },
  J: { text: 'J', color: '#00FF00', below: false },
  D4: { text: '★B', color: '#E53935', below: true },
  D5: { text: '★B', color: '#4CAF50', below: true },
  D6: { text: '★B', color: '#2979FF', below: true },
  NEWOW_ESCAPE_D1: { text: '★S逃命', color: '#E53935', below: false },
  NEWOW_ESCAPE_D2: { text: '★S逃', color: '#4CAF50', below: false },
  NEWOW_ESCAPE_D3: { text: '★S跑', color: '#2979FF', below: false },
}

/** Display placement only: signal kind, timing and ownership always come from the server. */
export function newowProcessHintDisplay(hint: NewowProductHintMarker, bar: NewowProductChartBar) {
  const appearance = appearances[hint.kind]
  if (!appearance || hint.anchorPrice === null || !Number.isFinite(hint.value)
    || hint.barEnd !== bar.barEnd || hint.physicalContract !== bar.physicalContract
    || hint.segmentId !== bar.segmentId || hint.sourceIdentity !== bar.sourceIdentity) return null
  return {
    ...appearance,
    // Niuwa positions low text at LOW * .99; this never changes the reference price.
    displayPrice: appearance.below ? bar.low * .99 : bar.high,
    padding: appearance.cycle ? 4 : 3,
  }
}


export const MAIN_RISE_LABEL_FONT = '600 10px -apple-system, "PingFang SC", "Helvetica Neue", Arial, sans-serif'
export interface PositionedProcessHint {
  id:string;kind:string;barEnd:string;x:number;y:number;text:string;color:string;below:boolean;cycle?:boolean
}
const sourceOrder:Readonly<Record<string,number>>={NEWOW_ESCAPE_D1:0,NEWOW_ESCAPE_D2:1,NEWOW_ESCAPE_D3:2,D4:3,D5:4,D6:5}
/** Public draw order: all TA text, then Magic11, then J. J never consumes a slot. */
export function layoutMainRiseProcessLabels<T extends PositionedProcessHint>(points:readonly T[]):T[] {
  const group=(p:T)=>p.kind==='J'?2:p.cycle?1:0
  const ordered=points.map((point,index)=>({point,index})).sort((a,b)=>group(a.point)-group(b.point)
    ||Date.parse(a.point.barEnd)-Date.parse(b.point.barEnd)
    ||(sourceOrder[a.point.kind]??0)-(sourceOrder[b.point.kind]??0)||a.index-b.index)
  const placed:Array<{x:number;y:number}>=[],result:T[]=[]
  for(const {point} of ordered){
    if(!Number.isFinite(point.x)||!Number.isFinite(point.y))continue
    if(point.kind==='J'){result.push({...point});continue}
    for(let step=0;step<=3;step++){
      const y=point.y+(point.below?1:-1)*step*12
      if(placed.some(p=>Math.abs(p.x-point.x)<12&&Math.abs(p.y-y)<11))continue
      placed.push({x:point.x,y});result.push({...point,y});break
    }
  }
  return result
}
export function drawMainRiseProcessLabels(ctx:CanvasRenderingContext2D,points:readonly PositionedProcessHint[],dark:boolean):void {
  ctx.save();ctx.font=MAIN_RISE_LABEL_FONT;ctx.textAlign='center';ctx.lineJoin='round';ctx.lineWidth=2.4
  ctx.strokeStyle=dark?'rgba(0,0,0,0.78)':'rgba(255,255,255,0.92)'
  for(const point of points){
    ctx.textBaseline=point.below?'top':'bottom'
    ctx.strokeText(point.text,point.x,point.y);ctx.fillStyle=point.color;ctx.fillText(point.text,point.x,point.y)
  }
  ctx.restore()
}
