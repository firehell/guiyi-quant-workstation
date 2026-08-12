<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MarketRadarItem } from '@/types/market'
import { PRODUCT_SECTORS } from '@/utils/productDirectory'

const props = defineProps<{ items: MarketRadarItem[]; watchlist: string[] }>()
const emit = defineEmits<{ open: [item: MarketRadarItem]; toggleWatchlist: [symbol: string] }>()
const mode = ref<'all' | 'watchlist'>('all')
const sector = ref('all')

const rows = computed(() => props.items.filter((item) =>
  (mode.value === 'all' || props.watchlist.includes(item.symbol))
  && (sector.value === 'all' || item.sector === sector.value),
))
function percent(value: number | null) { return value === null ? '—' : `${(value * 100).toFixed(1)}%` }
function ratio(value: number | null) { return value === null ? '—' : `${value.toFixed(2)}x` }
</script>

<template>
  <section class="market-detail" aria-labelledby="market-detail-heading">
    <header><div><span>完整宇宙明细</span><h2 id="market-detail-heading">全市场明细</h2></div><div class="market-detail__filters"><button :class="{ active: mode === 'all' }" @click="mode = 'all'">全部</button><button :class="{ active: mode === 'watchlist' }" @click="mode = 'watchlist'">自选</button><select v-model="sector" aria-label="按板块筛选"><option value="all">全部板块</option><option v-for="item in PRODUCT_SECTORS" :key="item.id" :value="item.id">{{ item.label }}</option></select></div></header>
    <div class="market-detail__scroll"><table><thead><tr><th>品种</th><th>板块</th><th>1D</th><th>5D</th><th>量比</th><th>OI变化</th><th>ATR分位</th><th>20日位置</th><th>状态</th><th>自选</th></tr></thead><tbody><tr v-for="item in rows" :key="item.symbol"><td><button :aria-label="`${item.symbol.toUpperCase()} ${item.product_name}`" @click="emit('open', item)">{{ item.symbol.toUpperCase() }} {{ item.product_name }}</button></td><td>{{ item.sector }}</td><td>{{ percent(item.price_change_1d) }}</td><td>{{ percent(item.price_change_5d) }}</td><td>{{ ratio(item.volume_ratio20) }}</td><td>{{ percent(item.oi_change_1d) }}</td><td>{{ percent(item.atr14_percentile252) }}</td><td>{{ percent(item.position20) }}</td><td>{{ item.reason_codes.length ? '关注' : '常规' }}</td><td><button @click="emit('toggleWatchlist', item.symbol)">{{ watchlist.includes(item.symbol) ? '已自选' : '加入' }}</button></td></tr></tbody></table></div>
  </section>
</template>

<style scoped>
.market-detail { padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }.market-detail header { display: flex; justify-content: space-between; gap: 16px; align-items: end; }.market-detail header span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-detail h2 { margin: 3px 0 0; font-size: var(--gy-font-size-md); }.market-detail__filters { display: flex; gap: 6px; }.market-detail button, .market-detail select { border: 1px solid var(--gy-border); border-radius: 4px; padding: 4px 7px; background: var(--gy-bg-app); color: inherit; font-size: var(--gy-font-size-xs); cursor: pointer; }.market-detail button.active { color: #38bdf8; border-color: #38bdf8; }.market-detail__scroll { overflow-x: auto; margin-top: 14px; }table { width: 100%; min-width: 880px; border-collapse: collapse; font-size: var(--gy-font-size-sm); }th, td { padding: 8px; border-bottom: 1px solid var(--gy-border); text-align: right; white-space: nowrap; }th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }td { font-family: var(--gy-font-mono); }td button { font-family: inherit; }td:first-child button { padding: 0; border: 0; text-align: left; }
@media (max-width: 720px) { .market-detail header { align-items: start; flex-direction: column; }.market-detail__filters { flex-wrap: wrap; } }
</style>
