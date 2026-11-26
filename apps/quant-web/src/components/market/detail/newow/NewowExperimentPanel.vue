<script setup lang="ts">
import { experimentVolumeBars, type ExperimentVolumeSource } from '@/utils/newowExperimentVolume'
import { volumeColors, validVolume, VOLUME_DISPLAY_VERSION, VOLUME_SCALE_OPTIONS } from '@/utils/volumeDisplay'
import { readNewowChartDisplayTheme } from '@/utils/newowChartDisplayTheme'
import { createChartHost, DISPLAY_CATALOG, type ChartHost } from '@guiyi/quant-chart'
import ChartLayerDiagnostics from '../../../kline/ChartLayerDiagnostics.vue'

import NewowBreakoutOverlay from './NewowBreakoutOverlay.vue'
import {breakoutBand,type BreakoutPoint,type NewowBreakoutEvent} from '@/utils/newowBreakoutEvents'
import NewowDisplayOverlay from './NewowDisplayOverlay.vue'
import {displayIndexVisible,type DisplayPoint,type NewowDisplayEvent} from '@/utils/newowDisplayEvents'
import { MAX_ACCUMULATED_REFERENCE_TRADES } from '@/utils/newowReferenceParts'
import PerformancePanel from '../../../performance/PerformancePanel.vue'
import ReturnCurveSvg from '../../../charts/ReturnCurveSvg.vue'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
import { marketFrequencyLabel } from '@/utils/marketDisplay'

import NewowVisualOverlayControls from './NewowVisualOverlayControls.vue'
import { readVisualOverlayPreferences, saveVisualOverlayPreferences, visualDonchian, retainBuildStop, retainedStopPrice, type RetainedBuildStop } from '@/utils/newowVisualOverlays'
import {newowReferencePoints,newowReferencePrice,newowReferencePercent} from '@/utils/newowPagePresentation'
import {computed,inject,onBeforeUnmount,onMounted,ref,shallowRef,watch} from 'vue'
import {createChart,type CandlestickData,type IChartApi,type ISeriesApi,type Time,type IRange} from 'lightweight-charts'
import {DETAIL_CHART_SESSION,detailChartVolumeBars, detailChartViewport,placeDetailChartViewport,detailChartTime,detailChartIndex,resetDetailChartWindow,type DetailChartSession} from '@/utils/detailChartSession'
import {getNewowExperiment,getNewowExperimentHistory} from '@/api/newowExperiments'
import {EXPERIMENT_OPTIONS,ExperimentRequestGeneration,experimentRangeParams,experimentVisibleSegments,experimentMarkerLabel,type ExperimentRange,type ExperimentDetail,type ExperimentBar,type ExperimentKind} from '@/utils/newowExperiments'
import {formatPerformancePercent} from '@/utils/marketDisplay'
import {pagePerformanceAnnualized} from '@/utils/newowPagePerformance'
import {layoutNiuwaReferenceCallouts,type PositionedCallout} from '@/utils/referenceCalloutLayout'
import {formatChartTimeInShanghai} from '@/utils/barTime'
const emit=defineEmits<{'select-breakout':[event:NewowBreakoutEvent]; 'select-display':[event:NewowDisplayEvent]; 'analyze-channel': []; context: [value: {asOf:string;physicalContract:string|null;segmentId:string|null;latestState:import('@/utils/newowExperiments').ExperimentSegment['latest_state']|null}|null] }>()
const props=defineProps<{product:string;frequency:string;kind:ExperimentKind;asOf:string|null;volumeBars?:readonly ExperimentVolumeSource[]}>()
const detailSession=inject<DetailChartSession|null>(DETAIL_CHART_SESSION,null)
let retainedStop:RetainedBuildStop|null=null
const data=shallowRef<ExperimentDetail|null>(null),loading=ref(false),error=ref<string|null>(null),container=ref<HTMLElement|null>(null)
const inputRejected = ref(false)
const requestErrorCode = computed(() => inputRejected.value ? 'NEWOW_RESPONSE_INVALID' : error.value ? 'NEWOW_EXPERIMENT_UNAVAILABLE' : null)
function emptyLayerStatus() {
 return loading.value ? 'loading' : inputRejected.value ? 'invalid_source' : error.value ? 'compute_error' : 'missing_input'
}
const visualOverlays=ref(readVisualOverlayPreferences())
watch(visualOverlays,value=>{saveVisualOverlayPreferences(value);render()})
const range=ref<ExperimentRange>('1y')
const selectedSegment=ref<string|null>(null)
const visibleSegments=computed(()=>experimentVisibleSegments(data.value,selectedSegment.value))
const chartBars=computed(()=>{const segment=visibleSegments.value[0];return data.value?.segments.length&&!segment?[]:(data.value?.bars??[]).filter(b=>!segment||b.segment_id===segment.segment_id)})
const volumeBars=computed(()=>experimentVolumeBars(chartBars.value,props.volumeBars??[]))
let volumeThemeObserver:MutationObserver|null=null
const chartMarkers=computed(()=>{const segment=visibleSegments.value[0];return data.value?.segments.length&&!segment?[]:(data.value?.markers??[]).filter(m=>!segment||m.segment_id===segment.segment_id)})
watch([data,selectedSegment],()=>{const segment=visibleSegments.value[0];emit('context',data.value?{asOf:data.value.as_of,physicalContract:segment?.physical_contract??null,segmentId:segment?.segment_id??null,latestState:segment?.latest_state??null}:null)})
watch(data,()=>{selectedSegment.value=null})
const recordCount=ref(3),historyRows=ref<Record<string,unknown>[]>([]),historyStarted=ref(false),historyLoading=ref(false),historyError=ref(''),historyBefore=ref<string|null>(null)
let historyController:AbortController|null=null,historyGeneration=0
function resetHistory(){historyGeneration++;historyController?.abort();historyRows.value=[];historyStarted.value=false;historyLoading.value=false;historyError.value='';historyBefore.value=null}
onBeforeUnmount(resetHistory)
async function moreRecords(){
 const panel=data.value,segment=visibleSegments.value[0];if(!panel||!segment||historyLoading.value)return
 if(historyRows.value.length>recordCount.value){recordCount.value=historyRows.value.length;return}
 if(historyStarted.value&&!historyBefore.value){recordCount.value=historyRows.value.length;return}
 if(historyRows.value.length>=MAX_ACCUMULATED_REFERENCE_TRADES){historyError.value='已达到单页记录上限，请缩小统计窗口。';return}
 const own=++historyGeneration;historyController?.abort();historyController=new AbortController();historyLoading.value=true;historyError.value=''
 try{
  const page=await getNewowExperimentHistory({product:props.product,frequency:props.frequency,kind:props.kind,as_of:panel.as_of,...experimentRangeParams(panel.as_of,range.value),snapshot_token:panel.meta.snapshot_token,reference_part:'history',reference_mode:mode.value,segment_id:segment.segment_id,...(historyStarted.value&&historyBefore.value?{history_before:historyBefore.value}:{}),history_limit:Math.min(50,MAX_ACCUMULATED_REFERENCE_TRADES-historyRows.value.length)},panel,historyController.signal)
  if(own!==historyGeneration)return
  historyRows.value=historyStarted.value?[...historyRows.value,...page.items]:page.items;historyStarted.value=true;historyBefore.value=page.next_before;recordCount.value=historyRows.value.length
 }catch(failure){if(own===historyGeneration){
  const classification=failure instanceof Error && 'classification' in failure ? failure.classification : null
  if(classification==='conflict'||classification==='response_invalid'){resetHistory();data.value=null;inputRejected.value=true;error.value='快照已变化或响应校验失败，旧结果已清除，请重试当前实验。'}
  else historyError.value='历史记录暂时读取失败，请重试。'
 }}finally{if(own===historyGeneration)historyLoading.value=false}
}
watch([data,selectedSegment],()=>{recordCount.value=3})
const mode=ref<'ordinary'|'theoretical'>('ordinary')
watch([data,selectedSegment,mode],resetHistory)
watch(mode,()=>{recordCount.value=3})
watch(()=>[props.product,props.frequency].join(':'),()=>{mode.value='ordinary'})
function selectRange(next: ExperimentRange | 'ideal') { mode.value = next === 'ideal' ? 'theoretical' : 'ordinary'; range.value = next === 'ideal' ? 'all' : next }
const curvePlot=computed(()=>{
 const segment=visibleSegments.value[0],model=segment?.[mode.value]
 const dates=Array.isArray(model?.dates)?model.dates as string[]:[]
 const equity=Array.isArray(model?.equity)?model.equity as string[]:[]
 return returnCurveLayout(dates.map((date,i)=>({date:formatChartTimeInShanghai(date).slice(0,10),position:Date.parse(date),value:equity[i]===undefined?null:Number(equity[i]),segment:segment?.segment_id??'missing'})),{headroom:1.1,areaBaseline:'zero',valueUnit:'percentage_points'})
})
const option=computed(()=>EXPERIMENT_OPTIONS.find(x=>x.kind===props.kind)!)
const generation=new ExperimentRequestGeneration()
async function load() {
 const token = generation.begin()
 data.value = null
 selectedSegment.value = null
 retainedStop = null
 error.value = null
 inputRejected.value = false
 if (!props.asOf) { loading.value = false; return }
 loading.value = true
 try {
  const result = await getNewowExperiment({ product: props.product, frequency: props.frequency, kind: props.kind,
   as_of: props.asOf, ...experimentRangeParams(props.asOf, range.value) }, token.signal)
  if (token.current()) data.value = result
 } catch (failure) {
  if (!token.current()) return
  const classification = failure instanceof Error && 'classification' in failure ? failure.classification : null
  inputRejected.value = classification === 'response_invalid' || classification === 'conflict'
  error.value = '实验数据暂不可用，请重试。'
 } finally {
  if (token.current()) loading.value = false
 }
}
watch(()=>[props.product,props.frequency,props.kind,props.asOf,range.value],load,{immediate:true})
let chart:IChartApi|null=null,observer:ResizeObserver|null=null
let host: ChartHost | null = null
let candles: ISeriesApi<'Candlestick'> | null = null
let priceWritten = false
let priceWriteFailed = false
let volume: ISeriesApi<'Histogram'> | null = null
let upper: ISeriesApi<'Line'> | null = null
let lower: ISeriesApi<'Line'> | null = null
function inspectLayers() { return host?.diagnostics() ?? [] }
const time=(text:string):Time=>detailChartTime({time:text,trading_day:formatChartTimeInShanghai(text).slice(0,10)},props.frequency)
const sharedViewport=shallowRef<IRange<Time>|null>(null),sharedCursor=shallowRef<Time|null>(null),sharedRightScaleWidth=ref(0)
function publishViewport(){sharedRightScaleWidth.value=chart?.priceScale?.('right').width?.()??0;sharedViewport.value=chartBars.value.length?chart?.timeScale().getVisibleRange?.()??null:null}
function applySharedViewport(value:IRange<Time>|null){
 if(!chart||!value||!chartBars.value.length)return
 if(JSON.stringify(chart.timeScale().getVisibleRange?.())!==JSON.stringify(value))chart.timeScale().setVisibleRange(value)
}
function applySharedCursor(value:Time|null){
 if(JSON.stringify(sharedCursor.value)===JSON.stringify(value))return
 sharedCursor.value=value
 const bar=chartBars.value.find(b=>JSON.stringify(time(b.bar_end))===JSON.stringify(value))
 if(value!==null&&bar&&candles)chart?.setCrosshairPosition(Number(bar.close),value,candles)
 else chart?.clearCrosshairPosition()
}
let resetViewport=false
let framedBars: readonly ExperimentBar[] | null = null
watch([data,selectedSegment],()=>{sharedViewport.value=null;sharedCursor.value=null})
watch(selectedSegment,()=>{if(chart){resetDetailChartWindow(chart);resetViewport=true}})
function renderVisual(){
 if(!chart||!host)return
 host.removeLayer('donchian')
 host.removeLayer('stop')
 if(!candles || !priceWritten)return
 const bars=chartBars.value
 if(visualOverlays.value.donchian){
  const points=visualDonchian(bars.map(b=>({time:b.bar_end,high:Number(b.high),low:Number(b.low),owner:`${b.physical_contract}:${b.segment_id}`})),visualOverlays.value.window)
  host.renderLayer('donchian', 'newow_donchian', 'main', 'band', layer => {
   for(const [side,color] of [['upper','rgba(52,199,89,0.7)'],['lower','rgba(255,59,48,0.7)']] as const){
    const line=layer.line({color,lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false})
    line.setData(points.map(p=>({time:time(p.time),...(p[side]===null?{}:{value:p[side]!})})))
   }
   const last = points.filter(point => point.upper !== null && point.lower !== null).at(-1)
   layer.updateDiagnostics({ ...experimentDiagnostics(last?.time),
    formulaVersion: displayFormula('newow_donchian'),
    status: last ? 'ready' : bars.length ? 'warming' : 'missing_input',
    warmup: { available: Math.min(bars.length, visualOverlays.value.window), required: visualOverlays.value.window },
   })
  })
 }
 const range=chart.timeScale().getVisibleLogicalRange()
 const visible=bars.filter((bar,i)=>{const index=detailChartIndex(chart!,time(bar.bar_end),i);return !range||(index>=Math.ceil(range.from)&&index<=Math.floor(range.to))})
 const pct=props.kind==='osc-test4'?0.12:0.07
 retainedStop=retainBuildStop(retainedStop, `${props.product}:${props.frequency}:${props.kind}`, chartMarkers.value.map(m=>({time:m.bar_end,owner:`${m.physical_contract}:${m.segment_id}`,price:m.reference_price,action:m.action})),visible.map(b=>({time:b.bar_end,owner:`${b.physical_contract}:${b.segment_id}`})))
 const price=retainedStopPrice(retainedStop,pct)
 const anchor = candles
 if (price !== null && retainedStop && props.kind !== 'osc-test5') {
  const cutoff = retainedStop.anchor.time
  host.renderLayer('stop', 'newow_stop', 'main', 'price_level_zone', layer => {
   layer.priceLevel(anchor,{price,color:'#3B82F6',lineStyle:2,lineWidth:1,title:`止损价（−${pct*100}%）`,axisLabelVisible:true})
   layer.updateDiagnostics({ ...experimentDiagnostics(cutoff), formulaVersion: displayFormula('newow_stop'), status: 'ready' })
  })
 }
}
const callouts=shallowRef<PositionedCallout[]>([])
const breakoutPoints=ref<BreakoutPoint[]>([]),showBreakoutShapes=ref(true),showBreakoutWicks=ref(true)
const displayPoints=ref<DisplayPoint[]>([]),displayWidth=ref(0),displayHeight=ref(0)
watch([showBreakoutShapes, showBreakoutWicks], () => projectCallouts())

type PositionedFact = { bar_end: string; formula_version: string | null }
function renderPositionedOverlay(id: string, enabled: boolean, project: () => readonly PositionedFact[] | null) {
 return host?.renderLayer(id, id, 'main', 'marker', layer => {
  const positioned = enabled ? project() : []
  if (positioned === null) return
  let latest: PositionedFact | undefined
  for (const fact of positioned) {
   if (!latest || Date.parse(fact.bar_end) > Date.parse(latest.bar_end)) latest = fact
  }
  layer.updateDiagnostics({ ...experimentDiagnostics(latest?.bar_end), formulaVersion: latest?.formula_version ?? null,
   status: !enabled ? 'hidden' : latest ? 'ready' : emptyLayerStatus(), lastError: enabled ? requestErrorCode.value : null })
 })
}

function projectCallouts() {
 breakoutPoints.value = []
 displayPoints.value = []
 callouts.value = []
 const activeChart = chart
 const anchor = candles
 const scale = activeChart?.timeScale()
 const bounds = container.value
 const width = scale?.width?.() ?? bounds?.clientWidth ?? 0
 const height = activeChart?.panes()[0]?.getHeight?.() ?? 414
 displayWidth.value = width
 displayHeight.value = height
 const bars = priceWritten && anchor && scale ? chartBars.value : []
 const range = scale?.getVisibleLogicalRange() ?? null
 const isVisible = (x: number | null, y: number | null) => x !== null && y !== null &&
  Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= width && y >= 0 && y <= height

 if (!renderPositionedOverlay('newow_display_events', true, () => {
  displayPoints.value = (data.value?.display_events ?? []).flatMap(event => {
   if (event.kind === 'TREND_REVERSAL') return []
   const bar = bars.find(b => b.bar_end === event.bar_end && b.physical_contract === event.physical_contract && b.segment_id === event.segment_id)
   if (!bar) return []
   const x = scale!.timeToCoordinate(time(bar.bar_end))
   const y = anchor!.priceToCoordinate(event.kind === 'OSC_BREAKDOWN' ? Number(bar.low) : Number(bar.high) * (event.kind === 'ZLGJ_J' ? 1.01 : 1))
   return x != null && y != null && displayIndexVisible(detailChartIndex(activeChart!, time(bar.bar_end), bars.indexOf(bar)), range) ? [{ event, x, y }] : []
  })
  return displayPoints.value.length ? null : []
 })) displayPoints.value = []

 const candleWidth = Math.max(2, width / Math.max(1, range ? range.to - range.from : bars.length) * .6)
 const byEvent = new Map<string, BreakoutPoint>()
 for (const [id, wick, show] of [['newow_breakouts', false, showBreakoutShapes.value], ['newow_wicks', true, showBreakoutWicks.value]] as const) {
  renderPositionedOverlay(id, props.kind === 'osc-test5' && show, () => {
   const projected = (data.value?.breakout_events ?? []).flatMap(event => {
    if (event.kind.startsWith('wick_') !== wick) return []
    const bar = bars.find(b => b.bar_end === event.bar_end && b.physical_contract === event.physical_contract && b.calculation_segment_id === event.calculation_segment_id)
    if (!bar) return []
    const x = scale!.timeToCoordinate(time(bar.bar_end))
    const y = anchor!.priceToCoordinate(Number(event.side === 'up' ? bar.high : bar.low))
    const index = bars.indexOf(bar)
    return x != null && y != null && displayIndexVisible(detailChartIndex(activeChart!, time(bar.bar_end), index), range) ? [{ event, x, y, candleWidth,
     band: breakoutBand(event, bars, index, i => scale!.timeToCoordinate(time(bars[i]!.bar_end)), price => anchor!.priceToCoordinate(price), candleWidth),
    }] : []
   })
   for (const point of projected) byEvent.set(point.event.event_id, point)
   return projected.filter(point => isVisible(point.x, point.y)).map(point => point.event)
  })
 }
 breakoutPoints.value = (data.value?.breakout_events ?? []).flatMap(event => {
  const point = byEvent.get(event.event_id)
  return point ? [point] : []
 })

 if (!renderPositionedOverlay('newow_actions', true, () => {
  callouts.value = layoutNiuwaReferenceCallouts(chartMarkers.value.flatMap(marker => {
   const bar = bars.find(b => b.bar_end === marker.bar_end && b.physical_contract === marker.physical_contract && b.segment_id === marker.segment_id)
   if (!bar) return []
   const x = scale!.timeToCoordinate?.(time(marker.bar_end)), y = anchor!.priceToCoordinate?.(Number(marker.reference_price))
   if (x == null || y == null) return []
   const high = anchor!.priceToCoordinate(Number(bar.high)), low = anchor!.priceToCoordinate(Number(bar.low))
   return [{ callout: { id: marker.marker_id, time: marker.bar_end, physicalContract: marker.physical_contract, price: marker.reference_price,
    title: experimentMarkerLabel(marker), detail: '', tone: 'neutral' as const, above: marker.action === 'CLEAR' }, x, y, boxWidth: 100, boxHeight: 28,
    ...(high != null && low != null ? { candle: { left: x - 8, top: Math.min(high, low) - 3, width: 16, height: Math.abs(high - low) + 6 } } : {}),
   }]
  }), width, height)
  return callouts.value.map(({ callout }) => ({ bar_end: callout.time, formula_version: data.value?.formula_version ?? null }))
 })) callouts.value = []
}
function recordDisplayPaint(events: readonly NewowDisplayEvent[] | null) {
 if (!host) return
 if (events === null) {
  host.layer('newow_display_events', 'newow_display_events', 'main').updateDiagnostics({
   ...experimentDiagnostics(), formulaVersion: null, status: 'renderer_failure', renderer: 'marker', lastError: 'CHART_RENDERER_PAINT_FAILED',
  })
 } else {
  renderPositionedOverlay('newow_display_events', true, () => events)
 }
}
function displayFormula(id: string) {
 const source = DISPLAY_CATALOG[id]?.source
 return source?.type === 'display_transform' ? source.version : null
}

function experimentDiagnostics(cutoff?: string) {
 return {
  frequency: props.frequency,
  sourceIdentity: cutoff ? data.value?.meta?.data_revision_identity ?? data.value?.meta?.input_content_sha256 ?? null : null,
  dataCutoff: cutoff ?? null,
 }
}

function renderPrice() {
 if (!host) return
 const bars = chartBars.value
 const last = bars.at(-1)
 const retained = last ? undefined : detailSession?.readBaseLayer('candles')
 const facts = retained ?? { ...experimentDiagnostics(last?.bar_end), formulaVersion: null,
  cacheState: null, physicalContract: last?.physical_contract }
 const layer = host.layer('price', 'price', 'main')
 try {
  candles ??= layer.candles({ upColor: '#ff3b30', downColor: '#34c759', wickUpColor: '#ff3b30', wickDownColor: '#34c759', borderVisible: false })
  if (bars.length || !detailSession) candles.setData(bars.map(bar => ({
   time: time(bar.bar_end), open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close),
   physicalContract: bar.physical_contract.toUpperCase(),
  } satisfies CandlestickData<Time> & { physicalContract: string })))
  if (priceWriteFailed && !detailSession) candles.applyOptions({ visible: true })
  priceWritten = true
  priceWriteFailed = false
  layer.updateDiagnostics({ ...facts, renderer: 'candles', status: facts.dataCutoff ? 'ready' : emptyLayerStatus(),
   lastError: !facts.dataCutoff ? requestErrorCode.value : null })
  detailSession?.recordBaseLayer('candles', facts)
 } catch {
  priceWritten = false
  priceWriteFailed = true
  if (!detailSession) {
   try { candles?.applyOptions({ visible: false }) } catch { /* Retry the price write independently. */ }
  }
  const invalid = { ...experimentDiagnostics(), formulaVersion: null, cacheState: null }
  layer.updateDiagnostics({ ...invalid, renderer: 'candles', status: 'renderer_failure', lastError: 'CHART_RENDERER_UPDATE_FAILED' })
  detailSession?.recordBaseLayer('candles', invalid)
 }
}

function renderVolume(chart: IChartApi) {
 if (!host) return
 const input = detailChartVolumeBars(chart, volumeBars.value)
 const colors = volumeColors(input, readNewowChartDisplayTheme())
 const last = input.filter(validVolume).at(-1)
 const lastSource = last && 'sourceIdentity' in last && typeof last.sourceIdentity === 'string' ? last.sourceIdentity : null
 const retained = detailSession?.readBaseLayer('volume')
 const facts = { frequency: props.frequency, formulaVersion: VOLUME_DISPLAY_VERSION, cacheState: null,
  dataCutoff: last?.time ?? null, physicalContract: last?.physicalContract,
  sourceIdentity: lastSource ?? (!volumeBars.value.length && retained?.dataCutoff === last?.time ? retained?.sourceIdentity ?? null : null) }
 const written = host.renderLayer('volume', 'generic_volume', 'volume', 'histogram', layer => {
  if (!volume) {
   volume = layer.histogram({ priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false, priceScaleId: 'volume' })
   volume.priceScale().applyOptions(VOLUME_SCALE_OPTIONS)
  }
  volume.setData(input.map((bar, index) => ({
   time: detailChartTime({ time: bar.time, trading_day: bar.tradingDay ?? bar.trading_day }, props.frequency),
   ...(validVolume(bar) ? { value: bar.volume, color: colors[index] } : {}),
  })))
  layer.updateDiagnostics({ ...facts, status: last ? 'ready' : emptyLayerStatus(), lastError: last ? null : requestErrorCode.value })
  detailSession?.recordBaseLayer('volume', facts)
 })
 if (!written) volume = null
}

function renderChannel() {
 if (!host) return
 const bars = priceWritten ? chartBars.value : []
 const level = (value: string | null) => value !== null && Number.isFinite(Number(value))
 const last = bars.filter(bar => level(bar.channel_high) || level(bar.channel_low)).at(-1)
 const written = host.renderLayer('channel', 'newow_oscillation', 'main', 'line', layer => {
  upper ??= layer.line({ color: '#f7bb23', lineWidth: 2, priceLineVisible: false })
  lower ??= layer.line({ color: '#3984ff', lineWidth: 2, priceLineVisible: false })
  upper.setData(bars.map(bar => ({ time: time(bar.bar_end), ...(level(bar.channel_high) ? { value: Number(bar.channel_high) } : {}) })))
  lower.setData(bars.map(bar => ({ time: time(bar.bar_end), ...(level(bar.channel_low) ? { value: Number(bar.channel_low) } : {}) })))
  const readiness = visibleSegments.value[0]?.readiness ?? data.value?.readiness
  layer.updateDiagnostics({ ...experimentDiagnostics(last?.bar_end), formulaVersion: data.value?.formula_version ?? null,
   status: last ? 'ready' : readiness?.status === 'WARMUP' ? 'warming' : emptyLayerStatus(),
   lastError: requestErrorCode.value ?? readiness?.reason_code ?? null })
 })
 if (!written) { upper = null; lower = null }
}

function render(){
 if (!chart || !host) return
 const standaloneRange = !detailSession && !resetViewport ? chart.timeScale().getVisibleLogicalRange() : null
 const shouldFrame = resetViewport || framedBars !== chartBars.value
 resetViewport = false
 renderPrice()
 renderVolume(chart)
 renderChannel()
 if (priceWritten && chartBars.value.length) {
  if (!detailSession || (shouldFrame && !detailChartViewport(chart))) placeDetailChartViewport(chart, standaloneRange)
  framedBars = chartBars.value
 }
 publishViewport()
 renderVisual()
 projectCallouts()
}
watch([data,selectedSegment,loading,error,()=>props.volumeBars],render)
onMounted(() => {
 if (!container.value) return
 if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
  volumeThemeObserver = new MutationObserver(render)
  for (const root of [document.documentElement, document.body]) {
   if (root) volumeThemeObserver.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
  }
 }
 chart = (detailSession?.acquire ?? createChart)(container.value, {
  height: 500, width: container.value.clientWidth,
  layout: { background: { color: '#fff' }, textColor: '#333', fontSize: 12 },
  localization: { timeFormatter: formatChartTimeInShanghai, priceFormatter: (value: number) => newowReferencePrice(String(value)) },
  timeScale: { timeVisible: true },
  grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
 })
 host = createChartHost(chart)
 chart.priceScale('right').applyOptions({ scaleMargins: { top: .05, bottom: .14 } })
 const timeScale = chart.timeScale()
 const onRange = () => {
  publishViewport()
  renderVisual()
  projectCallouts()
 }
 timeScale.subscribeVisibleLogicalRangeChange(onRange)
 host.own(() => timeScale.unsubscribeVisibleLogicalRangeChange?.(onRange))
 const onCrosshair: Parameters<IChartApi['subscribeCrosshairMove']>[0] = param => {
  const next = chartBars.value.length ? param.time ?? null : null
  if (JSON.stringify(sharedCursor.value) !== JSON.stringify(next)) sharedCursor.value = next
 }
 const mountedChart = chart
 mountedChart.subscribeCrosshairMove?.(onCrosshair)
 host.own(() => mountedChart.unsubscribeCrosshairMove?.(onCrosshair))
 observer = new ResizeObserver(() => {
  if (!container.value) return
  chart?.applyOptions({ width: container.value.clientWidth })
  publishViewport()
  projectCallouts()
 })
 observer.observe(container.value)
 render()
})
onBeforeUnmount(() => {
 volumeThemeObserver?.disconnect()
 generation.clear()
 emit('context', null)
 observer?.disconnect()
 host?.dispose()
})
const pct=(v:unknown,signed=true)=>typeof v==='string'?formatPerformancePercent(v,signed):'—'
const date=(v:unknown)=>typeof v==='string'?formatChartTimeInShanghai(time(v)):'—'
const annualized=(model:Record<string,unknown>|null)=>pagePerformanceAnnualized(model&&Array.isArray(model.dates)&&Array.isArray(model.equity)?{dates:model.dates as string[],equity:model.equity as string[]}:null)
const annualizedText=(model:Record<string,unknown>|null)=>{const value=annualized(model);return value===null?'--':newowReferencePercent(String(value))}
const summary=(model:Record<string,unknown>|null)=>model?.summary as Record<string,unknown>|undefined
const totalRecords=(model:Record<string,unknown>|null)=>Number(model?.total_count??allRecords(model).length)
const records=(model:Record<string,unknown>|null)=>historyStarted.value?historyRows.value:allRecords(model).slice().reverse()
const allRecords=(model:Record<string,unknown>|null)=>Array.isArray(model?.trades)?model.trades as Record<string,unknown>[]:[]
</script>
<template>
<section class="experiment-panel newow-reference" aria-label="震荡实验策略">
<header class="experiment-heading"><strong>{{option.label}}</strong><slot name="frequency" /></header>
<p v-if="loading" role="status">正在读取实验策略…</p><p v-else-if="error" role="alert">{{error}} <button @click="load">重试</button></p><p v-else-if="!asOf" role="status">等待当前周期行情快照…</p><p v-else-if="(visibleSegments[0]?.readiness??data?.readiness)?.status==='DATA_INSUFFICIENT'" role="status">当前合约段数据不足，暂时没有实验结果。</p><p v-else-if="(visibleSegments[0]?.readiness??data?.readiness)?.status==='WARMUP'" role="status">当前合约段正在预热。</p>
<slot name="overview" />
<div class="experiment-chart-controls"><template v-if="kind==='osc-test5'"><button type="button" :aria-pressed="showBreakoutShapes" @click="showBreakoutShapes=!showBreakoutShapes">突破形态</button><button type="button" :aria-pressed="showBreakoutWicks" @click="showBreakoutWicks=!showBreakoutWicks">影线提示</button></template><slot name="chart-controls" /><NewowVisualOverlayControls v-model="visualOverlays" @analyze="emit('analyze-channel')" /><ChartLayerDiagnostics :inspect="inspectLayers" /></div>
<div class="experiment-chart-wrap"><NewowBreakoutOverlay :points="breakoutPoints" :width="displayWidth" :height="displayHeight" :shapes="showBreakoutShapes" :wicks="showBreakoutWicks" @select-breakout="emit('select-breakout',$event)" /><NewowDisplayOverlay :points="displayPoints" :width="displayWidth" :height="displayHeight" @select-display="emit('select-display',$event)" @paint="recordDisplayPaint" /><div ref="container" class="experiment-chart" />
<div class="experiment-callouts" aria-label="实验策略参考动作"><svg aria-hidden="true"><polyline v-for="item in callouts" :key="item.callout.id" :points="`${item.x},${item.y} ${item.x},${(item.y+item.lineY)/2} ${item.lineX},${(item.y+item.lineY)/2} ${item.lineX},${item.lineY}`" fill="none" /></svg>
<div v-for="item in callouts" :key="item.callout.id" class="experiment-callout" :class="{'is-compact':item.compact}" :style="{left:`${item.left}px`,top:`${item.top}px`,width:`${item.width}px`,height:`${item.height}px`}" :data-action-id="item.callout.id" :data-reference-price="item.callout.price" :title="`${item.callout.title} ${newowReferencePrice(item.callout.price)} · ${item.callout.time} · ${item.callout.physicalContract}`"><template v-if="!item.compact"><strong>{{item.callout.title}}</strong><span>{{newowReferencePrice(item.callout.price)}}</span></template><template v-else>{{item.callout.above?'▽':'△'}}</template></div></div></div>
<slot name="chart-auxiliary" :viewport="sharedViewport" :on-viewport="applySharedViewport" :right-scale-width="sharedRightScaleWidth" :cursor="sharedCursor" :on-cursor="applySharedCursor" />
<PerformancePanel kind="页面参考" :since="data?.window?.since" :through="data?.window?.through" :cutoff="data?.as_of" :version="data?.formula_version" :loading="loading" :error="error" description="实验策略 · 按合约计算段统计 · 零费用与滑点 · 非可执行收益"><header class="newow-reference__returns-heading"><span class="newow-reference__annualized" title="当前模式及合约段的页面曲线自然日年化">年化 {{annualizedText(visibleSegments[0]?.[mode] ?? null)}}</span></header>
<div class="newow-reference__presets experiment-mode" aria-label="页面统计快捷窗口"><button v-for="r in [{id:'3m',label:'近3月'},{id:'1y',label:'近1年'},{id:'3y',label:'近3年'},{id:'year',label:'今年'}]" :key="r.id" type="button" :aria-pressed="mode==='ordinary' && range===r.id" @click="selectRange(r.id as ExperimentRange)">{{r.label}}</button><button type="button" class="newow-reference__ideal" :aria-pressed="mode==='theoretical'" @click="selectRange('ideal')">理论值</button><button type="button" :aria-pressed="mode==='ordinary' && range==='all'" @click="selectRange('all')">全部</button></div>
<template v-if="data"><label class="experiment-contract">合约计算段 <select v-model="selectedSegment"><option :value="null">当前计算段 · {{data.segments.at(-1)?.physical_contract}}</option><option v-for="s in data.segments.slice(0,-1)" :key="s.segment_id" :value="s.segment_id">{{s.physical_contract}} · {{date(s.statistics_window?.through)}}</option></select></label></template>
<ReturnCurveSvg :plot="curvePlot" label="实验策略页面参考曲线" area zero-line />
<template v-if="data"><section v-for="segment in visibleSegments" :key="segment.segment_id" class="experiment-segment"><p class="experiment-segment-status">{{segment.physical_contract}}<span v-if="segment.status==='ROLLOVER_INTERRUPTED'"> · 换月中断</span><span v-else-if="segment.status==='DATA_CONFLICT'"> · 数据中断</span></p>
<template v-for="model in [segment[mode]]" :key="mode"><p v-if="model===null" role="status">该合约段不足11根，参考收益暂不可用。</p>
<section class="newow-reference__summary"><dl class="newow-reference__metrics" data-testid="experiment-summary"><div><dt>累计参考收益（百分点）</dt><dd :data-direction="Number(summary(model)?.cum_return_percentage_points)>=0?'up':'down'">{{newowReferencePoints(summary(model)?.cum_return_percentage_points as string | undefined)}}</dd></div><div><dt>胜率</dt><dd>{{pct(summary(model)?.accuracy_pct,false)}}</dd></div><div><dt>年化收益 <span title="按当前曲线首末净值比及上海日历跨度折算365日复合年化；页面参考，不代表可执行收益。">ⓘ</span></dt><dd>{{annualizedText(model)}}</dd></div><div><dt>{{mode==='ordinary'?'页面曲线回撤（百分点）':'单笔最大亏损（百分点）'}}</dt><dd class="newow-reference__drawdown">{{newowReferencePoints(summary(model)?.max_drawdown_percentage_points as string | undefined)}}</dd></div></dl></section>
<header class="experiment-records-heading"><strong>历史参考记录</strong><span>历史页面参考，仅供参考，不作为实时买卖提示</span></header>
<p v-if="!allRecords(model).length">当前口径暂无页面估值交易。</p>
<article v-for="(trade,i) in records(model).slice(0,recordCount)" :key="`${segment.segment_id}:${trade.entry_bar_end}:${trade.exit_bar_end}:${i}`" class="newow-reference__card" :data-page-force-close="trade.force_close"><header><strong class="experiment-badge">{{trade.force_close?'持仓参考中':marketFrequencyLabel(frequency as import('@/types/market').MarketFrequency)}}</strong><strong :data-direction="Number(trade.return_percentage_points)>=0?'up':'down'">{{trade.force_close?'参考浮动':'盈亏'}} {{newowReferencePercent(trade.return_percentage_points as string)}}</strong></header><p class="experiment-record-line"><span><b class="experiment-buy">建仓参考</b> <strong>{{newowReferencePrice(trade.entry_reference_price as string)}}</strong></span><time :datetime="trade.entry_bar_end as string">{{date(trade.entry_bar_end)}}</time></p><p class="experiment-record-line"><span><b class="experiment-sell">{{trade.force_close?'参考估值':trade.stop_loss?'止损清仓':trade.confirm_exit?'确认清仓':'清仓参考'}}</b>  <strong>{{newowReferencePrice(trade.exit_reference_price as string)}}</strong></span><time :datetime="trade.exit_bar_end as string">{{date(trade.exit_bar_end)}}</time></p></article>
<p v-if="historyError" role="alert">{{historyError}}</p><p class="experiment-record-count">共 {{totalRecords(model)}} 笔页面参考记录，{{`已加载 ${Math.min(recordCount, records(model).length)} 笔`}}</p><button v-if="recordCount<totalRecords(model)" class="experiment-show-all" type="button" :disabled="historyLoading" @click="moreRecords">加载更多参考记录</button><button v-else-if="recordCount>3 && totalRecords(model)>3" class="experiment-show-all" type="button" @click="recordCount=3">收起</button>
</template></section></template>
</PerformancePanel><slot name="path" />
<details v-if="data" class="experiment-basis"><summary>详情与口径</summary><p>{{option.description}}。</p><p v-if="kind!=='osc-test5'">跳空止损参考价取止损价与开盘价较低者；测试2目标参考价取锁定目标与开盘价较高者。普通统计保留末根收盘强制平仓；理论统计为基础震荡回看理想模型，与实验策略独立，按合约计算。</p><p v-if="kind==='osc-test5'">统一真突破内核参考 · 持仓不按末根强制平仓；理论值采用持仓区间事后最高价。突破待确认只展示，不产生主动作。</p><p>页面参考 · 零手续费与滑点。黄线 HHV10、蓝线 LLV10；不代表可执行收益。</p><p v-if="data.window">统计窗口 {{data.window.since}} 至 {{data.window.through}} · 主图最多显示最近2000根</p><p>截至 {{date(data.as_of)}} · {{data.formula_version}}</p><p v-for="segment in visibleSegments" :key="segment.segment_id">{{segment.latest_state?.holding?'持有':'空仓'}} · 建仓参考价 {{newowReferencePrice(segment.latest_state?.entry_reference_price)}}<template v-if="kind!=='osc-test5'"> · {{kind==='osc-test4'?'12%':'7%'}}止损 {{newowReferencePrice(segment.latest_state?.stop_reference_price)}}</template><template v-if="kind==='osc-test2'"> · 锁定目标 {{newowReferencePrice(segment.latest_state?.locked_target)}}</template><template v-if="kind==='osc-test4'"> · 确认参考价 {{newowReferencePrice(segment.latest_state?.confirm_reference)}}</template></p></details>
</section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>
.experiment-panel{min-width:0;background:var(--gy-bg-panel);padding:10px;border-radius:8px;gap:8px}.experiment-heading,.experiment-chart-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between}.experiment-panel p,.experiment-contract,.experiment-basis{font-size:12px;color:var(--gy-text-muted)}.experiment-chart-wrap{position:relative;min-width:0}.experiment-chart{height:500px;min-width:0}.experiment-curve{height:180px}.experiment-mode{justify-content:center}.experiment-mode button[aria-pressed="true"]{color:#ff6b2c;border-color:#ff6b2c}.experiment-contract{align-self:flex-end}.experiment-segment-status{margin:4px 0}.experiment-callouts{position:absolute;inset:0;pointer-events:none;z-index:4;overflow:hidden}.experiment-callouts svg{position:absolute;inset:0;width:100%;height:100%;stroke:#9B8169;stroke-width:1}.experiment-callout{position:absolute;display:grid;place-content:center;box-sizing:border-box;overflow:hidden;border:1.5px solid #AD5734;border-radius:8px;background:var(--gy-bg-panel);color:#665044;font-size:11px;line-height:13px;text-align:center;padding:1px 4px}.experiment-callout strong,.experiment-callout span{white-space:nowrap}.experiment-callout.is-compact{padding:0}.experiment-records-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:13px;margin:14px 0 8px}.experiment-records-heading span,.experiment-record-line time{font-size:11px;color:var(--gy-text-muted)}.newow-reference__card{margin:8px 0}.newow-reference__card header,.experiment-record-line{display:flex;justify-content:space-between;align-items:center;gap:8px}.experiment-record-line{margin:6px 0}.experiment-buy,[data-direction="up"]{color:#ff403a}.experiment-sell,[data-direction="down"]{color:#34c759}.experiment-badge{background:#ff9500;border-radius:3px;padding:3px 7px;color:white;font-size:11px}.experiment-record-count{text-align:center}.experiment-show-all{display:block;margin:8px auto;padding:7px 22px;border:1px solid var(--gy-border);background:white;border-radius:20px;font-size:12px}.experiment-basis summary{cursor:pointer}@media(max-width:600px){.experiment-mode{gap:5px}.experiment-records-heading span{max-width:50%;text-align:right}.experiment-record-line time{max-width:44%;text-align:right}}
</style>
