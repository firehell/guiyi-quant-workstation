<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { mountChartHost, type ChartHost } from '@guiyi/quant-chart'
import { createChart, type ISeriesApi, type IRange, type MouseEventParams, type Time } from 'lightweight-charts'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { alignNewowAuxiliaryChartModel, buildNewowProductChartModel, chartMarkerTime } from './newowProductChartPrimitives'
import { NewowZhaoyaoMirrorPrimitive, buildNewowZhaoyaoMirrorData } from './newowZhaoyaoMirrorPrimitive'
import { NewowUpDownEnergyPrimitive, buildNewowUpDownEnergyData } from './newowUpDownEnergyPrimitive'
import { NewowMainForceControlPrimitive, buildNewowMainForceData } from './newowMainForceControlPrimitive'
import { NewowTrendReversalPrimitive, buildNewowTrendReversalData } from './newowTrendReversalPrimitive'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'

const props = defineProps<{ label?: string; chart: NewowProductSectionResponse<'chart'> | null; auxiliary: NewowProductSectionResponse<'auxiliary'> | null; error?: string | null; rightScaleWidth?: number; viewport?: IRange<Time>|null; cursor?: Time|null }>()
const emit=defineEmits<{viewport:[value:IRange<Time>|null];cursor:[value:Time|null]}>()
const container = ref<HTMLElement | null>(null)
const aligned = computed(() => alignNewowAuxiliaryChartModel(props.chart, props.auxiliary))
let host: ChartHost | null = null
let series: ISeriesApi<'Line'> | null = null
const pane = { auxiliary: 'shared' } as const
const primitives = {
  zhaoyao_mirror: new NewowZhaoyaoMirrorPrimitive(),
  up_down_energy: new NewowUpDownEnergyPrimitive(),
  main_force_control: new NewowMainForceControlPrimitive(),
  trend_reversal: new NewowTrendReversalPrimitive(),
}
let activeComponent: keyof typeof primitives | null = null
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
  const next = value?.component
  const component = next && Object.hasOwn(primitives, next) ? next as keyof typeof primitives : null
  if (component !== activeComponent) {
    host.removeLayer('selected')
    if (component) host.layer('selected', `newow.${component}`, pane).primitive(series, primitives[component])
    activeComponent = component
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
watch([() => props.chart, () => props.auxiliary], render, { flush: 'post' })
onBeforeUnmount(() => { host?.dispose(); host = null; series = null })
</script>
<template>
  <section class="shared-auxiliary" :aria-label="label ?? '震荡背景辅助指标'">
    <slot name="controls" />
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!aligned" role="status">当前合约段的辅助指标未就绪。</p>
    <!-- Only actual auxiliary gestures may drive the main viewport. LWC applies
         programmatic ranges asynchronously and may clamp them to loaded data. -->
    <div ref="container" class="shared-auxiliary__canvas" :style="{width:'calc(100% - '+(rightScaleWidth??0)+'px)'}" @wheel.capture.passive="armViewportGesture" @pointerdown.capture="startViewportGesture" @pointermove.capture="draggingViewport && armViewportGesture()" @pointerup="draggingViewport=false" @pointercancel="draggingViewport=false" @pointerleave="draggingViewport=false" />
  </section>
</template>
<style scoped>
.shared-auxiliary{background:var(--gy-bg-panel);border-top:1px solid #eee;padding:6px 0}.shared-auxiliary__canvas{height:138px;min-width:0}p{font-size:11px;color:#94611b;margin:5px 10px}
</style>
