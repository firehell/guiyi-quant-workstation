/** Geometry only; trade pairing, sampling and ETA are owned by the pure server model. */
export function historicalPathGeometry(path: import('../types/newowDecisionV2.ts').HistoricalPath, width=900) {
  const points=[...path.buys,...path.sells]
  const time=(d:string)=>Date.parse(d+'T00:00:00Z')
  const last=path.source?.as_of.slice(0,10) ?? points.at(-1)?.date ?? '1970-01-01'
  const end=Math.max(time(last),...points.map(p=>time(p.date)),time(path.eta?.date ?? last))
  const first=Math.min(...points.map(p=>time(p.date)))
  const prices=[...points.map(p=>Number(p.price)),Number(path.current),Number(path.holding?path.target:path.cost)].filter(p=>Number.isFinite(p)&&p>0)
  const pad=(Math.max(...prices)-Math.min(...prices))*0.14 || 1
  const low=Math.min(...prices)-pad,high=Math.max(...prices)+pad
  const x=(date:string)=>45+(time(date)-first)/(end-first || 1)*(width-100)
  const y=(price:string)=>270-(Number(price)-low)/(high-low || 1)*225
  const buy=path.buys.map(p=>({...p,x:x(p.date),y:y(p.price)})),sell=path.sells.map(p=>({...p,x:x(p.date),y:y(p.price)}))
  const interp=(line:typeof buy,d:string)=>{
    if (!line.length) return 0
    const t=time(d)
    if (t<=time(line[0]!.date)) return line[0]!.y
    for(let i=1;i<line.length;i++) if(t<=time(line[i]!.date)) {const a=line[i-1]!,b=line[i]!;return a.y+(b.y-a.y)*(t-time(a.date))/(time(b.date)-time(a.date)||1)}
    return line.at(-1)!.y
  }
  const dates=[...new Set(points.map(p=>p.date))].sort()
  const kind=new Map([...path.buys.map(p=>[p.date,'buy'] as const),...path.sells.map(p=>[p.date,'sell'] as const)])
  const segments=(points:typeof buy,color:string)=>points.flatMap((p,i)=>{
    const next=points[i+1];if(!next)return []
    const chain=[p.date,...dates.filter(d=>d>p.date&&d<next.date),next.date]
    return chain.slice(0,-1).map((d,j)=>({x1:x(d),y1:interp(points,d),x2:x(chain[j+1]!),y2:interp(points,chain[j+1]!),color,holding:kind.get(d)==='buy'}))
  })
  const forecastDate=path.eta?.date ?? last
  const to=path.eta?.to_price ?? (path.holding?path.target:path.cost)
  const extended=(points:typeof buy)=>to && points.length && forecastDate>points.at(-1)!.date ? [...points,{date:forecastDate,price:to,x:x(forecastDate),y:y(to)}]:points
  const extBuy=extended(buy),extSell=extended(sell)
  const envelopeDates=[...new Set([...dates,...(to?[forecastDate]:[])])].sort()
  const labels:Array<{x:number;y:number;text:string}> = []
  for(const p of [...buy.slice(-2),...sell.slice(-2)]) {
    const lx=Math.max(45,Math.min(width-100,p.x))
    let ly=p.y-9
    for(const offset of [0,-14,14,-28,28,-42,42,-56,56,-70,70]) {
      const candidate=Math.max(16,Math.min(280,p.y-9+offset))
      if(!labels.some(q=>Math.abs(q.x-lx)<95&&Math.abs(q.y-candidate)<13)){ly=candidate;break}
    }
    labels.push({x:lx,y:ly,text:p.price})
  }
  const envelope=[...envelopeDates.map(d=>`${x(d)},${Math.min(interp(extBuy,d),interp(extSell,d))}`),...[...envelopeDates].reverse().map(d=>`${x(d)},${Math.max(interp(extBuy,d),interp(extSell,d))}`)].join(' ')
  return {width,buy,sell,envelope,labels,segments:[...segments(buy,'#1f5fa9'),...segments(sell,'#2e9e8f')],current:path.current ? {x:x(last),y:y(path.current)}:null,
    forecast:to ? {x:x(forecastDate),y:y(to),price:to}:null,
    background:path.background.map(b=>({...b,x:x(b.start),width:Math.max(0,x(b.end)-x(b.start))})),
    ticks:[...new Set(path.axis_dates ?? [dates[0]!,...([1,2].map(i=>new Date(first+(end-first)*i/3).toISOString().slice(0,10))),forecastDate])].map(date=>({date,x:x(date)}))}
}
