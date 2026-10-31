<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { createChart, LineSeries, type IChartApi, type ISeriesApi, type IRange, type Time } from 'lightweight-charts'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import { alignNewowAuxiliaryChartModel, buildNewowProductChartModel, chartMarkerTime } from './newowProductChartPrimitives'
import { NewowZhaoyaoMirrorPrimitive, buildNewowZhaoyaoMirrorData } from './newowZhaoyaoMirrorPrimitive'
import { NewowUpDownEnergyPrimitive, buildNewowUpDownEnergyData } from './newowUpDownEnergyPrimitive'
import { NewowMainForceControlPrimitive, buildNewowMainForceData } from './newowMainForceControlPrimitive'
import { NewowTrendReversalPrimitive, buildNewowTrendReversalData } from './newowTrendReversalPrimitive'
import { formatChartAxisTimeInShanghai, formatChartTimeInShanghai } from '@/utils/barTime'

const props = defineProps<{ chart: NewowProductSectionResponse<'chart'> | null; auxiliary: NewowProductSectionResponse<'auxiliary'> | null; error?: string | null; rightScaleWidth?: number; viewport?: IRange<Time>|null; cursor?: Time|null }>()
const emit=defineEmits<{viewport:[value:IRange<Time>|null];cursor:[value:Time|null]}>()
const container = ref<HTMLElement | null>(null)
const aligned = computed(() => alignNewowAuxiliaryChartModel(props.chart, props.auxiliary))
let chart: IChartApi | null = null, series: ISeriesApi<'Line'> | null = null, observer: ResizeObserver | null = null
const mirror = new NewowZhaoyaoMirrorPrimitive(), energy = new NewowUpDownEnergyPrimitive(), control = new NewowMainForceControlPrimitive(), reversal = new NewowTrendReversalPrimitive()
let writtenChart:typeof props.chart=null,hasWrittenBars=false,projectingRange=false,projectingCursor=false
let userRangePending=false,draggingViewport=false
function armViewportGesture(){userRangePending=true}
function startViewportGesture(){draggingViewport=true;armViewportGesture()}
function syncViewport(){
 if(!chart||!hasWrittenBars||writtenChart!==props.chart)return
 projectingRange=true;userRangePending=false
 try{if(props.viewport)chart.timeScale().setVisibleRange(props.viewport);else chart.timeScale().fitContent()}
 finally{projectingRange=false}
}
function syncCursor(){
 if(!chart||!series||writtenChart!==props.chart)return
 projectingCursor=true
 try{if(props.cursor!=null&&hasWrittenBars)chart.setCrosshairPosition(0,props.cursor,series);else chart.clearCrosshairPosition()}
 finally{projectingCursor=false}
}
function render() {
  if (!series || !chart) return
  const model = props.chart ? buildNewowProductChartModel(props.chart) : null
  const value = aligned.value
  if(model)chart.applyOptions({timeScale:{timeVisible:model.identity.frequency.endsWith('m')}})
  series.setData(model?.bars.map(bar => ({ time: chartMarkerTime(bar.barEnd, model.identity.frequency, bar.tradingDay), value: 0 })) ?? [])
  mirror.setData(value?.component === 'zhaoyao_mirror' ? buildNewowZhaoyaoMirrorData(value.series) : [], 12)
  energy.setData(value?.component === 'up_down_energy' && model ? buildNewowUpDownEnergyData(value.series, model.bars) : [], 12)
  control.setData(value?.component === 'main_force_control' && props.auxiliary?.value?.component === 'main_force_control' ? buildNewowMainForceData(value.series, props.auxiliary.value.segments) : [], 12)
  reversal.setData(value?.component === 'trend_reversal' ? buildNewowTrendReversalData(value.series) : [], 12)
  writtenChart=props.chart;hasWrittenBars=Boolean(model?.bars.length)
  if(!hasWrittenBars){userRangePending=false;chart.clearCrosshairPosition();return}
  syncViewport();syncCursor()
}
onMounted(() => {
  if (!container.value) return
  chart = createChart(container.value, { height: 138, width: container.value.clientWidth, localization:{timeFormatter:formatChartTimeInShanghai}, layout: { textColor: '#8e8e93', fontSize: 11, background: { color: '#fff' } }, rightPriceScale: { visible: false }, timeScale: { tickMarkFormatter: formatChartAxisTimeInShanghai }, grid: { vertLines: { visible: false }, horzLines: { visible: false } } })
  series = chart.addSeries(LineSeries, { color: 'transparent', lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
  for (const primitive of [mirror, energy, control, reversal]) series.attachPrimitive(primitive)
  observer = new ResizeObserver(() => { if (chart && container.value) chart.resize(container.value.clientWidth, 138) })
  observer.observe(container.value)
  chart.timeScale().subscribeVisibleLogicalRangeChange(()=>{if(projectingRange||!userRangePending||!hasWrittenBars||writtenChart!==props.chart)return;userRangePending=false;const value=chart?.timeScale().getVisibleRange()??null;if(JSON.stringify(value)!==JSON.stringify(props.viewport??null))emit('viewport',value)})
  chart.subscribeCrosshairMove(param=>{if(projectingCursor||!hasWrittenBars||writtenChart!==props.chart)return;const next=param.time??null;if(JSON.stringify(next)!==JSON.stringify(props.cursor??null))emit('cursor',next)})
  render()
})
watch(()=>props.viewport,syncViewport,{flush:'post'})
watch(()=>props.cursor,syncCursor,{flush:'post'})
watch([() => props.chart, () => props.auxiliary], render, { flush: 'post' })
onBeforeUnmount(() => { observer?.disconnect(); chart?.remove(); chart = null; series = null })
</script>
<template>
  <section class="shared-auxiliary" aria-label="震荡背景辅助指标">
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
