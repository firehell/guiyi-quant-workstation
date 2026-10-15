<script setup lang="ts">
import { ref, watch } from 'vue'
import type { VisualOverlayPreferences } from '@/utils/newowVisualOverlays'
import { validDonchianWindow } from '@/utils/newowVisualOverlays'
const props = defineProps<{ modelValue: VisualOverlayPreferences }>()
const emit = defineEmits<{ 'update:modelValue': [value: VisualOverlayPreferences]; analyze: [] }>()
const open = ref(false)
const draft = ref(props.modelValue.window)
const invalid = ref(false)
watch(() => props.modelValue.window, value => { draft.value = value })
function showConfig() { draft.value = props.modelValue.window; invalid.value = false; open.value = !open.value }
function apply() {
  if (!validDonchianWindow(Number(draft.value))) { invalid.value = true; return }
  emit('update:modelValue', { ...props.modelValue, window: Number(draft.value) })
  invalid.value = false
  open.value = false
}
function analyze() { open.value = false; emit('analyze') }
</script>
<template>
  <div class="visual-overlay-controls" aria-label="图表参考叠加" @keydown.esc="open = false">
    <div class="donchian-toggle">
      <button class="donchian-dot" aria-label="唐奇安通道" :aria-pressed="modelValue.donchian" @click="emit('update:modelValue', { ...modelValue, donchian: !modelValue.donchian })" />
      <button class="donchian-label" :aria-expanded="open" @click="showConfig">通道</button>
      <div v-if="open" class="donchian-popup" role="dialog" aria-label="唐奇安通道配置">
        <div class="donchian-fields">
          <label>窗口 <input :value="draft" @input="draft = Number(($event.target as HTMLInputElement).value)" aria-label="唐奇安窗口" type="number" min="5" max="120" step="1" @keydown.enter.prevent="apply" /></label>
          <span>根K</span><button class="apply" @click="apply">应用</button><button class="close" @click="open = false">关闭</button>
        </div>
        <p v-if="invalid" role="alert">请输入5～120的整数</p>
        <button class="analyze" @click="analyze">分析最佳目标价/吸筹价周期</button>
      </div>
    </div>
    <button class="stop-toggle" :aria-pressed="modelValue.stop" @click="emit('update:modelValue', { ...modelValue, stop: !modelValue.stop })">止损参考线</button>
  </div>
</template>
<style scoped>
.visual-overlay-controls{display:inline-flex;align-items:center;gap:8px;font-size:12px;color:var(--gy-text-muted)}
.donchian-toggle{position:relative;display:inline-flex;align-items:center;gap:4px;margin-left:12px}
.donchian-dot{width:8px;height:8px;padding:0;border:0;border-radius:50%;background:var(--gy-text-muted);cursor:pointer}
.donchian-dot[aria-pressed="true"]{background:#34c759}
.donchian-label{padding:0;border:0;background:transparent;color:var(--gy-text-muted);font-size:12px;cursor:pointer}
.donchian-popup{position:absolute;top:24px;right:0;z-index:30;width:280px;max-width:calc(100vw - 32px);padding:8px 10px;border:1px solid #3a3a3c;border-radius:8px;background:var(--gy-text-primary);box-shadow:0 4px 16px #0008}
.donchian-fields{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.donchian-fields label{display:flex;align-items:center;gap:6px}
input{width:42px;padding:2px 4px;border:1px solid #3a3a3c;border-radius:4px;background:#2c2c2e;color:var(--gy-bg-panel);text-align:center;font-size:11px}
.apply,.close{padding:2px 8px;border:0;border-radius:4px;color:white;background:#0a84ff;cursor:pointer}.close{background:#3a3a3c}
.analyze{width:100%;margin-top:8px;padding:4px 8px;background:#ff9500;color:var(--gy-bg-panel);border:0;border-radius:4px;font-size:10px;cursor:pointer}
.stop-toggle{padding:6px;border:1px solid #ddd;border-radius:4px;background:var(--gy-bg-panel);color:var(--gy-text-muted);font-size:12px}.stop-toggle[aria-pressed="true"]{color:#2563eb;border-color:#2563eb}
p{margin:6px 0;color:#b42318}
</style>
