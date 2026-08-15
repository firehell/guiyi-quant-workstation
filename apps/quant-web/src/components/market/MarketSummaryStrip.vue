<script setup lang="ts">
import type { MarketRadarResponse } from '@/types/market'

defineProps<{ radar: MarketRadarResponse }>()
</script>

<template>
  <section class="radar-summary" aria-labelledby="market-summary-heading">
    <div class="radar-summary__meta">
      <span class="radar-summary__eyebrow">Market Radar</span>
      <h2 id="market-summary-heading">市场概览</h2>
      <strong>{{ radar.expected_as_of }} · {{ radar.participant_count }}/{{ radar.active_count }}</strong>
    </div>
    <div class="radar-summary__chips">
      <span class="radar-summary__chip">上涨 <b class="radar-summary__count radar-summary__count--up">{{ radar.summary.up_count }}</b></span>
      <span class="radar-summary__chip">下跌 <b class="radar-summary__count radar-summary__count--down">{{ radar.summary.down_count }}</b></span>
      <span class="radar-summary__chip">放量 <b class="radar-summary__count">{{ radar.summary.volume_expansion_count }}</b></span>
      <span class="radar-summary__chip">明显增仓 <b class="radar-summary__count">{{ radar.summary.oi_increase_count }}</b></span>
      <span class="radar-summary__chip">高波动 <b class="radar-summary__count">{{ radar.summary.high_volatility_count }}</b></span>
    </div>
  </section>
</template>

<style scoped>
.radar-summary { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 10px 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.radar-summary__meta { display: flex; align-items: baseline; gap: 10px; }
.radar-summary__eyebrow { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.radar-summary__meta h2 { margin: 0; font-size: var(--gy-font-size-md); }
.radar-summary__meta strong { font-family: var(--gy-font-mono); font-size: var(--gy-font-size-xs); color: var(--gy-text-muted); font-weight: 400; }
.radar-summary__chips { display: flex; gap: 8px; flex-wrap: wrap; }
.radar-summary__chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--gy-bg-app); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-pill); color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); }
.radar-summary__count { font-family: var(--gy-font-mono); font-weight: 500; color: var(--gy-text-primary); }
.radar-summary__count--up { color: var(--gy-up); }
.radar-summary__count--down { color: var(--gy-down); }
@media (max-width: 720px) { .radar-summary { align-items: flex-start; flex-direction: column; gap: 8px; } }
</style>
