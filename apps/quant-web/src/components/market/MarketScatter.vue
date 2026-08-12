<script setup lang="ts">
import { computed } from 'vue'
import type { MarketRadarItem } from '@/types/market'

const props = defineProps<{ items: MarketRadarItem[] }>()
const emit = defineEmits<{ open: [item: MarketRadarItem] }>()

const points = computed(() => props.items.filter((item) => item.price_change_1d !== null && item.oi_change_1d !== null))
const scale = computed(() => Math.max(
  0.05,
  ...points.value.flatMap((item) => [Math.abs(item.price_change_1d!), Math.abs(item.oi_change_1d!)]),
))

function pointStyle(item: MarketRadarItem) {
  const max = scale.value
  const x = 50 + (item.price_change_1d! / max) * 44
  const y = 50 - (item.oi_change_1d! / max) * 44
  const size = 8 + Math.min(10, Math.log10(Math.max(item.turnover ?? 1, 1)) * 2)
  return { left: `${Math.min(94, Math.max(4, x))}%`, top: `${Math.min(94, Math.max(4, y))}%`, width: `${size}px`, height: `${size}px` }
}

function percent(value: number | null) { return value === null ? '—' : `${(value * 100).toFixed(1)}%` }
</script>

<template>
  <section class="market-scatter" aria-labelledby="market-scatter-heading">
    <header><span>结构分布</span><h2 id="market-scatter-heading">价格变化 × OI 变化</h2></header>
    <div class="market-scatter__quadrants" aria-hidden="true">
      <span class="q q--tl">下跌 + 增仓</span><span class="q q--tr">上涨 + 增仓</span>
      <span class="q q--bl">下跌 + 减仓</span><span class="q q--br">上涨 + 减仓</span>
    </div>
    <div class="market-scatter__plot" aria-label="价格变化与持仓变化散点图">
      <i class="market-scatter__vertical" /><i class="market-scatter__horizontal" />
      <button
        v-for="item in points"
        :key="item.symbol"
        class="market-scatter__point"
        :style="pointStyle(item)"
        :aria-label="`${item.symbol.toUpperCase()} ${item.product_name}`"
        :title="`${item.symbol.toUpperCase()} ${item.product_name} · 1D ${percent(item.price_change_1d)} · OI ${percent(item.oi_change_1d)} · 量比 ${item.volume_ratio20?.toFixed(2) ?? '—'} · ATR ${percent(item.atr14_percentile252)}`"
        @click="emit('open', item)"
      />
      <p v-if="!points.length">暂无同时具备价格与 OI 变化的数据</p>
    </div>
  </section>
</template>

<style scoped>
.market-scatter { position: relative; padding: 16px; min-height: 300px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); overflow: hidden; }.market-scatter header span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-scatter h2 { margin: 3px 0 0; font-size: var(--gy-font-size-md); }
.market-scatter__plot { position: relative; height: 220px; margin-top: 18px; border: 1px solid var(--gy-border); background: linear-gradient(90deg, transparent 49.8%, var(--gy-border) 50%, transparent 50.2%), linear-gradient(transparent 49.8%, var(--gy-border) 50%, transparent 50.2%), var(--gy-bg-app); }.market-scatter__point { position: absolute; transform: translate(-50%, -50%); padding: 0; border: 2px solid #0f172a; border-radius: 50%; background: #38bdf8; cursor: pointer; box-shadow: 0 0 0 1px rgba(56,189,248,.45); }.market-scatter__point:hover { background: #f59e0b; }.market-scatter__plot p { margin: 0; padding: 96px 16px; text-align: center; color: var(--gy-text-muted); }
.market-scatter__quadrants { position: absolute; inset: 62px 16px 16px; pointer-events: none; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.q { position: absolute; }.q--tl { top: 4px; left: 6px; }.q--tr { top: 4px; right: 6px; }.q--bl { bottom: 4px; left: 6px; }.q--br { right: 6px; bottom: 4px; }
</style>
