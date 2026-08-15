<script setup lang="ts">
import type { MarketRadarResponse } from '@/types/market'

defineProps<{ radar: MarketRadarResponse }>()
</script>

<template>
  <section class="radar-summary" aria-labelledby="market-summary-heading">
    <div class="radar-summary__heading">
      <div>
        <span>Market Radar</span>
        <h2 id="market-summary-heading">市场概览</h2>
      </div>
      <strong>{{ radar.expected_as_of }} · {{ radar.participant_count }}/{{ radar.active_count }}</strong>
    </div>
    <div class="radar-summary__metrics">
      <div><span>上涨</span><strong>{{ radar.summary.up_count }}</strong></div>
      <div><span>下跌</span><strong>{{ radar.summary.down_count }}</strong></div>
      <div><span>放量</span><strong>{{ radar.summary.volume_expansion_count }}</strong></div>
      <div><span>明显增仓</span><strong>{{ radar.summary.oi_increase_count }}</strong></div>
      <div><span>高波动</span><strong>{{ radar.summary.high_volatility_count }}</strong></div>
    </div>
  </section>
</template>

<style scoped>
.radar-summary { padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel-strong); }
.radar-summary__heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }.radar-summary__heading span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.radar-summary__heading h2 { margin: 3px 0 0; font-size: var(--gy-font-size-lg); }.radar-summary__heading strong { font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); }
.radar-summary__metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin-top: 16px; }.radar-summary__metrics > div { padding: 8px 10px; background: var(--gy-bg-app); border-radius: var(--gy-radius-sm); }.radar-summary__metrics span { display: block; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.radar-summary__metrics strong { display: block; margin-top: 3px; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-lg); }
@media (max-width: 720px) { .radar-summary__metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }.radar-summary__heading { align-items: baseline; }.radar-summary__heading strong { font-size: var(--gy-font-size-xs); } }
</style>
