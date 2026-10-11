import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'
import type { PatternGeometry, PatternPoint } from '../../../../utils/newowPatternDisplay.ts'
import { chartMarkerTime } from './newowProductChartPrimitives.ts'
/** Hindsight decoration only; always anchored to the accepted chart time/price scales. */
export class NewowPublicPatternPrimitive implements ISeriesPrimitive<Time> {
 private attachment:SeriesAttachedParameter<Time>|null=null
 private data:PatternGeometry|null=null
 private view:IPrimitivePaneView={zOrder:()=> 'normal',renderer:()=>({draw:target=>this.draw(target)})}
 attached(attachment:SeriesAttachedParameter<Time>){this.attachment=attachment}
 detached(){this.attachment=null;this.data=null}
 paneViews():readonly IPrimitivePaneView[]{return [this.view]}
 setData(data:PatternGeometry|null){this.data=data;this.attachment?.requestUpdate()}
 private draw(target:Parameters<IPrimitivePaneRenderer['draw']>[0]){
 const attachment=this.attachment,data=this.data;if(!attachment||!data)return
 target.useMediaCoordinateSpace(({context:ctx,mediaSize})=>{
 const xy=(p:PatternPoint)=>{const x=attachment.chart.timeScale().timeToCoordinate(chartMarkerTime(p.barEnd,data.frequency,p.tradingDay)),y=attachment.series.priceToCoordinate(p.price);return x===null||y===null?null:{x,y}}
 ctx.save();ctx.beginPath();ctx.rect?.(0,0,mediaSize.width,mediaSize.height);ctx.clip?.();ctx.strokeStyle='#1b5e20';ctx.fillStyle='#1b5e20';ctx.lineWidth=2;ctx.lineJoin='round';ctx.lineCap='round'
 for(const line of data.lines){const ps=line.points.map(xy);if(ps.some(p=>p===null)||!ps.length)continue
 const a=ps[0]!;ctx.setLineDash(line.dashed?[6,4]:[]);ctx.beginPath();ctx.moveTo(a.x,a.y)
 if(line.curve&&ps.length===3){const b=ps[1]!,c=ps[2]!
 if(line.curve==='cup'){
 const dx=Math.abs(b.x-a.x),x1=a.x+dx*.28,x2=a.x+dx*.5,x3=a.x+dx*.72
 ctx.bezierCurveTo(a.x+dx*.1,a.y+(b.y-a.y)*.05,x1-dx*.05,b.y-(b.y-a.y)*.35,x1,b.y-(b.y-a.y)*.08)
 ctx.bezierCurveTo(x1+dx*.05,b.y+(a.y-b.y)*.02,x2-dx*.03,b.y+(a.y-b.y)*.02,x2,b.y)
 ctx.bezierCurveTo(x2+dx*.03,b.y+(a.y-b.y)*.02,x3-dx*.05,b.y-(b.y-c.y)*.08,x3,b.y-(b.y-c.y)*.08)
 ctx.bezierCurveTo(x3+dx*.05,b.y-(b.y-c.y)*.35,c.x-dx*.15,c.y+(b.y-c.y)*.05,c.x,c.y)
 }else{
 const depth=Math.abs(a.y-b.y)
 ctx.bezierCurveTo(a.x+(b.x-a.x)*.3,a.y+depth*.22,a.x+(b.x-a.x)*.7,b.y-depth*.12,b.x,b.y)
 ctx.bezierCurveTo(b.x+(c.x-b.x)*.3,b.y+(c.y-b.y)*.5,b.x+(c.x-b.x)*.7,c.y-(c.y-b.y)*.25,c.x,c.y)
 }
 }else for(const p of ps.slice(1))ctx.lineTo(p!.x,p!.y)
 ctx.stroke()
 }
 ctx.setLineDash([]);ctx.font='600 11px -apple-system,sans-serif'
 for(const p of data.anchors){const v=xy(p);if(!v)continue;ctx.beginPath();ctx.arc(v.x,v.y,4.5,0,Math.PI*2);ctx.fill();ctx.fillText(`${p.label} ${p.price.toFixed(2)}`,v.x+7,v.y-9)}
 const first=data.lines[0]?.points[0];const label=first?xy(first):null
 if(label)ctx.fillText(data.label,Math.max(4,Math.min(label.x,mediaSize.width-180)),Math.max(15,label.y-26))
 ctx.restore()
 })
 }
}
