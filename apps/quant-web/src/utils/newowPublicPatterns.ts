/** Public v3.3.79 hindsight shapes. Caller must supply one completed-bar owner segment. */
export const NEWOW_PUBLIC_PATTERNS_METADATA = { version: 'newow_public_patterns_v3379_v1', pageParity: true, executable: false, repainting: true } as const
export interface PatternBar { high: number; low: number; close: number; volume: number; open?: number }
export interface NewowPublicPatternBase { start: number; end: number; low: number }
export type NewowPublicPatternType = 'cup-handle'|'saucer'|'double-bottom'|'flat-base'|'ascending-base'|'consolidation'|'tight-area'
export interface NewowPublicPattern { type: NewowPublicPatternType; score: number; params: Record<string,number|boolean|NewowPublicPatternBase[]> }
type Bars = readonly PatternBar[]
const candidate = (type: NewowPublicPatternType, score: number, params: NewowPublicPattern['params']): NewowPublicPattern => ({type,score,params})
function extrema(b: Bars, start: number, end: number, key: 'high'|'low', maximum: boolean) {
 let value = maximum ? -Infinity : Infinity, index = -1
 for(let i=start;i<=end;i++) if(maximum ? b[i]![key]>value : b[i]![key]<value) {value=b[i]![key];index=i}
 return {value,index}
}
function rise(b: Bars, hi: number, hh: number, span: number) { const low=extrema(b,Math.max(0,hi-span),hi-1,'low',false).value; return low<Infinity?(hh-low)/low*100:0 }
function roundedCup(b: Bars, frequency: string, saucer: boolean): NewowPublicPattern|null {
 const n=b.length; if(n<(saucer?30:35))return null
 const {index:hi,value:hh}=extrema(b,0,Math.floor(n*.8),'high',true)
 let preRisePct=hi>20?rise(b,hi,hh,60):0
 if(preRisePct<30)return null
 const {index:loi,value:lo}=extrema(b,hi+1,n-1,'low',false)
 if(loi<0)return null
 const cupDepthPct=(hh-lo)/hh*100
 if(cupDepthPct<(saucer?5:8)||cupDepthPct>(saucer?30:50))return null
 if(!saucer&&loi-hi+1>10) {
  const q=Math.floor((loi-hi+1)/4)
  let first=0,last=0
  for(let i=0;i<q;i++){first+=b[hi+i]!.low;last+=b[loi-q+1+i]!.low}
  first/=q;last/=q
  if(Math.abs(first-last)/Math.max(first,last)>.15)return null
 }
 const {index:rhi,value:rh}=extrema(b,loi+1,n-1,'high',true)
 if(rhi<0||(saucer&&rh<hh*.85))return null
 let hStart=-1,hEnd=-1,hHigh=rh,hLow=rh
 const maxHandleLen=Math.floor((rhi-loi)*(saucer?.2:.4))
 const handleEnd=Math.min(n-1,rhi+maxHandleLen)
 for(let i=rhi+1;i<=handleEnd;i++) {
  hHigh=Math.max(hHigh,b[i]!.high);hLow=Math.min(hLow,b[i]!.low)
  const decline=(rh-b[i]!.low)/rh*100
  if(saucer?decline>=5&&decline<=10:b[i]!.low<=rh*.95&&b[i]!.low>=rh*.88){hStart=rhi+1;hEnd=i;break}
 }
 if(!saucer&&hStart<0) for(let i=rhi+1;i<=handleEnd;i++) {
  hHigh=Math.max(hHigh,b[i]!.high);hLow=Math.min(hLow,b[i]!.low)
  if((rh-b[i]!.low)/rh*100>=3){hStart=rhi+1;hEnd=i;break}
 }
 // The third public fallback repeats the >=3 test and cannot change the result.
 const hasHandle=hStart>=0&&hEnd>=0, handleDays=hasHandle?hEnd-hStart+1:0,baseDays=loi-hi
 if(!saucer&&hasHandle){const depth=(rh-hLow)/rh*100;if(depth<8||depth>15)return null}
 if(saucer&&hi>10)preRisePct=rise(b,hi,hh,30)
 let score=preRisePct>=30?25:preRisePct>=20?Math.floor(25-(30-preRisePct)):0
 if(saucer){score+=cupDepthPct>=5&&cupDepthPct<=10?25:cupDepthPct>=3&&cupDepthPct<=15?20:0;score+=hasHandle?(handleDays<=10?20:handleDays<=20?15:0)+30:15}
 else {
  score+=cupDepthPct>=12&&cupDepthPct<=18?25:cupDepthPct>=8&&cupDepthPct<=25?20:cupDepthPct>=5&&cupDepthPct<=35?15:0
  const weeks=frequency==='week'?baseDays:Math.round(baseDays/5)
  score+=weeks>=4&&weeks<=20?20:weeks>=2&&weeks<=30?15:baseDays>=3?10:0
  if(hasHandle&&handleDays>0)score+=15
  if(hasHandle)score+=15
 }
 score=Math.min(100,Math.max(0,score));if(score<(saucer?30:35))return null
 const params:NewowPublicPattern['params']={hi,hh,loi,lo,rhi,rh,hStart,hEnd,hHigh,hLow,preRisePct,cupDepthPct,hasHandle}
 if(!saucer){params.baseDays=baseDays;params.handleDays=handleDays}
 return candidate(saucer?'saucer':'cup-handle',score,params)
}
function doubleBottom(b:Bars):NewowPublicPattern|null {
 const n=b.length;if(n<35)return null;let best:NewowPublicPattern|null=null
 for(let b1=Math.floor(n*.4);b1<n-20;b1++)for(let b2=b1+15;b2<=Math.min(b1+60,n-10);b2++){
  const low=Math.min(b[b1]!.low,b[b2]!.low),diff=Math.abs(b[b2]!.low-b[b1]!.low)/low
  if(diff>.08)continue
  const neckLinePrice=extrema(b,b1,b2,'high',true).value,rebound=(neckLinePrice-low)/low,depth=rebound*100
  if(rebound<.1||depth<10||depth>50)continue
  const baseDays=b2-b1;if(baseDays<20)continue
  let breakoutIdx=-1;for(let i=b2+1;i<n;i++)if(b[i]!.high>=neckLinePrice*.99){breakoutIdx=i;break}
  const score=35+(baseDays<=50?20:15)+(diff<=.03?15:diff<=.05?10:5)+(rebound>=.2?15:rebound>=.15?10:5)
  if(!best||score>best.score)best=candidate('double-bottom',score,{bottom1Idx:b1,bottom2Idx:b2,neckLinePrice,baseDays,breakoutIdx})
 }
 return best
}
function flatBase(b:Bars):NewowPublicPattern|null {
 if(b.length<25)return null;let best:NewowPublicPattern|null=null
 for(let end=b.length-1;end>=40;end--)for(let start=end-15;start>=Math.max(0,end-40);start--){
  const days=end-start+1;if(days>40)continue
  const upperPrice=extrema(b,start,end,'high',true).value,lowerPrice=extrema(b,start,end,'low',false).value,amplitude=upperPrice/lowerPrice
  if(amplitude>1.1)continue
  const score=40+(amplitude<=1.05?25:amplitude<=1.08?20:15)+(days>=20&&days<=35?20:15)
  if(!best||score>best.score)best=candidate('flat-base',score,{startIdx:start,endIdx:end,upperPrice,lowerPrice,days})
 }
 return best
}
function windowShape(b:Bars,tight:boolean):NewowPublicPattern|null {
 const min=tight?15:20,max=tight?30:60,n=b.length;if(n<min)return null;let best:NewowPublicPattern|null=null
 for(let start=0;start<n-min;start++)for(let len=min;len<=Math.min(max,n-start);len++){
  const end=start+len;let high=-Infinity,low=Infinity,sum=0,volFirst=0,volSecond=0
  for(let i=start;i<end;i++){
   const v=tight?b[i]!.close:b[i]!.high,w=tight?b[i]!.close:b[i]!.low
   high=Math.max(high,v);low=Math.min(low,w);sum+=b[i]!.close
   if(i<start+Math.floor(len/2))volFirst+=b[i]!.volume;else volSecond+=b[i]!.volume
  }
  const pct=(high-low)/(tight?sum/len:low)*100
  if(pct>(tight?3:15))continue
  const score=tight?(pct<=1.5?50:pct<=2.5?40:30)+(len>=25?30:len>=20?20:10):(pct<=8?30:pct<=12?20:10)+(len>=40?30:len>=30?20:10)+(volSecond<volFirst?20:0)
  if(score<(tight?40:30)||best&&score<=best.score)continue
  best=candidate(tight?'tight-area':'consolidation',Math.min(score,80),tight?{startIdx:start,endIdx:end-1,tightPct:pct,length:len}:{startIdx:start,endIdx:end-1,upperPrice:high,lowerPrice:low,length:len})
 }
 return best
}
function ascendingBases(b:Bars):NewowPublicPattern|null {
 const n=b.length;if(n<45)return null
 // Every public interval spans 16..61 bars. Precompute exact extrema once.
 const lows=Array.from({length:n},(_,start)=>{const row:number[]=[];let low=Infinity;for(let end=start;end<Math.min(n,start+61);end++){low=Math.min(low,b[end]!.low);row[end-start]=low}return row})
 const getLow=(s:number,e:number)=>lows[s]![e-s]!
 type Third={base:NewowPublicPatternBase;lift:number;bonus:number}
 const cache=new Map<number,[Third|null,Third|null]>()
 function thirdChoices(s:number,e:number):[Third|null,Third|null]{
  const key=s* n+e,existing=cache.get(key);if(existing)return existing
  const previous=getLow(s,e);const result:[Third|null,Third|null]=[null,null]
  for(let start=e+10;start<=Math.min(e+60,n-20);start++)for(let end=start+15;end<=Math.min(start+60,n-10);end++){
   const low=getLow(start,end);if(low<=previous)continue
   const lift=(low-previous)/previous*100,liftBonus=lift>=2&&lift<=15?15:0
   // Cache separately for valid/invalid first-base length; preserve earliest tie.
   for(let mode=0;mode<2;mode++){
    const bonus=liftBonus+(mode===0&&e-s+1<=60&&end-start+1<=60?20:0)
    if(!result[mode]||bonus>result[mode]!.bonus)result[mode]={base:{start,end,low},lift,bonus}
   }
  }
  cache.set(key,result);return result
 }
 let best:NewowPublicPattern|null=null
 for(let s1=Math.floor(n*.2);s1<n-70;s1++)for(let e1=s1+15;e1<=Math.min(s1+60,n-60);e1++){
  const low1=getLow(s1,e1)
  for(let s2=e1+10;s2<=Math.min(e1+60,n-40);s2++)for(let e2=s2+15;e2<=Math.min(s2+60,n-30);e2++){
   const low2=getLow(s2,e2);if(low2<=low1)continue
   const lift1to2=(low2-low1)/low1*100,third=thirdChoices(s2,e2)[e1-s1+1<=60?0:1]
   if(!third)continue
   const score=50+(lift1to2>=2&&lift1to2<=15?15:0)+third.bonus
   if(!best||score>best.score)best=candidate('ascending-base',score,{bases:[{start:s1,end:e1,low:low1},{start:s2,end:e2,low:low2},third.base],count:3,lift1to2,lift2to3:third.lift})
   // 100 is the absolute maximum. Later candidates cannot replace the first tie.
   if(score===100)return best
  }
 }
 return best
}
export function detectNewowPublicPatterns(bars:Bars,frequency='week'):NewowPublicPattern[]{
 if(bars.length<12)return []
 if(bars.some(b=>![b.high,b.low,b.close,b.volume].every(Number.isFinite)||b.low<=0||b.close<=0||b.high<b.low||b.volume<0))throw new Error('Invalid public-pattern OHLCV input')
 const results=[roundedCup(bars,frequency,false),roundedCup(bars,frequency,true),doubleBottom(bars),flatBase(bars),ascendingBases(bars),windowShape(bars,false),windowShape(bars,true)]
 return results.filter((p):p is NewowPublicPattern=>p!==null&&p.score>=30).sort((a,b)=>b.score-a.score)
}
