<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MarketRadarItem, MarketRadarSectorSummary } from '@/types/market'
import { PRODUCT_SECTORS } from '@/utils/productDirectory'

const props = defineProps<{
  items: MarketRadarItem[]
  sectors: MarketRadarSectorSummary[]
  watchlist: string[]
}>()
const emit = defineEmits<{ open: [item: MarketRadarItem]; toggleWatchlist: [symbol: string] }>()
const mode = ref<'all' | 'watchlist'>('all')
const activeSector = ref('')

const sectorLabels = new Map<string, string>(PRODUCT_SECTORS.map((sector) => [sector.id, sector.label]))

/** 板块 Tab 直接复用后端 sector_summary 的顺序与集合，默认选中第一个。 */
const tabs = computed(() => props.sectors.map((sector) => ({
  id: sector.sector,
  label: sectorLabels.get(sector.sector) || sector.sector,
  median: sector.median_price_change_1d,
})))

watch(tabs, (next) => {
  if (!next.some((tab) => tab.id === activeSector.value)) activeSector.value = next[0]?.id ?? ''
}, { immediate: true })

const rows = computed(() => props.items.filter((item) =>
  (mode.value === 'all' || props.watchlist.includes(item.symbol))
  && (!activeSector.value || item.sector === activeSector.value),
))
function percent(value: number | null) { return value === null ? '—' : `${(value * 100).toFixed(1)}%` }
function ratio(value: number | null) { return value === null ? '—' : `${value.toFixed(2)}x` }
function medianTone(value: number | null) { return value === null ? 'flat' : value > 0 ? 'up' : value < 0 ? 'down' : 'flat' }
</script>

<template>
  <section class="market-detail" aria-labelledby="market-detail-heading">
    <header>
      <div><span>完整宇宙明细</span><h2 id="market-detail-heading">全市场明细</h2></div>
      <div class="market-detail__modes">
        <button :class="{ active: mode === 'all' }" @click="mode = 'all'">全部</button>
        <button :class="{ active: mode === 'watchlist' }" @click="mode = 'watchlist'">自选</button>
      </div>
    </header>
    <div v-if="tabs.length" class="market-detail__tabs" role="tablist" aria-label="按板块筛选">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        role="tab"
        :aria-selected="activeSector === tab.id"
        :class="['market-detail__tab', { 'market-detail__tab--active': activeSector === tab.id }]"
        @click="activeSector = tab.id"
      >
        {{ tab.label }}
        <span :class="['market-detail__tab-median', `market-detail__tab-median--${medianTone(tab.median)}`]">{{ percent(tab.median) }}</span>
      </button>
    </div>
    <div class="market-detail__scroll"><table><thead><tr><th>品种</th><th>板块</th><th>1D</th><th>5D</th><th>量比</th><th>OI变化</th><th>ATR分位</th><th>20日位置</th><th>状态</th><th>自选</th></tr></thead><tbody><tr v-for="item in rows" :key="item.symbol"><td><button :aria-label="`${item.symbol.toUpperCase()} ${item.product_name}`" @click="emit('open', item)">{{ item.symbol.toUpperCase() }} {{ item.product_name }}</button></td><td>{{ sectorLabels.get(item.sector) || item.sector }}</td><td>{{ percent(item.price_change_1d) }}</td><td>{{ percent(item.price_change_5d) }}</td><td>{{ ratio(item.volume_ratio20) }}</td><td>{{ percent(item.oi_change_1d) }}</td><td>{{ percent(item.atr14_percentile252) }}</td><td>{{ percent(item.position20) }}</td><td>{{ item.reason_codes.length ? '关注' : '常规' }}</td><td><button @click="emit('toggleWatchlist', item.symbol)">{{ watchlist.includes(item.symbol) ? '已自选' : '加入' }}</button></td></tr></tbody></table></div>
  </section>
</template>

<style scoped>
.market-detail { padding: 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-panel); }
.market-detail header { display: flex; justify-content: space-between; gap: 16px; align-items: end; }
.market-detail header span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.market-detail h2 { margin: 3px 0 0; font-size: var(--gy-font-size-md); }
.market-detail__modes { display: flex; gap: 6px; }
.market-detail__modes button { border: 1px solid var(--gy-border); border-radius: 4px; padding: 4px 7px; background: var(--gy-bg-app); color: inherit; font-size: var(--gy-font-size-xs); cursor: pointer; }
.market-detail__modes button.active { color: var(--gy-accent); border-color: var(--gy-accent); }
.market-detail__tabs { display: flex; gap: 2px; margin-top: 12px; border-bottom: 1px solid var(--gy-border); overflow-x: auto; }
.market-detail__tab { position: relative; display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px 9px; border: 0; background: none; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); cursor: pointer; white-space: nowrap; transition: color var(--gy-transition-fast); }
.market-detail__tab::after { content: ''; position: absolute; right: 8px; bottom: -1px; left: 8px; height: 2px; border-radius: 2px 2px 0 0; background: var(--gy-accent); transform: scaleX(0); transition: transform 150ms ease; }
.market-detail__tab:hover { color: var(--gy-text-primary); }
.market-detail__tab--active { color: var(--gy-accent); }
.market-detail__tab--active::after { transform: scaleX(1); }
.market-detail__tab-median { padding: 1px 5px; border-radius: var(--gy-radius-pill); font-family: var(--gy-font-mono); font-size: var(--gy-font-size-xs); }
.market-detail__tab-median--up { color: var(--gy-up); background: var(--gy-up-soft); }
.market-detail__tab-median--down { color: var(--gy-down); background: var(--gy-down-soft); }
.market-detail__tab-median--flat { color: var(--gy-text-muted); background: var(--gy-bg-elevated); }
.market-detail__scroll { overflow-x: auto; margin-top: 6px; }
table { width: 100%; min-width: 880px; border-collapse: collapse; font-size: var(--gy-font-size-sm); }
th, td { padding: 8px; border-bottom: 1px solid var(--gy-border); text-align: right; white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
td { font-family: var(--gy-font-mono); }
td button { font-family: inherit; }
td:first-child button { padding: 0; border: 0; background: none; color: inherit; text-align: left; cursor: pointer; }
td:first-child button:hover { color: var(--gy-accent); }
td:last-child button { border: 1px solid var(--gy-border); border-radius: 4px; padding: 2px 7px; background: var(--gy-bg-app); color: inherit; font-size: var(--gy-font-size-xs); cursor: pointer; }
@media (max-width: 720px) { .market-detail header { align-items: start; flex-direction: column; } }
</style>
