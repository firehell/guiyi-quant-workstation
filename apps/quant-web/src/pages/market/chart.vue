<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NDrawer, NDrawerContent, NSpin, NTag, useMessage } from 'naive-ui'
import ProductResearchSidebar from '@/components/market/ProductResearchSidebar.vue'
import PriceVolumeOiPanel from '@/components/market/PriceVolumeOiPanel.vue'
import ProductWorkspaceToolbar from '@/components/market/ProductWorkspaceToolbar.vue'
import SubingStatusStrip from '@/components/market/SubingStatusStrip.vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getMarketDominants, getProductResearch, getSubingResearch } from '@/api/market'
import {
  getAlertRuntimeStatus,
  getAlertEvents,
  getProductAlerts,
  setAlertProductEnabled,
  type AlertRuntimeStatus,
  type ProductAlertRuleState,
} from '@/api/alerts'
import { useMarketSeries } from '@/composables/useMarketSeries'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import type {
  DominantContractItem,
  MarketFrequency,
  ProductResearchResponse,
  ResearchOverlayId,
  SeriesKind,
  SubingResearchResponse,
} from '@/types/market'
import {
  filterBarsToSubingSegment,
  isSubingSupportedFrequency,
  MARKET_FREQUENCIES,
  shouldScheduleSubingCompanionRefresh,
} from '@/types/market'
import { isCurrentAlertMutation } from '@/utils/alertControl'
import {
  loadMainChartPreferences,
  resolveEffectiveSeriesIdentity,
  saveMainChartPreferences,
  visibleMainIndicatorsForOverlay,
} from '@/utils/mainIndicators'
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
const selectedOverlay = ref<ResearchOverlayId>(initialMainChartPreferences.selectedOverlay)
const research = ref<ProductResearchResponse | null>(null)
const researchLoading = ref(false)
const researchError = ref(false)
const subing = ref<SubingResearchResponse | null>(null)
const subingLoading = ref(false)
const subingError = ref(false)
const alertRule = ref<ProductAlertRuleState | null>(null)
const alertRuntimeStatus = ref<AlertRuntimeStatus | null>(null)
const alertLoading = ref(false)
const alertSaving = ref(false)
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
const {
  markers: persistentAlertMarkers,
  sync: syncPersistentAlertMarkers,
  dispose: disposePersistentAlertMarkers,
} = usePersistentAlertMarkers({ fetchEvents: getAlertEvents })
let metadataReady = false
let synchronizingSymbol = false
let researchGeneration = 0
let alertGeneration = 0
let subingGeneration = 0
let subingRefreshTimer: ReturnType<typeof setTimeout> | null = null

const SUBING_COMMON_BOUNDARY_REFRESH_MS = 600

const symbol = ref(resolveInitialSymbol())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(resolveInitialSeriesKind())
const frequency = ref<MarketFrequency>(resolveInitialFrequency())

const loading = computed(() => loadingInitial.value
  || loadingBefore.value
  || (selectedOverlay.value === 'subing' && subingSupported.value && subingLoading.value))
const followLatest = ref(true)
const selectedDominant = computed(() => dominants.value.find((item) => item.product === symbol.value))
const subingSupported = computed(() => isSubingSupportedFrequency(frequency.value))
const visibleMainIndicators = computed(() => {
  if (selectedOverlay.value === 'subing' && !subingSupported.value) return []
  return visibleMainIndicatorsForOverlay(selectedOverlay.value)
})
const effectiveIdentity = computed(() => currentIdentity())
const visibleBars = computed(() => {
  if (selectedOverlay.value !== 'subing') return bars.value
  if (!subingSupported.value) return bars.value
  const segmentStart = subing.value?.segment_start_trading_day
  return segmentStart ? filterBarsToSubingSegment(bars.value, segmentStart) : []
})
const visibleStartTradingDay = computed(() => visibleBars.value[0]?.trading_day || '')
const canLoadEarlier = computed(() => {
  if (selectedOverlay.value !== 'subing' || !subingSupported.value) return hasMoreBefore.value
  const segmentStart = subing.value?.segment_start_trading_day
  const visibleStart = visibleStartTradingDay.value
  return !!segmentStart && !!visibleStart && visibleStart > segmentStart && hasMoreBefore.value
})
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
const htdyVisible = computed(() => selectedOverlay.value === 'htdy')

onMounted(async () => {
  document.addEventListener('fullscreenchange', syncFullscreen)
  metadataLoading.value = true
  try {
    dominants.value = (await getMarketDominants()).items
    if (!dominants.value.some((item) => item.product === symbol.value)) {
      symbol.value = dominants.value[0]?.product || ''
    }
    await refreshSeries()
    metadataReady = true
    void refreshSubing()
    void refreshResearch()
    void refreshAlerts()
  } catch {
    error.value = '行情元数据加载失败'
  } finally {
    metadataLoading.value = false
  }
})

watch(symbol, async () => {
  if (!metadataReady) return
  resetSubingSnapshot()
  synchronizingSymbol = true
  try {
    await refreshSeries()
    void refreshSubing()
    void refreshAlerts()
  } finally {
    synchronizingSymbol = false
  }
})

watch([contract, seriesKind, frequency], async () => {
  if (!metadataReady || synchronizingSymbol) return
  resetSubingSnapshot()
  await refreshSeries()
  void refreshSubing()
})

watch(selectedOverlay, async () => {
  if (!metadataReady || synchronizingSymbol) return
  resetSubingSnapshot()
  await refreshSeries()
  void refreshSubing()
})

watch([symbol, seriesKind, contract], () => {
  if (metadataReady) void syncPersistentAlertMarkers(currentIdentity(), [], 'replace')
})

watch([frequency, selectedOverlay], () => {
  if (metadataReady) void syncPersistentAlertMarkers(currentIdentity(), [], 'replace')
})

watch([symbol, seriesKind, contract], () => {
  if (metadataReady && !synchronizingSymbol) void refreshResearch()
})

watch(selectedOverlay, () => {
  if (metadataReady && !synchronizingSymbol) void refreshResearch()
})

watch([symbol, seriesKind, frequency, researchSidebarOpen, watchlist], persistWorkspacePreferences, { deep: true })

watch(frequency, (period) => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, period })
})

watch(mutation, (nextMutation) => {
  const rendered = selectedOverlay.value === 'subing' ? visibleBars.value : bars.value
  void syncPersistentAlertMarkers(currentIdentity(), rendered, nextMutation.kind)
  if (selectedOverlay.value === 'subing') {
    if (nextMutation.kind === 'live' && subingSupported.value) void refreshSubing()
    chart.value?.replaceBars(rendered, nextMutation.kind !== 'replace' || !followLatest.value)
    if (nextMutation.kind === 'live' && followLatest.value) chart.value?.scrollToLatest()
    return
  }
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
  subingGeneration += 1
  clearSubingRefreshTimer()
  dispose()
  disposePersistentAlertMarkers()
})

function currentIdentity() {
  const effective = resolveEffectiveSeriesIdentity({
    overlay: selectedOverlay.value,
    userSeriesKind: seriesKind.value,
    userContract: contract.value || undefined,
    dominantContract: selectedDominant.value?.actual_contract,
  })
  return {
    seriesKind: effective.seriesKind,
    symbol: symbol.value,
    contract: effective.contract,
    frequency: frequency.value,
  }
}

async function refreshSeries() {
  if (!symbol.value) return false
  if (selectedOverlay.value === 'subing' && !selectedDominant.value?.actual_contract) {
    error.value = '苏冰观察需要当前主力合约，等待主力映射'
    return false
  }
  const requested = currentIdentity()
  if (requested.seriesKind === 'contract' && !requested.contract) {
    error.value = '指定真实合约时 contract 必填'
    return false
  }
  error.value = null
  followLatest.value = true
  try {
    await replaceSeries(requested)
    if (!isCurrentIdentity(requested)) return false
    await router.replace({ query: {
      symbol: requested.symbol,
      contract: contract.value || undefined,
      series_kind: seriesKind.value,
      frequency: requested.frequency,
    } })
    return true
  } catch {
    if (!isCurrentIdentity(requested)) return false
    error.value = '读取失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
    return false
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

function resetSubingSnapshot() {
  subingGeneration += 1
  clearSubingRefreshTimer()
  subing.value = null
  subingError.value = false
  subingLoading.value = selectedOverlay.value === 'subing' && subingSupported.value
  chart.value?.replaceBars(visibleBars.value)
}

async function refreshSubing(allowDelayedRefresh = true) {
  const requestedSymbol = symbol.value
  const requestedFrequency = frequency.value
  if (
    selectedOverlay.value !== 'subing'
    || !requestedSymbol
    || !isSubingSupportedFrequency(requestedFrequency)
  ) {
    subingLoading.value = false
    return
  }
  if (allowDelayedRefresh) clearSubingRefreshTimer()
  const requestGeneration = ++subingGeneration
  subingLoading.value = true
  subingError.value = false
  try {
    const expectedDominant = selectedDominant.value
    if (!expectedDominant) throw new Error('dominant metadata unavailable')
    let snapshot = await getSubingResearch({
      symbol: requestedSymbol,
      frequency: requestedFrequency,
    })
    if (!isCurrentSubingRequest(requestGeneration, requestedSymbol, requestedFrequency)) return
    if (!isSubingSnapshotForDominant(snapshot, expectedDominant)) {
      subing.value = null
      chart.value?.replaceBars(visibleBars.value, !followLatest.value)
      const refreshedDominants = await getMarketDominants()
      if (!isCurrentSubingRequest(requestGeneration, requestedSymbol, requestedFrequency)) return
      dominants.value = refreshedDominants.items
      const refreshedExpected = selectedDominant.value
      if (!refreshedExpected) throw new Error('dominant metadata unavailable')
      const seriesReloaded = await refreshSeries()
      if (!seriesReloaded) throw new Error('dominant contract series reload failed')
      if (!isCurrentSubingRequest(requestGeneration, requestedSymbol, requestedFrequency)) return
      snapshot = await getSubingResearch({
        symbol: requestedSymbol,
        frequency: requestedFrequency,
      })
      if (!isCurrentSubingRequest(requestGeneration, requestedSymbol, requestedFrequency)) return
      if (!isSubingSnapshotForDominant(snapshot, refreshedExpected)) {
        throw new Error('SuBing snapshot dominant identity mismatch')
      }
    }
    subing.value = snapshot
    chart.value?.replaceBars(visibleBars.value, !followLatest.value)
    if (allowDelayedRefresh && shouldScheduleSubingCompanionRefresh(snapshot)) {
      subingRefreshTimer = setTimeout(() => {
        subingRefreshTimer = null
        if (requestGeneration !== subingGeneration) return
        void refreshSubing(false)
      }, SUBING_COMMON_BOUNDARY_REFRESH_MS)
    }
  } catch {
    if (requestGeneration !== subingGeneration) return
    subing.value = null
    subingError.value = true
    chart.value?.replaceBars(visibleBars.value, !followLatest.value)
  } finally {
    if (requestGeneration === subingGeneration) subingLoading.value = false
  }
}

function isCurrentSubingRequest(
  generation: number,
  requestedSymbol: string,
  requestedFrequency: MarketFrequency,
) {
  return generation === subingGeneration
    && selectedOverlay.value === 'subing'
    && symbol.value === requestedSymbol
    && frequency.value === requestedFrequency
}

function isSubingSnapshotForDominant(
  snapshot: SubingResearchResponse,
  expected: DominantContractItem,
) {
  return snapshot.actual_contract === expected.actual_contract
    && snapshot.dominant_mapping_date === expected.dominant_mapping_date
}

function clearSubingRefreshTimer() {
  if (subingRefreshTimer === null) return
  clearTimeout(subingRefreshTimer)
  subingRefreshTimer = null
}

async function refreshAlerts() {
  if (!symbol.value) return
  const requestGeneration = ++alertGeneration
  const requestedSymbol = symbol.value
  alertLoading.value = true
  alertRule.value = null
  try {
    const [scope, runtimeStatus] = await Promise.all([
      getProductAlerts(requestedSymbol),
      getAlertRuntimeStatus(),
    ])
    if (requestGeneration !== alertGeneration || symbol.value !== requestedSymbol) return
    alertRule.value = scope.rules.find((rule) => rule.rule_code === 'htdy_original_15m') || null
    alertRuntimeStatus.value = runtimeStatus
  } catch {
    if (requestGeneration !== alertGeneration || symbol.value !== requestedSymbol) return
    alertRule.value = null
    alertRuntimeStatus.value = 'failed'
  } finally {
    if (requestGeneration === alertGeneration) alertLoading.value = false
  }
}

async function toggleAlert(enabled: boolean) {
  const current = alertRule.value
  const requestedSymbol = symbol.value
  const requestGeneration = alertGeneration
  if (!current || !requestedSymbol || alertSaving.value) return
  alertSaving.value = true
  try {
    const updated = await setAlertProductEnabled(current.rule_code, requestedSymbol, enabled)
    if (isCurrentAlertMutation({
      requestGeneration,
      currentGeneration: alertGeneration,
      requestedSymbol,
      currentSymbol: symbol.value,
      requestedRuleCode: current.rule_code,
      currentRuleCode: alertRule.value?.rule_code,
      updatedRuleCode: updated.rule_code,
    })) {
      alertRule.value = updated
    }
  } catch {
    message.error('Alert Scope 更新失败')
  } finally {
    alertSaving.value = false
  }
}

async function loadEarlierBars() {
  if (selectedOverlay.value === 'subing' && subingSupported.value) {
    const segmentStart = subing.value?.segment_start_trading_day
    const visibleStart = visibleStartTradingDay.value
    if (!segmentStart || !visibleStart || visibleStart <= segmentStart) return
  }
  try {
    await loadMoreBefore()
  } catch {
    error.value = '读取更早历史失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
  }
}

function isCurrentIdentity(candidate: ReturnType<typeof currentIdentity>) {
  const current = currentIdentity()
  return candidate.seriesKind === current.seriesKind
    && candidate.symbol === current.symbol
    && candidate.contract === current.contract
    && candidate.frequency === current.frequency
}

function updateSelectedOverlay(value: ResearchOverlayId) {
  selectedOverlay.value = value
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, selectedOverlay: value })
}

function toggleWatchlist() {
  const next = toggleWatchlistSymbol({
    version: 1,
    symbol: symbol.value || null,
    seriesKind: seriesKind.value === 'continuous' ? 'continuous' : 'actual_dominant',
    frequency: frequency.value,
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
    frequency: frequency.value,
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
      :selected-overlay="selectedOverlay"
      :fullscreen="fullscreen"
      @update:symbol="symbol = $event"
      @update:series-kind="seriesKind = $event"
      @update:frequency="frequency = $event"
      @update:contract="contract = $event"
      @update:selected-overlay="updateSelectedOverlay"
      @open-research="openResearchDrawer"
      @toggle-fullscreen="toggleFullscreen"
      @back="router.push({ name: 'market' })"
    />

    <NSpin :show="metadataLoading">
      <NAlert v-if="error" type="error" :show-icon="true">{{ error }}</NAlert>
      <NCard size="small" :bordered="false" class="identity-card">
        <div class="identity-row">
          <strong>{{ symbol.toUpperCase() }} {{ selectedDominant?.product_name }}</strong>
          <NTag>{{ effectiveIdentity.seriesKind }}</NTag>
          <NTag>{{ frequency }}</NTag>
          <span>{{ visibleBars.length }} bars</span>
          <span v-if="canonicalCoverage">{{ canonicalCoverage.start }} → {{ canonicalCoverage.end }}</span>
          <NTag v-if="canLoadEarlier" type="info">可继续向前加载</NTag>
          <NTag data-testid="market-display-state" :type="isLiveDisplay ? 'success' : 'default'">{{ isLiveDisplay ? 'Live' : 'Historical' }}</NTag>
          <NTag data-testid="market-phase">{{ phaseLabel }}</NTag>
          <span v-if="isLiveDisplay && marketState?.live_contract">当前 Live 主力合约 {{ marketState.live_contract }}</span>
          <NTag v-if="afterMarketFailed" type="warning">最近盘后更新失败</NTag>
          <NButton v-if="!followLatest" size="small" secondary @click="chart?.scrollToLatest()">回到最新</NButton>
        </div>
      </NCard>
      <div ref="workspaceElement" class="product-workspace">
        <div class="product-workspace__main" :class="{ 'product-workspace__main--sidebar-closed': !researchSidebarOpen }">
          <div
            class="product-workspace__kline"
            :data-visible-start-trading-day="visibleStartTradingDay"
            :data-visible-main-indicators="visibleMainIndicators.join(',')"
          >
            <SubingStatusStrip
              v-if="selectedOverlay === 'subing'"
              :snapshot="subing"
              :loading="subingLoading || metadataLoading"
              :error="subingError"
              :supported="subingSupported"
            />
            <NAlert v-if="htdyVisible" type="warning" :show-icon="false" class="product-workspace__htdy-risk">
              火天大有原始观察 · 未来引用/重绘风险 · 仅供人工观察
            </NAlert>
            <KlineChart
              ref="chart"
              :bars="visibleBars"
              :loading="loading"
              :error="error"
              :period="frequency"
              :visible-main-indicators="visibleMainIndicators"
              :alert-markers="persistentAlertMarkers"
              @need-more-before="loadEarlierBars"
              @follow-latest-change="followLatest = $event"
            />
          </div>
          <ProductResearchSidebar
            class="product-workspace__sidebar"
            :dominant="selectedDominant"
            :series-kind="effectiveIdentity.seriesKind"
            :frequency="frequency"
            :contract="effectiveIdentity.contract || ''"
            :live="isLiveDisplay"
            :phase="phaseLabel"
            :has-more-before="canLoadEarlier"
            :watchlisted="watchlisted"
            :research="research"
            :research-loading="researchLoading"
            :research-error="researchError"
            :selected-overlay="selectedOverlay"
            :subing="subing"
            :subing-loading="subingLoading || metadataLoading"
            :subing-error="subingError"
            :subing-supported="subingSupported"
            :alert-rule="alertRule"
            :alert-runtime-status="alertRuntimeStatus"
            :alert-loading="alertLoading"
            :alert-saving="alertSaving"
            @toggle-watchlist="toggleWatchlist"
            @toggle-alert="toggleAlert"
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
          :series-kind="effectiveIdentity.seriesKind"
          :frequency="frequency"
          :contract="effectiveIdentity.contract || ''"
          :live="isLiveDisplay"
          :phase="phaseLabel"
          :has-more-before="canLoadEarlier"
          :watchlisted="watchlisted"
          :research="research"
          :research-loading="researchLoading"
          :research-error="researchError"
          :selected-overlay="selectedOverlay"
          :subing="subing"
          :subing-loading="subingLoading || metadataLoading"
          :subing-error="subingError"
          :subing-supported="subingSupported"
          :alert-rule="alertRule"
          :alert-runtime-status="alertRuntimeStatus"
          :alert-loading="alertLoading"
          :alert-saving="alertSaving"
          @toggle-watchlist="toggleWatchlist"
          @toggle-alert="toggleAlert"
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
.product-workspace__htdy-risk { margin-bottom: 8px; }
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
