<script setup lang="ts">
import { computed } from 'vue'
import type { MarketRadarSectorSummary } from '@/types/market'
import { PRODUCT_SECTORS } from '@/utils/productDirectory'

const props = defineProps<{ sectors: MarketRadarSectorSummary[] }>()
const labels = new Map<string, string>(PRODUCT_SECTORS.map((sector) => [sector.id, sector.label]))
const rows = computed(() => props.sectors.map((sector) => ({ ...sector, label: labels.get(sector.sector) || sector.sector })))
function percent(value: number | null) { return value === null ? '—' : `${(value * 100).toFixed(1)}%` }
</script>

<template>
  <section class="market-sectors" aria-labelledby="market-sectors-heading">
    <header><span>既有 taxonomy</span><h2 id="market-sectors-heading">板块概览</h2></header>
    <div class="market-sectors__grid">
      <article v-for="sector in rows" :key="sector.sector">
        <strong>{{ sector.label }}</strong>
        <small>{{ sector.participant_count }}/{{ sector.total_count }} 参与</small>
        <dl><div><dt>中位1D</dt><dd>{{ percent(sector.median_price_change_1d) }}</dd></div><div><dt>关注</dt><dd>{{ sector.attention_count }}</dd></div></dl>
      </article>
    </div>
  </section>
</template>

<style scoped>
.market-sectors { padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }.market-sectors header span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-sectors h2 { margin: 3px 0 0; font-size: var(--gy-font-size-md); }.market-sectors__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; margin-top: 14px; }.market-sectors article { padding: 10px; background: var(--gy-bg-app); border-radius: var(--gy-radius-sm); }.market-sectors article > small { display: block; margin-top: 3px; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-sectors dl { display: flex; gap: 16px; margin: 10px 0 0; }.market-sectors dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-sectors dd { margin: 3px 0 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); }
</style>
