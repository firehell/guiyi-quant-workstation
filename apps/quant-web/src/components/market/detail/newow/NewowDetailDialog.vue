<script setup lang="ts">
import { ref, useId } from 'vue'
import { useDetailOverlay } from '../overlay/useDetailOverlay'
const props = defineProps<{ open: boolean; title: string; identityKey: string; wide?: boolean; variant?: 'niuwa-indicator' | 'ai-analysis' }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const titleId = `newow-dialog-title-${useId()}`
function close() { emit('close') }
const { onNativeClose, onBackdrop } = useDetailOverlay({
  panel: dialog, open: () => props.open, identity: () => props.identityKey, native: true, close,
})
</script>
<template>
  <dialog ref="dialog" class="newow-detail-dialog gy-detail-dialog" :class="{ 'newow-detail-dialog--wide': wide, 'newow-detail-dialog--niuwa-indicator': variant === 'niuwa-indicator', 'newow-detail-dialog--ai-analysis': variant === 'ai-analysis' }" :aria-labelledby="titleId" @cancel.prevent="close" @close="onNativeClose" @click="onBackdrop">
    <header><h2 :id="titleId">{{ title }}</h2><button v-if="!variant" type="button" aria-label="关闭解释" autofocus @click="close">×</button></header>
    <div class="newow-detail-dialog__body"><slot /></div>
    <footer><slot name="footer"><button type="button" @click="close">知道了</button></slot></footer>
  </dialog>
</template>
<style scoped>
.newow-detail-dialog { width:min(400px, calc(100vw - 32px)); border:1px solid var(--gy-newow-overlay-border); border-radius:12px; background:var(--gy-newow-overlay-bg); color:var(--gy-newow-overlay-text); }
.newow-detail-dialog--wide { width:min(640px, calc(100vw - 32px)); }
header, footer { display:flex; align-items:center; justify-content:space-between; padding:16px 20px; flex-shrink:0; }
h2 { margin:0; font-size:18px; }
.newow-detail-dialog__body { padding:0 20px; min-height:0; overflow:auto; overflow-wrap:anywhere; }
button { min-height:var(--gy-overlay-touch-target); min-width:var(--gy-overlay-touch-target); border:0; border-radius:7px; background:var(--gy-newow-overlay-control-bg); color:var(--gy-newow-overlay-control-text); cursor:pointer; }
footer { justify-content:center; } footer button { width:108px; background:var(--gy-newow-overlay-action); color:var(--gy-bg-panel); border-radius:999px; font-size:14px; }
.newow-detail-dialog--niuwa-indicator { width:min(360px, calc(100vw - 24px)); max-height:calc(100dvh - 24px); border:0; border-radius:22px; color:#373b42; }
.newow-detail-dialog--niuwa-indicator header { justify-content:center; padding:24px 24px 14px; }
.newow-detail-dialog--niuwa-indicator h2 { font-size:17px; font-weight:750; line-height:1.35; text-align:center; }
.newow-detail-dialog--niuwa-indicator .newow-detail-dialog__body { padding:0 24px; }
.newow-detail-dialog--niuwa-indicator footer { padding:16px 24px 24px; }
.newow-detail-dialog--niuwa-indicator footer button { width:108px; min-height:38px; border-radius:999px; background:var(--gy-newow-overlay-action); font-size:14px; font-weight:650; }
.newow-detail-dialog--ai-analysis { width:min(360px, calc(100vw - 24px)); max-height:calc(100dvh - var(--gy-overlay-viewport-gap)); border:0; border-radius:16px; color:var(--gy-text-primary); box-shadow:var(--gy-newow-ai-overlay-shadow); }
.newow-detail-dialog--ai-analysis::backdrop { background:var(--gy-newow-ai-overlay-backdrop); }
.newow-detail-dialog--ai-analysis header { justify-content:center; padding:24px 24px 16px; }
.newow-detail-dialog--ai-analysis h2 { font-size:16px; font-weight:600; text-align:center; }
.newow-detail-dialog--ai-analysis .newow-detail-dialog__body { padding:0 24px; }
.newow-detail-dialog--ai-analysis footer { padding:14px 24px 24px; }
</style>

<style scoped>
.newow-detail-dialog--ai-analysis footer :deep(.ai-primary) { background:var(--gy-newow-overlay-action); }
</style>
