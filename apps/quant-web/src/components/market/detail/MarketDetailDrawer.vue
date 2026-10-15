<script setup lang="ts">
import { ref } from 'vue'
import { useDetailOverlay } from './overlay/useDetailOverlay'
import MarketDetailIcon from './MarketDetailIcon.vue'

const props = defineProps<{ open: boolean; title: string }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
useDetailOverlay({ panel, open: () => props.open, close: () => emit('close') })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="detail-drawer" @mousedown.self="emit('close')">
      <section
        ref="panel"
        class="detail-drawer__panel"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <header>
          <h2>{{ title }}</h2>
          <button type="button" aria-label="关闭" @click="emit('close')">
            <MarketDetailIcon name="close" />
          </button>
        </header>
        <div class="detail-drawer__content"><slot /></div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.detail-drawer { position: fixed; inset: 0; z-index: 1200; display: grid; align-items: end; background: var(--gy-overlay-drawer-backdrop); }
.detail-drawer__panel { max-height: min(78vh, 680px); overflow: auto; border-radius: var(--gy-radius-xl) var(--gy-radius-xl) 0 0; background: var(--gy-bg-overlay); box-shadow: var(--gy-shadow-overlay); }
.detail-drawer__panel:focus { outline: none; }
.detail-drawer header { position: sticky; top: 0; display: flex; align-items: center; justify-content: space-between; gap: var(--gy-space-3); padding: var(--gy-space-3) var(--gy-space-4); border-bottom: 1px solid var(--gy-border); background: var(--gy-bg-overlay); }
.detail-drawer h2 { margin: 0; color: var(--gy-text-primary); font-size: var(--gy-font-size-lg); }
.detail-drawer button { display: inline-grid; min-width: var(--gy-overlay-touch-target); min-height: var(--gy-overlay-touch-target); place-items: center; border: 0; border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: transparent; cursor: pointer; }
.detail-drawer button:hover { background: var(--gy-bg-hover); }
.detail-drawer button:focus-visible { outline: var(--gy-overlay-focus-width) solid var(--gy-border-focus); outline-offset: 2px; }
.detail-drawer__content { padding: var(--gy-space-4); }
</style>
