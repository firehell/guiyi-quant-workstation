import { closedReferenceCurve, sumReferenceReturns } from './newowReferenceCurve.ts'
export interface HoldingCurvePoint {
  bar_end: string
  trading_day: string
  physical_contract: string
  segment_id: string
  calculation_segment_id: string
  closed_return_percentage_points: string
  floating_return_pct: string | null
  marked_return_percentage_points: string | null
  entry_trading_day?: string | null
  reference_trade_id: string | null
  status: string
}
export interface HoldingCurve {
  model_version: string
  page_parity: boolean
  executable: boolean
  points: readonly HoldingCurvePoint[]
}
/** Uses complete server replay, never the limited chart or recent record list. */
export function holdingCurvePlot(curve: HoldingCurve | null | undefined, since: string, through: string) {
  const empty = (message: string) => ({ points: [] as (HoldingCurvePoint & { x: number; y: number })[], segments: [] as string[], levels: [] as {y:number;label:string}[], zero: 140, message })
  if (!curve || curve.model_version !== 'newow_reference_marked_curve_v1' || !curve.page_parity || curve.executable) return empty('逐 Bar 持有过程暂不可用。')
  const source = curve.points.filter(p => p.trading_day >= since && p.trading_day <= through)
  const points = source.filter(p => p.marked_return_percentage_points !== null)
  const start = Date.parse(since), end = Date.parse(through) + 86400000
  if (!points.length) return empty('该窗口暂无有效持有过程。')
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || points.some((p,i) => !Number.isFinite(Number(p.marked_return_percentage_points)) || !Number.isFinite(Date.parse(p.bar_end)) || (i > 0 && p.bar_end <= points[i-1]!.bar_end))) return empty('持有过程事实不完整，暂不绘制曲线。')
  let low = 0, high = 0
  for (const p of points) { low = Math.min(low,Number(p.marked_return_percentage_points)); high = Math.max(high,Number(p.marked_return_percentage_points)) }
  low *= 1.1; high = high * 1.1 || (low < 0 ? 0 : 1)
  const y = (value: number) => 140 - (value-low)/(high-low)*140
  const plotted = points.map(p => ({...p,x: Math.max(0,Math.min(712,(Date.parse(p.bar_end)+8*3600000-start)/(end-start)*712)), y:y(Number(p.marked_return_percentage_points))}))
  const segments: string[] = []
  let owner = ''
  const breaks = new Set(source.filter(p=>p.marked_return_percentage_points===null).map(p=>p.bar_end))
  let previous = ''
  for (const p of plotted) {
    const next = `${p.physical_contract}|${p.segment_id}|${p.calculation_segment_id}`
    if (next !== owner || [...breaks].some(t=>t>previous && t<p.bar_end)) { segments.push(''); owner = next }
    previous = p.bar_end
    segments[segments.length-1] += `${p.x},${p.y} `
  }
  return {points:plotted,segments,zero:y(0),levels:Array.from({length:5},(_,i)=>({y:i*35,label:`${(high-(high-low)*i/4).toFixed(1)}%`})),message:null}
}
export interface FusionTheory {
  model_version: string
  hindsight: boolean
  executable: boolean
  returns: readonly {reference_trade_id:string;return_pct:string;ideal_exit_price:string}[]
  sum_return_percentage_points: string
  win_rate_pct?: string | null
  mean_return_pct?: string | null
}
type CurveTrade = {reference_trade_id:string;status:'OPEN'|'CLOSED'|'ROLLOVER_INTERRUPTED'|'DATA_INTERRUPTED';statistics_membership:string|null;reference_return_pct:string|null;exit_bar_end:string|null}
export function fusionTheoreticalCurve<T extends CurveTrade>(data: {curve?:readonly T[];items:readonly T[];records_truncated:boolean;groups:readonly {model:string;closed_count:number;sum_return_percentage_points:string|null}[];theoretical?:FusionTheory|null}) {
  const fail = () => ({points:[] as {trade:T;cumulative:string;value:number}[],message:'理论值所需的完整持有区段暂不可用。'})
  const group = data.groups.find(g=>g.model==='fusion'), theory=data.theoretical
  if (!group || !theory || theory.model_version!=='newow_dual_fusion_hindsight_peak_high_v1' || !theory.hindsight || theory.executable) return fail()
  const ordinary = closedReferenceCurve(data.curve??data.items,group.closed_count,group.sum_return_percentage_points,'entry_in_window_v1',data.curve===undefined&&data.records_truncated)
  if (ordinary.message) return fail()
  const returns = new Map(theory.returns.map(t=>[t.reference_trade_id,t.return_pct]))
  if (returns.size!==ordinary.points.length || theory.returns.length!==ordinary.points.length || ordinary.points.some(p=>!returns.has(p.trade.reference_trade_id))) return fail()
  return closedReferenceCurve(ordinary.points.map(p=>({...p.trade,reference_return_pct:returns.get(p.trade.reference_trade_id)!})),group.closed_count,theory.sum_return_percentage_points)
}

/** Rebase fusion's local date tabs by entry membership, while preserving null interruptions. */
export function holdingCurveWindow(curve: HoldingCurve | null | undefined, trades: readonly (CurveTrade & {entry_trading_day?:string;entry_bar_end:string})[], since: string, through: string): HoldingCurve | null {
  if (!curve) return null
  const closed = trades.filter(t=>t.status==='CLOSED' && t.statistics_membership==='entry_in_window_v1' && (t.entry_trading_day ?? new Date(Date.parse(t.entry_bar_end)+8*3600000).toISOString().slice(0,10)) >= since && (t.entry_trading_day ?? new Date(Date.parse(t.entry_bar_end)+8*3600000).toISOString().slice(0,10)) <= through).sort((a,b)=>(a.exit_bar_end??'').localeCompare(b.exit_bar_end??''))
  let total = '0', index = 0
  const points: HoldingCurvePoint[] = []
  for (const p of curve.points) {
    while (index < closed.length && closed[index]!.exit_bar_end! <= p.bar_end) {
      const next = closed[index++]!
      if (next.reference_return_pct === null) return null
      const sum = sumReferenceReturns([total,next.reference_return_pct]); if (sum === null) return null
      total = sum
    }
    if (p.trading_day < since || p.trading_day > through) continue
    const member = p.entry_trading_day != null && p.entry_trading_day >= since && p.entry_trading_day <= through
    const floating = p.marked_return_percentage_points === null ? null : member ? p.floating_return_pct : '0'
    points.push({...p,closed_return_percentage_points:total,floating_return_pct:floating,marked_return_percentage_points:floating===null?null:sumReferenceReturns([total,floating])})
  }
  return {...curve,points}
}
