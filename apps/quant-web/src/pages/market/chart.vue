<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NDrawer, NDrawerContent, NSpin, NTag, useMessage } from 'naive-ui'
import ProductResearchSidebar from '@/components/market/ProductResearchSidebar.vue'
import PriceVolumeOiPanel from '@/components/market/PriceVolumeOiPanel.vue'
import ProductWorkspaceToolbar from '@/components/market/ProductWorkspaceToolbar.vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getMarketDominants, getProductResearch } from '@/api/market'
import { useMarketSeries } from '@/composables/useMarketSeries'
import type { DominantContractItem, MainIndicatorId, MarketFrequency, ProductResearchResponse, SeriesKind } from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'
import { loadMainChartPreferences, saveMainChartPreferences } from '@/utils/mainIndicators'
import {
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
  toggleWatchlistSymbol,
} from '@/utils/marketWorkspacePreferences'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const initialWorkspacePreferences = loadMarketWorkspacePreferences()
const initialMainChartPreferences = loadMainChartPreferences()
const metadataLoading = ref(false)
const error = ref<string | null>(null)
const dominants = ref<DominantContractItem[]>([])
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const workspaceElement = ref<HTMLElement | null>(null)
const fullscreen = ref(false)
const researchDrawerOpen = ref(false)
const researchSidebarOpen = ref(initialWorkspacePreferences.researchSidebarOpen)
const watchlist = ref(initialWorkspacePreferences.watchlist)
const visibleMainIndicators = ref<MainIndicatorId[]>(initialMainChartPreferences.visibleMainIndicators)
const research = ref<ProductResearchResponse | null>(null)
const researchLoading = ref(false)
const researchError = ref(false)
const {
  bars,
  hasMoreBefore,
  canonicalCoverage,
  loadingInitial,
  loadingBefore,
  marketState,
  liveUnavailable,
  mutation,
  replaceSeries,
  loadMoreBefore,
  dispose,
} = useMarketSeries()
let metadataReady = false
let synchronizingSymbol = false
let researchGeneration = 0

const symbol = ref(resolveInitialSymbol())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(resolveInitialSeriesKind())
const frequency = ref<MarketFrequency>(resolveInitialFrequency())

const loading = computed(() => loadingInitial.value || loadingBefore.value)
const followLatest = ref(true)
const selectedDominant = computed(() => dominants.value.find((item) => item.product === symbol.value))
const isLiveDisplay = computed(() => !!marketState.value?.live_eligible
  && !!marketState.value.live_available
  && !liveUnavailable.value)
const phaseLabel = computed(() => {
  switch (marketState.value?.phase) {
    case 'TRADING': return '交易中'
    case 'BREAK': return '盘中休市'
    case 'CLOSED': return '已收盘'
    default: return '状态未知'
  }
})
const afterMarketFailed = computed(() => {
  const afterMarket = marketState.value?.after_market
  return !!afterMarket && typeof afterMarket === 'object' && afterMarket.last_failure != null
})
const watchlisted = computed(() => watchlist.value.includes(symbol.value))

onMounted(async () => {
  document.addEventListener('fullscreenchange', syncFullscreen)
  metadataLoading.value = true
  try {
    dominants.value = (await getMarketDominants()).items
    if (!dominants.value.some((item) => item.product === symbol.value)) {
      symbol.value = dominants.value[0]?.product || ''
    }
    if (seriesKind.value !== 'contract' || !contract.value) syncDominantContract()
    await refreshSeries()
    metadataReady = true
    void refreshResearch()
  } catch {
    error.value = '行情元数据加载失败'
  } finally {
    metadataLoading.value = false
  }
})

watch(symbol, async () => {
  if (!metadataReady) return
  synchronizingSymbol = true
  try {
    if (seriesKind.value !== 'contract') syncDominantContract()
    await refreshSeries()
  } finally {
    synchronizingSymbol = false
  }
})

watch([contract, seriesKind, frequency], () => {
  if (metadataReady && !synchronizingSymbol) void refreshSeries()
})

watch([symbol, seriesKind, contract], () => {
  if (metadataReady && !synchronizingSymbol) void refreshResearch()
})

watch([symbol, seriesKind, researchSidebarOpen, watchlist], persistWorkspacePreferences, { deep: true })

watch(frequency, (period) => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, period })
})

watch(mutation, (nextMutation) => {
  if (!chart.value) return
  if (nextMutation.kind === 'replace') {
    chart.value.replaceBars(bars.value, !followLatest.value)
    return
  }
  if (nextMutation.kind === 'prepend') {
    chart.value.prependBars(nextMutation.bars)
    return
  }
  for (const bar of nextMutation.bars) chart.value.updateBar(bar)
  if (followLatest.value) chart.value.scrollToLatest()
})

onUnmounted(() => {
  document.removeEventListener('fullscreenchange', syncFullscreen)
  dispose()
})

function syncDominantContract() {
  const value = dominants.value.find((item) => item.product === symbol.value)
  if (value) contract.value = value.actual_contract
}

function currentIdentity() {
  return {
    seriesKind: seriesKind.value,
    symbol: symbol.value,
    contract: seriesKind.value === 'contract' ? contract.value : undefined,
    frequency: frequency.value,
  }
}

async function refreshSeries() {
  if (!symbol.value) return
  if (seriesKind.value === 'contract' && !contract.value) {
    error.value = '指定真实合约时 contract 必填'
    return
  }
  const requested = currentIdentity()
  error.value = null
  followLatest.value = true
  try {
    await replaceSeries(requested)
    if (!isCurrentIdentity(requested)) return
    await router.replace({ query: {
      symbol: requested.symbol,
      contract: contract.value,
      series_kind: requested.seriesKind,
      frequency: requested.frequency,
    } })
  } catch {
    if (!isCurrentIdentity(requested)) return
    error.value = '读取失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
  }
}

async function refreshResearch() {
  if (!symbol.value) return
  const requestGeneration = ++researchGeneration
  const requested = currentIdentity()
  researchLoading.value = true
  researchError.value = false
  research.value = null
  try {
    const snapshot = await getProductResearch({
      symbol: requested.symbol,
      seriesKind: requested.seriesKind,
      contract: requested.contract,
    })
    if (requestGeneration !== researchGeneration || !isCurrentIdentity(requested)) return
    research.value = snapshot
  } catch {
    if (requestGeneration !== researchGeneration || !isCurrentIdentity(requested)) return
    researchError.value = true
  } finally {
    if (requestGeneration === researchGeneration) researchLoading.value = false
  }
}

async function loadEarlierBars() {
  try {
    await loadMoreBefore()
  } catch {
    error.value = '读取更早历史失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
  }
}

function isCurrentIdentity(candidate: ReturnType<typeof currentIdentity>) {
  return candidate.seriesKind === seriesKind.value
    && candidate.symbol === symbol.value
    && candidate.contract === (seriesKind.value === 'contract' ? contract.value : undefined)
    && candidate.frequency === frequency.value
}

function updateVisibleMainIndicators(value: MainIndicatorId[]) {
  visibleMainIndicators.value = value
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, visibleMainIndicators: value })
}

function toggleWatchlist() {
  const next = toggleWatchlistSymbol({
    version: 1,
    symbol: symbol.value || null,
    seriesKind: seriesKind.value === 'continuous' ? 'continuous' : 'actual_dominant',
    researchSidebarOpen: researchSidebarOpen.value,
    watchlist: watchlist.value,
  }, symbol.value)
  watchlist.value = next.watchlist
}

function persistWorkspacePreferences() {
  saveMarketWorkspacePreferences({
    version: 1,
    symbol: symbol.value || null,
    seriesKind: seriesKind.value === 'continuous' ? 'continuous' : 'actual_dominant',
    researchSidebarOpen: researchSidebarOpen.value,
    watchlist: watchlist.value,
  })
}

function openResearchDrawer() {
  if (window.innerWidth >= 1600) {
    researchSidebarOpen.value = !researchSidebarOpen.value
    return
  }
  researchDrawerOpen.value = true
}

async function toggleFullscreen() {
  if (!workspaceElement.value) return
  try {
    if (document.fullscreenElement === workspaceElement.value) {
      await document.exitFullscreen()
    } else {
      await workspaceElement.value.requestFullscreen()
    }
  } catch {
    message.error('当前浏览器不支持 K 线全屏')
  }
}

function syncFullscreen() {
  fullscreen.value = document.fullscreenElement === workspaceElement.value
}

function resolveInitialSymbol() {
  const fromRoute = normalizeSymbol(route.query.symbol)
  return fromRoute || initialWorkspacePreferences.symbol || ''
}

function resolveInitialSeriesKind(): SeriesKind {
  if (route.query.series_kind === 'continuous' || route.query.series_kind === 'contract') {
    return route.query.series_kind
  }
  if (route.query.series_kind === 'actual_dominant') return 'actual_dominant'
  return initialWorkspacePreferences.seriesKind
}

function resolveInitialFrequency(): MarketFrequency {
  const fromRoute = normalizeFrequency(route.query.frequency)
  if (fromRoute) return fromRoute
  const fromMainPreferences = normalizeFrequency(initialMainChartPreferences.period)
  return fromMainPreferences || '15m'
}

function normalizeFrequency(value: unknown): MarketFrequency | null {
  return MARKET_FREQUENCIES.includes(value as MarketFrequency) ? value as MarketFrequency : null
}

function normalizeSymbol(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim().toLowerCase()
  return /^[a-z]+$/.test(normalized) ? normalized : null
}
</script>

<template>
  <div class="chart-page">
    <ProductWorkspaceToolbar
      :symbol="symbol"
      :series-kind="seriesKind"
      :frequency="frequency"
      :contract="contract"
      :dominants="dominants"
      :visible-main-indicators="visibleMainIndicators"
      :fullscreen="fullscreen"
      @update:symbol="symbol = $event"
      @update:series-kind="seriesKind = $event"
      @update:frequency="frequency = $event"
      @update:contract="contract = $event"
      @update:visible-main-indicators="updateVisibleMainIndicators"
      @open-research="openResearchDrawer"
      @toggle-fullscreen="toggleFullscreen"
      @back="router.push({ name: 'market' })"
    />

    <NSpin :show="metadataLoading">
      <NAlert v-if="error" type="error" :show-icon="true">{{ error }}</NAlert>
      <NCard size="small" :bordered="false" class="identity-card">
        <div class="identity-row">
          <strong>{{ symbol.toUpperCase() }} {{ selectedDominant?.product_name }}</strong>
          <NTag>{{ seriesKind }}</NTag>
          <NTag>{{ frequency }}</NTag>
          <span>{{ bars.length }} bars</span>
          <span v-if="canonicalCoverage">{{ canonicalCoverage.start }} → {{ canonicalCoverage.end }}</span>
          <NTag v-if="hasMoreBefore" type="info">可继续向前加载</NTag>
          <NTag data-testid="market-display-state" :type="isLiveDisplay ? 'success' : 'default'">{{ isLiveDisplay ? 'Live' : 'Historical' }}</NTag>
          <NTag data-testid="market-phase">{{ phaseLabel }}</NTag>
          <span v-if="isLiveDisplay && marketState?.live_contract">当前 Live 主力合约 {{ marketState.live_contract }}</span>
          <NTag v-if="afterMarketFailed" type="warning">最近盘后更新失败</NTag>
          <NButton v-if="!followLatest" size="small" secondary @click="chart?.scrollToLatest()">回到最新</NButton>
        </div>
      </NCard>
      <div ref="workspaceElement" class="product-workspace">
        <div class="product-workspace__main" :class="{ 'product-workspace__main--sidebar-closed': !researchSidebarOpen }">
          <div class="product-workspace__kline">
            <KlineChart
              ref="chart"
              :bars="bars"
              :loading="loading"
              :error="error"
              :period="frequency"
              :visible-main-indicators="visibleMainIndicators"
              @need-more-before="loadEarlierBars"
              @follow-latest-change="followLatest = $event"
            />
          </div>
          <ProductResearchSidebar
            class="product-workspace__sidebar"
            :dominant="selectedDominant"
            :series-kind="seriesKind"
            :frequency="frequency"
            :contract="contract"
            :live="isLiveDisplay"
            :phase="phaseLabel"
            :has-more-before="hasMoreBefore"
            :watchlisted="watchlisted"
            :research="research"
            :research-loading="researchLoading"
            :research-error="researchError"
            @toggle-watchlist="toggleWatchlist"
          />
        </div>
      </div>
      <PriceVolumeOiPanel
        v-if="research"
        class="product-workspace__research-panel"
        :daily="research.recent_daily"
      />
      <NAlert v-else-if="researchError" type="warning" :show-icon="false" class="product-workspace__research-panel">
        研究数据暂不可用；K 线仍使用既有 Canonical / Live 读取链路。
      </NAlert>
    </NSpin>

    <NDrawer v-model:show="researchDrawerOpen" :width="320" placement="right">
      <NDrawerContent title="研究" closable>
        <ProductResearchSidebar
          :dominant="selectedDominant"
          :series-kind="seriesKind"
          :frequency="frequency"
          :contract="contract"
          :live="isLiveDisplay"
          :phase="phaseLabel"
          :has-more-before="hasMoreBefore"
          :watchlisted="watchlisted"
          :research="research"
          :research-loading="researchLoading"
          :research-error="researchError"
          @toggle-watchlist="toggleWatchlist"
        />
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.chart-page { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.identity-card { background: var(--gy-bg-panel); }
.identity-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.product-workspace { min-width: 0; }
.product-workspace__main { display: grid; grid-template-columns: minmax(0, 1fr) 296px; gap: 12px; align-items: start; }
.product-workspace__main--sidebar-closed { grid-template-columns: minmax(0, 1fr); }
.product-workspace__main--sidebar-closed .product-workspace__sidebar { display: none; }
.product-workspace__kline { min-width: 0; }
.product-workspace__sidebar { position: sticky; top: 0; }
.product-workspace__research-panel { margin-top: 12px; }
.product-workspace:fullscreen { display: grid; place-items: stretch; padding: 16px; background: var(--gy-bg-app); }
.product-workspace:fullscreen .product-workspace__main { grid-template-columns: minmax(0, 1fr); height: 100%; }
.product-workspace:fullscreen .product-workspace__kline { min-height: 100%; }
.product-workspace:fullscreen .product-workspace__sidebar { display: none; }

@media (max-width: 1599px) {
  .product-workspace__main { grid-template-columns: minmax(0, 1fr); }
  .product-workspace__sidebar { display: none; }
}
</style>
