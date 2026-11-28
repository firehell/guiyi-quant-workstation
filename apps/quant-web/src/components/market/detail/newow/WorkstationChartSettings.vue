<script setup lang="ts">
import { computed, ref } from 'vue'
import { MAX_AUXILIARY_PANES } from '@guiyi/quant-chart'
import { strokeOptions, type Stroke, type StrokeId, PANE_HEIGHTS, paneOptions, workstationOverlays, type PaneId, type PaneSpec, type WorkstationLayers, type WorkstationOverlay } from '@/utils/workstationChartPanes'
const layers = defineModel<WorkstationLayers>({ required: true })
const props = defineProps<{ strategy?: string }>()
const styleChoice = ref<StrokeId>('ema_10')
const styles = computed(() => strokeOptions.filter(([id]) => {
  if (id.startsWith('ema_')) return layers.value.overlays.includes(id as WorkstationOverlay)
  if (id.startsWith('boll_')) return layers.value.overlays.includes('boll')
  if (id.startsWith('macd_')) return layers.value.panes.some(p => p.id === 'macd')
  if (props.strategy === 'trend') return id === 'a' || id === 'b'
  if (props.strategy === 'oscillation') return id === 'upper' || id === 'lower'
  return props.strategy === 'main_rise' && id.startsWith('ma')
}))
const stroke = computed(() => styles.value.find(([id]) => id === styleChoice.value) ?? styles.value[0])
function styleLine(change: Stroke) {
  if (!stroke.value) return
  const id = stroke.value[0]
  layers.value = { ...layers.value, strokes: { ...layers.value.strokes, [id]: { ...layers.value.strokes?.[id], ...change } } }
}
function toggle(id: WorkstationOverlay) {
  const current = layers.value.overlays
  layers.value = { ...layers.value, overlays: current.includes(id) ? current.filter(item => item !== id) : [...current, id] }
}
function setPanes(panes: PaneSpec[]) { layers.value = { ...layers.value, panes } }
function change(index: number, patch: Partial<PaneSpec>) {
  setPanes(layers.value.panes.map((pane, i) => i === index ? { ...pane, ...patch } : pane))
}
function move(index: number, direction: number) {
  const panes = [...layers.value.panes]
  const target = index + direction
  if (target < 0 || target >= panes.length) return
  panes.splice(target, 0, ...panes.splice(index, 1))
  setPanes(panes)
}
function add() {
  const next = paneOptions.find(item => !layers.value.panes.some(pane => pane.id === item.id))
  if (next && layers.value.panes.length < MAX_AUXILIARY_PANES) setPanes([...layers.value.panes, { id: next.id, height: 144 }])
}
</script>
<template>
  <details class="workstation-chart-settings">
    <summary>指标与副图</summary>
    <fieldset><legend>Quant Core 价格叠加</legend>
      <label v-for="item in workstationOverlays" :key="item.id"><input type="checkbox" :checked="layers.overlays.includes(item.id)" @change="toggle(item.id)" />{{ item.label }}</label>
    </fieldset>
    <fieldset v-if="stroke"><legend>线条样式</legend>
      <select aria-label="调整线条" :value="stroke[0]" @change="styleChoice = ($event.target as HTMLSelectElement).value as StrokeId"><option v-for="[id, label] in styles" :key="id" :value="id">{{ label }}</option></select>
      <label>颜色 <input type="color" :value="layers.strokes?.[stroke[0]]?.color ?? stroke[2]" @input="styleLine({ color: ($event.target as HTMLInputElement).value })" /></label>
      <label>线宽 <select :value="layers.strokes?.[stroke[0]]?.lineWidth ?? (stroke[0] === 'ema_21' ? 2 : 1)" @change="styleLine({ lineWidth: Number(($event.target as HTMLSelectElement).value) as Stroke['lineWidth'] })"><option v-for="n in [1,2,3,4]" :key="n" :value="n">{{ n }} px</option></select></label>
    </fieldset>
    <label><input type="checkbox" :checked="layers.logPrice" @change="layers = { ...layers, logPrice: !layers.logPrice }" />主图对数价格轴</label>
    <fieldset><legend>副图 · 独立纵轴</legend>
      <div v-for="(pane, i) in layers.panes" :key="i" class="pane-row">
        <select :value="pane.id" :aria-label="`副图 ${i+1} 指标`" @change="change(i, { id: ($event.target as HTMLSelectElement).value as PaneId })">
          <option v-for="option in paneOptions" :key="option.id" :value="option.id" :disabled="layers.panes.some((p,j) => j !== i && p.id === option.id)">{{ option.id === 'zhaoyao_mirror' ? option.label + '（回看重绘）' : option.label }}</option>
        </select>
        <label>高度 <select :value="pane.height" @change="change(i, { height: Number(($event.target as HTMLSelectElement).value) })"><option v-for="n in PANE_HEIGHTS" :key="n" :value="n">{{ n }} px</option></select></label>
        <button type="button" :disabled="!i" @click="move(i,-1)">上移</button><button type="button" :disabled="i+1 === layers.panes.length" @click="move(i,1)">下移</button>
        <button type="button" @click="setPanes(layers.panes.filter((_,j) => j !== i))">移除</button>
      </div>
      <button type="button" :disabled="layers.panes.length >= MAX_AUXILIARY_PANES" @click="add">添加副图</button>
    </fieldset>
  </details>
</template>
<style scoped>
.workstation-chart-settings { padding: 6px 10px; border: 1px solid var(--gy-border); font-size: 13px; }
summary, button, select { cursor: pointer; }
fieldset { border: 0; margin: 8px 0; padding: 0; }
label { display: inline-flex; align-items: center; gap: 4px; margin: 2px 10px 2px 0; }
.pane-row { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin: 4px 0; }
select,button { min-height: 28px; border: 1px solid var(--gy-border); background: var(--gy-bg-panel); color: inherit; }
</style>
