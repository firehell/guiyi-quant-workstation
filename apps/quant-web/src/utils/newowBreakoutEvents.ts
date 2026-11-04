import {previewInstant} from './candidatePreviewInstant.ts'
export const BREAKOUT_VERSION='newow_breakout_shapes_detail3449_v1'
/** Independent display facts; pending never represents an actionable signal. */
export interface NewowBreakoutEvent {
 event_id:string;display_version:typeof BREAKOUT_VERSION;formula_version:typeof BREAKOUT_VERSION;
 product:string;frequency:string;bar_end:string;known_at:string;occur_bar_end:string;confirmed_at:string|null;
 physical_contract:string;segment_id:string;calculation_segment_id:string;
 kind:'true_up'|'false_up'|'true_down'|'false_down'|'wick_upper'|'wick_lower'|'pending';side:'up'|'down';
 level:string;buffer:string;threshold:string;volume_ratio:string|null;
 volume_ok:boolean;doubt:boolean;regime:'up'|'down'|'osc'|'unknown';occur_high:string;occur_low:string;confirm_close:string|null;
 bar_gap:1|null;source_sha256:string;input_sha256:string;executable:false;
}
interface Owner {bar_end:string;physical_contract:string;segment_id:string;calculation_segment_id?:string}
export function normalizeBreakoutEvents(raw:unknown,bars:readonly Owner[],frequency:string,asOf:string,product?:string):NewowBreakoutEvent[]{
 if(!Array.isArray(raw))throw Error('突破展示事实无效')
 const seen=new Set<string>(),cutoff=previewInstant(asOf),owners=new Map(bars.map(b=>[previewInstant(b.bar_end),b]))
 const number=(x:unknown)=>typeof x==='string'&&/^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(x)&&Number.isFinite(Number(x))
 return raw.map((e:NewowBreakoutEvent)=>{
  const occur=previewInstant(e?.occur_bar_end),confirm=previewInstant(e?.confirmed_at??''),known=previewInstant(e?.known_at),end=previewInstant(e?.bar_end),bar=owners.get(end)
  if(!e||!bar||!e.event_id||seen.has(e.event_id)||e.display_version!==BREAKOUT_VERSION||e.formula_version!==BREAKOUT_VERSION
    ||e.frequency!==frequency||(product!==undefined&&e.product!==product)||!e.product||e.executable!==false
    ||e.physical_contract!==bar.physical_contract||e.segment_id!==bar.segment_id||e.calculation_segment_id!==bar.calculation_segment_id
    ||occur===null||known===null||cutoff===null||known>cutoff||end===null||known<end
    ||!['true_up','false_up','true_down','false_down','wick_upper','wick_lower','pending'].includes(e.kind)||!['up','down'].includes(e.side)||(e.kind.startsWith('true_')||e.kind.startsWith('false_'))&&!e.kind.endsWith(e.side)
    ||![e.volume_ok,e.doubt].every(v=>typeof v==='boolean')
    ||![e.level,e.buffer,e.threshold,e.occur_high,e.occur_low].every(number)||Number(e.buffer)<0||Number(e.occur_high)<Number(e.occur_low)
    ||(e.volume_ratio!==null&&!number(e.volume_ratio))||!['up','down','osc','unknown'].includes(e.regime)
    ||![e.source_sha256,e.input_sha256].every(s=>/^[a-f0-9]{64}$/.test(s))
    ||(['pending','wick_upper','wick_lower'].includes(e.kind)?(e.confirmed_at!==null||e.bar_gap!==null||e.confirm_close!==null||end!==occur):(confirm===null||confirm<=occur||end!==confirm||e.bar_gap!==1||!number(e.confirm_close))))throw Error('突破展示身份或时序冲突')
  const occurrence=owners.get(occur)
  if(occurrence&&(occurrence.physical_contract!==e.physical_contract||occurrence.segment_id!==e.segment_id||occurrence.calculation_segment_id!==e.calculation_segment_id))throw Error('突破跨计算段')
  if(occurrence&&['true_up','false_up','true_down','false_down'].includes(e.kind)){const i=bars.indexOf(occurrence);if(bars[i+1]!==bar)throw Error('突破确认非相邻Bar')}
  seen.add(e.event_id);return {...e,bar_end:bar.bar_end}
 })
}
export const breakoutTitle=(e:NewowBreakoutEvent)=>e.kind==='pending'?(e.side==='up'?'突破待定':'跌破待定'):({true_up:'真突破·转撑',false_up:'假突破',true_down:'真跌破·转压',false_down:'假跌破',wick_upper:'上影诱多',wick_lower:'下影诱空'}[e.kind])+(e.doubt?'（弱）':'')
/** Public capsule dates refer to occurrence and confirmation, in Shanghai calendar time. */
export function breakoutDateLine(e:NewowBreakoutEvent):string {
 const day=(raw:string)=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(raw)).slice(5)
 return e.kind.startsWith('wick_')?day(e.occur_bar_end):`${day(e.occur_bar_end)} › ${e.confirmed_at?day(e.confirmed_at):'—'}`
}
export interface BreakoutPoint {event:NewowBreakoutEvent;x:number;y:number;wickUpperY?:number;wickLowerY?:number}
export interface BreakoutLabel extends BreakoutPoint {label:string;detail:string;left:number;top:number;width:number;height:30;color:string}
export function layoutBreakouts(points:readonly BreakoutPoint[],width:number,height:number,showShapes=true,showWicks=false):BreakoutLabel[]{
 const labels:BreakoutLabel[]=[]
 for(const p of points){
  if(![p.x,p.y].every(Number.isFinite)||p.x<0||p.x>width||p.y<0||p.y>height)continue
  const add=(label:string,y:number,color:string)=>{
   if(width<24||height<30)return
   const w=Math.min(112,width,Math.max(76,label.length*(p.event.kind.startsWith('wick_')?10:11)+10)),left=Math.max(0,Math.min(width-w,p.x-w/2))
   const candidates=[0,32,-32,64]
   const top=candidates.map(delta=>y+delta).find(top=>top>=0&&top+30<=height&&!labels.some(q=>left<q.left+q.width+2&&left+w+2>q.left&&top<q.top+32&&top+32>q.top))
   if(top===undefined)return
   labels.push({...p,label,detail:breakoutDateLine(p.event),left,top,width:w,height:30,color})
  }
  if(showShapes&&!p.event.kind.startsWith('wick_'))add(breakoutTitle(p.event),p.y+(p.event.side==='up'?-34:6),p.event.kind==='pending'?'#8a9099':p.event.kind==='true_up'||p.event.kind==='false_down'?'#e53935':'#23a85a')
  if(showWicks&&p.event.kind.startsWith('wick_'))add(breakoutTitle(p.event),p.y,'#ed8b20')
 }
 return labels
}
