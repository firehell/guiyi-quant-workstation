import type { CrossPeriodPrices, NewowDecisionV2, Cdv2 } from '../types/newowDecisionV2'
import { formatMarketDecimal } from './marketDisplay.ts'
export type StatusRisk = 'bullish' | 'cautious' | 'warning' | 'bearish' | 'unknown'
type Signal = 'buy' | 'hold' | 'sell' | 'wait'
type Row = readonly [string, StatusRisk, string]
// Public v3.3.59 RESONANCE_MAP, week first. Presentation only; never alters a strategy state.
const TREND: Record<string, Row> = {
 'buy-buy':['上涨启动','bullish','周日双建仓，主升浪启动，可重仓介入'],
 'buy-hold':['震荡上涨','bullish','双周期看多，可加仓 1-2 层'],
 'buy-sell':['趋势回调','cautious','周建仓日清仓，反向背离，减仓观望'],
 'buy-wait':['筑底反弹','warning','周建仓日空仓，震荡磨底，观望'],
 'hold-buy':['上涨中继','bullish','周持有日建仓，回踩可加仓'],
 'hold-hold':['上涨趋势','bullish','周日双持有，趋势延续，继续持有'],
 'hold-sell':['高位震荡','cautious','周持有日清仓，反弹减仓，保留底仓'],
 'hold-wait':['高位震荡','cautious','周持有日空仓，上涨乏力，谨慎持有'],
 'sell-buy':['震荡反弹','warning','周清仓日建仓，背离，逢反弹减仓'],
 'sell-hold':['震荡反弹','warning','周清仓日持有，反弹减仓离场'],
 'sell-sell':['下跌趋势','bearish','周日双清仓，主跌浪，清仓离场'],
 'sell-wait':['震荡下跌','bearish','周清仓日空仓，下跌末期，等反转'],
 'wait-buy':['筑底反转','bearish','周空仓日建仓，背离，不追高'],
 'wait-hold':['筑底反弹','warning','周空仓日持有，等右侧确认'],
 'wait-sell':['震荡下跌','bearish','周空仓日清仓，加速下行，继续空仓'],
 'wait-wait':['震荡下跌','bearish','周日双空仓，筑底观望，等信号'],
}
// Explicit daily/weekly adapter. The original 27-row matrix requires H; absent H is NOT idle.
const OSC: Record<string, Row> = {
 'holding-holding':['震荡上涨','bullish','周日均处于参考持有，观察吸筹与目标区间'],
 'holding-cleared':['高位震荡','cautious','周线参考持有，日线已清仓，观察日线是否回补'],
 'holding-idle':['震荡整理','cautious','周线参考持有，等待日线确认'],
 'cleared-holding':['震荡反弹','warning','周线已清仓，日线参考持有，观察周线是否修复'],
 'cleared-cleared':['震荡下跌','bearish','周日均已清仓，等待新信号'],
 'cleared-idle':['震荡观望','bearish','周线已清仓，日线待信号'],
 'idle-holding':['震荡试盘','cautious','日线参考持有，观察周线是否跟上'],
 'idle-cleared':['震荡离场','warning','日线已清仓，周线待信号'],
 'idle-idle':['震荡观望','unknown','周日暂无动作信号，继续观察'],
}
const riskLabels: Record<StatusRisk,string> = {bullish:'积极做多',cautious:'谨慎持有',warning:'减仓观望',bearish:'空仓防御',unknown:'等待信号'}
const signalLabels: Record<Signal,string> = {buy:'建仓',hold:'持有',sell:'清仓',wait:'空仓'}
const oscState = (s:Signal) => s==='buy'||s==='hold'?'holding':s==='sell'?'cleared':'idle'
function fact(cd:Cdv2|undefined,role:string) { return cd?.facts.find(f=>f.role===role) }
function signal(f:Cdv2['facts'][number]|undefined):Signal|null { return f?.status==='ready' && ['buy','hold','sell','wait'].includes(f.state??'') ? f!.state as Signal : null }
export function buildStatusCard(value:NewowDecisionV2|null, strategy:string) {
 const cd=value?.cdv2, axis=strategy==='oscillation'?'oscillation':'trend'
 const wf=fact(cd,axis+'_week'),df=fact(cd,axis+'_day'),w=signal(wf),d=signal(df)
 const compatible = w!==null && d!==null && !!wf?.physical_contract && !!wf.segment_id && wf.physical_contract===df?.physical_contract && wf.segment_id===df?.segment_id
 const supported=strategy==='trend'||strategy==='oscillation'
 const row:Row = supported && compatible ? (strategy==='oscillation'?OSC[oscState(w!)+'-'+oscState(d!)]:TREND[w+'-'+d])! : ['日周状态不足','unknown',supported?'当前周日策略状态或合约上下文不足，等待已完成数据':'主升浪尚无独立日周摘要输入']
 const [name,risk,rawAdvice]=row
 const bear=cd?.trend_bias==='bearish'
 const guard=(s:string)=>bear?s.replace(/加仓/g,'持仓').replace(/建仓/g,'持仓'):s
 const tag=(s:Signal|null)=>({state:s??'unknown',label:s===null?'未就绪':strategy==='oscillation'?({holding:'持有',cleared:'已清仓',idle:'待信号'}[oscState(s)]):signalLabels[s]})
 const exposure=cd?(cd.reference_exposure_range || (cd.reference_exposure_cap===0?'0%':'—')):'—'
 const current=value?.prices?.current_price
 const priceCompatible=compatible && current?.physical_contract===wf?.physical_contract && current?.segment_id===wf?.segment_id
 const progress=priceCompatible&&supported ? statusPriceProgress(value?.prices??null,risk) : null
 return {name:guard(name),risk,riskLabel:guard(riskLabels[risk]),advice:guard(rawAdvice),week:tag(w),day:tag(d),weekFact:wf,dayFact:df,exposure,progress,
  explanation: `${guard(name)}，周线${tag(w).label}＋日线${tag(d).label}。${guard(rawAdvice)}。${progress ? '目标价 '+formatMarketDecimal(value?.prices?.status_card.target?.display_value??value?.prices?.status_card.target?.raw)+'，吸筹价 '+formatMarketDecimal(value?.prices?.status_card.absorb?.display_value??value?.prices?.status_card.absorb?.raw)+'。' : '参考价格暂不可用。'}建议仓位参考强度 ${exposure}；仅作日周解释，不代表账户持仓、保证金比例或手数。`}
}

// Bounded decimal lexemes -> scaled integers. No price arithmetic through binary floats.
function decimal(raw:string|undefined):{n:bigint;scale:number}|null {
 if(!raw||raw.length>128) return null
 const m=/^\+?(\d+)(?:\.(\d{1,24}))?$/.exec(raw)
 return m?{n:BigInt(m[1]!+(m[2]??'')),scale:(m[2]??'').length}:null
}
function ratio(a:bigint,b:bigint,signed=false) {
 const n=a*1000n, magnitude=n<0n?-n:n
 const rounded=(magnitude+b/2n)/b
 return `${n<0n?'-':signed?'+':''}${rounded/10n}.${rounded%10n}`
}
export function statusPriceProgress(prices:CrossPeriodPrices|null,risk:StatusRisk) {
 if(!prices||risk==='unknown')return null
 const a=prices.status_card.absorb,t=prices.status_card.target,c=prices.current_price
 if(!a||!t||!c.physical_contract||!c.segment_id||[a,t].some(p=>p.physical_contract!==c.physical_contract||p.segment_id!==c.segment_id))return null
 const parts=[decimal(a.raw),decimal(t.raw),decimal(c.raw)]
 if(parts.some(p=>!p||p.n<=0n))return null
 const scale=Math.max(...parts.map(p=>p!.scale)),[low,high,now]=parts.map(p=>p!.n*10n**BigInt(scale-p!.scale)) as [bigint,bigint,bigint]
 const delta=high-low,range=(delta<0n?-delta:delta)||10n**BigInt(scale)
 const down=risk==='bearish'||risk==='warning',distance=down?high-now:now-low
 const clamped=distance<0n?0n:distance>range?range:distance
 return {leftLabel:down?'目标':'吸筹',rightLabel:down?'吸筹':'目标',leftPrice:down?t:a,rightPrice:down?a:t,
  leftStatisticLabel:down?'已跌':'已涨',rightStatisticLabel:down?'距吸筹':'距目标',
  leftStatistic:(down?(now<=high?'-':'+')+ratio(now<=high?high-now:now-high,high):ratio(now-low,low,true))+'%',rightStatistic:ratio(down?now-low:high-now,down?low:high)+'%',progress:ratio(clamped,range)}
}
