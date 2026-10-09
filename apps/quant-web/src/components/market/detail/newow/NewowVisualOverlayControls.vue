<script setup lang="ts">
import type { VisualOverlayPreferences } from '@/utils/newowVisualOverlays'
import { validDonchianWindow } from '@/utils/newowVisualOverlays'
const props = defineProps<{ modelValue: VisualOverlayPreferences }>()
const emit = defineEmits<{ 'update:modelValue': [value: VisualOverlayPreferences] }>()
function setWindow(event: Event) {
  const input = event.target as HTMLInputElement
  const window = Number(input.value)
  if (validDonchianWindow(window)) emit('update:modelValue', { ...props.modelValue, window })
  else input.value = String(props.modelValue.window)
}
</script>
<template><div class="visual-overlay-controls" aria-label="图表参考叠加">
<button :aria-pressed="modelValue.donchian" @click="emit('update:modelValue',{...modelValue,donchian:!modelValue.donchian})">唐奇安通道</button>
<label>窗口 <input aria-label="唐奇安窗口" type="number" min="5" max="120" step="1" :value="modelValue.window" @change="setWindow" /></label>
<button :aria-pressed="modelValue.stop" @click="emit('update:modelValue',{...modelValue,stop:!modelValue.stop})">止损参考线</button>
<span>仅图表参考</span></div></template>
<style scoped>.visual-overlay-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:#667085}input{width:56px}button{padding:6px;border:1px solid #ddd;border-radius:4px;background:#fff;color:#667085}button[aria-pressed="true"]{color:#2563eb;border-color:#2563eb}</style>
