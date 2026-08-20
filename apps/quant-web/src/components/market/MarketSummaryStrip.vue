<script setup lang="ts">
import type { MarketRadarResponse } from '@/types/market'

defineProps<{ radar: MarketRadarResponse }>()
</script>

<template>
  <section class="radar-summary" aria-labelledby="market-summary-heading">
    <div class="radar-summary__meta">
      <span class="radar-summary__eyebrow">Market Radar</span>
      <h2 id="market-summary-heading">市场概览</h2>
      <div class="radar-summary__freshness">
        <span>当前数据日期 <b>{{ radar.data_as_of }}</b></span>
        <span>目标交易日 <b>{{ radar.target_as_of }}</b></span>
        <span
          class="radar-summary__state"
          :class="`radar-summary__state--${radar.freshness_state}`"
        >{{ radar.freshness_message }}</span>
        <span class="radar-summary__participation">{{ radar.participant_count }}/{{ radar.active_count }}</span>
      </div>
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
.radar-summary { display: flex; align-items: center; gap: 14px; padding: 10px 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); overflow: hidden; }
.radar-summary__meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.radar-summary__eyebrow { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.radar-summary__meta h2 { margin: 0; font-size: var(--gy-font-size-md); }
.radar-summary__freshness { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.radar-summary__freshness b, .radar-summary__participation { font-family: var(--gy-font-mono); color: var(--gy-text-secondary); font-weight: 500; }
.radar-summary__state { padding: 2px 8px; border-radius: var(--gy-radius-pill); font-weight: 500; }
.radar-summary__state--current { color: var(--gy-status-ok); background: var(--gy-status-ok-soft); }
.radar-summary__state--pending_after_market { color: var(--gy-status-warning); background: var(--gy-status-warning-soft); }
.radar-summary__state--degraded { color: var(--gy-status-error); background: var(--gy-status-error-soft); }
.radar-summary__chips { display: flex; gap: 8px; flex-wrap: nowrap; min-width: 0; overflow-x: auto; }
.radar-summary__chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: var(--gy-bg-app); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-pill); color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); }
.radar-summary__count { font-family: var(--gy-font-mono); font-weight: 500; color: var(--gy-text-primary); }
.radar-summary__count--up { color: var(--gy-up); }
.radar-summary__count--down { color: var(--gy-down); }
@media (max-width: 980px) { .radar-summary { align-items: flex-start; flex-direction: column; gap: 8px; } }
@media (max-width: 720px) { .radar-summary__meta { align-items: flex-start; flex-direction: column; } .radar-summary__freshness { align-items: flex-start; flex-direction: column; } }
</style>
