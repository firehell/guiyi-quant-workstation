import type { NewowProductChartBar } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
import type { NewowPublicPattern } from './newowPublicPatterns.ts'
import type { NewowProductFrequency } from '../types/newowProduct.ts'
export const NEWOW_PATTERN_WORKER_FACTORY = Symbol('newow-pattern-worker-factory')
export const NEWOW_PATTERN_NAMES: Record<NewowPublicPattern['type'],string> = {'cup-handle':'杯柄',saucer:'浅碟','double-bottom':'双底','flat-base':'平台','ascending-base':'递升',consolidation:'盘整','tight-area':'窄幅'}
export interface PatternOwner {key:string;bars:readonly NewowProductChartBar[]}
export interface PatternChoice {key:string;windowKey:string;ownerKey:string;bars:readonly NewowProductChartBar[];pattern:NewowPublicPattern}
export interface PatternJob {key:string;period:'day'|'week';groups:PatternOwner[]}
export interface PatternResult {key:string;results:{ownerKey:string;patterns:NewowPublicPattern[]}[];error:string|null}
export interface PatternWorker {postMessage(job:PatternJob):void;terminate():void;onmessage:((event:{data:PatternResult})=>void)|null;onerror:((event:unknown)=>void)|null}
export function splitNewowPatternOwners(bars:readonly NewowProductChartBar[]):PatternOwner[] {
 const groups:{key:string;bars:NewowProductChartBar[]}[]=[]
 for(const bar of bars){const owner=JSON.stringify([bar.physicalContract,bar.segmentId,bar.calculationSegmentId]);const tail=groups.at(-1)
 if(!tail || !tail.key.startsWith(owner+'#')) groups.push({key:owner+'#'+groups.length,bars:[bar]})
 else tail.bars.push(bar)
 }
 return groups
}
/** At most one cancellable worker; stale generations cannot publish overlays. */
export class PatternScanSession {
 private worker:PatternWorker|null=null;private generation=0
 private factory:()=>PatternWorker;private accept:(value:PatternResult)=>void
 constructor(factory:()=>PatternWorker,accept:(value:PatternResult)=>void){this.factory=factory;this.accept=accept}
 cancel(){++this.generation;this.worker?.terminate();this.worker=null}
 run(job:PatternJob){this.cancel();const generation=this.generation;const worker=this.factory();this.worker=worker
 worker.onmessage=event=>{if(generation===this.generation&&event.data.key===job.key)this.accept(event.data)}
 worker.onerror=()=>{if(generation===this.generation)this.accept({key:job.key,results:[],error:'PATTERN_COMPUTATION_FAILED'})}
 worker.postMessage(job)
 }
}
export interface PatternPoint {barEnd:string;tradingDay:string;price:number}
export interface PatternGeometry {label:string;frequency:NewowProductFrequency;lines:{points:PatternPoint[];dashed:boolean;curve?:'cup'|'saucer'}[];anchors:(PatternPoint&{label:string})[]}
export function buildNewowPatternGeometry(choice:Pick<PatternChoice,'bars'|'pattern'>,frequency:NewowProductFrequency):PatternGeometry {
 const {bars,pattern}=choice;const p=pattern.params
 const num=(key:string)=>{const n=p[key];if(typeof n!=='number'||!Number.isFinite(n))throw Error('pattern value');return n}
 const point=(i:number,price:number):PatternPoint=>{const b=bars[i];if(!Number.isInteger(i)||!b)throw Error('pattern index');if(!Number.isFinite(price)||price<=0)throw Error('pattern price');return {barEnd:b.barEnd,tradingDay:b.tradingDay,price}}
 const out:PatternGeometry={label:`${NEWOW_PATTERN_NAMES[pattern.type]} · ${pattern.score}分 · 回看`,frequency,lines:[],anchors:[]}
 const line=(points:PatternPoint[],dashed=false,curve?:'cup'|'saucer')=>out.lines.push({points,dashed,curve})
 const mark=(i:number,price:number,label:string)=>out.anchors.push({...point(i,price),label})
 const box=(start:number,end:number,upper:number,lower:number)=>{line([point(start,upper),point(end,upper),point(end,lower),point(start,lower),point(start,upper)]);line([point(start,upper),point(bars.length-1,upper)],true)}
 if(pattern.type==='cup-handle'||pattern.type==='saucer'){
 const hi=num('hi'),loi=num('loi'),rhi=num('rhi'),hh=num('hh'),lo=num('lo'),rh=num('rh')
 line([point(hi,hh),point(loi,lo),point(rhi,rh)],false,pattern.type==='saucer'?'saucer':'cup');mark(hi,hh,'旧高');mark(loi,lo,pattern.type==='saucer'?'碟底':'杯底');mark(rhi,rh,'右沿')
 if(num('hStart')>=0&&num('hEnd')>=0){line([point(rhi,rh),point(num('hEnd'),num('hLow'))]);mark(num('hEnd'),num('hLow'),'柄')}
 const pivot=pattern.type==='cup-handle'?Math.max(hh,rh):rh
 line([point(rhi,pivot),point(bars.length-1,pivot)],true)
 }else if(pattern.type==='double-bottom'){
 const b1=num('bottom1Idx'),b2=num('bottom2Idx');point(b1,1);point(b2,1)
 let mid=b1;for(let i=b1;i<=b2;i++)if(bars[i]!.high>bars[mid]!.high)mid=i
 const pts=[point(b1,bars[b1]!.low),point(mid,num('neckLinePrice')),point(b2,bars[b2]!.low)]
 if(num('breakoutIdx')>=0)pts.push(point(num('breakoutIdx'),bars[num('breakoutIdx')]!.high))
 line(pts);line([point(b1,num('neckLinePrice')),point(bars.length-1,num('neckLinePrice'))],true);mark(b1,bars[b1]!.low,'底1');mark(b2,bars[b2]!.low,'底2')
 }else if(pattern.type==='ascending-base'){
 const bases=p.bases;if(!Array.isArray(bases))throw Error('pattern bases')
 for(const [i,b]of bases.entries()){point(b.start,b.low);point(b.end,b.low);let high=b.low;for(let j=b.start;j<=b.end;j++)high=Math.max(high,bars[j]!.high);box(b.start,b.end,high,b.low);mark(b.start,b.low,`底${i+1}`)}
 line(bases.map(b=>point(b.start,b.low)))
 }else{
 const start=num('startIdx'),end=num('endIdx');point(start,1);point(end,1)
 let upper:number,lower:number
 if(pattern.type==='tight-area'){upper=-Infinity;lower=Infinity;for(let i=start;i<=end;i++){upper=Math.max(upper,bars[i]!.close);lower=Math.min(lower,bars[i]!.close)}}
 else{upper=num('upperPrice');lower=num('lowerPrice')}
 box(start,end,upper,lower);mark(start,upper,'上沿');mark(end,lower,'下沿')
 }
 return out
}
