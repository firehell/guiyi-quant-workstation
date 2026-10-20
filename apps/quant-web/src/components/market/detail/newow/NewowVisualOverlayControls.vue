<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import type { VisualOverlayPreferences } from '@/utils/newowVisualOverlays'
import { validDonchianWindow } from '@/utils/newowVisualOverlays'
const props = defineProps<{ modelValue: VisualOverlayPreferences }>()
const emit = defineEmits<{ 'update:modelValue': [value: VisualOverlayPreferences]; analyze: [] }>()
const root = ref<HTMLElement | null>(null), input = ref<HTMLInputElement | null>(null)
const open = ref(false)
const popupStyle = ref({left:'16px',top:'0px'})
function outside(event: PointerEvent) { if (event.target instanceof Node && !root.value?.contains(event.target)) open.value = false }
onMounted(() => { if (typeof document !== 'undefined') document.addEventListener('pointerdown', outside) })
onBeforeUnmount(() => { if (typeof document !== 'undefined') document.removeEventListener('pointerdown', outside) })
const draft = ref(props.modelValue.window)
const invalid = ref(false)
watch(() => props.modelValue.window, value => { draft.value = value })
async function showConfig() { draft.value = props.modelValue.window; invalid.value = false; open.value = !open.value; if (open.value) { const rect=root.value?.getBoundingClientRect?.(); if (rect) popupStyle.value={left:`${Math.max(16,Math.min(rect.left,window.innerWidth-318))}px`,top:`${rect.bottom+4}px`}; await nextTick(); input.value?.focus?.(); input.value?.select?.() } }
function apply() {
  if (!validDonchianWindow(Number(draft.value))) { invalid.value = true; return }
  emit('update:modelValue', { ...props.modelValue, window: Number(draft.value) })
  invalid.value = false
  open.value = false
}
function analyze() { open.value = false; emit('analyze') }
</script>
<template>
  <div ref="root" class="visual-overlay-controls" aria-label="图表参考叠加" @keydown.esc="open = false">
    <div class="donchian-toggle">
      <button class="donchian-dot" aria-label="唐奇安通道" :aria-pressed="modelValue.donchian" @click="emit('update:modelValue', { ...modelValue, donchian: !modelValue.donchian })" />
      <button class="donchian-label" :aria-expanded="open" @click="showConfig">通道</button>
      <div v-if="open" class="donchian-popup" :style="popupStyle" role="dialog" aria-label="唐奇安通道配置">
        <div class="donchian-fields">
          <label>窗口 <input ref="input" :value="draft" @input="draft = Number(($event.target as HTMLInputElement).value)" aria-label="唐奇安窗口" type="text" inputmode="numeric" pattern="[0-9]*" @keydown.enter.prevent="apply" /></label>
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
.visual-overlay-controls .donchian-dot{min-height:8px!important;width:8px;height:8px;padding:0;border:0;border-radius:50%;background:var(--gy-text-muted);cursor:pointer}
.donchian-dot[aria-pressed="true"]{background:#34c759}
.visual-overlay-controls .donchian-label{min-height:24px!important;padding:0;border:0;background:transparent;color:var(--gy-text-muted);font-size:12px;cursor:pointer}
.donchian-popup{position:fixed;z-index:30;box-sizing:border-box;width:302px;max-width:calc(100vw - 32px);padding:8px 10px;border:1px solid #3a3a3c;border-radius:8px;background:var(--gy-bg-panel);color:var(--gy-text-primary);box-shadow:0 4px 16px #0008}
.donchian-fields{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.donchian-fields label{display:flex;align-items:center;gap:6px}
input{width:42px;padding:2px 4px;border:1px solid #3a3a3c;border-radius:4px;background:#2c2c2e;color:#fff;text-align:center;font-size:11px}
.apply,.close{padding:2px 8px;border:0;border-radius:4px;color:white;background:#0a84ff;cursor:pointer}.close{background:#3a3a3c}
.analyze{width:100%;margin-top:8px;padding:4px 8px;background:#ff9500;color:var(--gy-bg-panel);border:0;border-radius:4px;font-size:10px;cursor:pointer}
.stop-toggle{padding:6px;border:1px solid #ddd;border-radius:4px;background:var(--gy-bg-panel);color:var(--gy-text-muted);font-size:12px}.stop-toggle[aria-pressed="true"]{color:#2563eb;border-color:#2563eb}
p{margin:6px 0;color:#b42318}
</style>
