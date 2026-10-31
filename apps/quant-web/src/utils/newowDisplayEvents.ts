/** Independent public display facts; never strategy actions or fills. */
export interface NewowDisplayEvent {
  event_id: string; display_version: 'newow_public_display_v3431_v1';
  kind: 'OSC_BREAKDOWN' | 'MAIN_RISE_J' | 'ZLGJ_J' | 'TREND_REVERSAL';
  source_strategy: string; formula_version: string; frequency: string;
  bar_end: string; known_at: string; physical_contract: string; segment_id: string; calculation_segment_id: string;
  source_build_id: string | null; build_bar_end: string | null; build_threshold: string | null;
  observed_close: string; signal_kind: 'rebound' | 'adjust' | null;
  page_parity: true; executable: false; quantity_effect: 'none';
}
export interface DisplayOwnerBar {bar_end:string;physical_contract:string;segment_id:string;calculation_segment_id?:string;close:string;trading_day?:string}
export function normalizeDisplayEvents(value: unknown, bars: readonly DisplayOwnerBar[], frequency:string, asOf:string): NewowDisplayEvent[] {
  if (!Array.isArray(value)) throw Error('display events invalid')
  const ids=new Set<string>(), owners=new Map(bars.map(b=>[Date.parse(b.bar_end),b]))
  return value.map((e:NewowDisplayEvent)=>{
    const bar=owners.get(Date.parse(e?.bar_end)); const decimal=(s:unknown)=>typeof s==='string'&&/^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(s)&&Number.isFinite(Number(s))
    if (!e || !bar || !/^[a-f0-9]{64}$/.test(e.event_id) || ids.has(e.event_id) || e.display_version!=='newow_public_display_v3431_v1'
      || !['OSC_BREAKDOWN','MAIN_RISE_J','ZLGJ_J','TREND_REVERSAL'].includes(e.kind) || e.frequency!==frequency
      || e.physical_contract!==bar.physical_contract || e.segment_id!==bar.segment_id || e.calculation_segment_id!==bar.calculation_segment_id
      || !Number.isFinite(Date.parse(e.known_at)) || Date.parse(e.known_at)!==Date.parse(e.bar_end) || Date.parse(e.known_at)>=Date.parse(asOf)
      || !e.formula_version || !decimal(e.observed_close) || Number(e.observed_close)!==Number(bar.close)
      || e.page_parity!==true || e.executable!==false || e.quantity_effect!=='none') throw Error('display event owner or identity conflict')
    if (e.kind==='OSC_BREAKDOWN') {
      if (!['oscillation','osc-test','osc-test2','osc-test3','osc-test4'].includes(e.source_strategy) || !e.source_build_id || !decimal(e.build_threshold)
        || !e.build_bar_end || !Number.isFinite(Date.parse(e.build_bar_end)) || Date.parse(e.build_bar_end)>Date.parse(e.bar_end) || e.signal_kind!==null) throw Error('display build association invalid')
    } else if(e.source_build_id!==null||e.build_bar_end!==null||e.build_threshold!==null
      || (e.kind==='ZLGJ_J'?(e.source_strategy!=='oscillation_attack'||e.signal_kind!==null):e.kind==='MAIN_RISE_J'?(e.source_strategy!=='main_rise'||e.signal_kind!==null):(e.source_strategy!=='trend_reversal'||!['rebound','adjust'].includes(e.signal_kind??'')))) throw Error('display source invalid')
    ids.add(e.event_id); return {...e,bar_end:bar.bar_end}
  })
}
export const BREAKDOWN_FONT='bold 10px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif'
export const REDUCE_J_FONT='600 10px -apple-system, sans-serif'
export interface DisplayPoint {event:NewowDisplayEvent;x:number;y:number}
export interface DisplayLabel extends DisplayPoint {label:string;width:number}
export function layoutDisplayLabels(points:readonly DisplayPoint[], measure:(label:string)=>number): DisplayLabel[] {
  const placed:DisplayLabel[]=[]
  for (const point of points) {
    if(point.event.kind==='TREND_REVERSAL') continue
    const isBreak=point.event.kind==='OSC_BREAKDOWN',label=isBreak?'↓破位'+Number(point.event.observed_close).toFixed(2):'J'
    const width=isBreak?Math.round(measure(label))+12:measure(label)
    let y=point.y+(isBreak?4:point.event.kind==='ZLGJ_J'?-2:-3)
    if(isBreak) for(let t=0;t<3;t++) {
      if(!placed.some(p=>p.event.kind==='OSC_BREAKDOWN'&&Math.abs(p.x-point.x)<(p.width+width)/2+2&&Math.abs(p.y-y)<14)) break
      y+=17
    }
    placed.push({...point,y,label,width})
  }
  return placed
}
export function drawDisplayLabels(ctx:CanvasRenderingContext2D, labels:readonly DisplayLabel[], dark:boolean):void {
  ctx.save();ctx.textAlign='center'
  // Oscillation source paints ZLGJ, then reduce-J, then breakdown pills.
  for(const p of labels.filter(p=>p.event.kind==='ZLGJ_J')) {
    ctx.font=REDUCE_J_FONT;ctx.textBaseline='alphabetic';ctx.fillStyle='#34c759';ctx.fillText('J',p.x,p.y)
  }
  for(const p of labels.filter(p=>p.event.kind==='MAIN_RISE_J')) {
    ctx.font=REDUCE_J_FONT;ctx.textBaseline='bottom';ctx.lineJoin='round';ctx.lineWidth=2.4
    ctx.strokeStyle=dark?'rgba(0,0,0,0.78)':'rgba(255,255,255,0.92)';ctx.strokeText('J',p.x,p.y)
    ctx.fillStyle='#00FF00';ctx.fillText('J',p.x,p.y)
  }
  for(const p of labels.filter(p=>p.event.kind==='OSC_BREAKDOWN')) {
    ctx.font=BREAKDOWN_FONT;ctx.textBaseline='middle';ctx.beginPath();ctx.roundRect(p.x-p.width/2,p.y,p.width,16,8)
    ctx.fillStyle='#00FF00';ctx.fill();ctx.fillStyle='#003300';ctx.fillText(p.label,p.x,p.y+8.5)
  }
  ctx.restore()
}
export function displayEventTitle(e:NewowDisplayEvent):string {
  return e.kind==='MAIN_RISE_J'?`主升浪 reduce-J · ${e.formula_version} · ${e.bar_end}（过程提示，非成交）`
    :e.kind==='ZLGJ_J'?`主力攻击线 ZLGJ-J · ${e.formula_version} · ${e.bar_end}（独立算法提示，非成交）`
    :`首次破位 · 当根收盘价 ${Number(e.observed_close).toFixed(2)} · 建仓阈值 ${e.build_threshold}（展示提示，非成交）`
}
export function trendReversalBadge(events:readonly NewowDisplayEvent[], bars:readonly DisplayOwnerBar[]):{state:'active'|'gone';title:string}|null {
  const last=bars.at(-1);if(!last)return null
  const owned=bars.filter(b=>b.physical_contract===last.physical_contract&&b.segment_id===last.segment_id&&b.calculation_segment_id===last.calculation_segment_id)
  if(owned.length<2)return null
  for(let age=0;age<3;age++) {
    const bar=owned.at(-1-age);if(!bar)break
    const e=events.find(e=>e.kind==='TREND_REVERSAL'&&e.bar_end===bar.bar_end&&e.physical_contract===last.physical_contract&&e.calculation_segment_id===last.calculation_segment_id)
    if(!e)continue
    const kind=e.signal_kind==='rebound'?'反弹':'调整',date=(b:DisplayOwnerBar)=>e.frequency==='1d'||e.frequency==='1w'?(b.trading_day??b.bar_end.slice(0,10)):new Date(b.bar_end).toLocaleString('sv-SE',{timeZone:'Asia/Shanghai',hour12:false})
    return age===0?{state:'active',title:`趋势转折副图有「${kind}」信号（${date(bar)}），点开查看`}
      :{state:'gone',title:`趋势转折副图「${kind}」信号已于 ${date(owned.at(-age)!)} 消失（转折已出现），信号日 ${date(bar)}，点开查看`}
  }
  return null
}

/** The public canvas includes floor(from)..ceil(to), including the last Bar. */
export function displayIndexVisible(index:number,range:{from:number;to:number}|null):boolean {
  return range===null||(index>=Math.floor(range.from)&&index<=Math.ceil(range.to))
}
