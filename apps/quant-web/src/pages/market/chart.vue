<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NDrawer, NDrawerContent, NSpin, NTag, useMessage } from 'naive-ui'
import ProductCheckSidebar from '@/components/market/ProductCheckSidebar.vue'
import ProductWorkspaceToolbar from '@/components/market/ProductWorkspaceToolbar.vue'
import SubingStrategyPerformancePanel from '@/components/market/SubingStrategyPerformancePanel.vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import {
  getMarketDominants,
  getProductResearch,
  getSubingStrategyHistory,
  getSubingStrategyCurrent,
  getSubingStrategyPerformance,
  getSubingResearch,
} from '@/api/market'
import {
  getAlertRuntimeStatus,
  getAlertEvents,
  getProductCurrentAlertEvents,
  getProductAlerts,
  setAlertProductEnabled,
  setAlertProductFrequencyEnabled,
} from '@/api/alerts'
import { useMarketSeries } from '@/composables/useMarketSeries'
import {
  RANGE_DETECTOR_WARMUP_INSUFFICIENT,
  RANGE_DETECTOR_WARMUP_LOAD_FAILED,
  useRangeDetectorOverlayWarmup,
} from '@/composables/useRangeDetectorOverlayWarmup'
import { usePersistentAlertMarkers } from '@/composables/usePersistentAlertMarkers'
import { useHistoricalResearchMarkers } from '@/composables/useHistoricalResearchMarkers'
import { useProductAlertScope } from '@/composables/useProductAlertScope'
import { useProductCurrentAlertEvents } from '@/composables/useProductCurrentAlertEvents'
import { useProductSymbolIdentityCoordinator } from '@/composables/useProductSymbolIdentityCoordinator'
import { useSubingObservation } from '@/composables/useSubingObservation'
import { useSubingStrategyCurrent } from '@/composables/useSubingStrategyCurrent'
import type {
  DominantContractItem,
  MainIndicatorId,
  MarketFrequency,
  OptionalEmaIndicatorId,
  ProductResearchResponse,
  ResearchOverlayId,
  SeriesKind,
  SubingStrategyPerformanceResponse,
} from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'
import { lifecycleSnapshotToMarkers } from '@/utils/subingLifecycleMarkers'
import { ALERT_RULE_CODES } from '@/utils/alertRules'
import { earlierHistoryLoadError } from '@/utils/errorRedaction'
import { alertMarkersForOverlay, mergeKlineMarkers } from '@/utils/alertMarkers'
import { reconcileSubingStrategyActions } from '@/utils/subingStrategyReconciliation'
import { buildKlineDerivedData } from '@/utils/klineViewModel'
import {
  loadMainChartPreferences,
  normalizeOptionalEmaIndicators,
  resolveEffectiveSeriesIdentity,
  researchOverlayCapability,
  saveMainChartPreferences,
  subingStrategyHistoricalCapability,
  visibleMainIndicatorsForOverlay,
} from '@/utils/mainIndicators'
import {
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
} from '@/utils/marketWorkspacePreferences'
import {
  resolveSubingConfirmChartEntry,
  resolveSubingDailyWatchChartEntry,
  seriesRefreshQuery,
} from '@/utils/marketChartEntry'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const initialWorkspacePreferences = loadMarketWorkspacePreferences()
const initialMainChartPreferences = loadMainChartPreferences()
const initialConfirmEntry = resolveSubingConfirmChartEntry(route.query)
const dailyWatchEntry = resolveSubingDailyWatchChartEntry(route.query)
const metadataLoading = ref(false)
const error = ref<string | null>(null)
const dominants = ref<DominantContractItem[]>([])
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const workspaceElement = ref<HTMLElement | null>(null)
const fullscreen = ref(false)
const researchDrawerOpen = ref(false)
const researchSidebarOpen = ref(initialWorkspacePreferences.researchSidebarOpen)
const selectedOverlay = ref<ResearchOverlayId>(
  initialConfirmEntry?.overlay ?? initialMainChartPreferences.selectedOverlay,
)
const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([
  ...initialMainChartPreferences.optionalEmaIndicators,
])
const showRangeDetector = ref(initialMainChartPreferences.showRangeDetector)
const showSubingInternalProcess = ref(
  initialMainChartPreferences.showSubingInternalProcess,
)
const showSubingStrategyPerformance = ref(
  initialMainChartPreferences.showSubingStrategyPerformance,
)
const research = ref<ProductResearchResponse | null>(null)
const researchLoading = ref(false)
const researchError = ref(false)
const strategyPerformance = ref<SubingStrategyPerformanceResponse | null>(null)
const strategyPerformanceLoading = ref(false)
const strategyPerformanceError = ref<string | null>(null)
let strategyPerformanceGeneration = 0
let strategyPerformanceController: AbortController | null = null
const symbol = ref(initialConfirmEntry?.symbol ?? dailyWatchEntry?.symbol ?? resolveInitialSymbol())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(
  initialConfirmEntry?.seriesKind ?? dailyWatchEntry?.seriesKind ?? resolveInitialSeriesKind(),
)
const frequency = ref<MarketFrequency>(
  initialConfirmEntry?.frequency ?? dailyWatchEntry?.frequency ?? resolveInitialFrequency(),
)
const followLatest = ref(initialConfirmEntry?.actionId ? false : true)
const focusedActionRevealed = ref(false)
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
const {
  markers: persistentAlertMarkers,
  strategyEvents: persistentStrategyEvents,
  sync: syncPersistentAlertMarkers,
  dispose: disposePersistentAlertMarkers,
} = usePersistentAlertMarkers({ fetchEvents: getAlertEvents })
const {
  markers: historicalResearchMarkers,
  subingStrategyActions,
  subingStrategyEpisodes,
  loading: historicalResearchLoading,
  error: historicalResearchError,
  sync: syncHistoricalResearchMarkers,
  dispose: disposeHistoricalResearchMarkers,
} = useHistoricalResearchMarkers({
  fetchSubingStrategy: getSubingStrategyHistory,
})
const {
  current: subingStrategyCurrent,
  loading: subingStrategyCurrentLoading,
  error: subingStrategyCurrentError,
  refresh: refreshSubingStrategyCurrent,
  invalidate: invalidateSubingStrategyCurrent,
  markUnavailable: markSubingStrategyCurrentUnavailable,
  dispose: disposeSubingStrategyCurrent,
} = useSubingStrategyCurrent({ fetchCurrent: getSubingStrategyCurrent })
const {
  subing,
  subingLoading,
  subingError,
  subingSupported,
  reset: resetSubingSnapshot,
  markUnavailable: markSubingUnavailable,
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
  invalidateIdentity: invalidateAlertIdentity,
  markUnavailable: markAlertsUnavailable,
  toggleSubingProduct,
  toggleHtdyCurrentFrequency,
  dispose: disposeProductAlertScope,
} = useProductAlertScope({
  symbol,
  frequency,
  fetchProductAlerts: getProductAlerts,
  fetchRuntimeStatus: getAlertRuntimeStatus,
  setProductEnabled: setAlertProductEnabled,
  setProductFrequencyEnabled: setAlertProductFrequencyEnabled,
  notifyError: (text) => message.error(text),
})
const {
  loading: currentEventsLoading,
  status: currentEventsStatus,
  items: currentEvents,
  refresh: refreshCurrentEvents,
  invalidateIdentity: invalidateCurrentEventsIdentity,
  markUnavailable: markCurrentEventsUnavailable,
  dispose: disposeProductCurrentAlertEvents,
} = useProductCurrentAlertEvents({ symbol, fetchCurrentEvents: getProductCurrentAlertEvents })
let metadataReady = false
let researchGeneration = 0
let canonicalReplacementGeneration = 0
let pendingHistoricalOverlayRefresh = false
const {
  synchronizing: synchronizingSymbol,
  synchronize: synchronizeSymbolIdentity,
  dispose: disposeSymbolIdentityCoordinator,
} = useProductSymbolIdentityCoordinator({
  invalidateFacts: invalidateSymbolFacts,
  refreshMarket: refreshSeries,
  refreshFacts: refreshSymbolFacts,
  rejectFacts: rejectSymbolFacts,
})

const loading = computed(() => loadingInitial.value || loadingBefore.value)
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
const effectiveIdentity = computed(() => currentIdentity())
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
  if (rangeDetectorWarmup.unavailableReason.value === RANGE_DETECTOR_WARMUP_LOAD_FAILED) return '箱体历史预载失败'
  if (rangeDetectorWarmup.unavailableReason.value === RANGE_DETECTOR_WARMUP_INSUFFICIENT) return '箱体历史预载不足'
  return null
})
const overlayCapability = computed(() => researchOverlayCapability(
  selectedOverlay.value,
  effectiveIdentity.value.seriesKind,
  frequency.value,
))
const showSubingEmaRibbon = computed(() => (
  selectedOverlay.value === 'subing' && overlayCapability.value.supported
))
const confirmEntry = computed(() => resolveSubingConfirmChartEntry(route.query))
const focusedActionId = computed(() => confirmEntry.value?.actionId ?? null)
const visibleBars = computed(() => bars.value)
const subingStrategySupported = computed(() => subingStrategyHistoricalCapability(
  effectiveIdentity.value.seriesKind,
  frequency.value,
))
const visibleStartTradingDay = computed(() => visibleBars.value[0]?.trading_day || '')
const lifecycleMarkers = computed(() => {
  if (!showSubingInternalProcess.value) return []
  if (!overlayCapability.value.supported || subingLoading.value || subingError.value) return []
  return selectedOverlay.value === 'subing' && subing.value
    ? lifecycleSnapshotToMarkers(subing.value.lifecycle)
    : []
})
const liveStrategyEvents = computed(() => {
  const byId = new Map<string, typeof currentEvents.value[number]>()
  for (const event of [...persistentStrategyEvents.value, ...currentEvents.value]) {
    if (event.action_id) byId.set(event.action_id, event)
  }
  return [...byId.values()]
})
const strategyReconciliation = computed(() => reconcileSubingStrategyActions(
  subingStrategyActions.value,
  subingStrategyEpisodes.value,
  liveStrategyEvents.value,
))
const visibleHistoricalResearchMarkers = computed(() => (
  selectedOverlay.value === 'subing'
    ? strategyReconciliation.value.markers
    : historicalResearchMarkers.value
))
const researchMarkers = computed(() => mergeKlineMarkers(
  lifecycleMarkers.value,
  visibleHistoricalResearchMarkers.value,
))
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
const htdyVisible = computed(() => selectedOverlay.value === 'htdy')
const visibleAlertMarkers = computed(() => alertMarkersForOverlay(
  selectedOverlay.value,
  persistentAlertMarkers.value,
))
const latestHtdyObservation = computed(() => {
  if (!htdyVisible.value || !overlayCapability.value.supported) return null
  return buildKlineDerivedData(visibleBars.value, ['htdy']).htdy?.markers.at(-1) ?? null
})
const productCheckSidebarProps = computed(() => ({
  dominant: selectedDominant.value,
  seriesKind: effectiveIdentity.value.seriesKind,
  frequency: frequency.value,
  contract: effectiveIdentity.value.contract || '',
  live: isLiveDisplay.value,
  phase: phaseLabel.value,
  hasMoreBefore: canLoadEarlier.value,
  canonicalCoverage: canonicalCoverage.value,
  research: research.value,
  researchLoading: researchLoading.value,
  researchError: researchError.value,
  selectedOverlay: selectedOverlay.value,
  subing: subing.value,
  subingLoading: subingLoading.value || metadataLoading.value,
  subingError: subingError.value,
  subingSupported: subingSupported.value,
  alertRules: alertRules.value,
  alertRuntimeStatus: alertRuntimeStatus.value,
  alertLoading: alertLoading.value,
  savingRuleCodes: savingRuleCodes.value,
  currentEventsLoading: currentEventsLoading.value,
  currentEventsStatus: currentEventsStatus.value,
  currentEvents: currentEvents.value,
  htdyObservation: latestHtdyObservation.value,
  subingStrategySupported: subingStrategySupported.value,
  subingStrategyCurrent: subingStrategyCurrent.value,
  subingStrategyCurrentLoading: subingStrategyCurrentLoading.value,
  subingStrategyCurrentError: subingStrategyCurrentError.value,
  subingStrategyReconciliationErrors: strategyReconciliation.value.errorCodes,
  showSubingInternalProcess: showSubingInternalProcess.value,
  focusedActionId: focusedActionId.value,
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
    void synchronizeSymbolIdentity()
  } catch {
    error.value = '行情元数据加载失败'
  } finally {
    metadataLoading.value = false
  }
})

watch(symbol, () => {
  if (!metadataReady) return
  void synchronizeSymbolIdentity()
})

watch([contract, seriesKind, frequency], async () => {
  if (!metadataReady) return
  if (synchronizingSymbol.value) {
    void synchronizeSymbolIdentity()
    return
  }
  resetSubingSnapshot()
  if (await refreshSeries()) void refreshSubing()
})

watch([showRangeDetector, showSubingInternalProcess, showSubingStrategyPerformance], () => {
  const current = loadMainChartPreferences()
  saveMainChartPreferences({
    ...current,
    showRangeDetector: showRangeDetector.value,
    showSubingInternalProcess: showSubingInternalProcess.value,
    showSubingStrategyPerformance: showSubingStrategyPerformance.value,
  })
})

watch(selectedOverlay, () => {
  if (synchronizingSymbol.value) {
    pendingHistoricalOverlayRefresh = true
    resetSubingSnapshot()
    return
  }
  pendingHistoricalOverlayRefresh = false
  resetSubingSnapshot()
  void refreshSubing()
  void syncHistoricalResearchMarkers(
    currentHistoricalMarkerIdentity(),
    visibleBars.value,
    canonicalCoverage.value,
    'replace',
  )
  if (selectedOverlay.value === 'subing') {
    void refreshSubingStrategyCurrent(currentSubingStrategyIdentity())
  } else {
    invalidateSubingStrategyCurrent()
  }
  void syncChartLocationQuery()
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

watch([seriesKind, contract], () => {
  if (metadataReady && !synchronizingSymbol.value) void refreshResearch()
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
  void syncHistoricalResearchMarkers(
    currentHistoricalMarkerIdentity(),
    bars.value,
    canonicalCoverage.value,
    nextMutation.kind,
  )
  if (nextMutation.kind === 'live' && selectedOverlay.value === 'subing' && subingSupported.value) {
    void refreshSubing()
    void refreshCurrentEvents()
    if (subingStrategySupported.value) {
      void refreshSubingStrategyCurrent(currentSubingStrategyIdentity())
    }
  }
  if (!chart.value) return
  if (nextMutation.kind === 'replace') {
    chart.value.replaceBars(bars.value, !followLatest.value)
    void tryRevealFocusedAction()
    return
  }
  if (nextMutation.kind === 'prepend') {
    chart.value.prependBars(nextMutation.bars)
    return
  }
  for (const bar of nextMutation.bars) chart.value.updateBar(bar)
  if (followLatest.value) chart.value.scrollToLatest()
})

watch(focusedActionId, () => {
  focusedActionRevealed.value = false
  tryRevealFocusedAction()
})

watch([currentEvents, historicalResearchMarkers, visibleBars], () => {
  tryRevealFocusedAction()
})

onUnmounted(() => {
  strategyPerformanceController?.abort()
  strategyPerformanceController = null
  document.removeEventListener('fullscreenchange', syncFullscreen)
  disposeSymbolIdentityCoordinator()
  disposeSubingObservation()
  disposeProductAlertScope()
  disposeProductCurrentAlertEvents()
  dispose()
  disposePersistentAlertMarkers()
  disposeHistoricalResearchMarkers()
  disposeSubingStrategyCurrent()
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

function currentHistoricalMarkerIdentity() {
  return {
    overlay: selectedOverlay.value,
    seriesKind: effectiveIdentity.value.seriesKind,
    symbol: symbol.value,
    frequency: frequency.value,
  }
}

function currentSubingStrategyIdentity() {
  const identity = currentIdentity()
  return {
    seriesKind: identity.seriesKind,
    symbol: identity.symbol,
    frequency: identity.frequency,
    contract: identity.seriesKind === 'actual_dominant'
      ? selectedDominant.value?.actual_contract ?? null
      : identity.contract ?? null,
  }
}

function syncChartLocationQuery() {
  return router.replace({
    query: seriesRefreshQuery({
      symbol: symbol.value,
      contract: contract.value,
      seriesKind: seriesKind.value,
      frequency: frequency.value,
      overlay: selectedOverlay.value,
      confirm: confirmEntry.value,
    }),
  })
}

function focusedActionTime(actionId: string): string | null {
  const live = liveStrategyEvents.value.find((event) => event.action_id === actionId)
  if (live?.strategy_action?.effective_bar_end) return live.strategy_action.effective_bar_end
  if (live?.bar_end) return live.bar_end
  const historical = subingStrategyActions.value.find((action) => action.action_id === actionId)
  return historical?.effective_bar_end ?? null
}

function tryRevealFocusedAction() {
  const actionId = focusedActionId.value
  if (!actionId || focusedActionRevealed.value || !chart.value) return
  const time = focusedActionTime(actionId)
  if (!time) return
  if (chart.value.revealTime(time)) focusedActionRevealed.value = true
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
  followLatest.value = focusedActionId.value === null
  try {
    await replaceSeries(requested)
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) return false
    await syncChartLocationQuery()
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) return false
    return true
  } catch {
    if (replacementGeneration !== canonicalReplacementGeneration || !isCurrentIdentity(requested)) return false
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

function invalidateResearch(): void {
  researchGeneration += 1
  research.value = null
  researchError.value = false
  researchLoading.value = true
}

function markResearchUnavailable(): void {
  research.value = null
  researchError.value = true
  researchLoading.value = false
}

function invalidateSymbolFacts(): void {
  invalidateResearch()
  resetSubingSnapshot()
  invalidateAlertIdentity()
  invalidateCurrentEventsIdentity()
  invalidateSubingStrategyCurrent()
  strategyPerformanceController?.abort()
  strategyPerformanceController = null
  strategyPerformanceGeneration += 1
  strategyPerformance.value = null
  strategyPerformanceLoading.value = true
  strategyPerformanceError.value = null
}

function rejectSymbolFacts(): void {
  markResearchUnavailable()
  markSubingUnavailable()
  markAlertsUnavailable()
  markCurrentEventsUnavailable()
  markSubingStrategyCurrentUnavailable()
  strategyPerformanceController?.abort()
  strategyPerformanceController = null
  strategyPerformanceGeneration += 1
  strategyPerformance.value = null
  strategyPerformanceLoading.value = false
  strategyPerformanceError.value = 'SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE'
}

function refreshSymbolFacts(): readonly Promise<void>[] {
  if (pendingHistoricalOverlayRefresh) {
    pendingHistoricalOverlayRefresh = false
    void syncHistoricalResearchMarkers(
      currentHistoricalMarkerIdentity(),
      visibleBars.value,
      canonicalCoverage.value,
      'replace',
    )
  }
  return [
    refreshResearch(),
    refreshSubing(),
    refreshAlerts(),
    refreshCurrentEvents(),
    refreshSubingStrategyCurrent(currentSubingStrategyIdentity()),
    refreshStrategyPerformance(),
  ]
}

async function refreshStrategyPerformance(): Promise<void> {
  const requestSymbol = symbol.value
  const generation = ++strategyPerformanceGeneration
  strategyPerformanceController?.abort()
  const controller = new AbortController()
  strategyPerformanceController = controller
  strategyPerformanceLoading.value = true
  strategyPerformanceError.value = null
  try {
    const result = await getSubingStrategyPerformance({ symbol: requestSymbol, signal: controller.signal })
    if (generation !== strategyPerformanceGeneration || requestSymbol !== symbol.value) return
    strategyPerformance.value = result
  } catch {
    if (controller.signal.aborted) return
    if (generation !== strategyPerformanceGeneration || requestSymbol !== symbol.value) return
    strategyPerformance.value = null
    strategyPerformanceError.value = 'SUBING_STRATEGY_PERFORMANCE_UNAVAILABLE'
  } finally {
    if (strategyPerformanceController === controller) strategyPerformanceController = null
    if (generation === strategyPerformanceGeneration) strategyPerformanceLoading.value = false
  }
}

async function loadEarlierBars() {
  try {
    await loadMoreBefore()
  } catch (caught) {
    error.value = earlierHistoryLoadError(caught)
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

function updateOptionalEmaIndicators(value: OptionalEmaIndicatorId[]) {
  optionalEmaIndicators.value = normalizeOptionalEmaIndicators(value)
  const current = loadMainChartPreferences()
  saveMainChartPreferences({ ...current, optionalEmaIndicators: optionalEmaIndicators.value })
}

function updateShowRangeDetector(value: boolean) {
  showRangeDetector.value = value
  if (!value) rangeDetectorWarmup.reset()
}

function updateShowSubingInternalProcess(value: boolean) {
  showSubingInternalProcess.value = value
}

function updateShowSubingStrategyPerformance(value: boolean) {
  showSubingStrategyPerformance.value = value
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

function toggleSubingAlert(ruleCode: string, enabled: boolean) {
  if (selectedOverlay.value !== 'subing' || ruleCode !== ALERT_RULE_CODES.SUBING) return
  void toggleSubingProduct(ruleCode, enabled)
}

function toggleHtdyAlert(ruleCode: string, enabled: boolean) {
  if (selectedOverlay.value !== 'htdy' || ruleCode !== ALERT_RULE_CODES.HTDY) return
  void toggleHtdyCurrentFrequency(ruleCode, enabled)
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
      :show-range-detector="showRangeDetector"
      :show-subing-internal-process="showSubingInternalProcess"
      :show-subing-strategy-performance="showSubingStrategyPerformance"
      :fullscreen="fullscreen"
      @update:symbol="symbol = $event"
      @update:series-kind="seriesKind = $event"
      @update:frequency="frequency = $event"
      @update:contract="contract = $event"
      @update:selected-overlay="updateSelectedOverlay"
      @update:optional-ema-indicators="updateOptionalEmaIndicators"
      @update:show-range-detector="updateShowRangeDetector"
      @update:show-subing-internal-process="updateShowSubingInternalProcess"
      @update:show-subing-strategy-performance="updateShowSubingStrategyPerformance"
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
      <NAlert
        v-else-if="historicalResearchError"
        type="warning"
        :show-icon="true"
      >{{ selectedOverlay === 'subing'
          ? '历史因果投影暂不可用；Canonical K 线与当前苏冰观察仍可正常查看。'
          : '历史因果投影暂不可用；Canonical K 线仍可正常查看。' }}</NAlert>
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
        <span class="product-status-strip__bars">{{ visibleBars.length }} bars</span>
        <NButton v-if="!followLatest" size="small" secondary @click="chart?.scrollToLatest()">回到最新</NButton>
      </div>
      <div ref="workspaceElement" class="product-workspace">
        <div class="product-workspace__main" :class="{ 'product-workspace__main--sidebar-closed': !researchSidebarOpen }">
          <div
            class="product-workspace__kline"
            :data-visible-start-trading-day="visibleStartTradingDay"
            :data-visible-main-indicators="visibleMainIndicators.join(',')"
            :data-subing-ema-ribbon="showSubingEmaRibbon ? 'true' : 'false'"
            :data-range-detector-enabled="showRangeDetector ? 'true' : 'false'"
            :data-range-detector-anchor="rangeDetectorReadyAnchor || undefined"
            :data-range-detector-warmup="rangeDetectorWarmupState"
            :data-range-detector-source-identity="rangeDetectorSourceIdentity"
            :data-focused-action-id="focusedActionId || undefined"
          >
            <KlineChart
              ref="chart"
              :bars="visibleBars"
              :loading="loading"
              :error="error"
              :period="frequency"
              :series-kind="effectiveIdentity.seriesKind"
              :visible-main-indicators="visibleMainIndicators"
              :show-subing-ema-ribbon="showSubingEmaRibbon"
              :range-detector-source-identity="rangeDetectorSourceIdentity"
              :range-detector-anchor-time="rangeDetectorReadyAnchor"
              :alert-markers="visibleAlertMarkers"
              :research-markers="researchMarkers"
              :data-historical-research-loading="historicalResearchLoading"
              @need-more-before="loadEarlierBars"
              @follow-latest-change="followLatest = $event"
            />
          </div>
          <div class="product-workspace__sidebar-wrap">
            <ProductCheckSidebar
              v-bind="productCheckSidebarProps"
              @toggle-subing-alert="toggleSubingAlert"
              @toggle-htdy-alert="toggleHtdyAlert"
            />
          </div>
        </div>
      </div>
    </NSpin>

    <SubingStrategyPerformancePanel
      v-if="showSubingStrategyPerformance"
      :symbol="symbol"
      :result="strategyPerformance"
      :loading="strategyPerformanceLoading"
      :error="strategyPerformanceError"
    />

    <NDrawer v-model:show="researchDrawerOpen" :width="320" placement="right">
      <NDrawerContent title="检查" closable>
        <ProductCheckSidebar
          v-bind="productCheckSidebarProps"
          @toggle-subing-alert="toggleSubingAlert"
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
/* 侧栏与左侧 K 线列（含副图）等高：wrap 随 grid 行高拉伸，侧栏绝对填充并内部滚动 */
.product-workspace__sidebar-wrap { position: relative; min-width: 0; min-height: 0; }
.product-workspace__sidebar-wrap > .product-workspace__sidebar { position: absolute; inset: 0; overflow-y: auto; }
.product-workspace:fullscreen { display: grid; place-items: stretch; padding: 16px; background: var(--gy-bg-app); }
.product-workspace:fullscreen .product-workspace__main { grid-template-columns: minmax(0, 1fr); height: 100%; }
.product-workspace:fullscreen .product-workspace__kline { min-height: 100%; }
.product-workspace:fullscreen .product-workspace__sidebar-wrap { display: none; }

@media (min-width: 980px) {
  .chart-page { height: 100%; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; }
  .chart-page > :deep(.n-spin-container) { display: flex; flex: 0 0 auto; min-height: 0; flex-direction: column; width: 100%; }
  .chart-page :deep(.n-spin-content) { display: flex; flex: 0 0 auto; min-height: 0; flex-direction: column; width: 100%; }
  .product-workspace, .product-workspace__main { flex: 0 0 auto; min-height: 0; width: 100%; min-width: 0; }
  .product-workspace { display: flex; }
  .product-workspace__kline { display: flex; min-width: 0; width: 100%; }
  .product-workspace__kline :deep(.kline-shell) {
    flex: none;
    width: 100%;
    min-width: 0;
    min-height: 480px;
    height: clamp(480px, calc(100vh - 320px), 900px);
  }
  .chart-page :deep([data-testid='subing-strategy-performance']) { flex: 0 0 auto; width: 100%; }
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
