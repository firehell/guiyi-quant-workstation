<script setup lang="ts">
/**
 * 行情 K 线工作台：历史/Live 模式、viewport 懒加载、信号 deep-link、
 * 主图指标与 Live 20s 轮询刷新。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCheckbox, NDatePicker, NPopover, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import FuturesResearchPanel from '@/components/research/FuturesResearchPanel.vue'
import LiveTargetPanel from '@/components/market/LiveTargetPanel.vue'
import MarketContextBar, { type MarketDataMode } from '@/components/market/MarketContextBar.vue'
import MarketDataQualityCard from '@/components/market/MarketDataQualityCard.vue'
import MarketEvidenceDrawer from '@/components/market/MarketEvidenceDrawer.vue'
import MarketEvidenceStrip from '@/components/market/MarketEvidenceStrip.vue'
import MarketRightRail from '@/components/market/MarketRightRail.vue'
import MarketRuntimeObservationPanel from '@/components/market/MarketRuntimeObservationPanel.vue'
import { getLatestStrategySignals, getSignalEvent, getSignalEvents, getStage9WechatNotification } from '@/api/signal'
import type { SignalEventRecord, Stage9WechatNotification, StrategySignalRecord } from '@/types/signal'
import { getCanonicalMarketCoverage, getLiveMarketBars, getLiveMarketCoverage, getMarketBars, getMarketDominants, getMarketIndicators, getMarketMacdIndicator, getMarketWorkbenchCoverage } from '@/api/market'
import type {
  BarData,
  ChartOverlay,
  DominantContractItem,
  HoverKlineContext,
  KlineMarker,
  LiveMarketBarsQuality,
  MarketBarsRequestParams,
  MarketBarsCoverage,
  MarketBarsQuality,
  MarketMacdIndicatorResponse,
  MarketAccessMode,
  MarketCoverageItem,
  MarketReadLineage,
  MarketWorkbenchCoverage,
  MainIndicatorDefinition,
  MainIndicatorId,
  MainIndicatorSeries,
} from '@/types/market'
import { calculateATR, calculateEMA } from '@/utils/indicators'
import { buildReviewResearchQuery, parseResearchContext, safeReturnRoute } from '@/utils/researchNavigation'
import {
  activeIndicatorCodes,
  buildMainIndicatorRequestParams,
  filterVisibleMainIndicatorsForMode,
  isMainIndicatorAllowed,
  latestMainIndicatorValues,
  loadMainChartPreferences,
  MAIN_INDICATOR_DEFINITIONS,
  normalizeMainIndicatorSeries,
  saveMainChartPreferences,
  TREND_EMA_INDICATORS,
} from '@/utils/mainIndicators'
import { CHART_PERIOD_OPTIONS } from '@/utils/constants'
import {
  type ContractViewMode,
  BarMergeConflictError,
  barTimeMs,
  barsTimeExtent,
  computeViewportLoadRequest,
  continuousContractFor,
  defaultContractViewForPeriod,
  fullCoverageDateRangeMs,
  isLivePeriodSupported,
  MAX_BARS_PER_REQUEST,
  dedupeBarsByPeriod,
  mergeBarsByTime,
  resolveContractForView,
  resolveInitialBarsQuery,
  resolveLiveRefreshStart,
  trimBarsToMaxCount,
  type ViewportLoadRequest,
} from '@/utils/marketChartWindow'
import { applyRouteSelectionFromQuery, scopedCoverageParams } from '@/utils/marketChartInit'
import { buildMarketQualificationPresentation } from '@/utils/marketEvidencePresentation'
import { isSyntheticFuturesContract, resolveActualContract } from '@/utils/marketContract'
import { selectSignalEventForChart, signalIdFromMarkerId, signalMarkerId } from '@/utils/marketSignalSelection'
import { signalSourceDataMode } from '@/utils/signalSourceMode'
import { resolveChartTheme } from '@/styles/chartTheme'
import { buildMarketRuntimeObservation } from '@/utils/marketRuntimeObservation'
import {
  buildMarketQualityImpact,
  type MarketQualityAction,
} from '@/utils/marketQualityPresentation'
import type { MarketRuntimeObservationContext } from '@/types/marketRuntimeObservation'
import {
  buildEmaObservationStatus,
  buildMarketChartRouteQuery,
  LIVE_INDICATOR_CONTEXT_PENDING_MESSAGE,
  qualityFailedObservationText,
  safeMarketApiError,
} from '@/utils/marketChartQuery'
import {
  loadMarketRightRailTab,
  resolveMarketRightRailTab,
  saveMarketRightRailTab,
  type MarketRightRailTab,
} from '@/utils/marketRightRail'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const chartTheme = resolveChartTheme()

type KlineChartExpose = {
  focusTime: (value: string) => void
}

type MarketDataQualityCardExpose = {
  focus: () => void
}

type BarsLoadMode = 'viewport' | 'explicit'
/** Live 模式定时增量刷新间隔（毫秒） */
const LIVE_REFRESH_INTERVAL_MS = 20_000

interface LoadBarsOptions {
  viewportWindow?: ViewportLoadRequest
  merge?: boolean
  liveRefresh?: boolean
  fitContent?: boolean
  visibleCenterMs?: number
}

const loadingMeta = ref(false)
const loadingDominants = ref(false)
const loadingBars = ref(false)
const loadingIndicators = ref(false)
const barsError = ref<string | null>(null)
const indicatorError = ref<string | null>(null)
const metaWarning = ref<string | null>(null)
const qualityWarningMessage = ref<string | null>(null)
const coverage = ref<MarketWorkbenchCoverage | null>(null)
const dominants = ref<DominantContractItem[]>([])
const bars = ref<BarData[]>([])
const quality = ref<MarketBarsQuality | LiveMarketBarsQuality | null>(null)
const barsCoverage = ref<MarketBarsCoverage | null>(null)
const barsLineage = ref<MarketReadLineage | null>(null)
const macdOverride = ref<MarketMacdIndicatorResponse | null>(null)
const macdError = ref<string | null>(null)
const hoverContext = ref<HoverKlineContext | null>(null)

const dataMode = ref<MarketDataMode>(route.query.data_mode === 'live' ? 'live' : 'historical')
const selectedSymbol = ref<string | null>(null)
const selectedActualContract = ref<string | null>(null)
const contractView = ref<ContractViewMode>('actual')
const selectedPeriod = ref<string | null>(null)
const accessMode = ref<MarketAccessMode>(route.query.access_mode === 'research' ? 'research' : 'browser')
const chartPreferences = loadMainChartPreferences()
const visibleMainIndicators = ref<MainIndicatorId[]>(
  filterVisibleMainIndicatorsForMode(chartPreferences.visibleMainIndicators, {
    dataMode: dataMode.value,
    accessMode: accessMode.value,
  }),
)
const mainIndicatorSeries = ref<MainIndicatorSeries[]>([])
const realtimeFollowPreference = ref(Boolean(chartPreferences.realtimeFollow))
const dateRange = ref<[number, number] | null>(null)
const barsLoadMode = ref<BarsLoadMode>('viewport')
const chartFitContent = ref(true)
const viewportLoadEnabled = ref(false)
const klineChartRef = ref<KlineChartExpose | null>(null)
const qualityCardRef = ref<MarketDataQualityCardExpose | null>(null)
const activeMarkerId = ref<string | null>(null)
const showSignalLayer = ref(route.query.signal_layer !== '0')
const latestSignals = ref<StrategySignalRecord[]>([])
const selectedSignalId = ref<number | null>(null)
const selectedSignalEvent = ref<SignalEventRecord | null>(null)
const selectedNotification = ref<Stage9WechatNotification | null>(null)
const loadingNotification = ref(false)
const notificationError = ref<string | null>(null)
const experimentalToolsOpen = ref(false)
const evidenceDrawerOpen = ref(false)
const activeRightRailTab = ref<MarketRightRailTab>(
  resolveMarketRightRailTab({
    preferred: loadMarketRightRailTab(),
    hasSignalContext: Boolean(route.query.signal_id || route.query.signal_event_id),
    hasReviewContext: Boolean(route.query.review_id),
  }),
)
/** 路由/K 线请求序号，丢弃过期异步结果 */
let marketRouteRequestId = 0
let macdRequestId = 0
let signalSelectionRequestId = 0
let syncingQueryFromState = false
let viewportLoadTimer: ReturnType<typeof setTimeout> | null = null
let liveRefreshTimer: ReturnType<typeof setInterval> | null = null
/** 防止 Live 20s 轮询与 visibility 恢复刷新重叠 */
let liveRefreshInFlight = false

const coverageItems = computed(() => coverage.value?.items || [])
const isLiveMode = computed(() => dataMode.value === 'live')
const useCanonicalHistorical = computed(() => !isLiveMode.value)
const canonicalDatasetKind = computed<'continuous' | 'actual_dominant' | undefined>(() => {
  if (!useCanonicalHistorical.value) return undefined
  return isContinuousView.value ? 'continuous' : 'actual_dominant'
})
const chartControlsBusy = computed(
  () => loadingBars.value || loadingMeta.value || loadingDominants.value || loadingIndicators.value,
)
const selectedContract = computed(() => {
  if (!selectedSymbol.value || !selectedActualContract.value) return null
  return resolveContractForView(selectedSymbol.value, selectedActualContract.value, contractView.value)
})
const isContinuousView = computed(() => contractView.value === 'continuous')
const contractViewLabel = computed(() => {
  if (!selectedSymbol.value || !selectedActualContract.value) return '-'
  return isContinuousView.value
    ? `主连研究 ${selectedDominant.value?.continuous_contract || `${selectedSymbol.value}.MAIN`}`
    : `真实主力 ${selectedActualContract.value}`
})
const selectedDominant = computed(() =>
  dominants.value.find((item) => item.product === selectedSymbol.value) || null,
)
const selectedItem = computed(() =>
  coverageItems.value.find(
    (item) => item.symbol === selectedSymbol.value && item.contract === selectedContract.value && item.period === selectedPeriod.value,
  ),
)
const selectedInstrument = computed(() => coverage.value?.instruments.find((item) => item.symbol === selectedSymbol.value))
const selectedContractInfo = computed(() => selectedInstrument.value?.contracts.find((item) => item.contract === selectedContract.value))

const chartPeriodOptions = computed(() => {
  const available = new Set(
    isContinuousView.value
      ? coverageItems.value
          .filter((item) => item.symbol === selectedSymbol.value && item.contract === selectedContract.value)
          .map((item) => item.period)
      : selectedDominant.value
        ? Object.entries(selectedDominant.value.bars_coverage)
            .filter(([, item]) => item.available)
            .map(([period]) => period)
        : selectedContractInfo.value?.periods.map((item) => item.period) || [],
  )
  return CHART_PERIOD_OPTIONS.map((item) => ({
    label: item.label,
    value: item.value,
    disabled:
      chartControlsBusy.value ||
      (available.size > 0 ? !available.has(item.value) : false) ||
      (isLiveMode.value && !isLivePeriodSupported(item.value)),
  }))
})

const latestBar = computed(() => bars.value.at(-1) || null)
const previousBar = computed(() => (bars.value.length >= 2 ? bars.value.at(-2) || null : null))
const matchedSignals = computed(() => latestSignals.value.filter((signal) => signalMatchesCurrentChart(signal)))
const signalMarkers = computed<KlineMarker[]>(() => {
  if (!showSignalLayer.value || isContinuousView.value) return []
  return matchedSignals.value
    .map((signal) => ({
      id: signalMarkerId(signal),
      time: signal.signal_time,
      label: signalMarkerLabel(signal),
      tooltip: signalMarkerTooltip(signal),
      color: signalMarkerColor(signal),
      position: signal.direction === 'long' ? 'belowBar' as const : 'aboveBar' as const,
      shape: 'circle' as const,
    }))
})
const chartMarkers = computed(() => signalMarkers.value)
const priceChange = computed(() => (latestBar.value && previousBar.value ? latestBar.value.close - previousBar.value.close : null))
const priceChangePercent = computed(() => {
  if (!latestBar.value || !previousBar.value || previousBar.value.close === 0) return null
  return ((latestBar.value.close - previousBar.value.close) / previousBar.value.close) * 100
})
const liveQuality = computed(() => (isLiveMode.value ? quality.value as LiveMarketBarsQuality | null : null))

const runtimeObservationContext = computed<MarketRuntimeObservationContext>(() =>
  buildMarketRuntimeObservation({
    data_mode: dataMode.value,
    confirmed_count: isLiveMode.value ? liveQuality.value?.passed_count ?? liveQuality.value?.chart_row_count ?? null : null,
    partial_count: isLiveMode.value ? liveQuality.value?.partial_count ?? null : null,
    chart_row_count: isLiveMode.value ? liveQuality.value?.chart_row_count ?? null : null,
    quality_status: isLiveMode.value
      ? liveQuality.value?.status || null
      : (quality.value as { status?: string } | null)?.status || null,
    profile_id: null,
    active_data_version: isLiveMode.value
      ? null
      : barsCoverage.value?.data_version || selectedItem.value?.data_version || null,
    actual_contract:
      contractView.value === 'actual' ? selectedActualContract.value || selectedContract.value || null : selectedContract.value || null,
  }),
)
const mainIndicatorDefinitions = MAIN_INDICATOR_DEFINITIONS
const mainIndicatorLatestValues = computed(() => latestMainIndicatorValues(mainIndicatorSeries.value, visibleMainIndicators.value))
const visibleMainIndicatorSet = computed(() => new Set(visibleMainIndicators.value))
const mainIndicatorModeContext = computed(() => ({
  dataMode: dataMode.value,
  accessMode: accessMode.value,
}))
const mainIndicatorStatusText = computed(() => {
  if (isLiveMode.value) return LIVE_INDICATOR_CONTEXT_PENDING_MESSAGE
  if (loadingIndicators.value) return '统一 EMA 计算中（前端展示计算 · 非 StrategySignal）'
  if (indicatorError.value) return '统一 EMA 加载失败'
  if (!visibleMainIndicators.value.length) return '主图指标已关闭'
  return '统一 EMA · 前端展示计算 · 非 StrategySignal'
})
const marketQualification = computed(() =>
  buildMarketQualificationPresentation({
    accessMode: accessMode.value,
    strictResearchReady: Boolean(barsLineage.value?.strict_research_ready),
    qualityStatus: barsCoverage.value?.quality_status || quality.value?.status || 'unknown',
    profileId: null,
    canonicalIdentity: useCanonicalHistorical.value,
  }),
)
const crossFileConflictCount = computed(() =>
  'cross_file_conflicts' in (quality.value || {})
    ? (quality.value as MarketBarsQuality).cross_file_conflicts || 0
    : 0,
)
const qualityImpact = computed(() => {
  const historicalQuality =
    !isLiveMode.value && quality.value && 'warning_reasons' in quality.value
      ? quality.value as MarketBarsQuality
      : null
  const warningReasons = [
    ...(historicalQuality?.warning_reasons || []),
    ...(qualityWarningMessage.value ? [qualityWarningMessage.value] : []),
  ]
  const hasHistoricalResponse = Boolean(quality.value || barsCoverage.value || bars.value.length)
  return buildMarketQualityImpact({
    qualityStatus: barsCoverage.value?.quality_status || quality.value?.status || 'unknown',
    warningReasons,
    crossFileConflicts: crossFileConflictCount.value,
    accessMode: accessMode.value,
    profileId: null,
    canonicalIdentity: useCanonicalHistorical.value,
    strictResearchReady: Boolean(barsLineage.value?.strict_research_ready),
    contractView: contractView.value,
    dataMode: dataMode.value,
    lineageReady: isLiveMode.value || !hasHistoricalResponse ? null : Boolean(barsLineage.value),
  })
})
const chartOverlays = computed<ChartOverlay[]>(() => {
  if (!latestBar.value) return []
  const recent = bars.value.slice(-20)
  const high20 = recent.length ? Math.max(...recent.map((bar) => bar.high)) : null
  const low20 = recent.length ? Math.min(...recent.map((bar) => bar.low)) : null
  const overlays: ChartOverlay[] = [
    { id: 'last-close', type: 'price_line', price: latestBar.value.close, label: '最新价', color: chartTheme.up, lineStyle: 'dashed' },
  ]
  if (high20) overlays.push({ id: 'high20', type: 'price_line', price: high20, label: '20高', color: '#ec4899', lineStyle: 'dotted' })
  if (low20) overlays.push({ id: 'low20', type: 'price_line', price: low20, label: '20低', color: chartTheme.down, lineStyle: 'dotted' })
  return overlays
})

function hoverMainIndicatorRows(context: HoverKlineContext | null) {
  return context?.mainIndicators || []
}

const strategyStatus = computed(() => {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) {
    return { label: '等待选择', type: 'default' as const, text: '请选择品种与周期。' }
  }
  if (loadingBars.value || loadingMeta.value || loadingDominants.value) {
    return { label: '加载中', type: 'default' as const, text: '正在加载 K 线数据…' }
  }
  if (!latestBar.value) {
    if (isLiveMode.value && selectedPeriod.value && !isLivePeriodSupported(selectedPeriod.value)) {
      return {
        label: 'Live 不支持',
        type: 'warning' as const,
        text: 'Live 模式仅支持 1m~60m 分钟周期；日/周线请切回历史模式查看。',
      }
    }
    if (dateRange.value) {
      return {
        label: '无数据',
        type: 'warning' as const,
        text: '当前日期范围内没有 K 线，请清空或调整日期窗口后刷新。',
      }
    }
    if (barsCoverage.value?.quality_status === 'failed') {
      return {
        label: '质量未通过',
        type: 'warning' as const,
        text: qualityFailedObservationText(),
      }
    }
    if (selectedDominant.value && !selectedDominant.value.quote_ready && !isLiveMode.value && !isContinuousView.value) {
      return { label: '暂无K线', type: 'warning' as const, text: '该主力合约尚未入库本地 K 线数据。' }
    }
    if (isContinuousView.value && !selectedItem.value && selectedPeriod.value) {
      return {
        label: '主连无数据',
        type: 'warning' as const,
        text: `主连 ${selectedContract.value || '-'} 的 ${selectedPeriod.value} 周期暂无 coverage，请确认数据已登记。`,
      }
    }
    if (!isContinuousView.value && isSyntheticFuturesContract(selectedActualContract.value)) {
      return { label: '合约无效', type: 'warning' as const, text: '当前为主连/合成合约，请使用真实主力合约查看行情。' }
    }
    return {
      label: '等待数据',
      type: 'default' as const,
      text: barsCoverage.value?.row_count
        ? `coverage 有 ${barsCoverage.value.row_count} 行，但当前窗口内无 bar。`
        : '当前选择暂无可展示 K 线。',
    }
  }
  const ema21 = calculateEMA(bars.value, 21).at(-1)?.value
  if (!ema21) {
    return {
      label: '预热中',
      type: 'warning' as const,
      text: 'K 线数量不足，EMA21/MACD 仍在预热（前端展示计算 · 非 StrategySignal）。',
    }
  }
  return buildEmaObservationStatus(latestBar.value.close, ema21)
})

const riskDraft = computed(() => {
  const atr = calculateATR(bars.value, 14).at(-1)?.value
  if (!latestBar.value || !atr) return null
  const accountEquity = 100000
  const riskBudget = accountEquity * 0.01
  return {
    atr,
    riskBudget,
    stopLong: latestBar.value.close - atr,
    stopShort: latestBar.value.close + atr,
  }
})

watch(
  () => ({
    visibleMainIndicators: [...visibleMainIndicators.value],
    period: selectedPeriod.value,
    realtimeFollow: realtimeFollowPreference.value,
  }),
  (preferences) => {
    saveMainChartPreferences({
      version: 1,
      visibleMainIndicators: preferences.visibleMainIndicators,
      period: preferences.period,
      realtimeFollow: preferences.realtimeFollow,
    })
  },
)

watch(
  mainIndicatorModeContext,
  (context) => {
    visibleMainIndicators.value = filterVisibleMainIndicatorsForMode(visibleMainIndicators.value, context)
  },
  { deep: true },
)

watch(
  () => [route.query.review_id, route.query.signal_id, route.query.signal_event_id],
  () => {
    activeRightRailTab.value = resolveMarketRightRailTab({
      preferred: loadMarketRightRailTab(),
      hasSignalContext: Boolean(route.query.signal_id || route.query.signal_event_id),
      hasReviewContext: Boolean(route.query.review_id),
    })
  },
)

function handleRightRailTab(value: MarketRightRailTab) {
  activeRightRailTab.value = value
  saveMarketRightRailTab(value)
}

function focusQualityCard() {
  qualityCardRef.value?.focus()
}

async function handleQualityAction(action: MarketQualityAction) {
  if (action === 'evidence') {
    evidenceDrawerOpen.value = true
    return
  }
  if (action === 'actual') {
    handleContractViewUpdate('actual')
    return
  }
  focusQualityCard()
}

// Reload backend EMA series when standard overlay selection changes.
// Skip the first run so initial loadBars() remains the sole first fetch.
// Pure HTDY toggles do not change activeIndicatorCodes and will not hit the API.
watch(
  () => activeIndicatorCodes(visibleMainIndicators.value).join(','),
  (codes, previousCodes) => {
    if (previousCodes === undefined) return
    if (codes === previousCodes) return
    if (!bars.value.length) return
    void loadMarketIndicators()
  },
)

onMounted(() => {
  document.addEventListener('visibilitychange', handleLiveVisibilityChange)
  // 缺少 symbol 时回列表页；actual contract 可由既有 dominant resolver 解析。
  if (!route.query.symbol) {
    void router.replace({ name: 'market' })
    return
  }
  void initializeChartPage().finally(syncLiveRefreshTimer)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleLiveVisibilityChange)
  stopLiveRefreshTimer()
  if (viewportLoadTimer) clearTimeout(viewportLoadTimer)
})

watch(
  [isLiveMode, selectedSymbol, selectedContract, selectedPeriod],
  syncLiveRefreshTimer,
  { flush: 'post' },
)

/** 页面初始化：并行拉元数据，按 route 选定品种并 loadBars。 */
async function initializeChartPage() {
  const requestId = ++marketRouteRequestId
  applyRouteSelectionFromQueryToState()
  viewportLoadEnabled.value = false
  const results = await Promise.allSettled([loadDominants(), loadScopedCoverage()])
  if (!isCurrentMarketRoute(requestId)) return
  const dominantsResult = results[0]
  if (dominantsResult.status === 'fulfilled' && !selectionMatchesRoute()) {
    applyInitialSelection()
  }
  await loadBars(requestId)
}

/** 将 route.query 解析为 chart 选中状态（symbol/contract/period/view 等）。 */
function applyRouteSelectionFromQueryToState() {
  const selection = applyRouteSelectionFromQuery({
    symbol: stringQuery(route.query.symbol),
    product: stringQuery(route.query.product),
    contract: stringQuery(route.query.contract),
    period: stringQuery(route.query.period),
    interval: stringQuery(route.query.interval),
    contract_view: stringQuery(route.query.contract_view),
  })
  accessMode.value = route.query.access_mode === 'research' ? 'research' : 'browser'
  if (!selection) return
  selectedSymbol.value = selection.selectedSymbol
  selectedActualContract.value = selection.selectedActualContract
  selectedPeriod.value = selection.selectedPeriod
  contractView.value = selection.contractView
}

function currentCoverageScope() {
  return scopedCoverageParams({
    symbol: selectedSymbol.value || stringQuery(route.query.symbol) || stringQuery(route.query.product),
    product: stringQuery(route.query.product),
    contract: selectedActualContract.value || stringQuery(route.query.contract),
    period: selectedPeriod.value || queryPeriod(),
    contract_view: contractView.value,
    access_mode: accessMode.value,
  })
}

async function loadLatestSignals(requestId = marketRouteRequestId) {
  if (!selectedSymbol.value || !selectedActualContract.value || !selectedPeriod.value) {
    latestSignals.value = []
    return
  }
  const contractKey = 'actual_contract'
  try {
    const page = await getLatestStrategySignals({
      product: selectedSymbol.value,
      [contractKey]: selectedActualContract.value,
      period: selectedPeriod.value,
      provider: 'rqdata',
      data_role: 'primary',
      limit: 50,
    })
    if (isCurrentMarketRoute(requestId)) {
      latestSignals.value = page.items
      if (selectedSignalId.value && !page.items.some((signal) => signal.id === selectedSignalId.value)) clearSignalSelection()
    }
  } catch {
    if (isCurrentMarketRoute(requestId)) {
      latestSignals.value = []
      clearSignalSelection()
    }
  }
}

async function loadDominants() {
  loadingDominants.value = true
  try {
    const response = await getMarketDominants()
    dominants.value = response.items
  } catch (err) {
    message.warning(safeMarketApiError(err, '加载主力合约列表失败'))
    dominants.value = []
  } finally {
    loadingDominants.value = false
  }
}

watch(
  () => [
    route.query.symbol,
    route.query.contract,
    route.query.period,
    route.query.interval,
    route.query.contract_view,
    route.query.access_mode,
    route.query.data_mode,
    route.query.time,
    route.query.datetime,
  ],
  () => {
    if (syncingQueryFromState) return
    const nextMode = route.query.data_mode === 'live' ? 'live' : 'historical'
    if (nextMode !== dataMode.value) {
      dataMode.value = nextMode
      void reloadChartPage()
      return
    }
    if (selectionMatchesRoute()) return
    const requestId = ++marketRouteRequestId
    applyRouteSelectionFromQueryToState()
    void loadScopedCoverage()
    void applyRouteSelectionAndLoad(requestId)
  },
)

async function reloadChartPage() {
  const requestId = ++marketRouteRequestId
  applyRouteSelectionFromQueryToState()
  viewportLoadEnabled.value = false
  await Promise.allSettled([loadDominants(), loadScopedCoverage()])
  await applyRouteSelectionAndLoad(requestId)
}

async function loadScopedCoverage() {
  loadingMeta.value = true
  metaWarning.value = null
  try {
    const params = currentCoverageScope()
    coverage.value = isLiveMode.value
      ? await getLiveMarketCoverage(params)
      : useCanonicalHistorical.value
        ? await getCanonicalMarketCoverage(selectedSymbol.value || 'jm')
        : await getMarketWorkbenchCoverage(params)
    syncDateRangeForSelection()
  } catch (err) {
    metaWarning.value = safeMarketApiError(err, '加载行情工作台元数据失败')
    coverage.value = null
  } finally {
    loadingMeta.value = false
  }
}

async function applyRouteSelectionAndLoad(requestId = ++marketRouteRequestId) {
  viewportLoadEnabled.value = false
  if (!selectionMatchesRoute()) applyInitialSelection()
  await loadBars(requestId)
}

/**
 * 核心 K 线加载：支持 viewport 合并、Live 增量、lineage 冲突 fail-closed；
 * 成功后联动指标与信号 marker 定位。
 */
async function loadBars(requestId = marketRouteRequestId, options: LoadBarsOptions = {}) {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) {
    bars.value = []
    clearMarketMacd()
    return
  }
  loadingBars.value = true
  barsError.value = null
  if (!options.merge) clearMarketMacd()
  try {
    const historicalParams = options.liveRefresh
      ? buildLiveRefreshBarsRequest()
      : buildBarsRequest(options.viewportWindow)
    if (!historicalParams) {
      bars.value = []
      clearMarketMacd()
      return
    }
    const response = isLiveMode.value
      ? await getLiveMarketBars({
          symbol: selectedSymbol.value,
          contract: selectedContract.value!,
          period: selectedPeriod.value,
          provider: selectedItem.value?.provider,
          source_mode: selectedItem.value?.source_mode,
          start: historicalParams.start,
          end: historicalParams.end,
          limit: historicalParams.limit,
        })
      : await getMarketBars(historicalParams)
    if (!isCurrentMarketRoute(requestId)) return
    const responseLineage = 'lineage' in response ? response.lineage : null
    if (options.merge) {
      if (barsLineage.value && responseLineage && responseLineage.lineage_token !== barsLineage.value.lineage_token) {
        throw new BarMergeConflictError([{ key: 'lineage', period: selectedPeriod.value, fields: ['lineage_token'] }])
      }
      const centerMs =
        options.visibleCenterMs ??
        (options.viewportWindow
          ? (options.viewportWindow.startMs + options.viewportWindow.endMs) / 2
          : Date.now())
      bars.value = dedupeBarsByPeriod(
        trimBarsToMaxCount(
          mergeBarsByTime(bars.value, response.bars, selectedPeriod.value),
          MAX_BARS_PER_REQUEST,
          centerMs,
          selectedPeriod.value,
        ),
        selectedPeriod.value,
      )
      chartFitContent.value = false
    } else {
      bars.value = dedupeBarsByPeriod(response.bars, selectedPeriod.value)
      chartFitContent.value = options.fitContent ?? barsLoadMode.value === 'explicit'
    }
    if (responseLineage) barsLineage.value = responseLineage
    quality.value = response.quality
    barsCoverage.value = response.coverage || null
    const crossFileConflictCount = 'cross_file_conflicts' in response.quality
      ? response.quality.cross_file_conflicts || 0
      : 0
    qualityWarningMessage.value =
      !isLiveMode.value && (response.quality?.status === 'warning' || crossFileConflictCount > 0)
        ? response.message || '数据质量 warning，仅供观察，不可用于严格研究/回测/信号'
        : null
    if (!options.merge) {
      await loadMarketIndicators(requestId)
      if (!isLiveMode.value && bars.value.length > 0) {
        const macdParams = buildMacdRequestParams()
        if (macdParams) await loadMarketMacdIndicator(requestId, macdParams)
      }
    }
    hoverContext.value = bars.value.at(-1)
      ? {
          time: bars.value.at(-1)!.time,
          bar: bars.value.at(-1)!,
        }
      : null
    if (!options.merge) {
      syncQuery()
      await loadLatestSignals(requestId)
      await restoreSignalEventFromRoute(requestId)
    }
    if (response.bars.length === 0 && !options.merge) {
      message.warning(response.message || '当前选择没有可展示的 K 线')
    }
    if (!dateRange.value && response.coverage?.start_time && response.coverage?.end_time) {
      syncDateRangeFromTimes(selectedPeriod.value, response.coverage.start_time, response.coverage.end_time)
    }
    if (!options.merge) viewportLoadEnabled.value = true
  } catch (err) {
    if (!isCurrentMarketRoute(requestId)) return
    barsError.value = err instanceof BarMergeConflictError
      ? '检测到同一 K 线键存在不同 OHLCV 或 lineage，已拒绝覆盖原图，请刷新并检查资产证据。'
      : safeMarketApiError(err, 'K 线加载失败')
    if (!options.merge) {
      bars.value = []
      mainIndicatorSeries.value = []
      quality.value = null
      barsCoverage.value = null
      barsLineage.value = null
      qualityWarningMessage.value = null
      clearMarketMacd()
      latestSignals.value = []
    }
  } finally {
    if (isCurrentMarketRoute(requestId)) loadingBars.value = false
  }
}

async function restoreSignalEventFromRoute(requestId: number) {
  const eventId = numericQuery(route.query.signal_event_id)
  if (!eventId) return
  try {
    const event = await getSignalEvent(eventId)
    if (!isCurrentMarketRoute(requestId)) return
    const eventMode = signalSourceDataMode(event.source_mode)
    if (eventMode !== dataMode.value) {
      selectedSignalEvent.value = null
      notificationError.value = `事件 #${event.id} 属于 ${eventMode}，与当前 ${dataMode.value} 模式隔离。`
      return
    }
    selectedSignalEvent.value = event
    selectedSignalId.value = event.signal_id || numericQuery(route.query.signal_id)
  } catch (err) {
    if (!isCurrentMarketRoute(requestId)) return
    selectedSignalEvent.value = null
    notificationError.value = safeMarketApiError(err, '恢复信号事件失败')
  }
}

function openReviewFromChart() {
  const context = parseResearchContext(route.query as Record<string, string | string[] | null | undefined>)
  const exactReturnRoute = context.reviewId ? safeReturnRoute(context.returnRoute) : null
  if (exactReturnRoute) {
    void router.push(exactReturnRoute)
    return
  }
  void router.push({ name: 'review', query: buildReviewResearchQuery(context) })
}

function stopLiveRefreshTimer() {
  if (!liveRefreshTimer) return
  clearInterval(liveRefreshTimer)
  liveRefreshTimer = null
}

/** Live 模式：页面可见时每 20s merge 增量 bar；hidden 时停表，恢复可见时立即补一次。 */
function syncLiveRefreshTimer() {
  stopLiveRefreshTimer()
  if (!isLiveMode.value || !selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return
  if (document.visibilityState !== 'visible') return
  liveRefreshTimer = setInterval(() => {
    void refreshLiveBars()
  }, LIVE_REFRESH_INTERVAL_MS)
}

async function refreshLiveBars() {
  if (!isLiveMode.value || document.visibilityState !== 'visible' || loadingBars.value || liveRefreshInFlight) return
  liveRefreshInFlight = true
  const requestId = ++marketRouteRequestId
  try {
    await loadBars(requestId, { merge: true, liveRefresh: true, fitContent: false })
  } finally {
    liveRefreshInFlight = false
  }
}

function handleLiveVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    stopLiveRefreshTimer()
    return
  }
  syncLiveRefreshTimer()
  void refreshLiveBars()
}

function buildBarsRequest(viewportWindow?: ViewportLoadRequest): MarketBarsRequestParams | null {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return null
  const isContinuousRequest = isContinuousView.value
  const base = {
    dataset_kind: canonicalDatasetKind.value,
    symbol: selectedSymbol.value,
    contract: selectedContract.value,
    period: selectedPeriod.value,
    provider: selectedItem.value?.provider,
    data_role: selectedItem.value?.data_role,
    access_mode: accessMode.value,
    quote_mode: !isContinuousRequest,
    allow_continuous: isContinuousRequest,
  }
  if (viewportWindow) {
    return {
      ...base,
      start: formatBarsRequestTime(viewportWindow.startMs),
      end: formatBarsRequestTime(viewportWindow.endMs),
      tail: false,
      limit: MAX_BARS_PER_REQUEST,
    }
  }
  if (barsLoadMode.value === 'explicit' && dateRange.value) {
    return {
      ...base,
      start: formatBarsRequestTime(dateRange.value[0]),
      end: formatBarsRequestTime(dateRange.value[1]),
      tail: false,
      limit: MAX_BARS_PER_REQUEST,
    }
  }
  const initial = resolveInitialBarsQuery(currentSelectionCoverageItem())
  if (initial) {
    return {
      ...base,
      start: formatBarsRequestTime(initial.startMs),
      end: formatBarsRequestTime(initial.endMs),
      tail: initial.tail,
      limit: initial.limit,
    }
  }
  return {
    ...base,
    start: dateRange.value ? formatBarsRequestTime(dateRange.value[0]) : undefined,
    end: dateRange.value ? formatBarsRequestTime(dateRange.value[1]) : undefined,
    tail: true,
    limit: MAX_BARS_PER_REQUEST,
  }
}

function buildLiveRefreshBarsRequest(): MarketBarsRequestParams | null {
  const base = buildBarsRequest()
  if (!base) return null
  return {
    ...base,
    start: resolveLiveRefreshStart(bars.value, selectedPeriod.value),
    end: undefined,
    tail: false,
    limit: MAX_BARS_PER_REQUEST,
  }
}

function buildMacdRequestParams(): MarketBarsRequestParams | null {
  const extent = barsTimeExtent(bars.value, selectedPeriod.value)
  if (!extent || !selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) {
    return buildBarsRequest()
  }
  const isContinuousRequest = isContinuousView.value
  return {
    dataset_kind: canonicalDatasetKind.value,
    symbol: selectedSymbol.value,
    contract: selectedContract.value,
    period: selectedPeriod.value,
    provider: selectedItem.value?.provider,
    data_role: selectedItem.value?.data_role,
    access_mode: accessMode.value,
    start: formatBarsRequestTime(extent.startMs),
    end: formatBarsRequestTime(extent.endMs),
    quote_mode: !isContinuousRequest,
    allow_continuous: isContinuousRequest,
    tail: false,
    limit: Math.min(MAX_BARS_PER_REQUEST, bars.value.length),
  }
}

function currentSelectionCoverageItem(): MarketCoverageItem | null {
  return (
    findCoverageItem(selectedSymbol.value, selectedContract.value, selectedPeriod.value) ||
    findCoverageItem(selectedSymbol.value, selectedActualContract.value, selectedPeriod.value) ||
    dominantCoverageItem(selectedSymbol.value, selectedActualContract.value, selectedPeriod.value)
  )
}

/** 视口滚动接近边界时 debounce 触发 viewport 懒加载。 */
function handleVisibleRangeChange(payload: { fromMs: number; toMs: number }) {
  if (!viewportLoadEnabled.value || barsLoadMode.value !== 'viewport' || loadingBars.value) return
  if (viewportLoadTimer) clearTimeout(viewportLoadTimer)
  viewportLoadTimer = setTimeout(() => {
    void maybeLoadViewportBars(payload)
  }, 300)
}

async function maybeLoadViewportBars(payload: { fromMs: number; toMs: number }) {
  const extent = barsTimeExtent(bars.value, selectedPeriod.value)
  if (!extent) return
  const coverageItem = currentSelectionCoverageItem()
  if (!coverageItem?.start_time || !coverageItem?.end_time) return
  const request = computeViewportLoadRequest({
    visibleFromMs: payload.fromMs,
    visibleToMs: payload.toMs,
    loadedStartMs: extent.startMs,
    loadedEndMs: extent.endMs,
    coverageStartMs: barTimeMs(coverageItem.start_time),
    coverageEndMs: barTimeMs(coverageItem.end_time),
  })
  if (!request) return
  await loadBars(marketRouteRequestId, {
    viewportWindow: request,
    merge: true,
    fitContent: false,
    visibleCenterMs: (payload.fromMs + payload.toMs) / 2,
  })
}

async function loadMarketIndicators(requestId = marketRouteRequestId) {
  indicatorError.value = null
  if (isLiveMode.value) {
    mainIndicatorSeries.value = []
    return
  }
  const isContinuousRequest = isContinuousView.value
  const params = buildMainIndicatorRequestParams({
    datasetKind: canonicalDatasetKind.value,
    symbol: selectedSymbol.value,
    contract: selectedContract.value,
    period: selectedPeriod.value,
    bars: bars.value,
    visibleIds: visibleMainIndicators.value,
    provider: selectedItem.value?.provider,
    dataRole: selectedItem.value?.data_role,
    accessMode: accessMode.value,
    expectedMarketDataFileId: null,
    expectedLineageToken: null,
    quoteMode: !isContinuousRequest,
    allowContinuous: isContinuousRequest,
  })
  if (!params) {
    mainIndicatorSeries.value = []
    return
  }
  loadingIndicators.value = true
  try {
    const response = await getMarketIndicators(params)
    if (!isCurrentMarketRoute(requestId)) return
    if (!barsLineage.value || response.lineage.lineage_token !== barsLineage.value.lineage_token) {
      throw new Error('MARKET_LINEAGE_CHANGED: EMA 与 bars lineage 不一致')
    }
    mainIndicatorSeries.value = normalizeMainIndicatorSeries(response.indicators)
  } catch (err) {
    if (!isCurrentMarketRoute(requestId)) return
    indicatorError.value = safeMarketApiError(err, '统一 EMA 指标加载失败')
    mainIndicatorSeries.value = []
  } finally {
    if (isCurrentMarketRoute(requestId)) loadingIndicators.value = false
  }
}

async function loadMarketMacdIndicator(requestId: number, params: MarketBarsRequestParams) {
  const token = ++macdRequestId
  macdError.value = null
  try {
    const response = await getMarketMacdIndicator(params)
    if (!isCurrentMarketRoute(requestId) || token !== macdRequestId) return
    if (!barsLineage.value || response.lineage.lineage_token !== barsLineage.value.lineage_token) {
      throw new Error('MARKET_LINEAGE_CHANGED: MACD 与 bars lineage 不一致')
    }
    macdOverride.value = response
  } catch (err) {
    if (!isCurrentMarketRoute(requestId) || token !== macdRequestId) return
    macdOverride.value = null
    macdError.value = safeMarketApiError(err, 'MACD 后端指标加载失败，已回退前端展示计算')
  }
}

function clearMarketMacd() {
  macdRequestId += 1
  macdOverride.value = null
  macdError.value = null
}

function handleDataModeUpdate(value: MarketDataMode) {
  if (chartControlsBusy.value) return
  if (value === dataMode.value) return
  marketRouteRequestId += 1
  clearSignalSelection()
  barsLoadMode.value = 'viewport'
  chartFitContent.value = true
  dataMode.value = value
  barsLineage.value = null
  barsError.value = null
  indicatorError.value = null
  metaWarning.value = null
  qualityWarningMessage.value = null
  if (value === 'live') {
    accessMode.value = 'browser'
  }
  if (value === 'live' && selectedPeriod.value && !isLivePeriodSupported(selectedPeriod.value)) {
    const fallback = chartPeriodOptions.value.find((item) => !item.disabled)?.value || '15m'
    selectedPeriod.value = fallback
    contractView.value = 'actual'
  }
  if (value === 'historical') {
    dateRange.value = null
  }
  coverage.value = null
  bars.value = []
  quality.value = null
  barsCoverage.value = null
  mainIndicatorSeries.value = []
  clearMarketMacd()
  void syncQuery().then(() => reloadChartPage())
}

function handleAccessModeUpdate(value: MarketAccessMode) {
  if (chartControlsBusy.value) return
  if (value === accessMode.value) return
  marketRouteRequestId += 1
  accessMode.value = value
  barsLineage.value = null
  if (value === 'research' && isLiveMode.value) dataMode.value = 'historical'
  coverage.value = null
  bars.value = []
  mainIndicatorSeries.value = []
  void syncQuery().then(() => reloadChartPage())
}

function applyInitialSelection() {
  const routeProduct = stringQuery(route.query.symbol) || stringQuery(route.query.product)
  const routeContract = resolveActualContract(routeProduct, stringQuery(route.query.contract), dominants.value)
  const routeDominant = routeProduct
    ? dominants.value.find(
        (item) =>
          item.product === routeProduct &&
          (!routeContract || item.actual_contract === routeContract),
      )
    : null
  const preferred = routeDominant || dominants.value.find((item) => item.quote_ready) || dominants.value[0]
  if (preferred) {
    applyDominantSelection(preferred, queryPeriod() || preferred.default_period)
    if (routeContract && preferred.actual_contract !== routeContract) {
      selectedActualContract.value = preferred.actual_contract
    }
    return
  }

  const querySelection = findCoverageItem(routeProduct, routeContract, queryPeriod())
  const defaults = coverage.value?.default_selection
  const fallback = defaults ? findCoverageItem(defaults.symbol, defaults.contract, defaults.period) : coverageItems.value[0]
  const selected = querySelection || fallback
  if (!selected) return
  selectedSymbol.value = selected.symbol
  selectedActualContract.value = resolveActualContract(selected.symbol, selected.contract, dominants.value)
  contractView.value = defaultContractViewForPeriod(selected.period)
  selectedPeriod.value = selected.period
  syncDateRange(selected)
}

function applyDominantSelection(item: DominantContractItem, period?: string | null) {
  barsLineage.value = null
  selectedSymbol.value = item.product
  selectedActualContract.value = item.actual_contract
  const actualAvailablePeriods = Object.entries(item.bars_coverage)
    .filter(([, coverageItem]) => coverageItem.available)
    .map(([name]) => name)
  const continuousAvailablePeriods = coverageItems.value
    .filter((row) => row.symbol === item.product && row.contract === continuousContractFor(item.product))
    .map((row) => row.period)
  const allAvailablePeriods = [...new Set([...actualAvailablePeriods, ...continuousAvailablePeriods])]
  const resolvedPeriod =
    (period && allAvailablePeriods.includes(period) ? period : null) ||
    (allAvailablePeriods.includes(item.default_period) ? item.default_period : null) ||
    allAvailablePeriods[0] ||
    item.default_period
  selectedPeriod.value = resolvedPeriod
  const routeView = stringQuery(route.query.contract_view)
  contractView.value =
    routeView === 'continuous' || routeView === 'actual'
      ? routeView
      : defaultContractViewForPeriod(resolvedPeriod)
  syncDateRangeForSelection(resolvedPeriod)
}

function syncDateRangeForSelection(period?: string | null) {
  const targetPeriod = period || selectedPeriod.value
  if (!targetPeriod) return
  const chartContractValue = selectedContract.value
  const coverageItem =
    findCoverageItem(selectedSymbol.value, chartContractValue, targetPeriod) ||
    findCoverageItem(selectedSymbol.value, selectedActualContract.value, targetPeriod) ||
    dominantCoverageItem(selectedSymbol.value, selectedActualContract.value, targetPeriod)
  syncDateRange(coverageItem)
}

function dominantCoverageItem(symbol?: string | null, contract?: string | null, period?: string | null) {
  if (!symbol || !contract || !period || !selectedDominant.value) return null
  const dominant = selectedDominant.value.product === symbol ? selectedDominant.value : dominants.value.find((item) => item.product === symbol)
  const periodCoverage = dominant?.bars_coverage?.[period]
  if (!periodCoverage?.available || !periodCoverage.start_time || !periodCoverage.end_time) return null
  return {
    symbol,
    contract,
    period,
    start_time: periodCoverage.start_time,
    end_time: periodCoverage.end_time,
  } as MarketCoverageItem
}

function syncDateRangeFromTimes(_period: string | null | undefined, startTime: string, endTime: string) {
  const end = new Date(endTime).getTime()
  const start = new Date(startTime).getTime()
  if (Number.isNaN(end) || Number.isNaN(start)) return
  dateRange.value = fullCoverageDateRangeMs(start, end)
}

function handleContractViewUpdate(value: ContractViewMode) {
  if (chartControlsBusy.value) return
  if (value === contractView.value) return
  marketRouteRequestId += 1
  clearSignalSelection()
  barsLoadMode.value = 'viewport'
  chartFitContent.value = true
  viewportLoadEnabled.value = false
  barsLineage.value = null
  contractView.value = value
  syncDateRangeForSelection()
  void loadBars()
}

function handlePeriodUpdate(value: string) {
  if (chartControlsBusy.value) return
  if (!value || value === selectedPeriod.value) return
  marketRouteRequestId += 1
  clearSignalSelection()
  barsLoadMode.value = 'viewport'
  chartFitContent.value = true
  viewportLoadEnabled.value = false
  barsLineage.value = null
  selectedPeriod.value = value
  contractView.value = defaultContractViewForPeriod(value)
  syncDateRangeForSelection(value)
  void loadBars()
}

function goBackToList() {
  void router.push({ name: 'market' })
}

function refreshBars() {
  marketRouteRequestId += 1
  barsLoadMode.value = 'explicit'
  chartFitContent.value = true
  viewportLoadEnabled.value = false
  barsLineage.value = null
  void loadBars(marketRouteRequestId, { fitContent: true })
}

function isMainIndicatorVisible(id: MainIndicatorId) {
  return visibleMainIndicatorSet.value.has(id)
}

function mainIndicatorCurrentValue(id: MainIndicatorId) {
  return mainIndicatorLatestValues.value.find((item) => item.id === id)?.value ?? null
}

function mainIndicatorAllowed(definition: MainIndicatorDefinition) {
  return isMainIndicatorAllowed(definition, mainIndicatorModeContext.value)
}

function mainIndicatorDisabledReason(definition: MainIndicatorDefinition) {
  if (!definition.available) return definition.unavailableReason || '当前不可用'
  if (!mainIndicatorAllowed(definition)) {
    if (definition.id === 'htdy') return '仅 historical/browser 人工观察'
    return '当前模式不可用'
  }
  if (definition.capability === 'observation_overlay') return '前端观察层 · 可勾选'
  return `lookback ${definition.lookbackBars}`
}

function setMainIndicatorVisible(definition: MainIndicatorDefinition, checked: boolean) {
  if (!mainIndicatorAllowed(definition)) return
  const existing = new Set(visibleMainIndicators.value)
  if (checked) {
    existing.add(definition.id)
  } else {
    existing.delete(definition.id)
  }
  visibleMainIndicators.value = MAIN_INDICATOR_DEFINITIONS
    .filter((item) => existing.has(item.id) && mainIndicatorAllowed(item))
    .map((item) => item.id)
}

function enableTrendEmaIndicators() {
  const existing = new Set(visibleMainIndicators.value)
  TREND_EMA_INDICATORS.forEach((id) => existing.add(id))
  visibleMainIndicators.value = MAIN_INDICATOR_DEFINITIONS
    .filter((item) => existing.has(item.id) && mainIndicatorAllowed(item))
    .map((item) => item.id)
}

async function handleMarkerClick(marker: KlineMarker) {
  const signalId = signalIdFromMarkerId(marker.id)
  if (!signalId) return
  const signal = matchedSignals.value.find((item) => item.id === signalId)
  if (!signal) return
  await selectSignal(signal, marker.id)
}

async function selectSignalFromList(signal: StrategySignalRecord) {
  await selectSignal(signal, signalMarkerId(signal))
  await nextTick()
  klineChartRef.value?.focusTime(nearestBarTime(signal.signal_time))
}

/** 选中信号 marker 后拉 signal_events 与企业微信通知状态（只读）。 */
async function selectSignal(signal: StrategySignalRecord, markerIdValue = signalMarkerId(signal)) {
  handleRightRailTab('signal')
  activeMarkerId.value = markerIdValue
  selectedSignalId.value = signal.id
  selectedSignalEvent.value = null
  selectedNotification.value = null
  notificationError.value = null
  loadingNotification.value = true
  const requestId = ++signalSelectionRequestId
  try {
    const events = await getSignalEvents(signal.id)
    if (requestId !== signalSelectionRequestId) return
    const event = selectSignalEventForChart(events, signal, {
      product: selectedSymbol.value,
      contract: selectedActualContract.value,
      period: selectedPeriod.value,
    })
    selectedSignalEvent.value = event
    if (!event) {
      notificationError.value = '未找到关联 signal_events。'
      return
    }
    try {
      selectedNotification.value = await getStage9WechatNotification(event.id)
      notificationError.value = null
    } catch (err) {
      selectedNotification.value = null
      notificationError.value = isNotFoundApiError(err) ? '尚无企业微信通知记录。' : safeMarketApiError(err, '加载企业微信通知状态失败')
    }
  } catch (err) {
    if (requestId !== signalSelectionRequestId) return
    selectedSignalEvent.value = null
    selectedNotification.value = null
    notificationError.value = safeMarketApiError(err, '加载信号事件失败')
  } finally {
    if (requestId === signalSelectionRequestId) loadingNotification.value = false
  }
}

function clearSignalSelection() {
  signalSelectionRequestId += 1
  selectedSignalId.value = null
  selectedSignalEvent.value = null
  selectedNotification.value = null
  loadingNotification.value = false
  notificationError.value = null
  if (activeMarkerId.value?.startsWith('signal-')) activeMarkerId.value = null
}

function syncDateRange(item: MarketCoverageItem | null | undefined) {
  if (!item?.end_time || !item.start_time) {
    dateRange.value = null
    return
  }
  const end = new Date(item.end_time).getTime()
  const start = new Date(item.start_time).getTime()
  dateRange.value = fullCoverageDateRangeMs(start, end)
}

function findCoverageItem(symbol?: string | null, contract?: string | null, period?: string | null) {
  if (!symbol || !contract || !period) return null
  return coverageItems.value.find((item) => item.symbol === symbol && item.contract === contract && item.period === period) || null
}

function queryPeriod() {
  return stringQuery(route.query.period) || stringQuery(route.query.interval)
}

function selectionMatchesRoute() {
  const routeProduct = stringQuery(route.query.symbol) || stringQuery(route.query.product)
  const routeContract = resolveActualContract(routeProduct, stringQuery(route.query.contract), dominants.value)
  const routeView = stringQuery(route.query.contract_view)
  return (
    routeProduct === selectedSymbol.value &&
    routeContract === selectedActualContract.value &&
    (route.query.access_mode === 'research' ? 'research' : 'browser') === accessMode.value &&
    (route.query.data_mode === 'live' ? 'live' : 'historical') === dataMode.value &&
    (routeView === contractView.value || (!routeView && contractView.value === defaultContractViewForPeriod(selectedPeriod.value || ''))) &&
    queryPeriod() === selectedPeriod.value
  )
}

function signalMatchesCurrentChart(signal: StrategySignalRecord) {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return false
  const product = signal.product || signal.symbol
  const period = signal.entry_interval || signal.interval || signal.period
  const contract = signal.actual_contract || signal.contract
  return product === selectedSymbol.value && contract === selectedActualContract.value && period === selectedPeriod.value
}

function signalMarkerLabel(signal: StrategySignalRecord) {
  const side = signal.direction === 'long' ? '多' : signal.direction === 'short' ? '空' : '观'
  return `${side}${signal.score_bucket || ''}`
}

function signalMarkerTooltip(signal: StrategySignalRecord) {
  const version = signal.strategy_version_id || signal.strategy_version || '-'
  const price = signal.signal_price ?? signal.price ?? signal.current_price
  return `${signal.strategy_code || signal.strategy_id} ${version} ${signal.period} ${signal.strategy_status} @ ${formatNumber(price)}`
}

function signalMarkerColor(signal: StrategySignalRecord) {
  if (signal.direction === 'long') return chartTheme.up
  if (signal.direction === 'short') return chartTheme.down
  return chartTheme.textMuted
}

function nearestBarTime(value: string) {
  if (!bars.value.length) return value
  const target = exchangeLocalTimeMs(value)
  if (!Number.isFinite(target)) return value
  let nearest = bars.value[0].time
  let distance = Math.abs(exchangeLocalTimeMs(nearest) - target)
  for (const bar of bars.value.slice(1)) {
    const current = exchangeLocalTimeMs(bar.time)
    if (!Number.isFinite(current)) continue
    const currentDistance = Math.abs(current - target)
    if (currentDistance < distance) {
      nearest = bar.time
      distance = currentDistance
    }
  }
  return nearest
}

function exchangeLocalTimeMs(value: string) {
  return new Date(String(value).replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')).getTime()
}

/** 将当前选中状态写回 URL（避免 watch 循环用 syncingQueryFromState 守卫）。 */
function syncQuery(): Promise<void> {
  if (!selectedSymbol.value || !selectedActualContract.value || !selectedPeriod.value) return Promise.resolve()
  syncingQueryFromState = true
  return router.replace({
    name: 'market-chart',
    query: buildMarketChartRouteQuery(
      {
        symbol: selectedSymbol.value,
        actualContract: selectedActualContract.value,
        period: selectedPeriod.value,
        contractView: contractView.value,
        accessMode: accessMode.value,
        dataMode: dataMode.value,
      },
      {
        strategy: stringQuery(route.query.strategy),
        time: stringQuery(route.query.time),
        datetime: stringQuery(route.query.datetime),
        signal_layer: stringQuery(route.query.signal_layer),
        signal_id: stringQuery(route.query.signal_id),
        signal_event_id: stringQuery(route.query.signal_event_id),
        review_id: stringQuery(route.query.review_id),
        return_route: stringQuery(route.query.return_route),
      },
    ),
  })
    .then(() => undefined)
    .finally(() => {
      syncingQueryFromState = false
    })
}

function isCurrentMarketRoute(requestId: number) {
  return requestId === marketRouteRequestId
}

function stringQuery(value: unknown) {
  return typeof value === 'string' ? value : null
}

function numericQuery(value: unknown) {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null
}

function formatDate(value: number) {
  const item = new Date(value)
  const year = item.getFullYear()
  const month = String(item.getMonth() + 1).padStart(2, '0')
  const day = String(item.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatBarsRequestTime(value: number) {
  return useCanonicalHistorical.value
    ? new Date(value).toISOString()
    : formatDate(value)
}

function qualityType(status: string | null | undefined) {
  if (status === 'passed') return 'success'
  if (status === 'warning') return 'warning'
  if (status === 'failed') return 'error'
  return 'default'
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function isNotFoundApiError(err: unknown) {
  return Boolean(
    typeof err === 'object' &&
      err !== null &&
      'response' in err &&
      (err as { response?: { status?: number } }).response?.status === 404,
  )
}
</script>

<template>
  <div class="market-chart-workbench">
    <main class="center-stage">
      <section class="chart-header">
        <MarketContextBar
          :title="selectedDominant?.product_name || selectedContractInfo?.name || selectedSymbol || '-'"
          :subtitle="`${contractViewLabel} · ${selectedDominant?.exchange_name || selectedDominant?.exchange || selectedContractInfo?.exchange || '-'}`"
          :busy="chartControlsBusy"
          :is-live-mode="isLiveMode"
          :contract-view="contractView"
          :data-mode="dataMode"
          :access-mode="accessMode"
          @back="goBackToList"
          @update:contract-view="handleContractViewUpdate"
          @update:data-mode="handleDataModeUpdate"
          @update:access-mode="handleAccessModeUpdate"
        />
        <div class="chart-header__secondary">
          <MarketEvidenceStrip
            :access-mode="accessMode"
            :quality-status="barsCoverage?.quality_status || quality?.status || 'unknown'"
            :strict-research-ready="Boolean(barsLineage?.strict_research_ready)"
            :data-version="barsCoverage?.data_version || selectedItem?.data_version || '无 data_version'"
            :data-versions="barsLineage?.data_versions || []"
            :asset-count="barsLineage?.asset_evidence?.length || barsLineage?.market_data_file_ids?.length || 0"
            :latest-time="barsCoverage?.latest_bar_time || selectedItem?.latest_bar_time || latestBar?.time || '-'"
            :period="selectedPeriod || '-'"
            :profile-id="null"
            profile-label="Canonical DatasetKey"
            @evidence="evidenceDrawerOpen = true"
          />
          <div class="chart-header__actions">
            <div class="chart-control-group" aria-label="指标与图层">
              <span class="chart-control-group__label">图层</span>
              <NPopover trigger="click" placement="bottom-end" :show-arrow="false">
              <template #trigger>
                <NButton size="small" :disabled="chartControlsBusy">
                  主图指标 {{ visibleMainIndicators.length }}
                </NButton>
              </template>
              <div class="main-indicator-popover">
                <div class="main-indicator-popover__head">
                  <strong>主图指标</strong>
                  <small>{{ mainIndicatorStatusText }}</small>
                  <NButton size="tiny" secondary @click="enableTrendEmaIndicators">趋势均线</NButton>
                </div>
                <div
                  v-for="definition in mainIndicatorDefinitions"
                  :key="definition.id"
                  class="main-indicator-row"
                  :class="{ 'main-indicator-row--disabled': !mainIndicatorAllowed(definition) }"
                >
                  <NCheckbox
                    :checked="isMainIndicatorVisible(definition.id)"
                    :disabled="!mainIndicatorAllowed(definition)"
                    @update:checked="(checked) => setMainIndicatorVisible(definition, checked)"
                  />
                  <span class="main-indicator-row__swatch" :style="{ backgroundColor: definition.color }" />
                  <div class="main-indicator-row__name">
                    <strong>{{ definition.displayName }}</strong>
                    <small>{{ mainIndicatorDisabledReason(definition) }}</small>
                    <small v-if="definition.id === 'htdy'" class="main-indicator-row__risk">
                      未来引用 / 重绘风险 · 公式语义尚未完全对齐 · 仅供人工观察 · 不进入严格研究、回测、信号、提醒或交易
                    </small>
                  </div>
                  <span class="main-indicator-row__value">{{ formatNumber(mainIndicatorCurrentValue(definition.id)) }}</span>
                  <NTag size="small" :type="definition.capability === 'observation_overlay' ? 'warning' : 'default'">
                    {{ definition.capability === 'observation_overlay' ? '重绘风险' : '—' }}
                  </NTag>
                </div>
              </div>
              </NPopover>
              <NButton size="small" :type="showSignalLayer ? 'primary' : 'default'" :disabled="chartControlsBusy" @click="showSignalLayer = !showSignalLayer">
                信号层
              </NButton>
            </div>
            <div class="chart-control-group" aria-label="数据窗口">
              <span class="chart-control-group__label">窗口</span>
              <NDatePicker v-model:value="dateRange" type="daterange" clearable size="small" :disabled="chartControlsBusy" />
              <NButton size="small" :loading="loadingBars" :disabled="chartControlsBusy && !loadingBars" @click="refreshBars">
                刷新
              </NButton>
            </div>
          </div>
        </div>
      </section>

      <NAlert v-if="metaWarning" type="warning" :bordered="false">{{ metaWarning }}</NAlert>
      <NAlert v-if="barsError" type="error" :bordered="false">{{ barsError }}</NAlert>
      <NAlert v-if="indicatorError" type="warning" :bordered="false">{{ indicatorError }}</NAlert>
      <NAlert v-if="macdError" type="warning" :bordered="false">{{ macdError }}</NAlert>

      <MarketDataQualityCard
        v-if="qualityImpact"
        ref="qualityCardRef"
        :impact="qualityImpact"
        @action="handleQualityAction"
      />

      <section class="quote-strip">
        <div class="quote-strip__identity">
          <span class="quote-strip__name">{{ selectedDominant?.product_name || selectedContractInfo?.name || selectedItem?.name || selectedSymbol || '-' }}</span>
          <span class="quote-strip__code">{{ contractViewLabel }} · {{ selectedDominant?.exchange || selectedContractInfo?.exchange || selectedItem?.exchange || '-' }}</span>
        </div>
        <div class="quote-strip__price" :class="(priceChange || 0) >= 0 ? 'text-up' : 'text-down'">
          <strong>{{ formatNumber(latestBar?.close) }}</strong>
          <span>
            {{ priceChange === null ? '-' : formatNumber(priceChange) }}
            {{ priceChangePercent === null ? '' : `${priceChangePercent.toFixed(2)}%` }}
          </span>
        </div>
        <div class="quote-strip__metric">
          <span>成交量</span><strong>{{ latestBar?.volume?.toLocaleString('zh-CN') || '-' }}</strong>
        </div>
        <div class="quote-strip__metric">
          <span>持仓</span><strong>{{ formatNumber(latestBar?.openInterest, 0) }}</strong>
        </div>
        <div class="quote-strip__metric">
          <span>交易日</span><strong>{{ latestBar?.trading_day || '-' }}</strong>
        </div>
      </section>

      <div class="kline-chart-host">
        <KlineChart
          ref="klineChartRef"
          :bars="bars"
          :markers="chartMarkers"
          :active-marker-id="activeMarkerId"
          :overlays="chartOverlays"
          :main-indicators="visibleMainIndicators"
          :main-indicator-series="mainIndicatorSeries"
          :loading="loadingBars"
          :error="barsError"
          :indicator-panels="['macd']"
          :macd-override="macdOverride"
          :period="selectedPeriod || undefined"
          :period-options="chartPeriodOptions"
          :fit-content="chartFitContent"
          :quality="quality"
          show-period-toolbar
          @update:period="handlePeriodUpdate"
          @hover="hoverContext = $event"
          @marker-click="handleMarkerClick"
          @visible-range-change="handleVisibleRangeChange"
          @quality-details="focusQualityCard"
        />
      </div>
    </main>

    <MarketRightRail :model-value="activeRightRailTab" @update:model-value="handleRightRailTab">
      <template #strategy>
        <section class="side-panel">
          <div class="side-panel__title">
            <span>当前盘面事实</span>
            <NTag size="small">{{ strategyStatus.label }}</NTag>
          </div>
          <p>{{ strategyStatus.text }}</p>
          <p>{{ mainIndicatorStatusText }}</p>
          <div class="snapshot-grid">
            <span>最新收盘</span><strong>{{ formatNumber(latestBar?.close) }}</strong>
            <span>K线数量</span><strong>{{ bars.length.toLocaleString('zh-CN') }}</strong>
            <span>合约 / 周期</span><strong>{{ selectedContract || '-' }} / {{ selectedPeriod || '-' }}</strong>
            <span>匹配信号</span><strong>{{ matchedSignals.length }}</strong>
          </div>
          <NAlert type="warning" :bordered="false">指标仅供技术观察；HTDY/XMA 重绘边界不变，不进入严格研究或交易。</NAlert>
        </section>

        <section class="side-panel">
          <div class="side-panel__title">
            <span>数据资格</span>
            <NTag size="small" :type="marketQualification.tone">{{ marketQualification.label }}</NTag>
          </div>
          <p>{{ marketQualification.summary }}</p>
          <div class="snapshot-grid">
            <span>访问模式</span><strong>{{ accessMode === 'research' ? '严格研究' : '浏览观察' }}</strong>
            <span>质量</span><strong>{{ barsCoverage?.quality_status || quality?.status || 'unknown' }}</strong>
            <span>数据身份</span><strong>Canonical DatasetKey</strong>
            <span>lineage</span><strong>{{ barsLineage ? '已绑定' : '未证明' }}</strong>
            <span>数据冲突</span><strong>{{ crossFileConflictCount.toLocaleString('zh-CN') }}</strong>
          </div>
          <NButton v-if="qualityImpact" size="small" secondary block @click="focusQualityCard">查看左侧质量影响</NButton>
        </section>

        <section class="side-panel">
          <div class="side-panel__title">十字线快照</div>
          <template v-if="hoverContext">
            <div class="snapshot-grid">
              <span>时间</span><strong>{{ hoverContext.time.replace('T', ' ').slice(0, 16) }}</strong>
              <span>开高低收</span><strong>{{ formatNumber(hoverContext.bar.open) }} / {{ formatNumber(hoverContext.bar.high) }} / {{ formatNumber(hoverContext.bar.low) }} / {{ formatNumber(hoverContext.bar.close) }}</strong>
              <template v-for="item in hoverMainIndicatorRows(hoverContext)" :key="item.id">
                <span>{{ item.displayName }}</span><strong>{{ formatNumber(item.value) }}</strong>
              </template>
              <span>MACD</span><strong>{{ formatNumber(hoverContext.macd?.histogram, 4) }}</strong>
              <span>ATR</span><strong>{{ formatNumber(hoverContext.atr, 4) }}</strong>
            </div>
          </template>
          <div v-else class="empty-note">移动十字线查看主图和副图联动数据。</div>
        </section>

        <section class="side-panel experimental-tools">
          <NButton size="small" secondary block @click="experimentalToolsOpen = !experimentalToolsOpen">
            {{ experimentalToolsOpen ? '收起' : '展开' }}实验工具
          </NButton>
          <template v-if="experimentalToolsOpen">
            <NAlert type="warning" :bordered="false">实验工具 · 非正式风控 · 不产生交易指令。</NAlert>
            <FuturesResearchPanel :symbol="selectedSymbol" :contract="selectedContract" :date-range="dateRange" />
            <div class="snapshot-grid">
              <span>账户假设</span><strong>100,000（示例）</strong>
              <span>单笔风险</span><strong>{{ riskDraft ? formatNumber(riskDraft.riskBudget) : '-' }}</strong>
              <span>ATR</span><strong>{{ riskDraft ? formatNumber(riskDraft.atr) : '-' }}</strong>
              <span>多 / 空止损</span><strong>{{ riskDraft ? `${formatNumber(riskDraft.stopLong)} / ${formatNumber(riskDraft.stopShort)}` : '-' }}</strong>
            </div>
          </template>
        </section>
      </template>

      <template #signal>
        <section class="side-panel signal-list-panel">
          <div class="side-panel__title">
            <span>StrategySignal</span>
            <NTag size="small">{{ matchedSignals.length }}</NTag>
          </div>
          <button
            v-for="signal in matchedSignals"
            :key="signal.id"
            class="signal-list-item"
            :class="{ 'signal-list-item--active': selectedSignalId === signal.id }"
            @click="selectSignalFromList(signal)"
          >
            <span><strong>{{ signalMarkerLabel(signal) }}</strong>{{ signal.strategy_code || signal.strategy_id }}</span>
            <small>{{ signal.entry_interval || signal.interval || signal.period }} · {{ signal.strategy_status }} · {{ formatNumber(signal.signal_price ?? signal.price ?? signal.current_price) }}</small>
          </button>
          <div v-if="!matchedSignals.length" class="empty-note">当前合约与周期暂无匹配 StrategySignal。</div>
        </section>

        <section class="side-panel">
          <div class="side-panel__title">
            <span>SignalEvent / 通知</span>
            <NTag size="small" :type="selectedNotification?.status === 'sent' ? 'success' : 'default'">
              {{ loadingNotification ? 'loading' : selectedNotification?.status || 'readonly' }}
            </NTag>
          </div>
          <div v-if="selectedSignalEvent" class="snapshot-grid">
            <span>事件</span><strong>#{{ selectedSignalEvent.id }} · {{ selectedSignalEvent.event_type }}</strong>
            <span>source_mode</span><strong>{{ selectedSignalEvent.source_mode }}</strong>
            <span>lifecycle</span><strong>{{ selectedSignalEvent.lifecycle_status }}</strong>
            <span>bar_end</span><strong>{{ (selectedSignalEvent.bar_end || selectedSignalEvent.signal_time || '-').replace('T', ' ').slice(0, 16) }}</strong>
            <span>通知尝试</span><strong>{{ selectedNotification ? `${selectedNotification.attempt_count}/${selectedNotification.max_attempts}` : '-' }}</strong>
          </div>
          <div v-else class="empty-note">选择信号 marker 后显示关联事件；historical 与 live 不混用。</div>
          <NAlert v-if="notificationError" type="warning" :bordered="false">{{ notificationError }}</NAlert>
          <NButton v-if="selectedSignalEvent || route.query.signal_event_id" size="small" secondary block @click="openReviewFromChart">
            打开事件复盘
          </NButton>
          <NButton size="small" secondary block @click="router.push({ name: 'signal' })">打开信号中心</NButton>
        </section>
      </template>

      <template #review>
        <section class="side-panel">
          <div class="side-panel__title">Signal Review</div>
          <div class="empty-note">复盘仅关联 StrategySignal / SignalEvent；行情页不加载回测报告或成交。</div>
          <NButton v-if="route.query.review_id" size="small" secondary block @click="openReviewFromChart">
            返回复盘
          </NButton>
          <NButton v-else-if="selectedSignalEvent || route.query.signal_event_id" size="small" secondary block @click="openReviewFromChart">
            打开事件复盘
          </NButton>
          <NButton v-else size="small" secondary block @click="router.push({ name: 'review' })">打开复盘中心</NButton>
        </section>
      </template>

      <template #runtime>
        <LiveTargetPanel compact />
        <section v-if="isLiveMode" class="side-panel">
          <div class="side-panel__title">
            <span>Live 质量</span>
            <NTag size="small" :type="qualityType(liveQuality?.status)">{{ liveQuality?.status || '-' }}</NTag>
          </div>
          <div class="snapshot-grid">
            <span>可画K线</span><strong>{{ (liveQuality?.chart_row_count || 0).toLocaleString('zh-CN') }}</strong>
            <span>原始行数</span><strong>{{ (liveQuality?.row_count || 0).toLocaleString('zh-CN') }}</strong>
            <span>warning</span><strong>{{ (liveQuality?.warning_count || 0).toLocaleString('zh-CN') }}</strong>
            <span>partial</span><strong>{{ (liveQuality?.partial_count || 0).toLocaleString('zh-CN') }}</strong>
            <span>failed</span><strong>{{ (liveQuality?.failed_count || 0).toLocaleString('zh-CN') }}</strong>
          </div>
          <small>Live 数据只用于显式观察，不进入默认回测或信号扫描。</small>
        </section>
        <section class="side-panel"><MarketRuntimeObservationPanel :context="runtimeObservationContext" /></section>
      </template>
    </MarketRightRail>

    <MarketEvidenceDrawer
      v-model:show="evidenceDrawerOpen"
      :lineage="barsLineage"
      :coverage="barsCoverage"
      :quality-status="barsCoverage?.quality_status || quality?.status || 'unknown'"
      :cross-file-conflict-count="crossFileConflictCount"
    />
  </div>
</template>

<style scoped>
.market-chart-workbench {
  display: grid;
  grid-template-columns: minmax(680px, 1fr) 300px;
  gap: var(--gy-space-3);
  min-width: 0;
  min-height: calc(100vh - var(--gy-header-height) - (var(--gy-content-padding) * 2));
  align-items: stretch;
}

.chart-header {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-2);
  padding: 10px 12px;
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  box-shadow: var(--gy-shadow-panel);
}

.chart-header__secondary {
  display: flex;
  align-items: stretch;
  flex-direction: column;
  min-width: 0;
  width: 100%;
  gap: var(--gy-space-2);
}

.chart-header__secondary {
  padding-top: var(--gy-space-2);
  border-top: 1px solid var(--gy-border-subtle);
}

.chart-header__actions {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
  gap: var(--gy-space-2);
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.chart-control-group {
  display: flex;
  align-items: center;
  gap: var(--gy-space-2);
  min-width: 0;
  padding-left: var(--gy-space-2);
  border-left: 1px solid var(--gy-border-subtle);
}

.chart-control-group:first-child {
  padding-left: 0;
  border-left: 0;
}

.chart-control-group__label {
  color: var(--gy-text-disabled);
  font-size: var(--gy-font-size-xs);
}

.main-indicator-popover {
  width: 340px;
  max-width: min(340px, calc(100vw - 32px));
  padding: 4px;
}

.main-indicator-popover__head,
.main-indicator-row {
  display: flex;
  align-items: center;
  gap: var(--gy-space-2);
}

.main-indicator-popover__head {
  justify-content: space-between;
  padding: 4px 2px 10px;
  color: var(--gy-text-primary);
}

.main-indicator-row {
  min-height: 42px;
  padding: 6px 2px;
  border-top: 1px solid var(--gy-border-subtle);
}

.main-indicator-row--disabled {
  opacity: 0.62;
}

.main-indicator-row__swatch {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.16);
}

.main-indicator-row__name {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.main-indicator-row__name strong {
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-sm);
}

.main-indicator-row__name small,
.main-indicator-row__value {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}

.main-indicator-row__risk {
  max-width: 190px;
  white-space: normal;
  line-height: 1.35;
}

.main-indicator-row__value {
  width: 72px;
  text-align: right;
  font-family: var(--gy-font-mono);
  font-variant-numeric: tabular-nums;
}

.center-stage {
  min-width: 0;
}

.center-stage {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
  min-height: 0;
}

.kline-chart-host {
  flex: 1 1 auto;
  min-height: 480px;
  display: flex;
  flex-direction: column;
}

.kline-chart-host :deep(.kline-shell) {
  flex: 1;
  min-height: 0;
}

.side-panel,
.quote-strip {
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  box-shadow: var(--gy-shadow-panel);
}

.quote-strip__name {
  color: var(--gy-text-primary);
  font-weight: 700;
}

.quote-strip__code,
.side-panel p,
.empty-note,
.side-panel small {
  color: var(--gy-text-muted);
}

.quote-strip {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) minmax(140px, auto) repeat(3, minmax(72px, auto));
  align-items: center;
  gap: var(--gy-space-3);
  min-height: 74px;
  padding: 12px 14px;
  color: var(--gy-text-secondary);
}

.quote-strip__identity,
.quote-strip__price,
.quote-strip__metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.quote-strip__price {
  align-items: flex-start;
}

.quote-strip__price strong {
  font-size: 28px;
  line-height: 1;
}

.quote-strip__price span,
.quote-strip__metric strong {
  font-size: var(--gy-font-size-sm);
}

.quote-strip__metric > span {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}

.quote-strip__price strong,
.quote-strip__price span,
.quote-strip__metric strong {
  font-family: var(--gy-font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.side-panel {
  padding: var(--gy-space-3);
}

.side-panel__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gy-space-2);
  margin-bottom: var(--gy-space-3);
  color: var(--gy-text-primary);
  font-weight: 700;
}

.side-panel__title::before {
  content: '';
  width: 3px;
  height: 13px;
  flex: 0 0 auto;
  margin-right: 3px;
  border-radius: 2px;
  background: var(--gy-accent);
}

.side-panel__title > span:first-child {
  margin-right: auto;
}

.signal-row,
.snapshot-grid {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: var(--gy-space-2);
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.signal-row {
  padding-top: 8px;
}

.snapshot-grid strong,
.signal-row strong {
  min-width: 0;
  color: var(--gy-text-primary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.signal-list-panel {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-2);
}

.signal-list-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  padding: var(--gy-space-2);
  color: var(--gy-text-secondary);
  text-align: left;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
  cursor: pointer;
  transition: border-color var(--gy-transition-fast), background-color var(--gy-transition-fast);
}

.signal-list-item:hover,
.signal-list-item--active {
  color: var(--gy-text-primary);
  background: var(--gy-bg-selected);
  border-color: var(--gy-accent);
}

.signal-list-item span,
.signal-list-item small {
  min-width: 0;
  overflow-wrap: anywhere;
}

.signal-list-item strong {
  margin-right: 6px;
  color: var(--gy-chart-ema);
}

.signal-list-item small {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

@media (min-width: 1200px) and (max-width: 1439px) {
  .market-chart-workbench {
    grid-template-columns: minmax(680px, 1fr) 280px;
  }

  .quote-strip {
    grid-template-columns: minmax(138px, 1fr) minmax(132px, auto) repeat(3, minmax(68px, auto));
  }

}

@media (max-width: 1199px) {
  .market-chart-workbench {
    grid-template-columns: minmax(0, 1fr);
  }

  .chart-header__secondary {
    align-items: stretch;
  }

  .chart-header__actions {
    width: 100%;
    justify-content: flex-end;
  }

  .quote-strip {
    grid-template-columns: minmax(150px, 1fr) minmax(140px, auto) repeat(3, minmax(80px, 1fr));
  }

  .kline-chart-host {
    min-height: 560px;
  }
}

@media (max-width: 760px) {
  .quote-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quote-strip__identity {
    grid-column: 1 / -1;
  }

  .chart-control-group {
    width: 100%;
    padding: 0;
    border-left: 0;
  }

  .chart-control-group :deep(.n-date-picker) {
    flex: 1;
    min-width: 0;
  }
}
</style>
