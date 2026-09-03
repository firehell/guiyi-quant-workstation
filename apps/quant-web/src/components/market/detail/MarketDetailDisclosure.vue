<script setup lang="ts">
import type { MarketDetailDisclosureSection } from '@/types/marketDetail'
import MarketDetailIcon from './MarketDetailIcon.vue'

defineProps<{
  section: MarketDetailDisclosureSection
  open: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()
</script>

<template>
  <section class="detail-disclosure" :class="`detail-disclosure--${section.tone}`">
    <button
      type="button"
      :aria-expanded="open"
      :aria-controls="`detail-disclosure-${section.id}`"
      @click="emit('toggle')"
    >
      <span class="detail-disclosure__title">{{ section.title }}</span>
      <span class="detail-disclosure__summary">{{ section.summary }}</span>
      <MarketDetailIcon :name="open ? 'chevron-down' : 'chevron-right'" :size="18" />
    </button>
    <div v-if="open" :id="`detail-disclosure-${section.id}`" class="detail-disclosure__content">
      <dl>
        <div v-for="row in section.rows" :key="`${section.id}-${row.label}`">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
      <p v-if="section.updatedAt" class="detail-disclosure__updated">更新于 {{ section.updatedAt }}</p>
      <slot />
    </div>
  </section>
</template>

<style scoped>
.detail-disclosure { overflow: hidden; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-detail-card-bg); }
.detail-disclosure--warning { border-color: var(--gy-detail-warning-border); }
.detail-disclosure--unavailable { border-color: color-mix(in srgb, var(--gy-status-error) 35%, transparent); }
.detail-disclosure > button { display: grid; grid-template-columns: minmax(0, auto) 1fr auto; align-items: center; gap: var(--gy-space-3); width: 100%; min-height: 52px; padding: var(--gy-space-2) var(--gy-space-3); border: 0; color: var(--gy-text-primary); background: transparent; font: inherit; text-align: left; cursor: pointer; }
.detail-disclosure > button:hover { background: var(--gy-bg-hover); }
.detail-disclosure > button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: -2px; }
.detail-disclosure__title { font-weight: 700; }
.detail-disclosure__summary { overflow: hidden; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.detail-disclosure__content { padding: 0 var(--gy-space-3) var(--gy-space-3); }
.detail-disclosure dl { margin: 0; }
.detail-disclosure dl div { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(0, 2fr); gap: var(--gy-space-3); padding: var(--gy-space-2) 0; border-top: 1px solid var(--gy-border-subtle); }
.detail-disclosure dt { color: var(--gy-text-muted); }
.detail-disclosure dd { margin: 0; color: var(--gy-text-primary); text-align: right; overflow-wrap: anywhere; }
.detail-disclosure__updated { margin: var(--gy-space-2) 0 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }

@media (max-width: 480px) {
  .detail-disclosure > button { grid-template-columns: 1fr auto; }
  .detail-disclosure__summary { grid-column: 1 / -1; grid-row: 2; text-align: left; white-space: normal; }
}
</style>
