<script setup lang="ts">
import { computed } from 'vue'

import type { MarketDetailFact } from '@/types/marketDetail'
import MarketDetailIcon from './MarketDetailIcon.vue'

const props = defineProps<{
  facts: readonly [MarketDetailFact, MarketDetailFact, MarketDetailFact]
}>()

const displayFacts = computed(() => {
  if (props.facts.length !== 3) throw new Error('MarketDetailFactStrip requires exactly three market detail facts')
  return props.facts
})
</script>

<template>
  <dl class="detail-fact-strip" data-detail-section="facts">
    <div v-for="fact in displayFacts" :key="fact.id" :class="`detail-fact-strip__item--${fact.tone}`">
      <dt>
        <MarketDetailIcon v-if="fact.icon" :name="fact.icon" :size="16" />
        {{ fact.label }}
      </dt>
      <dd>{{ fact.value }}</dd>
    </div>
  </dl>
</template>

<style scoped>
.detail-fact-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--gy-space-2); margin: 0; padding: var(--gy-space-4) 0; }
.detail-fact-strip > div { min-width: 0; padding: var(--gy-space-3); border: 1px solid var(--gy-border-subtle); border-radius: var(--gy-radius-lg); background: var(--gy-detail-section-bg); }
.detail-fact-strip dt { display: flex; align-items: center; gap: var(--gy-space-1); color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.detail-fact-strip dd { margin: var(--gy-space-2) 0 0; overflow-wrap: anywhere; color: var(--gy-text-primary); font-size: var(--gy-font-size-lg); font-weight: 700; }
.detail-fact-strip__item--up dd { color: var(--gy-up); }
.detail-fact-strip__item--down dd { color: var(--gy-down); }
.detail-fact-strip__item--warning { border-color: var(--gy-detail-warning-border) !important; }
.detail-fact-strip__item--unavailable dd { color: var(--gy-text-muted); }

@media (max-width: 480px) {
  .detail-fact-strip { grid-template-columns: 1fr; }
}
</style>
