<script setup lang="ts">
import { ref, useId } from 'vue'
import { useDetailOverlay } from './overlay/useDetailOverlay'
import MarketDetailIcon from './MarketDetailIcon.vue'

const props = defineProps<{ open: boolean; title: string; identityKey: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const titleId = `market-facts-dialog-title-${useId()}`
function close() { emit('close') }
const { onNativeClose, onBackdrop } = useDetailOverlay({
  panel: dialog, open: () => props.open, identity: () => props.identityKey, native: true, close,
})
</script>

<template>
  <dialog
    ref="dialog"
    class="market-facts-dialog gy-detail-dialog"
    :aria-labelledby="titleId"
    @cancel.prevent="close"
    @close="onNativeClose"
    @click="onBackdrop"
  >
    <header class="market-facts-dialog__header">
      <div class="market-facts-dialog__title-row">
        <h2 :id="titleId">{{ title }}</h2>
        <slot name="status" />
      </div>
      <button type="button" aria-label="关闭行情数据详情" autofocus @click="close">
        <MarketDetailIcon name="close" :size="18" />
      </button>
    </header>
    <div class="market-facts-dialog__body"><slot /></div>
  </dialog>
</template>

<style scoped>
.market-facts-dialog { width: min(520px, calc(100vw - 32px)); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-detail-card-bg); color: var(--gy-text-primary); }
.market-facts-dialog__header { display: flex; align-items: center; justify-content: space-between; gap: var(--gy-space-3); padding: var(--gy-space-4) var(--gy-space-5); border-bottom: 1px solid var(--gy-border); flex-shrink: 0; }
.market-facts-dialog__title-row { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; }
.market-facts-dialog h2 { margin: 0; font-size: var(--gy-font-size-lg); }
.market-facts-dialog button { display: grid; place-items: center; flex: 0 0 auto; width: 36px; height: 36px; padding: 0; border: 0; border-radius: var(--gy-radius-md); color: var(--gy-text-muted); background: var(--gy-bg-hover); cursor: pointer; }
.market-facts-dialog button:hover { color: var(--gy-text-primary); }
.market-facts-dialog__body { min-height: 0; padding: var(--gy-space-4) var(--gy-space-5) var(--gy-space-5); overflow: auto; overflow-wrap: anywhere; }

@media (max-width: 480px) {
  .market-facts-dialog__header { padding: var(--gy-space-3) var(--gy-space-4); }
  .market-facts-dialog__body { padding: var(--gy-space-3) var(--gy-space-4) var(--gy-space-4); }
}
</style>
