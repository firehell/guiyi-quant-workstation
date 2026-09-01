<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NDrawer, NDrawerContent, NSpin, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import ProductCheckSidebar from '@/components/market/ProductCheckSidebar.vue'
import ProductWorkspaceToolbar from '@/components/market/ProductWorkspaceToolbar.vue'
import {
  getAlertEvents,
  getAlertRuntimeStatus,
  getProductAlerts,
  setAlertProductFrequencyEnabled,
} from '@/api/alerts'
import { getMarketDominants, getProductResearch } from '@/api/market'
import { useMarketSeries } from '@/composables/useMarketSeries'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useProductAlertScope } from '@/composables/useProductAlertScope'
import { useProductSymbolIdentityCoordinator } from '@/composables/useProductSymbolIdentityCoordinator'
import {
  RANGE_DETECTOR_WARMUP_INSUFFICIENT,
  RANGE_DETECTOR_WARMUP_LOAD_FAILED,
  useRangeDetectorOverlayWarmup,
} from '@/composables/useRangeDetectorOverlayWarmup'
import type {
  DominantContractItem,
  MainIndicatorId,
  MarketFrequency,
  OptionalEmaIndicatorId,
  ProductResearchResponse,
  ResearchOverlayId,
  SeriesKind,
} from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'
import { ALERT_RULE_CODES } from '@/utils/alertRules'
import { alertMarkersForOverlay } from '@/utils/alertMarkers'
import { earlierHistoryLoadError } from '@/utils/errorRedaction'
import { buildKlineDerivedData } from '@/utils/klineViewModel'
import { seriesRefreshQuery } from '@/utils/marketChartEntry'
import {
  loadMainChartPreferences,
  normalizeOptionalEmaIndicators,
  researchOverlayCapability,
  resolveEffectiveSeriesIdentity,
  saveMainChartPreferences,
  visibleMainIndicatorsForOverlay,
} from '@/utils/mainIndicators'
import {
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
} from '@/utils/marketWorkspacePreferences'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const workspacePreferences = loadMarketWorkspacePreferences()
const chartPreferences = loadMainChartPreferences()
const metadataLoading = ref(false)
const error = ref<string | null>(null)
const dominants = ref<DominantContractItem[]>([])
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const workspaceElement = ref<HTMLElement | null>(null)
const fullscreen = ref(false)
const researchDrawerOpen = ref(false)
const researchSidebarOpen = ref(workspacePreferences.researchSidebarOpen)
const selectedOverlay = ref<ResearchOverlayId>(
  route.query.overlay === 'htdy' ? 'htdy' : chartPreferences.selectedOverlay,
)
const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([
  ...chartPreferences.optionalEmaIndicators,
])
const showRangeDetector = ref(chartPreferences.showRangeDetector)
const research = ref<ProductResearchResponse | null>(null)
const researchLoading = ref(false)
const researchError = ref(false)
const symbol = ref(resolveInitialSymbol())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(resolveInitialSeriesKind())
const frequency = ref<MarketFrequency>(resolveInitialFrequency())
const followLatest = ref(true)
let metadataReady = false
let researchGeneration = 0
let canonicalReplacementGeneration = 0

const selectedDominant = computed(() => (
  dominants.value.find((item) => item.product === symbol.value)
))
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
const {
  markers: persistentAlertMarkers,
  sync: syncPersistentAlertMarkers,
  dispose: disposePersistentAlertMarkers,
} = usePersistentAlertMarkers({ fetchEvents: getAlertEvents })
const {
  alertRules,
  alertRuntimeStatus,
  alertLoading,
  savingRuleCodes,
  refresh: refreshAlerts,
  invalidateIdentity: invalidateAlertIdentity,
  markUnavailable: markAlertsUnavailable,
  toggleHtdyCurrentFrequency,
  dispose: disposeProductAlertScope,
} = useProductAlertScope({
  symbol,
  frequency,
  fetchProductAlerts: getProductAlerts,
  fetchRuntimeStatus: getAlertRuntimeStatus,
  setProductFrequencyEnabled: setAlertProductFrequencyEnabled,
  notifyError: (text) => message.error(text),
})
const {
  synchronizing: synchronizingIdentity,
  synchronize: synchronizeIdentity,
  dispose: disposeIdentityCoordinator,
} = useProductSymbolIdentityCoordinator({
  invalidateFacts: invalidateFacts,
  refreshMarket: refreshSeries,
  refreshFacts: refreshFacts,
  rejectFacts: rejectFacts,
})

const loading = computed(() => loadingInitial.value || loadingBefore.value)
const effectiveIdentity = computed(() => currentIdentity())
const overlayCapability = computed(() => researchOverlayCapability(
  selectedOverlay.value,
  effectiveIdentity.value.seriesKind,
  frequency.value,
))
const visibleMainIndicators = computed<MainIndicatorId[]>(() => {
  if (!overlayCapability.value.supported) {
    return showRangeDetector.value ? ['range_detector'] : []
  }
  return visibleMainIndicatorsForOverlay(
    selectedOverlay.value,
    optionalEmaIndicators.value,
    showRangeDetector.value,
  )
})
const rangeDetectorSourceIdentity = computed(() => [
  effectiveIdentity.value.seriesKind,
  effectiveIdentity.value.symbol,
  effectiveIdentity.value.contract ?? '',
  frequency.value,
].join(':'))
const rangeDetectorWarmup = useRangeDetectorOverlayWarmup({
  bars,
  hasMoreBefore,
  enabled: showRangeDetector,
  identityKey: rangeDetectorSourceIdentity,
  loadMoreBefore,
})
const rangeDetectorReadyAnchor = computed(() => (
  rangeDetectorWarmup.unavailableReason.value === null
    ? rangeDetectorWarmup.anchorTime.value
    : null
))
const rangeDetectorWarmupState = computed(() => {
  if (!showRangeDetector.value) return 'disabled'
  if (rangeDetectorWarmup.loading.value) return 'loading'
  return rangeDetectorWarmup.unavailableReason.value === null && rangeDetectorReadyAnchor.value
    ? 'ready'
    : 'insufficient'
})
const rangeDetectorWarning = computed(() => {
  if (rangeDetectorWarmup.unavailableReason.value === RANGE_DETECTOR_WARMUP_LOAD_FAILED) {
    return '箱体历史预载失败'
  }
  if (rangeDetectorWarmup.unavailableReason.value === RANGE_DETECTOR_WARMUP_INSUFFICIENT) {
    return '箱体历史预载不足'
  }
  return null
})
const visibleAlertMarkers = computed(() => alertMarkersForOverlay(
  selectedOverlay.value,
  persistentAlertMarkers.value,
))
const latestHtdyObservation = computed(() => {
  if (selectedOverlay.value !== 'htdy' || !overlayCapability.value.supported) return null
  return buildKlineDerivedData(bars.value, ['htdy']).htdy?.markers.at(-1) ?? null
})
const isLiveDisplay = computed(() => Boolean(
  marketState.value?.live_eligible
  && marketState.value.live_available
  && !liveUnavailable.value,
))
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
  return Boolean(afterMarket && typeof afterMarket === 'object' && afterMarket.last_failure != null)
})
const productCheckSidebarProps = computed(() => ({
  dominant: selectedDominant.value,
  seriesKind: effectiveIdentity.value.seriesKind,
  frequency: frequency.value,
  contract: effectiveIdentity.value.contract || '',
  live: isLiveDisplay.value,
  phase: phaseLabel.value,
  hasMoreBefore: hasMoreBefore.value,
  canonicalCoverage: canonicalCoverage.value,
  research: research.value,
  researchLoading: researchLoading.value,
  researchError: researchError.value,
  selectedOverlay: selectedOverlay.value,
  alertRules: alertRules.value,
  alertRuntimeStatus: alertRuntimeStatus.value,
  alertLoading: alertLoading.value,
  savingRuleCodes: savingRuleCodes.value,
  htdyObservation: latestHtdyObservation.value,
}))

onMounted(async () => {
  document.addEventListener('fullscreenchange', syncFullscreen)
  metadataLoading.value = true
  try {
    dominants.value = (await getMarketDominants()).items
    if (!dominants.value.some((item) => item.product === symbol.value)) {
      symbol.value = dominants.value[0]?.product || ''
    }
    metadataReady = true
    await synchronizeIdentity()
  } catch {
    error.value = '行情元数据加载失败'
  } finally {
    metadataLoading.value = false
  }
})

watch([symbol, contract, seriesKind, frequency], () => {
  if (metadataReady && !synchronizingIdentity.value) void synchronizeIdentity()
})

watch(selectedOverlay, () => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, selectedOverlay: selectedOverlay.value })
  void syncChartLocationQuery()
})

watch(optionalEmaIndicators, () => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, optionalEmaIndicators: optionalEmaIndicators.value })
}, { deep: true })

watch(showRangeDetector, () => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, showRangeDetector: showRangeDetector.value })
  if (!showRangeDetector.value) rangeDetectorWarmup.reset()
})

watch([symbol, seriesKind, frequency, researchSidebarOpen], persistWorkspacePreferences, { deep: true })

watch(frequency, (period) => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, period })
})

watch(mutation, (nextMutation) => {
  if (showRangeDetector.value && rangeDetectorWarmup.anchorTime.value === null) {
    rangeDetectorWarmup.reset()
    void rangeDetectorWarmup.ensureReady()
  }
  void syncPersistentAlertMarkers(currentAlertMarkerIdentity(), bars.value, nextMutation.kind)
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
  disposeIdentityCoordinator()
  disposeProductAlertScope()
  disposePersistentAlertMarkers()
  dispose()
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

async function syncChartLocationQuery() {
  await router.replace({
    query: {
      ...seriesRefreshQuery({
        symbol: symbol.value,
        contract: contract.value,
        seriesKind: seriesKind.value,
        frequency: frequency.value,
      }),
      overlay: selectedOverlay.value === 'none' ? undefined : selectedOverlay.value,
    },
  })
}

async function refreshSeries() {
  const replacementGeneration = ++canonicalReplacementGeneration
  if (!symbol.value) {
    clearSeries()
    return false
  }
  const requested = currentIdentity()
  if (requested.seriesKind === 'contract' && !requested.contract) {
    clearSeries()
    error.value = '指定真实合约时 contract 必填'
    return false
  }
  error.value = null
  followLatest.value = true
  try {
    await replaceSeries(requested)
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) {
      return false
    }
    await syncChartLocationQuery()
    return replacementGeneration === canonicalReplacementGeneration && isCurrentIdentity(requested)
  } catch {
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) {
      return false
    }
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

function invalidateFacts() {
  researchGeneration += 1
  research.value = null
  researchError.value = false
  researchLoading.value = true
  invalidateAlertIdentity()
}

function rejectFacts() {
  research.value = null
  researchError.value = true
  researchLoading.value = false
  markAlertsUnavailable()
}

function refreshFacts(): readonly Promise<void>[] {
  return [refreshResearch(), refreshAlerts()]
}

function isCurrentIdentity(candidate: ReturnType<typeof currentIdentity>) {
  const current = currentIdentity()
  return candidate.seriesKind === current.seriesKind
    && candidate.symbol === current.symbol
    && candidate.contract === current.contract
    && candidate.frequency === current.frequency
}

async function loadEarlierBars() {
  try {
    await loadMoreBefore()
  } catch (caught) {
    error.value = earlierHistoryLoadError(caught)
    message.error(error.value)
  }
}

function updateSelectedOverlay(value: ResearchOverlayId) {
  selectedOverlay.value = value
}

function updateOptionalEmaIndicators(value: OptionalEmaIndicatorId[]) {
  optionalEmaIndicators.value = normalizeOptionalEmaIndicators(value)
}

function persistWorkspacePreferences() {
  saveMarketWorkspacePreferences({
    version: 1,
    symbol: symbol.value || null,
    seriesKind: seriesKind.value === 'continuous' ? 'continuous' : 'actual_dominant',
    frequency: frequency.value,
    researchSidebarOpen: researchSidebarOpen.value,
  })
}

function openResearchDrawer() {
  if (window.innerWidth >= 1200) {
    researchSidebarOpen.value = !researchSidebarOpen.value
    return
  }
  researchDrawerOpen.value = true
}

function toggleHtdyAlert(ruleCode: string, enabled: boolean) {
  if (selectedOverlay.value !== 'htdy' || ruleCode !== ALERT_RULE_CODES.HTDY) return
  void toggleHtdyCurrentFrequency(ruleCode, enabled)
}

async function toggleFullscreen() {
  if (!workspaceElement.value) return
  try {
    if (document.fullscreenElement === workspaceElement.value) await document.exitFullscreen()
    else await workspaceElement.value.requestFullscreen()
  } catch {
    message.error('当前浏览器不支持 K 线全屏')
  }
}

function syncFullscreen() {
  fullscreen.value = document.fullscreenElement === workspaceElement.value
}

function resolveInitialSymbol() {
  const fromRoute = normalizeSymbol(route.query.symbol)
  return fromRoute || workspacePreferences.symbol || ''
}

function resolveInitialSeriesKind(): SeriesKind {
  if (route.query.series_kind === 'continuous' || route.query.series_kind === 'contract') {
    return route.query.series_kind
  }
  if (route.query.series_kind === 'actual_dominant') return 'actual_dominant'
  return workspacePreferences.seriesKind
}

function resolveInitialFrequency(): MarketFrequency {
  const fromRoute = normalizeFrequency(route.query.frequency)
  if (fromRoute) return fromRoute
  const fromPreferences = normalizeFrequency(chartPreferences.period)
  return fromPreferences || '15m'
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
      :show-range-detector="showRangeDetector"
      :fullscreen="fullscreen"
      @update:symbol="symbol = $event"
      @update:series-kind="seriesKind = $event"
      @update:frequency="frequency = $event"
      @update:contract="contract = $event"
      @update:selected-overlay="updateSelectedOverlay"
      @update:optional-ema-indicators="updateOptionalEmaIndicators"
      @update:show-range-detector="showRangeDetector = $event"
      @open-research="openResearchDrawer"
      @toggle-fullscreen="toggleFullscreen"
      @back="router.push({ name: 'market' })"
    />

    <NSpin :show="metadataLoading">
      <NAlert v-if="error" type="error" :show-icon="true">{{ error }}</NAlert>
      <NAlert
        v-if="selectedOverlay !== 'none' && !overlayCapability.supported"
        type="warning"
        :show-icon="true"
      >当前序列或周期不支持该 Overlay；K 线保持原选择，不自动切换。</NAlert>
      <NAlert v-if="rangeDetectorWarning" type="warning" :show-icon="true">{{ rangeDetectorWarning }}</NAlert>
      <div class="product-status-strip" data-testid="product-status-strip">
        <strong>{{ effectiveIdentity.contract || selectedDominant?.actual_contract || symbol.toUpperCase() }}</strong>
        <NTag
          data-testid="market-display-state"
          :type="isLiveDisplay ? 'success' : (isPostCloseDisplay ? 'warning' : 'default')"
        >{{ displayStateLabel }}</NTag>
        <span data-testid="market-phase">{{ phaseLabel }}</span>
        <NTag v-if="afterMarketFailed" type="warning">最近盘后更新失败</NTag>
        <span v-else class="product-status-strip__ok">数据正常</span>
        <span class="product-status-strip__bars">{{ bars.length }} bars</span>
        <NButton v-if="!followLatest" size="small" secondary @click="chart?.scrollToLatest()">回到最新</NButton>
      </div>
      <div ref="workspaceElement" class="product-workspace">
        <div class="product-workspace__main" :class="{ 'product-workspace__main--sidebar-closed': !researchSidebarOpen }">
          <div
            class="product-workspace__kline"
            :data-visible-main-indicators="visibleMainIndicators.join(',')"
            :data-range-detector-enabled="showRangeDetector ? 'true' : 'false'"
            :data-range-detector-anchor="rangeDetectorReadyAnchor || undefined"
            :data-range-detector-warmup="rangeDetectorWarmupState"
            :data-range-detector-source-identity="rangeDetectorSourceIdentity"
          >
            <KlineChart
              ref="chart"
              :bars="bars"
              :loading="loading"
              :error="error"
              :period="frequency"
              :series-kind="effectiveIdentity.seriesKind"
              :visible-main-indicators="visibleMainIndicators"
              :range-detector-source-identity="rangeDetectorSourceIdentity"
              :range-detector-anchor-time="rangeDetectorReadyAnchor"
              :alert-markers="visibleAlertMarkers"
              @need-more-before="loadEarlierBars"
              @follow-latest-change="followLatest = $event"
            />
          </div>
          <div class="product-workspace__sidebar-wrap">
            <ProductCheckSidebar
              v-bind="productCheckSidebarProps"
              @toggle-htdy-alert="toggleHtdyAlert"
            />
          </div>
        </div>
      </div>
    </NSpin>

    <NDrawer v-model:show="researchDrawerOpen" :width="320" placement="right">
      <NDrawerContent title="检查" closable>
        <ProductCheckSidebar
          v-bind="productCheckSidebarProps"
          @toggle-htdy-alert="toggleHtdyAlert"
        />
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.chart-page { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.product-status-strip { display: flex; align-items: center; gap: 9px; min-width: 0; padding: 8px 12px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); flex-wrap: wrap; }
.product-status-strip strong { color: var(--gy-text-primary); font-family: var(--gy-font-mono); }
.product-status-strip__ok { color: var(--gy-status-success); }
.product-status-strip__bars { margin-left: auto; color: var(--gy-text-muted); }
.product-workspace { min-width: 0; }
.product-workspace__main { display: grid; grid-template-columns: minmax(0, 1fr) 296px; gap: 12px; align-items: stretch; }
.product-workspace__main--sidebar-closed { grid-template-columns: minmax(0, 1fr); }
.product-workspace__main--sidebar-closed .product-workspace__sidebar-wrap { display: none; }
.product-workspace__kline { min-width: 0; }
.product-workspace__sidebar-wrap { position: relative; min-width: 0; min-height: 0; }
.product-workspace__sidebar-wrap > .product-workspace__sidebar { position: absolute; inset: 0; overflow-y: auto; }
.product-workspace:fullscreen { display: grid; place-items: stretch; padding: 16px; background: var(--gy-bg-app); }
.product-workspace:fullscreen .product-workspace__main { grid-template-columns: minmax(0, 1fr); height: 100%; }
.product-workspace:fullscreen .product-workspace__kline { min-height: 100%; }
.product-workspace:fullscreen .product-workspace__sidebar-wrap { display: none; }

@media (min-width: 980px) {
  .chart-page { height: 100%; min-height: 0; overflow-y: auto; }
  .chart-page > :deep(.n-spin-container), .chart-page :deep(.n-spin-content) { display: flex; flex: 0 0 auto; min-height: 0; flex-direction: column; width: 100%; }
  .product-workspace, .product-workspace__main { flex: 0 0 auto; min-height: 0; width: 100%; min-width: 0; }
  .product-workspace { display: flex; }
  .product-workspace__kline { display: flex; min-width: 0; width: 100%; }
  .product-workspace__kline :deep(.kline-shell) { flex: none; width: 100%; min-width: 0; min-height: 480px; height: clamp(480px, calc(100vh - 320px), 900px); }
}

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
