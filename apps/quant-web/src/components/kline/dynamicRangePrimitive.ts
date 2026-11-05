import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time } from 'lightweight-charts'
import type { DynamicRangePoint } from '@/utils/dynamicRange'

interface Cell { x: number; width: number; upper: number | null; lower: number | null; fill: string }
export class DynamicRangePrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (()=>void) | null = null
  private points: readonly DynamicRangePoint[] = []
  private timeOf: ((iso: string)=>Time | null) | null = null
  private cells: Cell[] = []
  private renderer: IPrimitivePaneRenderer = { draw: (target) => target.useMediaCoordinateSpace(({context,mediaSize}) => {
    for (const c of this.cells) {
      context.fillStyle=c.fill; context.fillRect(c.x-c.width/2,0,c.width,mediaSize.height)
      if (c.upper!==null && c.lower!==null) {
        context.strokeStyle='#4e80d9'; context.lineWidth=1; context.setLineDash([])
        for (const y of [c.upper,c.lower]) { context.beginPath(); context.moveTo(c.x-c.width/2,y); context.lineTo(c.x+c.width/2,y); context.stroke() }
      }
    }
  }) }
  private view: IPrimitivePaneView = { zOrder:()=> 'bottom', renderer:()=>this.renderer }
  attached(p: SeriesAttachedParameter<Time>) { this.chart=p.chart as IChartApi; this.series=p.series; this.requestUpdate=p.requestUpdate }
  detached() { this.chart=null; this.series=null; this.requestUpdate=null }
  paneViews() { return [this.view] }
  setData(points: readonly DynamicRangePoint[], timeOf: (iso:string)=>Time|null) { this.points=points; this.timeOf=timeOf; this.requestUpdate?.() }
  updateAllViews() {
    this.cells=[]
    if(!this.chart || !this.series || !this.timeOf)return
    const width=this.chart.timeScale().options().barSpacing
    for(const p of this.points) {
      const t=this.timeOf(p.time), x=t===null?null:this.chart.timeScale().timeToCoordinate(t)
      if(x===null || x < -width || x > this.chart.timeScale().width()+width)continue
      this.cells.push({x,width,upper:p.box?this.series.priceToCoordinate(p.box.upper):null,
        lower:p.box?this.series.priceToCoordinate(p.box.lower):null,
        fill:{RANGE:'rgba(65,103,203,0.10)',TREND_UP:'rgba(232,82,82,0.16)',TREND_DOWN:'rgba(34,164,108,0.16)',UNKNOWN:'rgba(128,128,128,0.10)'}[p.regime]})
    }
  }
}
