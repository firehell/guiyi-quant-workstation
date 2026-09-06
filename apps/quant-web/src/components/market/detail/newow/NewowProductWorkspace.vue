<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { useNewowProduct } from '@/composables/useNewowProduct'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type {
  NewowAuxiliaryComponent,
  NewowProductSectionResponse,
} from '@/types/newowProduct'
import {
  buildNewowAuxiliaryChartModel,
  buildNewowAuxiliaryDisclosure,
  buildNewowProductChartModel,
  resolveNewowAuxiliaryRenderState,
  type NewowAuxiliaryChartModel,
  type NewowAuxiliaryChartPoint,
} from './newowProductChartPrimitives'
import NewowProductChartStage from './NewowProductChartStage.vue'

const props = defineProps<{ identity: MarketDetailIdentity }>()
const emit = defineEmits<{ 'focus-resolved': [barEnd: string] }>()

const identity = computed(() => props.identity)
const loader = useNewowProduct({ identity })
const selectedSignalId = ref<string | null>(null)
const selectedAuxiliary = ref<NewowAuxiliaryComponent | null>(null)
const chartResponse = computed(() => (
  loader.sections.chart.data.value?.section === 'chart'
    ? loader.sections.chart.data.value as NewowProductSectionResponse<'chart'>
    : null
))
const chartModel = computed(() => chartResponse.value === null ? null : buildNewowProductChartModel(chartResponse.value))
const selectedAction = computed(() => chartModel.value?.actions.find((action) => action.id === selectedSignalId.value) ?? null)
const auxiliaryResponse = computed(() => (
  loader.sections.auxiliary.data.value?.section === 'auxiliary'
    ? loader.sections.auxiliary.data.value as NewowProductSectionResponse<'auxiliary'>
    : null
))
const currentAuxiliaryResponse = computed(() => (
  auxiliaryResponse.value?.value?.component === selectedAuxiliary.value
    ? auxiliaryResponse.value
    : null
))
const auxiliaryPresentation = computed(() => resolveNewowAuxiliaryRenderState(
  loader.sections.auxiliary.state.value,
  currentAuxiliaryResponse.value?.value !== null && currentAuxiliaryResponse.value?.value !== undefined,
  loader.sections.auxiliary.error.value,
))
const auxiliaryChart = computed((): NewowAuxiliaryChartModel | null => {
  const value = currentAuxiliaryResponse.value?.value
  if (!auxiliaryPresentation.value.showRetainedValue || value === null || value === undefined || value.component === 'cup_handle') return null
  return buildNewowAuxiliaryChartModel(value)
})
const auxiliaryExtent = computed(() => {
  const values = auxiliaryChart.value?.series.flatMap((series) => series.points.map((point) => point.value)) ?? []
  if (values.length === 0) return { min: 0, max: 1 }
  const min = Math.min(...values)
  const max = Math.max(...values)
  return min === max ? { min: min - 1, max: max + 1 } : { min, max }
})
const auxiliaryDisclosure = computed(() => selectedAuxiliary.value === null ? null : buildNewowAuxiliaryDisclosure(
  selectedAuxiliary.value,
  props.identity.frequency as '1w' | '1d' | '60m',
  loader.sections.auxiliary.state.value,
))
const auxiliaryOptions = [
  { id: 'main_force_control', label: '主力控盘' },
  { id: 'up_down_energy', label: '涨跌动能' },
  { id: 'zhaoyao_mirror', label: '主力照妖镜' },
] as const

async function toggleAuxiliary(component: NewowAuxiliaryComponent): Promise<void> {
  if (selectedAuxiliary.value === component) {
    selectedAuxiliary.value = null
    return
  }
  selectedAuxiliary.value = component
  if (component === 'cup_handle' && props.identity.frequency !== '1d') return
  await loader.loadAuxiliary(component)
}

function auxiliaryPointX(point: NewowAuxiliaryChartPoint, model: NewowAuxiliaryChartModel): number {
  return model.totalPoints <= 1 ? 500 : 12 + (point.index / (model.totalPoints - 1)) * 976
}

function auxiliaryPointY(point: NewowAuxiliaryChartPoint): number {
  return 168 - ((point.value - auxiliaryExtent.value.min) / (auxiliaryExtent.value.max - auxiliaryExtent.value.min)) * 156
}

function auxiliaryPolyline(points: readonly NewowAuxiliaryChartPoint[], model: NewowAuxiliaryChartModel): string {
  return points.map((point) => `${auxiliaryPointX(point, model)},${auxiliaryPointY(point)}`).join(' ')
}

function auxiliaryColor(key: string): string {
  const keys = ['kongpan', 'var4', 'ma10', 'band_entry', 'rebound_entry', 'oversold_entry', 'var3', 'ma120', 'entry', 'wash', 'distribution', 'markup', 'exit', 'inducement', 'peaks', 'caution']
  const colors = ['#2563EB', '#D97706', '#16A34A', '#7C3AED', '#DC2626', '#0891B2', '#9333EA', '#64748B']
  return colors[Math.max(0, keys.indexOf(key)) % colors.length]!
}

function selectSignal(signalId: string): void {
  if (!chartModel.value?.actions.some((action) => action.id === signalId)) return
  selectedSignalId.value = signalId
}

function resolveSignalFocus(signalId: string): void {
  const action = chartModel.value?.actions.find((item) => item.id === signalId)
  if (action !== undefined && props.identity.focusBarEnd === action.barEnd) emit('focus-resolved', action.barEnd)
}

watch(() => [props.identity.view, props.identity.symbol, props.identity.strategy, props.identity.frequency].join(':'), () => {
  selectedSignalId.value = null
  selectedAuxiliary.value = null
}, { flush: 'sync' })
watch([chartModel, () => props.identity.focusBarEnd], ([model, focusBarEnd]) => {
  if (!focusBarEnd || model === null || selectedSignalId.value !== null) return
  selectedSignalId.value = model.actions.find((action) => action.barEnd === focusBarEnd)?.id ?? null
}, { immediate: true })

onBeforeUnmount(loader.dispose)
</script>

<template>
  <section
    class="newow-product-workspace"
    data-detail-workspace="newow"
    :data-strategy="identity.strategy"
    :data-frequency="identity.frequency"
    :data-chart-state="loader.sections.chart.state.value"
    :data-auxiliary-state="loader.sections.auxiliary.state.value"
  >
    <header class="newow-product-workspace__header">
      <div>
        <p>Newow 只读策略工作台</p>
        <strong>{{ identity.strategy }} · {{ identity.frequency }} · 真实主力</strong>
      </div>
      <span>completed only · auto_order=false</span>
    </header>

    <p v-if="loader.sections.chart.error.value" class="newow-product-workspace__notice" role="status">
      {{ loader.sections.chart.error.value }}：当前组合主图事实不可用或已过期，不从通用 K 线推断策略图层。
    </p>

    <NewowProductChartStage
      :response="chartResponse"
      :selected-signal-id="selectedSignalId"
      :loading="loader.sections.chart.state.value === 'loading'"
      :has-more-before="chartModel?.nextBefore != null"
      @load-earlier="loader.loadNextChartPage"
      @select-signal="selectSignal"
      @focus-resolved="resolveSignalFocus"
    />

    <p v-if="selectedAction" class="newow-product-workspace__selection" role="status">
      {{ selectedAction.kind }} · {{ selectedAction.referencePrice }} · {{ selectedAction.physicalContract }} · {{ selectedAction.barEnd }}
    </p>

    <section class="newow-product-workspace__auxiliary" aria-label="Newow 辅助图层">
      <div class="newow-product-workspace__auxiliary-controls">
        <button
          v-for="option in auxiliaryOptions"
          :key="option.id"
          type="button"
          :aria-pressed="selectedAuxiliary === option.id"
          @click="toggleAuxiliary(option.id)"
        >
          {{ option.label }}
        </button>
        <button
          type="button"
          :aria-pressed="selectedAuxiliary === 'cup_handle'"
          @click="toggleAuxiliary('cup_handle')"
        >
          杯柄
        </button>
      </div>
      <article v-if="auxiliaryDisclosure" class="newow-product-workspace__auxiliary-state" :data-applicability="auxiliaryDisclosure.applicability">
        <strong>{{ auxiliaryDisclosure.title }}</strong>
        <p>{{ auxiliaryDisclosure.disclosure }}</p>
        <p
          v-if="auxiliaryPresentation.message"
          class="newow-product-workspace__auxiliary-message"
          :data-resource-state="auxiliaryPresentation.mode"
          role="status"
        >
          {{ auxiliaryPresentation.message }}
        </p>
        <template v-if="auxiliaryPresentation.showRetainedValue && currentAuxiliaryResponse?.value">
          <p>公式 {{ currentAuxiliaryResponse.value.formula_version }} · 来源类别 {{ currentAuxiliaryResponse.value.source_category }}</p>
          <p>物理区段 {{ currentAuxiliaryResponse.value.segments.length }} · {{ currentAuxiliaryResponse.value.repainting ? '会重绘' : '非重绘' }}</p>
          <div v-if="auxiliaryChart?.series.length" class="newow-product-workspace__auxiliary-chart">
            <svg viewBox="0 0 1000 180" role="img" :aria-label="`${auxiliaryDisclosure.title}服务端序列`">
              <g v-for="series in auxiliaryChart.series" :key="series.id">
                <polyline
                  :points="auxiliaryPolyline(series.points, auxiliaryChart)"
                  :stroke="auxiliaryColor(series.key)"
                  fill="none"
                  vector-effect="non-scaling-stroke"
                />
                <circle
                  v-for="point in series.points"
                  :key="`${series.id}:${point.barEnd}`"
                  :cx="auxiliaryPointX(point, auxiliaryChart)"
                  :cy="auxiliaryPointY(point)"
                  :fill="auxiliaryColor(series.key)"
                  r="2.5"
                >
                  <title>{{ series.label }} · {{ point.value }} · {{ point.physicalContract }} · {{ point.barEnd }}</title>
                </circle>
              </g>
            </svg>
            <ul class="newow-product-workspace__auxiliary-legend">
              <li v-for="series in auxiliaryChart.series" :key="series.id">
                <i :style="{ background: auxiliaryColor(series.key) }" />
                {{ series.label }} · {{ series.points[series.points.length - 1]?.value }}
              </li>
            </ul>
          </div>
          <ul v-if="selectedAuxiliary === 'cup_handle'">
            <template v-for="segment in currentAuxiliaryResponse.value.segments" :key="segment.segment_id">
              <li v-for="witness in Array.isArray(segment.data) ? segment.data : []" :key="witness.witness_id">
                {{ witness.candidate_id }} · 确认 {{ witness.confirmed_at }}
              </li>
            </template>
          </ul>
        </template>
      </article>
    </section>
  </section>
</template>

<style scoped>
.newow-product-workspace { display: grid; gap: var(--gy-space-4); }
.newow-product-workspace__header { display: flex; align-items: center; justify-content: space-between; gap: var(--gy-space-3); padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.newow-product-workspace__header p, .newow-product-workspace__header strong, .newow-product-workspace__auxiliary-state p { margin: 0; }
.newow-product-workspace__header p, .newow-product-workspace__header span { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.newow-product-workspace__notice, .newow-product-workspace__selection, .newow-product-workspace__auxiliary-state { margin: 0; padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.newow-product-workspace__notice { color: var(--gy-status-warning); }
.newow-product-workspace__auxiliary { display: grid; gap: var(--gy-space-3); }
.newow-product-workspace__auxiliary-controls { display: flex; flex-wrap: wrap; gap: var(--gy-space-2); }
.newow-product-workspace__auxiliary-controls button { min-height: 44px; padding: 0 var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.newow-product-workspace__auxiliary-controls button[aria-pressed="true"] { border-color: var(--gy-border-focus); color: var(--gy-accent); }
.newow-product-workspace__auxiliary-state { display: grid; gap: var(--gy-space-2); color: var(--gy-text-secondary); }
.newow-product-workspace__auxiliary-message { color: var(--gy-status-warning); }
.newow-product-workspace__auxiliary-chart { display: grid; gap: var(--gy-space-2); }
.newow-product-workspace__auxiliary-chart svg { width: 100%; min-height: 180px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-elevated); }
.newow-product-workspace__auxiliary-chart polyline { stroke-width: 1.5; }
.newow-product-workspace__auxiliary-legend { display: flex; flex-wrap: wrap; gap: var(--gy-space-2) var(--gy-space-3); margin: 0; padding: 0; list-style: none; }
.newow-product-workspace__auxiliary-legend li { display: inline-flex; align-items: center; gap: 6px; }
.newow-product-workspace__auxiliary-legend i { width: 10px; height: 10px; border-radius: 50%; }
@media (max-width: 640px) { .newow-product-workspace__header { align-items: flex-start; flex-direction: column; } }
</style>
