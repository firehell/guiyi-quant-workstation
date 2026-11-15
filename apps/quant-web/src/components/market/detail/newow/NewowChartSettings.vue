<script lang="ts">
export interface NewowChartLayers {
  structure: boolean
  actions: boolean
  hints: boolean
  breakouts: boolean
  wicks: boolean
  trendTrack: boolean
  oscillationTrack: boolean
  comparisonBackground: boolean
  detail: boolean
}
</script>

<script setup lang="ts">
import { ref, watch } from 'vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
import {
  validDonchianWindow, type ChartAnnotationPreferences, type VisualOverlayPreferences,
} from '@/utils/newowVisualOverlays'

const props = defineProps<{
  open: boolean
  identityKey: string
  annotations: ChartAnnotationPreferences
  overlays: VisualOverlayPreferences
  layers: NewowChartLayers
  dual: boolean
  oscillation: boolean
}>()
const emit = defineEmits<{
  close: []
  'update:annotations': [value: ChartAnnotationPreferences]
  'update:overlays': [value: VisualOverlayPreferences]
  'update:layers': [value: NewowChartLayers]
  analyze: []
}>()
const draft = ref('')
const invalid = ref(false)
watch(() => [props.open, props.overlays.window] as const, ([open, value]) => {
  if (open) { draft.value = String(value); invalid.value = false }
}, { immediate: true })
function editWindow(event: Event) {
  draft.value = (event.target as HTMLInputElement).value
  invalid.value = false
}
function applyWindow() {
  const value = Number(draft.value)
  invalid.value = !validDonchianWindow(value)
  if (!invalid.value) emit('update:overlays', { ...props.overlays, window: value })
}
function toggle<K extends keyof NewowChartLayers>(key: K) {
  emit('update:layers', { ...props.layers, [key]: !props.layers[key] })
}
</script>

<template>
  <NewowDetailDialog :open="open" :identity-key="identityKey" title="图表设置" variant="chart-settings" @close="emit('close')">
    <div class="chart-settings">
      <label class="setting-row"><span>纯净模式</span><input type="checkbox" :checked="annotations.pure" @change="emit('update:annotations', { ...annotations, pure: !annotations.pure })" /></label>
      <label class="setting-row"><span>高低点标注（±10）</span><input type="checkbox" :checked="annotations.extrema" @change="emit('update:annotations', { ...annotations, extrema: !annotations.extrema })" /></label>
      <label class="setting-row"><span>九转序列</span><input type="checkbox" :disabled="annotations.pure" :checked="annotations.nineTurn" @change="emit('update:annotations', { ...annotations, nineTurn: !annotations.nineTurn })" /></label>
      <fieldset :disabled="annotations.pure">
        <legend>参考叠加</legend>
        <label class="setting-row"><span>唐奇安通道</span><input type="checkbox" :checked="overlays.donchian" @change="emit('update:overlays', { ...overlays, donchian: !overlays.donchian })" /></label>
        <form class="window" @submit.prevent="applyWindow">
          <label>唐奇安窗口 <input :value="draft" inputmode="numeric" :aria-invalid="invalid || undefined" @input="editWindow" /></label>
          <span>根 K 线</span><button>应用</button>
        </form>
        <p v-if="invalid" role="alert">请输入 5–120 的整数。</p>
        <button class="analysis" type="button" @click="emit('analyze')">分析最佳目标价与吸筹价周期</button>
      </fieldset>
      <fieldset :disabled="annotations.pure">
        <legend>图层</legend>
        <label class="setting-row"><span>策略线 / 趋势带</span><input type="checkbox" :checked="layers.structure" @change="toggle('structure')" /></label>
        <label class="setting-row"><span>建仓 / 清仓</span><input type="checkbox" :checked="layers.actions" @change="toggle('actions')" /></label>
        <label v-if="!dual" class="setting-row"><span>详细标记</span><input type="checkbox" :checked="layers.detail" @change="toggle('detail')" /></label>
        <label v-if="!dual" class="setting-row"><span>过程提示</span><input type="checkbox" :checked="layers.hints" @change="toggle('hints')" /></label>
        <template v-if="oscillation">
          <label class="setting-row"><span>突破形态</span><input type="checkbox" :checked="layers.breakouts" @change="toggle('breakouts')" /></label>
          <label class="setting-row"><span>影线提示</span><input type="checkbox" :checked="layers.wicks" @change="toggle('wicks')" /></label>
        </template>
        <div class="setting-row">
          <span>双策略标注密度</span>
          <div role="group" aria-label="双策略标注密度" class="density">
            <button type="button" :disabled="!dual" :aria-pressed="layers.detail" @click="emit('update:layers', { ...layers, detail: true })">详</button>
            <button type="button" :disabled="!dual" :aria-pressed="!layers.detail" @click="emit('update:layers', { ...layers, detail: false })">简</button>
          </div>
        </div>
        <template v-if="dual">
          <label class="setting-row"><span>趋势标记</span><input type="checkbox" :checked="layers.trendTrack" @change="toggle('trendTrack')" /></label>
          <label class="setting-row"><span>震荡标记</span><input type="checkbox" :checked="layers.oscillationTrack" @change="toggle('oscillationTrack')" /></label>
          <label class="setting-row"><span>背景着色</span><input type="checkbox" :checked="layers.comparisonBackground" @change="toggle('comparisonBackground')" /></label>
        </template>
      </fieldset>
    </div>
    <template #footer><button type="button" @click="emit('close')">完成</button></template>
  </NewowDetailDialog>
</template>

<style scoped>
.chart-settings { padding: 2px 0 8px; font-size: 14px; }
.setting-row { min-height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.setting-row input { inline-size: 18px; block-size: 18px; margin: 0 6px 0 0; accent-color: var(--gy-newow-overlay-action); }
fieldset { margin: 12px 0 0; padding: 4px 0; border: 0; border-top: 1px solid var(--gy-newow-overlay-border); }
legend { font-size: 12px; font-weight: 650; color: var(--gy-text-muted); padding-right: 6px; }
.window, .window label, .density { display: flex; align-items: center; gap: 6px; }
.window { flex-wrap: wrap; padding: 3px 0 8px; }
.window input { width: 44px; text-align: center; min-height: 30px; border-radius: 6px; border: 1px solid var(--gy-newow-overlay-border); background: var(--gy-bg-panel); color: inherit; }
button { min-height: 32px; padding: 0 10px; color: inherit; background: var(--gy-newow-overlay-control-bg); border: 1px solid var(--gy-newow-overlay-border); border-radius: 6px; cursor: pointer; }
button[aria-pressed="true"]:not(:disabled) { border-color: var(--gy-newow-overlay-action); }
button:disabled, fieldset:disabled { opacity: 0.65; cursor: default; }
.analysis { min-height: 36px; }
p { margin: 2px 0 8px; font-size: 12px; color: var(--gy-text-muted); }
</style>
