<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NSpin } from 'naive-ui'
import MarketAttentionList from '@/components/market/MarketAttentionList.vue'
import MarketDetailTable from '@/components/market/MarketDetailTable.vue'
import MarketScatter from '@/components/market/MarketScatter.vue'
import MarketSectorSummary from '@/components/market/MarketSectorSummary.vue'
import MarketSummaryStrip from '@/components/market/MarketSummaryStrip.vue'
import MarketFormalSignals from '@/components/market/MarketFormalSignals.vue'
import { getMarketRadar } from '@/api/market'
import type { CurrentFormalSignalItem } from '@/api/alerts'
import type { MarketRadarItem, MarketRadarResponse } from '@/types/market'
import { useCurrentFormalSignals } from '@/composables/useCurrentFormalSignals'
import {
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
  toggleWatchlistSymbol,
} from '@/utils/marketWorkspacePreferences'

const router = useRouter()
const loading = ref(true)
const error = ref(false)
const radar = ref<MarketRadarResponse | null>(null)
const {
  loading: formalLoading,
  status: formalStatus,
  tradingDay: formalTradingDay,
  items: formalItems,
  refresh: refreshFormalSignals,
} = useCurrentFormalSignals()
const preferences = ref(loadMarketWorkspacePreferences())
const freshnessIssue = computed(() => {
  if (!radar.value || radar.value.status === 'ready') return ''
  const parts = [
    radar.value.stale.length ? `stale ${radar.value.stale.join(', ')}` : '',
    radar.value.unavailable.length ? `unavailable ${radar.value.unavailable.join(', ')}` : '',
  ].filter(Boolean)
  return `Radar 数据不完整：${parts.join('；')}`
})

function openChart(item: MarketRadarItem) {
  const frequency = preferences.value.frequency
  void router.push({
    name: 'market-chart',
    query: { symbol: item.symbol, series_kind: 'actual_dominant', frequency },
  })
}

function openFormalSignal(item: CurrentFormalSignalItem) {
  void router.push({
    name: 'market-chart',
    query: { symbol: item.symbol, series_kind: 'actual_dominant', frequency: item.frequency },
  })
}

function toggleWatchlist(symbol: string) {
  preferences.value = toggleWatchlistSymbol(preferences.value, symbol)
  saveMarketWorkspacePreferences(preferences.value)
}

onMounted(async () => {
  void refreshFormalSignals()
  try {
    radar.value = await getMarketRadar()
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="market-radar-page">
    <header class="market-radar-page__intro"><h1>期货市场发现</h1><p>基于最近完整交易日的 Canonical 日线研究快照；所有内容仅供人工观察。</p></header>
    <MarketFormalSignals
      :loading="formalLoading"
      :status="formalStatus"
      :trading-day="formalTradingDay"
      :items="formalItems"
      @open="openFormalSignal"
    />
    <NSpin :show="loading">
      <NAlert v-if="error" type="warning" title="Radar 暂不可用">无法读取只读 Radar；可稍后重试，不影响 Product Workspace。</NAlert>
      <template v-else-if="radar">
        <NAlert v-if="freshnessIssue" type="warning" :title="freshnessIssue" />
        <MarketSummaryStrip :radar="radar" />
        <div class="market-radar-page__discovery"><MarketScatter :items="radar.items" @open="openChart" /><MarketAttentionList :items="radar.attention" @open="openChart" /></div>
        <MarketSectorSummary :sectors="radar.sector_summary" />
        <MarketDetailTable :items="radar.items" :watchlist="preferences.watchlist" @open="openChart" @toggle-watchlist="toggleWatchlist" />
      </template>
    </NSpin>
  </div>
</template>

<style scoped>
.market-radar-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.market-radar-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }.market-radar-page__intro p { margin: 0; color: var(--gy-text-muted); }.market-radar-page__discovery { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, .9fr); gap: 16px; }@media (max-width: 980px) { .market-radar-page__discovery { grid-template-columns: 1fr; } }
</style>
