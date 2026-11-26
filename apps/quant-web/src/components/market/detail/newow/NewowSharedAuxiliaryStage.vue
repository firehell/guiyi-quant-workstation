<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { mountChartHost, type ChartHost } from '@guiyi/quant-chart'
import { createChart, type ISeriesApi, type IRange, type MouseEventParams, type Time } from 'lightweight-charts'
import type { NewowAuxiliaryComponent, NewowProductSectionResponse, NewowResourceLifecycle } from '@/types/newowProduct'
import { alignNewowAuxiliaryChartModel, buildNewowProductChartModel, chartMarkerTime } from './newowProductChartPrimitives'
import { NewowZhaoyaoMirrorPrimitive, buildNewowZhaoyaoMirrorData } from './newowZhaoyaoMirrorPrimitive'
import { NewowUpDownEnergyPrimitive, buildNewowUpDownEnergyData } from './newowUpDownEnergyPrimitive'
import { NewowMainForceControlPrimitive, buildNewowMainForceData } from './newowMainForceControlPrimitive'
import { NewowTrendReversalPrimitive, buildNewowTrendReversalData } from './newowTrendReversalPrimitive'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'
import { newowAuxiliaryLayerStatus } from '@/utils/newowAdditionalPanes'
import { projectNewowAuxiliaryReadiness } from '@/utils/newowDetailPresentation'
import ChartLayerDiagnostics from '../../../kline/ChartLayerDiagnostics.vue'

const props = defineProps<{
  label?: string
  chart: NewowProductSectionResponse<'chart'> | null
  auxiliary: NewowProductSectionResponse<'auxiliary'> | null
  component?: NewowAuxiliaryComponent | null
  lifecycle?: NewowResourceLifecycle
  error?: string | null
  rightScaleWidth?: number
  viewport?: IRange<Time> | null
  cursor?: Time | null
}>()
const emit=defineEmits<{viewport:[value:IRange<Time>|null];cursor:[value:Time|null]}>()
const container = ref<HTMLElement | null>(null)
const aligned = computed(() => {
  const input = props.auxiliary?.value
  const model = alignNewowAuxiliaryChartModel(props.chart, props.auxiliary)
  if (!model || !input || (props.component && props.component !== input.component)) return null
  const visibleOwners = new Set(props.chart?.value?.bars.map(bar =>
    `${bar.physical_contract}:${bar.calculation_segment_id}:${bar.bar_end}`,
  ))
  const hasSharedBar = input.segments.some(segment => segment.bar_ends.some(end =>
    visibleOwners.has(`${segment.physical_contract}:${segment.segment_id}:${end}`),
  ))
  return hasSharedBar ? model : null
})
let host: ChartHost | null = null
let series: ISeriesApi<'Line'> | null = null
const pane = { auxiliary: 'shared' } as const
const primitives = {
  zhaoyao_mirror: new NewowZhaoyaoMirrorPrimitive(),
  up_down_energy: new NewowUpDownEnergyPrimitive(),
  main_force_control: new NewowMainForceControlPrimitive(),
  trend_reversal: new NewowTrendReversalPrimitive(),
}
let attachedComponent: keyof typeof primitives | null = null
let diagnosticComponent: keyof typeof primitives | null = null
function inspectLayers() { return host?.diagnostics() ?? [] }
let writtenChart:typeof props.chart=null,hasWrittenBars=false,projectingRange=false,projectingCursor=false
let userRangePending=false,draggingViewport=false
function armViewportGesture(){userRangePending=true}
function startViewportGesture(){draggingViewport=true;armViewportGesture()}
function syncViewport(){
 const chart = host?.chart
 if(!chart||!hasWrittenBars||writtenChart!==props.chart)return
 projectingRange=true;userRangePending=false
 try{if(props.viewport)chart.timeScale().setVisibleRange(props.viewport);else chart.timeScale().fitContent()}
 finally{projectingRange=false}
}
function syncCursor(){
 const chart = host?.chart
 if(!chart||!series||writtenChart!==props.chart)return
 projectingCursor=true
 try{if(props.cursor!=null&&hasWrittenBars)chart.setCrosshairPosition(0,props.cursor,series);else chart.clearCrosshairPosition()}
 finally{projectingCursor=false}
}
function render() {
  if (!series || !host) return
  const chart = host.chart
  const model = props.chart ? buildNewowProductChartModel(props.chart) : null
  const value = aligned.value
  if(model)chart.applyOptions({timeScale:{timeVisible:model.identity.frequency.endsWith('m')}})
  series.setData(model?.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, model.identity.frequency, bar.tradingDay), value: 0 })) ?? [])
  const response = props.auxiliary
  const requested = props.component ?? response?.value?.component
  const component = requested && Object.hasOwn(primitives, requested) ? requested as keyof typeof primitives : null
  const accepted = component && value?.component === component ? component : null
  if (accepted !== attachedComponent || component !== diagnosticComponent) {
    host.removeLayer('selected')
    if (accepted) host.layer('selected', `newow.${accepted}`, pane).primitive(series, primitives[accepted])
    attachedComponent = accepted
    diagnosticComponent = component
  }
  const latest = props.chart?.value?.bars.at(-1)
  host.layer('axis', 'auxiliary_axis', pane).updateDiagnostics({
    status: latest ? 'ready' : 'missing_input',
    sourceIdentity: props.chart?.meta.data_revision_identity ?? props.chart?.meta.input_content_sha256 ?? null,
    frequency: model?.identity.frequency ?? null,
    dataCutoff: latest?.bar_end ?? null,
  })
  if (component) {
    const readiness = accepted ? projectNewowAuxiliaryReadiness(response?.value, latest) : null
    const status = newowAuxiliaryLayerStatus(
      props.lifecycle ?? 'not_requested', Boolean(response?.value), Boolean(accepted), readiness?.currentStatus ?? null,
      value?.series.some(item => item.points.length > 0) ?? false, props.error ?? null,
    )
    host.layer('selected', `newow.${component}`, pane).updateDiagnostics({
      status,
      // A rejected response can identify itself, but does not establish plotted provenance.
      sourceIdentity: accepted ? response?.meta.data_revision_identity ?? response?.meta.input_content_sha256 ?? null : null,
      frequency: model?.identity.frequency ?? null,
      formulaVersion: accepted ? response?.value?.formula_version ?? null : null,
      dataCutoff: accepted ? response?.meta.as_of ?? null : null,
      lastError: props.error ?? (status === 'invalid_source' ? 'CHART_AUXILIARY_SOURCE_INVALID' : null),
    })
  }
  if (value?.component === 'zhaoyao_mirror') primitives.zhaoyao_mirror.setData(buildNewowZhaoyaoMirrorData(value.series), 12)
  if (value?.component === 'up_down_energy' && model) primitives.up_down_energy.setData(buildNewowUpDownEnergyData(value.series, model.bars), 12)
  if (value?.component === 'main_force_control' && props.auxiliary?.value?.component === 'main_force_control') {
    primitives.main_force_control.setData(buildNewowMainForceData(value.series, props.auxiliary.value.segments), 12)
  }
  if (value?.component === 'trend_reversal') primitives.trend_reversal.setData(buildNewowTrendReversalData(value.series), 12)
  writtenChart=props.chart;hasWrittenBars=Boolean(model?.bars.length)
  if(!hasWrittenBars){userRangePending=false;chart.clearCrosshairPosition();return}
  syncViewport();syncCursor()
}
function mountStandalonePane(container: HTMLElement, options: Parameters<typeof createChart>[1]) {
  const chart = createChart(container, options)
  // This standalone chart displays one logical auxiliary on its only native pane.
  return new Proxy(chart, {
    get(target, property) {
      if (property === 'addSeries') {
        return (...[definition, settings]: Parameters<typeof target.addSeries>) => target.addSeries(definition, settings, 0)
      }
      const value = Reflect.get(target, property)
      return typeof value === 'function' ? value.bind(target) : value
    },
  })
}
onMounted(() => {
  const canvas = container.value
  if (!canvas) return
  host = mountChartHost(canvas, {
    height: 138, width: canvas.clientWidth,
    localization: { timeFormatter: formatChartTimeInShanghai },
    layout: { textColor: '#8e8e93', fontSize: 11, background: { color: '#fff' } },
    rightPriceScale: { visible: false },
    timeScale: { tickMarkFormatter: formatChartAxisTimeInShanghai },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
  }, mountStandalonePane)
  const chart = host.chart
  host.addAuxiliary(pane.auxiliary)
  series = host.layer('axis', 'auxiliary_axis', pane).line({ color: 'transparent', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
  const observer = new ResizeObserver(() => chart.resize(canvas.clientWidth, 138))
  observer.observe(canvas)
  host.own(() => observer.disconnect())
  const scale = chart.timeScale()
  const onRange = () => {
    if (projectingRange || !userRangePending || !hasWrittenBars || writtenChart !== props.chart) return
    userRangePending = false
    const value = scale.getVisibleRange()
    if (JSON.stringify(value) !== JSON.stringify(props.viewport ?? null)) emit('viewport', value)
  }
  const onCursor = (param: MouseEventParams<Time>) => {
    if (projectingCursor || !hasWrittenBars || writtenChart !== props.chart) return
    const next = param.time ?? null
    if (JSON.stringify(next) !== JSON.stringify(props.cursor ?? null)) emit('cursor', next)
  }
  scale.subscribeVisibleLogicalRangeChange(onRange)
  host.own(() => scale.unsubscribeVisibleLogicalRangeChange(onRange))
  chart.subscribeCrosshairMove(onCursor)
  host.own(() => chart.unsubscribeCrosshairMove(onCursor))
  render()
})
watch(()=>props.viewport,syncViewport,{flush:'post'})
watch(()=>props.cursor,syncCursor,{flush:'post'})
watch([() => props.chart, () => props.auxiliary, () => props.component, () => props.lifecycle, () => props.error], render, { flush: 'post' })
onBeforeUnmount(() => { host?.dispose(); host = null; series = null })
</script>
<template>
  <section class="shared-auxiliary" :aria-label="label ?? '震荡背景辅助指标'">
    <div class="shared-auxiliary__toolbar">
      <slot name="controls" />
      <ChartLayerDiagnostics :inspect="inspectLayers" />
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!aligned" role="status">当前合约段的辅助指标未就绪。</p>
    <!-- Only actual auxiliary gestures may drive the main viewport. LWC applies
         programmatic ranges asynchronously and may clamp them to loaded data. -->
    <div ref="container" class="shared-auxiliary__canvas" :style="{width:'calc(100% - '+(rightScaleWidth??0)+'px)'}" @wheel.capture.passive="armViewportGesture" @pointerdown.capture="startViewportGesture" @pointermove.capture="draggingViewport && armViewportGesture()" @pointerup="draggingViewport=false" @pointercancel="draggingViewport=false" @pointerleave="draggingViewport=false" />
  </section>
</template>
<style scoped>
.shared-auxiliary{background:var(--gy-bg-panel);border-top:1px solid #eee;padding:6px 0}.shared-auxiliary__canvas{height:138px;min-width:0}p{font-size:11px;color:#94611b;margin:5px 10px}
.shared-auxiliary__toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding-inline: 6px; }
</style>
