<script setup lang="ts">
import { ref, watch } from 'vue'

import type { MarketDetailFact } from '@/types/marketDetail'
import MarketDetailDrawer from './MarketDetailDrawer.vue'
import MarketDetailFactStrip from './MarketDetailFactStrip.vue'

const props = withDefaults(defineProps<{
  banner: string
  tone?: 'info' | 'warning'
  facts: readonly MarketDetailFact[]
  identityKey: string
  title?: string
}>(), { tone: 'info', title: '当前状态依据' })
const open = ref(false)
watch(() => props.identityKey, () => { open.value = false })
</script>

<template>
  <section class="detail-status-strip" :data-tone="tone" role="status">
    <p>{{ banner }}</p>
    <dl aria-label="当前关键状态">
      <div v-for="fact in facts" :key="fact.id" :data-tone="fact.tone">
        <dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd>
      </div>
    </dl>
    <button type="button" @click="open = true">查看依据</button>
    <MarketDetailDrawer :open="open" :title="title" @close="open = false">
      <p>{{ banner }}</p>
      <MarketDetailFactStrip :facts="facts" />
      <slot />
    </MarketDetailDrawer>
  </section>
</template>

<style scoped>
.detail-status-strip { display: flex; align-items: center; gap: 8px 16px; min-width: 0; min-height: 44px; padding: 6px 10px; border: 1px solid var(--gy-border-subtle); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.detail-status-strip[data-tone="warning"] { border-color: var(--gy-detail-warning-border); background: var(--gy-surface-warning); }
.detail-status-strip p { flex: 1 1 240px; min-width: 0; margin: 0; overflow: hidden; color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); text-overflow: ellipsis; white-space: nowrap; }
.detail-status-strip dl { display: flex; align-items: center; gap: 12px; margin: 0; }
.detail-status-strip dl div { display: flex; align-items: baseline; gap: 4px; min-width: 0; }
.detail-status-strip dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); white-space: nowrap; }
.detail-status-strip dd { max-width: 150px; margin: 0; overflow: hidden; color: var(--gy-text-primary); font-size: var(--gy-font-size-sm); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.detail-status-strip dl div[data-tone="up"] dd { color: var(--gy-up); }
.detail-status-strip dl div[data-tone="down"] dd { color: var(--gy-down); }
.detail-status-strip button { min-height: 36px; padding: 0 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: transparent; font: inherit; white-space: nowrap; cursor: pointer; }
@media (max-width: 720px) {
  .detail-status-strip { flex-wrap: wrap; }
  .detail-status-strip p { flex-basis: calc(100% - 100px); }
  .detail-status-strip dl { order: 3; width: 100%; overflow-x: auto; padding-bottom: 2px; }
  .detail-status-strip button { min-height: 44px; }
}
</style>
