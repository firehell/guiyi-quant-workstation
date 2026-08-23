<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton } from 'naive-ui'
import MarketAttentionList from '@/components/market/MarketAttentionList.vue'
import MarketDetailTable from '@/components/market/MarketDetailTable.vue'
import MarketScatter from '@/components/market/MarketScatter.vue'
import MarketSummaryStrip from '@/components/market/MarketSummaryStrip.vue'
import MarketFormalSignals from '@/components/market/MarketFormalSignals.vue'
import MarketFocusList from '@/components/market/MarketFocusList.vue'
import MarketRadarSkeleton from '@/components/market/MarketRadarSkeleton.vue'
import { getMarketRadar, getMarketTrendFocus } from '@/api/market'
import { getEventStates } from '@/api/executionReview'
import type { CurrentFormalSignalItem } from '@/api/alerts'
import type { EventState } from '@/types/executionReview'
import type {
  MarketRadarItem,
  MarketRadarResponse,
  MarketTrendFocusItem,
  MarketTrendFocusResponse,
} from '@/types/market'
import { useCurrentFormalSignals } from '@/composables/useCurrentFormalSignals'
import {
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
  toggleWatchlistSymbol,
} from '@/utils/marketWorkspacePreferences'

const router = useRouter()
const loading = ref(false)
const error = ref(false)
const radar = ref<MarketRadarResponse | null>(null)
const trendFocus = ref<MarketTrendFocusResponse | null>(null)
const trendFocusError = ref(false)
const {
  loading: formalLoading,
  status: formalStatus,
  tradingDay: formalTradingDay,
  items: formalItems,
  refresh: refreshFormalSignals,
} = useCurrentFormalSignals()
const preferences = ref(loadMarketWorkspacePreferences())
const formalEventStates = ref<Record<number, EventState>>({})
let formalStateGeneration = 0
const freshnessIssue = computed(() => {
  if (!radar.value || radar.value.freshness_state !== 'degraded') return ''
  const parts = [
    radar.value.stale.length ? `stale ${radar.value.stale.join(', ')}` : '',
    radar.value.unavailable.length ? `unavailable ${radar.value.unavailable.join(', ')}` : '',
  ].filter(Boolean)
  return `Radar 数据不完整：${parts.join('；') || radar.value.freshness_message}`
})

function openChart(item: MarketRadarItem | MarketTrendFocusItem) {
  const frequency = preferences.value.frequency
  void router.push({
    name: 'market-chart',
    query: { symbol: item.symbol, series_kind: 'actual_dominant', frequency },
  })
}

function openFormalSignal(item: CurrentFormalSignalItem, state?: EventState) {
  if (state) {
    const useEpisode = state.state === 'open' || state.state === 'pending_review'
    void router.push({
      name: 'trade-records',
      query: {
        state: state.state,
        event_id: useEpisode ? undefined : String(item.id),
        episode_id: useEpisode && state.episode_id ? String(state.episode_id) : undefined,
      },
    })
    return
  }
  void router.push({
    name: 'market-chart',
    query: { symbol: item.symbol, series_kind: 'actual_dominant', frequency: item.frequency },
  })
}

watch([formalStatus, formalItems], () => {
  void refreshFormalEventStates()
}, { deep: true })

async function refreshFormalEventStates() {
  const generation = ++formalStateGeneration
  if (formalStatus.value !== 'ready' || formalItems.value.length === 0) {
    formalEventStates.value = {}
    return
  }
  try {
    const response = await getEventStates(formalItems.value.map((item) => item.id))
    if (generation !== formalStateGeneration) return
    formalEventStates.value = Object.fromEntries(response.items.map((item) => [item.event_id, item]))
  } catch {
    if (generation === formalStateGeneration) formalEventStates.value = {}
  }
}

function toggleWatchlist(symbol: string) {
  preferences.value = toggleWatchlistSymbol(preferences.value, symbol)
  saveMarketWorkspacePreferences(preferences.value)
}

async function refreshRadar() {
  if (loading.value) return
  loading.value = true
  error.value = false
  trendFocusError.value = false
  try {
    const [radarResult, trendFocusResult] = await Promise.allSettled([
      getMarketRadar(),
      getMarketTrendFocus(),
    ])
    if (radarResult.status === 'fulfilled') radar.value = radarResult.value
    else error.value = true
    if (trendFocusResult.status === 'fulfilled') trendFocus.value = trendFocusResult.value
    else trendFocusError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refreshFormalSignals()
  void refreshRadar()
})
</script>

<template>
  <div class="market-radar-page">
    <header class="market-radar-page__intro">
      <div><h1>期货市场发现</h1><p>基于最近完整交易日的 Canonical 日线研究快照；所有内容仅供人工观察。</p></div>
      <NButton secondary size="small" :loading="loading" :disabled="loading" @click="refreshRadar">刷新 Radar</NButton>
    </header>
    <MarketFormalSignals
      :loading="formalLoading"
      :status="formalStatus"
      :trading-day="formalTradingDay"
      :items="formalItems"
      :event-states="formalEventStates"
      @open="openFormalSignal"
    />
    <MarketRadarSkeleton v-if="loading && !radar" />
    <template v-else>
      <div v-if="error" class="market-radar-page__error">
        <NAlert
          type="warning"
          :title="radar ? 'Radar 刷新失败' : 'Radar 暂不可用'"
        >
          {{ radar ? '已保留上一份成功快照；重试前请以其时点为准。' : '无法读取只读 Radar；不影响 Product Workspace。' }}
        </NAlert>
        <NButton size="small" :loading="loading" :disabled="loading" @click="refreshRadar">重试</NButton>
      </div>
      <MarketFocusList
        :snapshot="trendFocus"
        :loading="loading && !trendFocus"
        :stale="trendFocusError && Boolean(trendFocus)"
        @open="openChart"
      />
      <template v-if="radar">
        <NAlert v-if="freshnessIssue" type="warning" :title="freshnessIssue" />
        <details class="market-radar-page__research" data-testid="market-full-research">
          <summary>展开全市场研究</summary>
          <div class="market-radar-page__research-content">
            <MarketSummaryStrip :radar="radar" />
            <div class="market-radar-page__discovery"><MarketScatter :items="radar.items" @open="openChart" /><MarketAttentionList :items="radar.attention" @open="openChart" /></div>
            <MarketDetailTable :items="radar.items" :sectors="radar.sector_summary" :watchlist="preferences.watchlist" @open="openChart" @toggle-watchlist="toggleWatchlist" />
          </div>
        </details>
      </template>
    </template>
  </div>
</template>

<style scoped>
.market-radar-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.market-radar-page__intro { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.market-radar-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }
.market-radar-page__intro p { margin: 0; color: var(--gy-text-muted); }
.market-radar-page__error { display: flex; align-items: center; gap: 10px; }
.market-radar-page__error :deep(.n-alert) { min-width: 0; flex: 1; }
.market-radar-page__research { min-width: 0; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); }
.market-radar-page__research > summary { padding: 14px 16px; color: var(--gy-accent); font-weight: 500; cursor: pointer; }
.market-radar-page__research-content { display: flex; flex-direction: column; gap: 16px; padding: 0 16px 16px; }
.market-radar-page__discovery { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, .9fr); gap: 16px; }
@media (max-width: 980px) { .market-radar-page__discovery { grid-template-columns: 1fr; } }
</style>
