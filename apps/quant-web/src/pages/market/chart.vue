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
  getProductCurrentAlertEvents,
  getProductAlerts,
  setAlertProductEnabled,
} from '@/api/alerts'
import { useMarketSeries } from '@/composables/useMarketSeries'
import { useMainForceMirrorV2 } from '@/composables/useMainForceMirrorV2'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useProductAlertScope } from '@/composables/useProductAlertScope'
import { useProductCurrentAlertEvents } from '@/composables/useProductCurrentAlertEvents'
import { useSubingObservation } from '@/composables/useSubingObservation'
import type {
  DominantContractItem,
  MarketFrequency,
  OptionalEmaIndicatorId,
  ProductResearchResponse,
  ResearchOverlayId,
  SeriesKind,
} from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'
import { lifecycleSnapshotToMarkers } from '@/utils/subingLifecycleMarkers'
import { buildKlineDerivedData } from '@/utils/klineViewModel'
import {
  normalizeSecondaryPanelPreference,
  type SecondaryPanelId,
} from '@/utils/mainForceMirrorV2Presentation'
import {
  loadMainChartPreferences,
  normalizeOptionalEmaIndicators,
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
const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([
  ...initialMainChartPreferences.optionalEmaIndicators,
])
const research = ref<ProductResearchResponse | null>(null)
const researchLoading = ref(false)
const researchError = ref(false)
const symbol = ref(resolveInitialSymbol())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(resolveInitialSeriesKind())
const frequency = ref<MarketFrequency>(resolveInitialFrequency())
const followLatest = ref(true)
const selectedSecondaryPanel = ref<SecondaryPanelId>(normalizeSecondaryPanelPreference(undefined))
const selectedDominant = computed(() => dominants.value.find((item) => item.product === symbol.value))
const {
  bars,
  hasMoreBefore,
  canonicalCoverage,
  loadingInitial,
  loadingBefore,
  marketState,
  liveUnavailable,
  overlaySource,
  mutation,
  replaceSeries,
  clearSeries,
  loadMoreBefore,
  dispose,
} = useMarketSeries()
const mirror = useMainForceMirrorV2()
const {
  markers: persistentAlertMarkers,
  sync: syncPersistentAlertMarkers,
  dispose: disposePersistentAlertMarkers,
} = usePersistentAlertMarkers({ fetchEvents: getAlertEvents })
const {
  subing,
  subingLoading,
  subingError,
  subingSupported,
  reset: resetSubingSnapshot,
  refresh: refreshSubing,
  dispose: disposeSubingObservation,
} = useSubingObservation({
  selectedOverlay,
  symbol,
  frequency,
  dominants,
  selectedDominant,
  fetchSnapshot: getSubingResearch,
  fetchDominants: getMarketDominants,
  refreshSeries: () => refreshSeries(),
})
const {
  alertRules,
  alertRuntimeStatus,
  alertLoading,
  savingRuleCodes,
  refresh: refreshAlerts,
  toggle: toggleAlert,
  dispose: disposeProductAlertScope,
} = useProductAlertScope({
  symbol,
  fetchProductAlerts: getProductAlerts,
  fetchRuntimeStatus: getAlertRuntimeStatus,
  setProductEnabled: setAlertProductEnabled,
  notifyError: (text) => message.error(text),
})
const {
  loading: currentEventsLoading,
  status: currentEventsStatus,
  items: currentEvents,
  refresh: refreshCurrentEvents,
  dispose: disposeProductCurrentAlertEvents,
} = useProductCurrentAlertEvents({ symbol, fetchCurrentEvents: getProductCurrentAlertEvents })
let metadataReady = false
let synchronizingSymbol = false
let researchGeneration = 0
let canonicalReplacementGeneration = 0
let canonicalPendingGeneration: number | null = null
let acceptedCanonical: { generation: number; identity: ReturnType<typeof currentIdentity> } | null = null
let mirrorRequestedCanonicalGeneration: number | null = null

const loading = computed(() => loadingInitial.value || loadingBefore.value)
const mainForceMirrorV2DisplayError = computed(() => {
  if (selectedSecondaryPanel.value !== 'main_force_mirror_v2') return null
  if (frequency.value !== '60m') return 'MFM_V2_UNSUPPORTED_FREQUENCY'
  if (effectiveIdentity.value.seriesKind !== 'actual_dominant' && effectiveIdentity.value.seriesKind !== 'contract') {
    return 'MFM_V2_UNSUPPORTED_SERIES_KIND'
  }
  return mirror.error.value
})
const visibleMainIndicators = computed(() => {
  if (selectedOverlay.value === 'subing' && !subingSupported.value) return []
  return visibleMainIndicatorsForOverlay(selectedOverlay.value, optionalEmaIndicators.value)
})
const effectiveIdentity = computed(() => currentIdentity())
const visibleBars = computed(() => bars.value)
const visibleStartTradingDay = computed(() => visibleBars.value[0]?.trading_day || '')
const lifecycleMarkers = computed(() => {
  if (subingLoading.value || subingError.value) return []
  return selectedOverlay.value === 'subing' && subing.value
    ? lifecycleSnapshotToMarkers(subing.value.lifecycle)
    : []
})
const canLoadEarlier = computed(() => hasMoreBefore.value)
const isLiveDisplay = computed(() => !!marketState.value?.live_eligible
  && !!marketState.value.live_available
  && !liveUnavailable.value)
const isPostCloseDisplay = computed(() => overlaySource.value === 'post_close')
const displayStateLabel = computed(() => {
  if (isPostCloseDisplay.value) return '收盘快照 · 待盘后更新'
  return isLiveDisplay.value ? 'Live' : 'Historical'
})
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
const latestHtdyObservation = computed(() => {
  if (!htdyVisible.value) return null
  return buildKlineDerivedData(visibleBars.value, ['htdy']).htdy?.markers.at(-1) ?? null
})

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
    void refreshCurrentEvents()
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

watch(selectedOverlay, () => {
  if (!metadataReady || synchronizingSymbol) return
  resetSubingSnapshot()
  void refreshSubing()
})

watch([symbol, seriesKind, contract], () => {
  if (metadataReady) void syncPersistentAlertMarkers(currentAlertMarkerIdentity(), [], 'replace')
})

watch(frequency, () => {
  if (metadataReady) void syncPersistentAlertMarkers(currentAlertMarkerIdentity(), [], 'replace')
})

watch(subing, () => {
  if (!metadataReady || selectedOverlay.value !== 'subing') return
  void syncPersistentAlertMarkers(currentAlertMarkerIdentity(), visibleBars.value, 'replace')
})

watch([symbol, seriesKind, contract], () => {
  if (metadataReady && !synchronizingSymbol) void refreshResearch()
})

watch([symbol, seriesKind, frequency, researchSidebarOpen, watchlist], persistWorkspacePreferences, { deep: true })

watch(frequency, (period) => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, period })
})

watch(mutation, (nextMutation) => {
  void syncPersistentAlertMarkers(currentAlertMarkerIdentity(), bars.value, nextMutation.kind)
  if (nextMutation.kind === 'live' && selectedOverlay.value === 'subing' && subingSupported.value) {
    void refreshSubing()
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
  disposeSubingObservation()
  disposeProductAlertScope()
  disposeProductCurrentAlertEvents()
  mirror.clear()
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

function currentAlertMarkerIdentity() {
  return {
    seriesKind: seriesKind.value,
    symbol: symbol.value,
    frequency: frequency.value,
  }
}

async function refreshSeries() {
  const replacementGeneration = ++canonicalReplacementGeneration
  canonicalPendingGeneration = replacementGeneration
  acceptedCanonical = null
  mirrorRequestedCanonicalGeneration = null
  mirror.clear()
  if (!symbol.value) {
    clearSeries()
    settleFailedCanonicalReplacement(replacementGeneration)
    return false
  }
  const requested = currentIdentity()
  if (requested.seriesKind === 'contract' && !requested.contract) {
    clearSeries()
    settleFailedCanonicalReplacement(replacementGeneration)
    error.value = '指定真实合约时 contract 必填'
    return false
  }
  error.value = null
  followLatest.value = true
  try {
    await replaceSeries(requested)
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) return false
    await router.replace({ query: {
      symbol: requested.symbol,
      contract: contract.value || undefined,
      series_kind: seriesKind.value,
      frequency: requested.frequency,
    } })
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) return false
    canonicalPendingGeneration = null
    acceptedCanonical = { generation: replacementGeneration, identity: { ...requested } }
    await requestMirrorForAcceptedCanonical()
    return true
  } catch {
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) return false
    settleFailedCanonicalReplacement(replacementGeneration)
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

async function loadEarlierBars() {
  try {
    await loadMoreBefore()
    if (selectedSecondaryPanel.value === 'main_force_mirror_v2'
      && canonicalPendingGeneration === null
      && acceptedCanonical
      && isCurrentIdentity(acceptedCanonical.identity)) {
      await mirror.loadMoreBefore()
    }
  } catch {
    error.value = '读取更早历史失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
  }
}

async function updateSecondaryPanel(value: SecondaryPanelId) {
  selectedSecondaryPanel.value = value
  if (value === 'macd') {
    mirrorRequestedCanonicalGeneration = null
    mirror.clear()
    return
  }
  await requestMirrorForAcceptedCanonical()
}

async function requestMirrorForAcceptedCanonical() {
  const accepted = acceptedCanonical
  if (selectedSecondaryPanel.value !== 'main_force_mirror_v2'
    || canonicalPendingGeneration !== null
    || !accepted
    || !isCurrentIdentity(accepted.identity)
    || mirrorRequestedCanonicalGeneration === accepted.generation) return
  mirrorRequestedCanonicalGeneration = accepted.generation
  await mirror.replace(accepted.identity)
}

function settleFailedCanonicalReplacement(generation: number) {
  if (generation !== canonicalReplacementGeneration) return
  canonicalPendingGeneration = null
  acceptedCanonical = null
  mirrorRequestedCanonicalGeneration = null
  mirror.clear()
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

function updateOptionalEmaIndicators(value: OptionalEmaIndicatorId[]) {
  optionalEmaIndicators.value = normalizeOptionalEmaIndicators(value)
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, optionalEmaIndicators: optionalEmaIndicators.value })
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
  if (window.innerWidth >= 1200) {
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
      :optional-ema-indicators="optionalEmaIndicators"
      :fullscreen="fullscreen"
      @update:symbol="symbol = $event"
      @update:series-kind="seriesKind = $event"
      @update:frequency="frequency = $event"
      @update:contract="contract = $event"
      @update:selected-overlay="updateSelectedOverlay"
      @update:optional-ema-indicators="updateOptionalEmaIndicators"
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
          <NTag
            data-testid="market-display-state"
            :type="isLiveDisplay ? 'success' : (isPostCloseDisplay ? 'warning' : 'default')"
          >{{ displayStateLabel }}</NTag>
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
            <KlineChart
              ref="chart"
              :bars="visibleBars"
              :loading="loading"
              :error="error"
              :period="frequency"
              :series-kind="effectiveIdentity.seriesKind"
              :visible-main-indicators="visibleMainIndicators"
              :alert-markers="persistentAlertMarkers"
              :research-markers="lifecycleMarkers"
              :secondary-panel="selectedSecondaryPanel"
              :main-force-mirror-v2-points="mirror.points.value"
              :main-force-mirror-v2-member-dataset="mirror.memberDataset.value"
              :main-force-mirror-v2-loading="mirror.loading.value"
              :main-force-mirror-v2-error="mainForceMirrorV2DisplayError"
              :main-force-mirror-v2-canonical-end="mirror.canonicalEnd.value"
              @need-more-before="loadEarlierBars"
              @follow-latest-change="followLatest = $event"
              @secondary-panel-change="updateSecondaryPanel"
            />
          </div>
          <div class="product-workspace__sidebar-wrap">
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
              :alert-rules="alertRules"
              :alert-runtime-status="alertRuntimeStatus"
              :alert-loading="alertLoading"
              :saving-rule-codes="savingRuleCodes"
              :current-events-loading="currentEventsLoading"
              :current-events-status="currentEventsStatus"
              :current-events="currentEvents"
              :htdy-observation="latestHtdyObservation"
              @toggle-watchlist="toggleWatchlist"
              @toggle-alert="toggleAlert"
            />
          </div>
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
          :alert-rules="alertRules"
          :alert-runtime-status="alertRuntimeStatus"
          :alert-loading="alertLoading"
          :saving-rule-codes="savingRuleCodes"
          :current-events-loading="currentEventsLoading"
          :current-events-status="currentEventsStatus"
          :current-events="currentEvents"
          :htdy-observation="latestHtdyObservation"
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
.product-workspace__main { display: grid; grid-template-columns: minmax(0, 1fr) 296px; gap: 12px; align-items: stretch; }
.product-workspace__main--sidebar-closed { grid-template-columns: minmax(0, 1fr); }
.product-workspace__main--sidebar-closed .product-workspace__sidebar-wrap { display: none; }
.product-workspace__kline { min-width: 0; }
/* 侧栏与左侧 K 线列（含副图）等高：wrap 随 grid 行高拉伸，侧栏绝对填充并内部滚动 */
.product-workspace__sidebar-wrap { position: relative; min-width: 0; min-height: 0; }
.product-workspace__sidebar-wrap > .product-workspace__sidebar { position: absolute; inset: 0; overflow-y: auto; }
.product-workspace__research-panel { margin-top: 12px; }
.product-workspace:fullscreen { display: grid; place-items: stretch; padding: 16px; background: var(--gy-bg-app); }
.product-workspace:fullscreen .product-workspace__main { grid-template-columns: minmax(0, 1fr); height: 100%; }
.product-workspace:fullscreen .product-workspace__kline { min-height: 100%; }
.product-workspace:fullscreen .product-workspace__sidebar-wrap { display: none; }

@media (min-width: 980px) and (max-width: 1199px) {
  .product-workspace__main { grid-template-columns: minmax(0, 1fr); }
  .product-workspace__sidebar-wrap { display: none; }
}
@media (max-width: 979px) {
  .product-workspace__main { grid-template-columns: minmax(0, 1fr); }
  .product-workspace__sidebar-wrap { position: static; }
  .product-workspace__sidebar-wrap > .product-workspace__sidebar { position: static; overflow: visible; }
}
</style>
