<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { useNewowProduct } from '@/composables/useNewowProduct'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type {
  NewowAuxiliaryComponent,
  NewowProductSectionResponse,
} from '@/types/newowProduct'
import {
  buildNewowAuxiliaryDisclosure,
  buildNewowProductChartModel,
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
        <template v-if="auxiliaryResponse?.value?.component === selectedAuxiliary">
          <p>公式 {{ auxiliaryResponse.value.formula_version }} · 来源 {{ auxiliaryResponse.value.source_category }}</p>
          <p>物理区段 {{ auxiliaryResponse.value.segments.length }} · {{ auxiliaryResponse.value.repainting ? '会重绘' : '非重绘' }}</p>
          <ul v-if="selectedAuxiliary === 'cup_handle'">
            <template v-for="segment in auxiliaryResponse.value.segments" :key="segment.segment_id">
              <li v-for="witness in Array.isArray(segment.data) ? segment.data : []" :key="witness.witness_id">
                {{ witness.candidate_id }} · 确认 {{ witness.confirmed_at }}
              </li>
            </template>
          </ul>
        </template>
        <p v-else-if="auxiliaryDisclosure.applicability === 'loading' || auxiliaryDisclosure.applicability === 'warming'">辅助资源独立准备中…</p>
        <p v-else-if="loader.sections.auxiliary.error.value">{{ loader.sections.auxiliary.error.value }}</p>
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
@media (max-width: 640px) { .newow-product-workspace__header { align-items: flex-start; flex-direction: column; } }
</style>
