<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCheckbox, NDatePicker, NEllipsis, NPopover, NRadioButton, NRadioGroup, NSelect, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import FuturesResearchPanel from '@/components/research/FuturesResearchPanel.vue'
import MarketStrategySidebar from '@/components/market/MarketStrategySidebar.vue'
import MarketRuntimeObservationPanel from '@/components/market/MarketRuntimeObservationPanel.vue'
import { getLatestStrategySignals, getSignalEvents, getStage9WechatNotification } from '@/api/signal'
import type { SignalEventRecord, Stage9WechatNotification, StrategySignalRecord } from '@/types/signal'
import { describeBacktestApiError, fetchAllBacktestReportTrades, getBacktestReport } from '@/api/backtestApi'
import { getDataProfiles, getLiveMarketBars, getLiveMarketCoverage, getMarketBars, getMarketDominants, getMarketIndicators, getMarketMacdIndicator, getMarketWorkbenchCoverage } from '@/api/market'
import type { BacktestReport, BacktestTrade } from '@/types/backtest'
import type {
  BarData,
  ChartOverlay,
  DominantContractItem,
  DataProfileSummary,
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
import { isSyntheticFuturesContract, resolveActualContract } from '@/utils/marketContract'
import { selectSignalEventForChart, signalIdFromMarkerId, signalMarkerId } from '@/utils/marketSignalSelection'
import { formatTradeMarkerText } from '@/utils/tradeMarker'
import { resolveChartTheme } from '@/styles/chartTheme'
import { buildMarketRuntimeObservation } from '@/utils/marketRuntimeObservation'
import type { MarketRuntimeObservationContext } from '@/types/marketRuntimeObservation'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const chartTheme = resolveChartTheme()

type KlineChartExpose = {
  focusTime: (value: string) => void
}

type BarsLoadMode = 'viewport' | 'explicit'
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
const loadingLinkedReport = ref(false)
const barsError = ref<string | null>(null)
const indicatorError = ref<string | null>(null)
const metaWarning = ref<string | null>(null)
const qualityWarningMessage = ref<string | null>(null)
const coverage = ref<MarketWorkbenchCoverage | null>(null)
const dominants = ref<DominantContractItem[]>([])
const dataProfiles = ref<DataProfileSummary[]>([])
const bars = ref<BarData[]>([])
const quality = ref<MarketBarsQuality | LiveMarketBarsQuality | null>(null)
const barsCoverage = ref<MarketBarsCoverage | null>(null)
const barsLineage = ref<MarketReadLineage | null>(null)
const macdOverride = ref<MarketMacdIndicatorResponse | null>(null)
const macdError = ref<string | null>(null)
const hoverContext = ref<HoverKlineContext | null>(null)

type DataMode = 'historical' | 'live'
const dataMode = ref<DataMode>(route.query.data_mode === 'live' ? 'live' : 'historical')
const selectedSymbol = ref<string | null>(null)
const selectedActualContract = ref<string | null>(null)
const contractView = ref<ContractViewMode>('actual')
const selectedPeriod = ref<string | null>(null)
const selectedProfileId = ref<string | null>(typeof route.query.profile_id === 'string' ? route.query.profile_id : null)
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
const linkedReport = ref<BacktestReport | null>(null)
const linkedTrades = ref<BacktestTrade[]>([])
const activeMarkerId = ref<string | null>(null)
const showSignalLayer = ref(route.query.signal_layer !== '0')
const latestSignals = ref<StrategySignalRecord[]>([])
const selectedSignalId = ref<number | null>(null)
const selectedSignalEvent = ref<SignalEventRecord | null>(null)
const selectedNotification = ref<Stage9WechatNotification | null>(null)
const loadingNotification = ref(false)
const notificationError = ref<string | null>(null)
let marketRouteRequestId = 0
let macdRequestId = 0
let signalSelectionRequestId = 0
let syncingQueryFromState = false
let viewportLoadTimer: ReturnType<typeof setTimeout> | null = null
let liveRefreshTimer: ReturnType<typeof setInterval> | null = null

const coverageItems = computed(() => coverage.value?.items || [])
const isLiveMode = computed(() => dataMode.value === 'live')
const isBacktestDeepLink = computed(() => Number(route.query.report_id) > 0)
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
      (available.size > 0 ? !available.has(item.value) : false) ||
      (isLiveMode.value && !isLivePeriodSupported(item.value)),
  }))
})

const latestBar = computed(() => bars.value.at(-1) || null)
const previousBar = computed(() => (bars.value.length >= 2 ? bars.value.at(-2) || null : null))
const linkedTrade = computed(() => {
  const tradeNo = stringQuery(route.query.trade_no)
  const tradeId = numericQuery(route.query.trade_id)
  if (tradeNo) return linkedTrades.value.find((trade) => trade.trade_no === tradeNo) || null
  if (tradeId) return linkedTrades.value.find((trade) => trade.id === tradeId) || null
  return null
})
const backtestMarkers = computed<KlineMarker[]>(() => linkedTrades.value.flatMap((trade) => tradeToMarkers(trade)))
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
const chartMarkers = computed(() => [...backtestMarkers.value, ...signalMarkers.value])
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
    profile_id: isLiveMode.value ? null : selectedProfileId.value || null,
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
  if (isLiveMode.value) return 'Live 指标待 C3'
  if (loadingIndicators.value) return '统一 EMA 计算中'
  if (indicatorError.value) return '统一 EMA 加载失败'
  if (!visibleMainIndicators.value.length) return '主图指标已关闭'
  return '统一 EMA'
})
const liveModeOptions = [
  { label: '历史', value: 'historical' },
  { label: 'Live', value: 'live' },
]
const accessModeOptions = [
  { label: '浏览', value: 'browser' as const },
  { label: '严格研究', value: 'research' as const },
]
const profileOptions = computed(() => dataProfiles.value.map((profile) => ({
  label: `${profile.label} · ${profile.quality_policy}`,
  value: profile.profile_id,
})))
const contractViewOptions = [
  { label: '真实主力', value: 'actual' as const },
  { label: '主连研究', value: 'continuous' as const },
]

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
        text: 'Live 模式仅支持 1m~60m，请切回历史模式查看日/周线。',
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
        text: `数据质量为 failed，暂不可展示。${barsCoverage.value.file_path ? ` 文件：${barsCoverage.value.file_path}` : ''}`,
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
  if (!ema21) return { label: '预热中', type: 'warning' as const, text: 'K 线数量不足，EMA21/MACD 仍在预热。' }
  if (latestBar.value.close >= ema21) {
    return { label: '多头观察', type: 'error' as const, text: '收盘价位于 EMA21 上方，可结合 MACD 和回测成交继续验证。' }
  }
  return { label: '空头/回避', type: 'success' as const, text: '收盘价位于 EMA21 下方，先按趋势过滤观察。' }
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
  if (!route.query.symbol || !route.query.contract) {
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

async function initializeChartPage() {
  const requestId = ++marketRouteRequestId
  applyRouteSelectionFromQueryToState()
  viewportLoadEnabled.value = false
  const results = await Promise.allSettled([loadDominants(), loadScopedCoverage(), loadDataProfiles()])
  if (!isCurrentMarketRoute(requestId)) return
  const dominantsResult = results[0]
  if (dominantsResult.status === 'fulfilled' && !selectionMatchesRoute() && !isBacktestDeepLink.value) {
    applyInitialSelection()
  }
  if (Number(route.query.report_id) > 0) {
    await applyRouteSelectionAndLoad(requestId)
    return
  }
  await loadBars(requestId)
}

function applyRouteSelectionFromQueryToState() {
  const selection = applyRouteSelectionFromQuery({
    symbol: stringQuery(route.query.symbol),
    product: stringQuery(route.query.product),
    contract: stringQuery(route.query.contract),
    period: stringQuery(route.query.period),
    interval: stringQuery(route.query.interval),
    contract_view: stringQuery(route.query.contract_view),
  })
  selectedProfileId.value = stringQuery(route.query.profile_id)
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
    profile_id: selectedProfileId.value || stringQuery(route.query.profile_id),
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
    const response = await getLatestStrategySignals({
      product: selectedSymbol.value,
      [contractKey]: selectedActualContract.value,
      period: selectedPeriod.value,
      provider: 'rqdata',
      data_role: 'primary',
      limit: 50,
    })
    if (isCurrentMarketRoute(requestId)) {
      latestSignals.value = response
      if (selectedSignalId.value && !response.some((signal) => signal.id === selectedSignalId.value)) clearSignalSelection()
    }
  } catch {
    if (isCurrentMarketRoute(requestId)) {
      latestSignals.value = []
      clearSignalSelection()
    }
  }
}

const selectedSignalForChart = computed(() => (selectedSignalId.value ? matchedSignals.value.find((signal) => signal.id === selectedSignalId.value) || null : null))
const latestSignalForChart = computed(() => selectedSignalForChart.value || matchedSignals.value[0] || null)

async function loadDominants() {
  loadingDominants.value = true
  try {
    const response = await getMarketDominants()
    dominants.value = response.items
  } catch (err) {
    message.warning(apiError(err, '加载主力合约列表失败'))
    dominants.value = []
  } finally {
    loadingDominants.value = false
  }
}

async function loadDataProfiles() {
  try {
    dataProfiles.value = (await getDataProfiles()).filter((profile) => profile.is_active)
  } catch (err) {
    dataProfiles.value = []
    metaWarning.value = apiError(err, '加载数据 Profile 失败')
  }
}

watch(
  () => [
    route.query.report_id,
    route.query.trade_id,
    route.query.trade_no,
    route.query.symbol,
    route.query.contract,
    route.query.period,
    route.query.interval,
    route.query.contract_view,
    route.query.profile_id,
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
  await Promise.allSettled([loadDominants(), loadScopedCoverage(), loadDataProfiles()])
  await applyRouteSelectionAndLoad(requestId)
}

async function loadScopedCoverage() {
  loadingMeta.value = true
  metaWarning.value = null
  try {
    if (!isLiveMode.value && accessMode.value === 'research' && !selectedProfileId.value) {
      coverage.value = null
      return
    }
    const params = currentCoverageScope()
    if (!isLiveMode.value && params?.access_mode === 'research' && !params.profile_id) {
      coverage.value = null
      return
    }
    coverage.value = isLiveMode.value
      ? await getLiveMarketCoverage(params)
      : await getMarketWorkbenchCoverage(params)
    syncDateRangeForSelection()
  } catch (err) {
    metaWarning.value = apiError(err, '加载行情工作台元数据失败')
    coverage.value = null
  } finally {
    loadingMeta.value = false
  }
}

async function applyRouteSelectionAndLoad(requestId = ++marketRouteRequestId) {
  viewportLoadEnabled.value = false
  const linkedSelectionApplied = await applyLinkedReportSelection(requestId)
  if (!isCurrentMarketRoute(requestId)) return
  if (!linkedSelectionApplied) applyInitialSelection()
  await loadBars(requestId)
}

async function loadBars(requestId = marketRouteRequestId, options: LoadBarsOptions = {}) {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) {
    bars.value = []
    clearMarketMacd()
    return
  }
  if (!isLiveMode.value && accessMode.value === 'research' && !selectedProfileId.value) {
    barsError.value = '严格研究模式必须选择 Profile'
    bars.value = []
    barsLineage.value = null
    mainIndicatorSeries.value = []
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
      await focusLinkedTradeMarker()
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
      : apiError(err, 'K 线加载失败')
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

function stopLiveRefreshTimer() {
  if (!liveRefreshTimer) return
  clearInterval(liveRefreshTimer)
  liveRefreshTimer = null
}

function syncLiveRefreshTimer() {
  stopLiveRefreshTimer()
  if (!isLiveMode.value || !selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return
  liveRefreshTimer = setInterval(() => {
    void refreshLiveBars()
  }, LIVE_REFRESH_INTERVAL_MS)
}

async function refreshLiveBars() {
  if (!isLiveMode.value || document.visibilityState !== 'visible' || loadingBars.value) return
  const requestId = ++marketRouteRequestId
  await loadBars(requestId, { merge: true, liveRefresh: true, fitContent: false })
}

function handleLiveVisibilityChange() {
  if (document.visibilityState !== 'visible') return
  syncLiveRefreshTimer()
  void refreshLiveBars()
}

function buildBarsRequest(viewportWindow?: ViewportLoadRequest): MarketBarsRequestParams | null {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return null
  const isContinuousRequest = isBacktestDeepLink.value
    ? isSyntheticFuturesContract(selectedContract.value || '')
    : isContinuousView.value
  const base = {
    symbol: selectedSymbol.value,
    contract: selectedContract.value,
    period: selectedPeriod.value,
    provider: selectedItem.value?.provider,
    data_role: selectedItem.value?.data_role,
    profile_id: selectedProfileId.value,
    access_mode: accessMode.value,
    expected_market_data_file_id: barsLineage.value?.market_data_file_id,
    expected_lineage_token: barsLineage.value?.lineage_token,
    quote_mode: !isBacktestDeepLink.value && !isContinuousRequest,
    allow_continuous: isBacktestDeepLink.value || isContinuousRequest,
  }
  if (viewportWindow) {
    return {
      ...base,
      start: formatDate(viewportWindow.startMs),
      end: formatDate(viewportWindow.endMs),
      tail: false,
      limit: MAX_BARS_PER_REQUEST,
    }
  }
  if (barsLoadMode.value === 'explicit' && dateRange.value) {
    return {
      ...base,
      start: formatDate(dateRange.value[0]),
      end: formatDate(dateRange.value[1]),
      tail: false,
      limit: MAX_BARS_PER_REQUEST,
    }
  }
  if (isBacktestDeepLink.value && dateRange.value) {
    return {
      ...base,
      start: formatDate(dateRange.value[0]),
      end: formatDate(dateRange.value[1]),
      tail: false,
      limit: MAX_BARS_PER_REQUEST,
    }
  }
  const initial = resolveInitialBarsQuery(currentSelectionCoverageItem())
  if (initial) {
    return {
      ...base,
      start: formatDate(initial.startMs),
      end: formatDate(initial.endMs),
      tail: initial.tail,
      limit: initial.limit,
    }
  }
  return {
    ...base,
    start: dateRange.value ? formatDate(dateRange.value[0]) : undefined,
    end: dateRange.value ? formatDate(dateRange.value[1]) : undefined,
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
  const isContinuousRequest = isBacktestDeepLink.value
    ? isSyntheticFuturesContract(selectedContract.value || '')
    : isContinuousView.value
  return {
    symbol: selectedSymbol.value,
    contract: selectedContract.value,
    period: selectedPeriod.value,
    provider: selectedItem.value?.provider,
    data_role: selectedItem.value?.data_role,
    profile_id: selectedProfileId.value,
    access_mode: accessMode.value,
    expected_market_data_file_id: barsLineage.value?.market_data_file_id,
    expected_lineage_token: barsLineage.value?.lineage_token,
    start: formatDate(extent.startMs),
    end: formatDate(extent.endMs),
    quote_mode: !isBacktestDeepLink.value && !isContinuousRequest,
    allow_continuous: isBacktestDeepLink.value || isContinuousRequest,
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
  const isContinuousRequest = isBacktestDeepLink.value
    ? isSyntheticFuturesContract(selectedContract.value || '')
    : isContinuousView.value
  const params = buildMainIndicatorRequestParams({
    symbol: selectedSymbol.value,
    contract: selectedContract.value,
    period: selectedPeriod.value,
    bars: bars.value,
    visibleIds: visibleMainIndicators.value,
    provider: selectedItem.value?.provider,
    dataRole: selectedItem.value?.data_role,
    profileId: selectedProfileId.value,
    accessMode: accessMode.value,
    expectedMarketDataFileId: barsLineage.value?.market_data_file_id,
    expectedLineageToken: barsLineage.value?.lineage_token,
    quoteMode: !isBacktestDeepLink.value && !isContinuousRequest,
    allowContinuous: isBacktestDeepLink.value || isContinuousRequest,
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
    indicatorError.value = apiError(err, '统一 EMA 指标加载失败')
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
    macdError.value = apiError(err, 'MACD 后端指标加载失败，已回退前端展示计算')
  }
}

function clearMarketMacd() {
  macdRequestId += 1
  macdOverride.value = null
  macdError.value = null
}

function handleDataModeUpdate(value: DataMode) {
  if (value === dataMode.value) return
  marketRouteRequestId += 1
  clearSignalSelection()
  barsLoadMode.value = 'viewport'
  chartFitContent.value = true
  dataMode.value = value
  barsLineage.value = null
  if (value === 'live') {
    accessMode.value = 'browser'
    selectedProfileId.value = null
  }
  if (value === 'live' && selectedPeriod.value && !isLivePeriodSupported(selectedPeriod.value)) {
    const fallback = chartPeriodOptions.value.find((item) => !item.disabled)?.value || '15m'
    selectedPeriod.value = fallback
    contractView.value = 'actual'
  }
  coverage.value = null
  metaWarning.value = null
  bars.value = []
  quality.value = null
  barsCoverage.value = null
  mainIndicatorSeries.value = []
  void syncQuery().then(() => reloadChartPage())
}

function handleAccessModeUpdate(value: MarketAccessMode) {
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

function handleProfileUpdate(value: string | null) {
  if (value === selectedProfileId.value) return
  marketRouteRequestId += 1
  selectedProfileId.value = value
  barsLineage.value = null
  coverage.value = null
  bars.value = []
  mainIndicatorSeries.value = []
  void syncQuery().then(() => reloadChartPage())
}

async function applyLinkedReportSelection(requestId = marketRouteRequestId) {
  const reportId = Number(route.query.report_id)
  if (!Number.isFinite(reportId) || reportId <= 0) {
    linkedReport.value = null
    linkedTrades.value = []
    activeMarkerId.value = null
    return false
  }
  loadingLinkedReport.value = true
  try {
    const [report, trades] = await Promise.all([getBacktestReport(reportId), fetchAllBacktestReportTrades(reportId)])
    if (!isCurrentMarketRoute(requestId)) return false
    linkedReport.value = report
    linkedTrades.value = trades
    selectedSymbol.value = report.symbol
    selectedActualContract.value = resolveActualContract(report.symbol, report.contract, dominants.value)
    if (isSyntheticFuturesContract(report.contract)) {
      contractView.value = 'continuous'
    }
    selectedPeriod.value = queryPeriod() || selectedTradeInterval(trades) || report.period
    const focusTime = queryTime() || linkedTrade.value?.open_time || trades[0]?.open_time || report.started_at || report.created_at
    if (focusTime) {
      const focus = new Date(focusTime).getTime()
      if (!Number.isNaN(focus)) dateRange.value = [focus - 5 * dayMs(), focus + 5 * dayMs()]
    } else {
      syncDateRange(selectedItem.value)
    }
    activeMarkerId.value = linkedTrade.value ? markerId(linkedTrade.value, 'open') : null
    return true
  } catch (err) {
    if (!isCurrentMarketRoute(requestId)) return false
    linkedReport.value = null
    linkedTrades.value = []
    message.warning(describeBacktestApiError(err, '加载回测复盘标记失败'))
    return false
  } finally {
    if (isCurrentMarketRoute(requestId)) loadingLinkedReport.value = false
  }
}

function applyInitialSelection() {
  if (isBacktestDeepLink.value) {
    const routeProduct = stringQuery(route.query.symbol)
    const resolvedContract = resolveActualContract(routeProduct, stringQuery(route.query.contract), dominants.value)
    const querySelection = findCoverageItem(routeProduct, resolvedContract, queryPeriod())
    const defaults = coverage.value?.default_selection
    const fallback = defaults ? findCoverageItem(defaults.symbol, defaults.contract, defaults.period) : coverageItems.value[0]
    const selected = querySelection || fallback
    if (!selected) return
    selectedSymbol.value = selected.symbol
    selectedActualContract.value = resolveActualContract(selected.symbol, selected.contract, dominants.value)
    selectedProfileId.value = selected.profile_id || selectedProfileId.value
    contractView.value = defaultContractViewForPeriod(selected.period)
    selectedPeriod.value = selected.period
    syncDateRange(selected)
    const focusTime = queryTime()
    if (focusTime) {
      const focus = new Date(focusTime).getTime()
      if (!Number.isNaN(focus)) dateRange.value = [focus - 3 * dayMs(), focus + 3 * dayMs()]
    }
    return
  }

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
  selectedProfileId.value = selected.profile_id || selectedProfileId.value
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

async function focusLinkedTradeMarker() {
  if (!linkedTrade.value) return
  activeMarkerId.value = markerId(linkedTrade.value, 'open')
  await nextTick()
  klineChartRef.value?.focusTime(nearestBarTime(linkedTrade.value.open_time))
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

async function selectSignal(signal: StrategySignalRecord, markerIdValue = signalMarkerId(signal)) {
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
      notificationError.value = isNotFoundApiError(err) ? '尚无企业微信通知记录。' : apiError(err, '加载企业微信通知状态失败')
    }
  } catch (err) {
    if (requestId !== signalSelectionRequestId) return
    selectedSignalEvent.value = null
    selectedNotification.value = null
    notificationError.value = apiError(err, '加载信号事件失败')
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
  if (Number(route.query.report_id) > 0) return false
  const routeProduct = stringQuery(route.query.symbol) || stringQuery(route.query.product)
  const routeContract = resolveActualContract(routeProduct, stringQuery(route.query.contract), dominants.value)
  const routeView = stringQuery(route.query.contract_view)
  return (
    routeProduct === selectedSymbol.value &&
    routeContract === selectedActualContract.value &&
    stringQuery(route.query.profile_id) === selectedProfileId.value &&
    (route.query.access_mode === 'research' ? 'research' : 'browser') === accessMode.value &&
    (routeView === contractView.value || (!routeView && contractView.value === defaultContractViewForPeriod(selectedPeriod.value || ''))) &&
    queryPeriod() === selectedPeriod.value
  )
}

function queryTime() {
  return stringQuery(route.query.time) || stringQuery(route.query.datetime)
}

function selectedTradeInterval(trades: BacktestTrade[]) {
  const tradeNo = stringQuery(route.query.trade_no)
  const tradeId = numericQuery(route.query.trade_id)
  const trade = tradeNo ? trades.find((item) => item.trade_no === tradeNo) : tradeId ? trades.find((item) => item.id === tradeId) : trades[0]
  return trade ? tradeEntryInterval(trade) : ''
}

function tradeToMarkers(trade: BacktestTrade): KlineMarker[] {
  const isLong = tradeDirectionSide(trade.direction) === 'long'
  const interval = tradeEntryInterval(trade)
  const exitStyle = exitMarkerStyle(trade)
  return [
    {
      id: markerId(trade, 'open'),
      time: nearestBarTime(trade.open_time),
      label: formatTradeMarkerText(trade, 'open'),
      tooltip: `${isLong ? '开多' : '开空'} ${trade.trade_no}${interval ? ` ${interval}` : ''}${tradeScoreTooltip(trade)} @ ${formatNumber(trade.open_price)} / ${trade.entry_reason || tradeRawString(trade, 'entry_reason') || '-'}`,
      color: isLong ? chartTheme.up : chartTheme.down,
      position: isLong ? 'belowBar' : 'aboveBar',
      shape: isLong ? 'arrowUp' : 'arrowDown',
    },
    {
      id: markerId(trade, 'close'),
      time: nearestBarTime(trade.close_time),
      label: formatTradeMarkerText(trade, 'close'),
      tooltip: `${exitStyle.label} ${isLong ? '平多' : '平空'} ${trade.trade_no} ${tradeHoldBars(trade)}K @ ${formatNumber(trade.close_price)} / ${rawExitReason(trade)}`,
      color: exitStyle.color,
      position: isLong ? 'aboveBar' : 'belowBar',
      shape: exitStyle.shape,
    },
  ]
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

function markerId(trade: BacktestTrade, side: 'open' | 'close') {
  return `trade-${trade.trade_no}-${side}`
}

function tradeEntryInterval(trade: BacktestTrade) {
  return tradeRawString(trade, 'entry_interval')
}

function tradeEntryScore(trade: BacktestTrade) {
  return numberFrom(tradeRawValue(trade, 'entry_score'), Number.NaN)
}

function tradeScoreLabel(trade: BacktestTrade | null) {
  if (!trade) return '-'
  const score = tradeEntryScore(trade)
  if (!Number.isFinite(score)) return '-'
  const grade = tradeRawString(trade, 'entry_grade')
  return grade ? `score ${score} / ${grade}` : `score ${score}`
}

function tradeScoreTooltip(trade: BacktestTrade) {
  const score = tradeEntryScore(trade)
  const scenes = tradeSceneTags(trade).slice(0, 2).join(',')
  const scorePart = Number.isFinite(score) ? ` score:${score}` : ''
  const scenePart = scenes ? ` tags:${scenes}` : ''
  return `${scorePart}${scenePart}`
}

function tradeConditionLabel(trade: BacktestTrade | null) {
  if (!trade) return '-'
  const satisfied = tradeRawList(trade, 'satisfied_conditions')
  const failed = tradeRawList(trade, 'failed_conditions').map((item) => `!${item}`)
  return [...satisfied, ...failed].join(' / ') || '-'
}

function tradeSceneLabel(trade: BacktestTrade | null) {
  if (!trade) return '-'
  return tradeSceneTags(trade).join(' / ') || '-'
}

function tradeSceneTags(trade: BacktestTrade) {
  return tradeRawList(trade, 'scene_tags')
}

function tradeHoldBars(trade: BacktestTrade) {
  return numberFrom(trade.holding_bars ?? trade.raw_payload?.hold_bars ?? trade.raw_payload?.holding_bars)
}

function exitMarkerStyle(trade: BacktestTrade) {
  const kind = tradeExitKind(trade)
  if (kind === 'delivery') return { label: '交割风险退出', color: '#f59e0b', shape: 'square' as const }
  if (kind === 'rollover') return { label: '换月退出', color: '#8b5cf6', shape: 'square' as const }
  if (kind === 'stop') return { label: '止损退出', color: '#f97316', shape: 'circle' as const }
  if (kind === 'time') return { label: '时间退出', color: '#38bdf8', shape: 'circle' as const }
  return { label: '普通退出', color: tradeDirectionSide(trade.direction) === 'long' ? chartTheme.down : chartTheme.up, shape: tradeDirectionSide(trade.direction) === 'long' ? 'arrowDown' as const : 'arrowUp' as const }
}

function tradeExitKind(trade: BacktestTrade) {
  const reason = `${trade.exit_reason || ''} ${tradeRawString(trade, 'exit_reason')} ${trade.rollover_reason || ''}`.toLowerCase()
  if (trade.delivery_risk_exit || reason.includes('delivery_risk_exit') || reason.includes('交割')) return 'delivery'
  if (trade.rollover_forced_exit || reason.includes('main_contract_roll_exit') || reason.includes('rollover') || reason.includes('换月')) return 'rollover'
  if (reason.includes('stop') || reason.includes('止损')) return 'stop'
  if (reason.includes('time') || reason.includes('max_hold') || reason.includes('hold_bars') || reason.includes('时间')) return 'time'
  return 'normal'
}

function rawExitReason(trade: BacktestTrade) {
  return trade.exit_reason || tradeRawString(trade, 'exit_reason') || '-'
}

function tradeRawString(trade: BacktestTrade, key: string) {
  const value = tradeRawValue(trade, key)
  return value === undefined || value === null ? '' : String(value)
}

function tradeRawValue(trade: BacktestTrade, key: string) {
  const direct = (trade as unknown as Record<string, unknown>)[key]
  return direct === undefined || direct === null || direct === '' ? trade.raw_payload?.[key] : direct
}

function tradeRawList(trade: BacktestTrade, key: string) {
  const value = tradeRawValue(trade, key)
  if (value === undefined || value === null || value === '') return []
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean)
  if (typeof value === 'string') {
    const stripped = value.trim()
    if (!stripped) return []
    try {
      const parsed = JSON.parse(stripped) as unknown
      if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean)
    } catch {
      return stripped.split(/[;,]/).map((item) => item.trim()).filter(Boolean)
    }
    return [stripped]
  }
  return [String(value)]
}

function tradeDirectionSide(direction: string) {
  const normalized = String(direction).trim().toLowerCase()
  if (['long', 'buy', '多'].includes(normalized)) return 'long'
  if (['short', 'sell', '空'].includes(normalized)) return 'short'
  return normalized.includes('空') || normalized.includes('short') || normalized.includes('sell') ? 'short' : 'long'
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

function syncQuery(): Promise<void> {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return Promise.resolve()
  syncingQueryFromState = true
  return router.replace({
    name: 'market-chart',
    query: {
      symbol: selectedSymbol.value,
      contract: selectedActualContract.value,
      period: selectedPeriod.value,
      contract_view: contractView.value === defaultContractViewForPeriod(selectedPeriod.value || '') ? undefined : contractView.value,
      strategy: stringQuery(route.query.strategy) || undefined,
      report_id: stringQuery(route.query.report_id) || undefined,
      trade_id: stringQuery(route.query.trade_id) || undefined,
      trade_no: stringQuery(route.query.trade_no) || undefined,
      time: stringQuery(route.query.time) || undefined,
      profile_id: selectedProfileId.value || undefined,
      access_mode: accessMode.value === 'research' ? 'research' : undefined,
      data_mode: dataMode.value === 'live' ? 'live' : undefined,
    },
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

function numberFrom(value: unknown, fallback = 0) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function dayMs() {
  return 24 * 60 * 60 * 1000
}

function formatDate(value: number) {
  const item = new Date(value)
  const year = item.getFullYear()
  const month = String(item.getMonth() + 1).padStart(2, '0')
  const day = String(item.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
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

function apiError(err: unknown, fallback: string) {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string | { code?: string; message?: string } } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail?.message) return detail.code ? `${detail.code}: ${detail.message}` : detail.message
    return fallback
  }
  return err instanceof Error ? err.message : fallback
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
        <div class="chart-header__primary">
          <NButton quaternary size="small" @click="goBackToList">← 返回列表</NButton>
          <div class="chart-header__title">
            <strong>{{ selectedDominant?.product_name || selectedContractInfo?.name || selectedSymbol || '-' }}</strong>
            <span>{{ contractViewLabel }} · {{ selectedDominant?.exchange_name || selectedDominant?.exchange || selectedContractInfo?.exchange || '-' }}</span>
          </div>
          <div class="chart-header__modes">
            <NRadioGroup :value="contractView" size="small" @update:value="handleContractViewUpdate">
              <NRadioButton v-for="item in contractViewOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </NRadioButton>
            </NRadioGroup>
            <NRadioGroup :value="dataMode" size="small" @update:value="handleDataModeUpdate">
              <NRadioButton v-for="item in liveModeOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </NRadioButton>
            </NRadioGroup>
            <NRadioGroup :value="accessMode" size="small" :disabled="isLiveMode" @update:value="handleAccessModeUpdate">
              <NRadioButton v-for="item in accessModeOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </NRadioButton>
            </NRadioGroup>
            <NSelect
              class="profile-select"
              size="small"
              clearable
              filterable
              :disabled="isLiveMode"
              :options="profileOptions"
              :value="selectedProfileId"
              placeholder="未绑定 Profile"
              @update:value="handleProfileUpdate"
            />
          </div>
        </div>
        <div class="chart-header__secondary">
          <div class="chart-lineage">
            <NTag size="small" type="info">{{ barsCoverage?.provider || selectedItem?.provider || (isLiveMode ? 'live' : '-') }}</NTag>
            <NTag size="small">{{ barsCoverage?.data_role || selectedItem?.data_role || 'primary' }}</NTag>
            <NTag size="small" :type="qualityType(barsCoverage?.quality_status || quality?.status)">
              {{ barsCoverage?.quality_status || quality?.status || 'unknown' }}
            </NTag>
            <NTag size="small" :type="barsLineage?.strict_research_ready ? 'success' : 'warning'">
              {{ barsLineage?.strict_research_ready ? '严格研究可用' : '仅浏览观察' }}
            </NTag>
            <NEllipsis class="chart-lineage__version" :tooltip="{ width: 420 }">
              数据版本 {{ barsCoverage?.data_version || selectedItem?.data_version || '无 data_version' }}
            </NEllipsis>
            <span>来源周期 {{ barsLineage?.source_interval || '未证明' }}</span>
            <span>最新 {{ (barsCoverage?.latest_bar_time || selectedItem?.latest_bar_time || latestBar?.time || '-').replace('T', ' ').slice(0, 16) }}</span>
          </div>
          <div class="chart-header__actions">
            <NPopover trigger="click" placement="bottom-end" :show-arrow="false">
              <template #trigger>
                <NButton size="small">
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
            <NButton size="small" :type="showSignalLayer ? 'primary' : 'default'" @click="showSignalLayer = !showSignalLayer">
              信号层
            </NButton>
            <NDatePicker v-model:value="dateRange" type="daterange" clearable size="small" />
            <NButton size="small" :loading="loadingBars" @click="refreshBars">刷新</NButton>
          </div>
        </div>
      </section>

      <NAlert v-if="metaWarning" type="warning" :bordered="false">{{ metaWarning }}</NAlert>
      <NAlert v-if="qualityWarningMessage" type="warning" :bordered="false">{{ qualityWarningMessage }}</NAlert>
      <NAlert v-if="barsError" type="error" :bordered="false">{{ barsError }}</NAlert>
      <NAlert v-if="indicatorError" type="warning" :bordered="false">{{ indicatorError }}</NAlert>
      <NAlert v-if="macdError" type="warning" :bordered="false">{{ macdError }}</NAlert>

      <section class="quote-strip">
        <div>
          <span class="quote-strip__name">{{ selectedDominant?.product_name || selectedContractInfo?.name || selectedItem?.name || selectedSymbol || '-' }}</span>
          <span class="quote-strip__code">{{ contractViewLabel }} · {{ selectedDominant?.exchange || selectedContractInfo?.exchange || selectedItem?.exchange || '-' }}</span>
        </div>
        <strong :class="(priceChange || 0) >= 0 ? 'text-up' : 'text-down'">{{ formatNumber(latestBar?.close) }}</strong>
        <span :class="(priceChange || 0) >= 0 ? 'text-up' : 'text-down'">
          {{ priceChange === null ? '-' : formatNumber(priceChange) }}
          {{ priceChangePercent === null ? '' : `${priceChangePercent.toFixed(2)}%` }}
        </span>
        <span>成交量 {{ latestBar?.volume?.toLocaleString('zh-CN') || '-' }}</span>
        <span>持仓 {{ formatNumber(latestBar?.openInterest, 0) }}</span>
        <span>交易日 {{ latestBar?.trading_day || '-' }}</span>
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
          :loading="loadingBars || loadingLinkedReport"
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
        />
      </div>
    </main>

    <aside class="right-rail">
      <MarketStrategySidebar
        :is-live-mode="isLiveMode"
        :strategy-status="strategyStatus"
        :bars-count="bars.length"
        :signal-count="matchedSignals.length"
        :quality-status="barsCoverage?.quality_status || quality?.status || null"
        :selected-contract="selectedActualContract"
        :selected-period="selectedPeriod"
        :linked-report="linkedReport"
        :latest-signal="latestSignalForChart"
        :selected-event="selectedSignalEvent"
        :notification="selectedNotification"
        :notification-loading="loadingNotification"
        :notification-error="notificationError"
        @open-report="router.push({ name: 'backtest', query: { report_id: String(linkedReport?.id) } })"
        @open-signal="router.push({ name: 'signal' })"
      />

      <section v-if="matchedSignals.length" class="side-panel signal-list-panel">
        <div class="side-panel__title">
          <span>当前信号</span>
          <NTag size="small">{{ matchedSignals.length }}</NTag>
        </div>
        <button
          v-for="signal in matchedSignals"
          :key="signal.id"
          class="signal-list-item"
          :class="{ 'signal-list-item--active': selectedSignalId === signal.id }"
          @click="selectSignalFromList(signal)"
        >
          <span>
            <strong>{{ signalMarkerLabel(signal) }}</strong>
            {{ signal.strategy_code || signal.strategy_id }}
          </span>
          <small>{{ signal.entry_interval || signal.interval || signal.period }} · {{ signal.strategy_status }} · {{ formatNumber(signal.signal_price ?? signal.price ?? signal.current_price) }}</small>
        </button>
      </section>

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
          <span>rejected</span><strong>{{ (liveQuality?.rejected_count || 0).toLocaleString('zh-CN') }}</strong>
        </div>
        <small>Live 数据只用于显式观察，不进入默认回测或信号扫描。</small>
      </section>

      <section class="side-panel">
        <MarketRuntimeObservationPanel :context="runtimeObservationContext" />
      </section>

      <section v-if="linkedReport" class="side-panel">
        <div class="side-panel__title">
          <span>回测复盘</span>
          <NTag size="small" type="info">#{{ linkedReport.id }}</NTag>
        </div>
        <div class="snapshot-grid">
          <span>策略</span><strong>{{ linkedReport.strategy_code || '-' }}</strong>
          <span>周期</span><strong>{{ linkedReport.period }} / {{ selectedPeriod }}</strong>
          <span>交易数</span><strong>{{ linkedTrades.length.toLocaleString('zh-CN') }}</strong>
          <span>选中交易</span><strong>{{ linkedTrade?.trade_no || '-' }}</strong>
          <span>评分</span><strong>{{ tradeScoreLabel(linkedTrade) }}</strong>
          <span>条件</span><strong>{{ tradeConditionLabel(linkedTrade) }}</strong>
          <span>场景</span><strong>{{ tradeSceneLabel(linkedTrade) }}</strong>
          <span>入场原因</span><strong>{{ linkedTrade?.entry_reason || (linkedTrade ? tradeRawString(linkedTrade, 'entry_reason') : '-') }}</strong>
          <span>退出原因</span><strong>{{ linkedTrade?.exit_reason || (linkedTrade ? tradeRawString(linkedTrade, 'exit_reason') : '-') }}</strong>
        </div>
        <NButton size="small" secondary block @click="router.push({ name: 'backtest', query: { report_id: String(linkedReport.id) } })">
          返回报告详情
        </NButton>
        <NButton
          v-if="linkedTrade?.id"
          size="small"
          secondary
          block
          @click="router.push({ name: 'review', query: { report_id: String(linkedReport.id), trade_id: String(linkedTrade.id) } })"
        >
          返回交易复盘
        </NButton>
      </section>

      <section class="side-panel side-panel--research">
        <FuturesResearchPanel
          :symbol="selectedSymbol"
          :contract="selectedContract"
          :date-range="dateRange"
        />
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

      <section class="side-panel">
        <div class="side-panel__title">风控试算</div>
        <template v-if="riskDraft">
          <div class="snapshot-grid">
            <span>账户假设</span><strong>100,000</strong>
            <span>单笔风险</span><strong>{{ formatNumber(riskDraft.riskBudget) }}</strong>
            <span>ATR</span><strong>{{ formatNumber(riskDraft.atr) }}</strong>
            <span>多单止损</span><strong>{{ formatNumber(riskDraft.stopLong) }}</strong>
            <span>空单止损</span><strong>{{ formatNumber(riskDraft.stopShort) }}</strong>
          </div>
          <small>仅用于研究界面展示，正式仓位以后端风控接口为准。</small>
        </template>
        <div v-else class="empty-note">ATR 预热完成后显示风险参考。</div>
      </section>
    </aside>
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

.chart-header__primary,
.chart-header__secondary,
.chart-header__modes,
.chart-lineage {
  display: flex;
  align-items: center;
  min-width: 0;
}

.chart-header__primary,
.chart-header__secondary {
  width: 100%;
  gap: var(--gy-space-3);
}

.chart-header__primary {
  min-height: 30px;
}

.chart-header__secondary {
  justify-content: space-between;
  padding-top: var(--gy-space-2);
  border-top: 1px solid var(--gy-border-subtle);
}

.chart-header__title {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.chart-header__title strong {
  color: var(--gy-text-primary);
  font-weight: 700;
}

.chart-header__title span,
.chart-header__actions,
.chart-lineage {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}

.chart-header__modes,
.chart-header__actions,
.chart-lineage {
  gap: var(--gy-space-2);
}

.profile-select {
  width: 230px;
}

.chart-header__modes,
.chart-header__actions {
  flex: 0 0 auto;
}

.chart-lineage {
  flex: 1;
  overflow: hidden;
}

.chart-lineage > span,
.chart-lineage__version {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chart-lineage__version {
  flex: 1;
  min-width: 0;
  max-width: 360px;
}

.chart-header__actions {
  display: flex;
  align-items: center;
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

.right-rail,
.center-stage {
  min-width: 0;
}

.right-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
  max-height: calc(100vh - var(--gy-header-height) - (var(--gy-content-padding) * 2));
  padding-right: 3px;
  overflow-y: auto;
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
  grid-template-columns: minmax(180px, 1fr) 120px 130px repeat(3, minmax(110px, auto));
  align-items: center;
  gap: var(--gy-space-3);
  min-height: 74px;
  padding: 12px 14px;
  color: var(--gy-text-secondary);
}

.quote-strip > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quote-strip strong {
  font-size: 28px;
  font-family: var(--gy-font-mono);
  font-variant-numeric: tabular-nums;
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
    grid-template-columns: minmax(150px, 1fr) 110px 110px repeat(3, minmax(92px, auto));
  }

  .chart-lineage span:nth-last-child(n + 2) {
    display: none;
  }
}

@media (max-width: 1199px) {
  .market-chart-workbench {
    grid-template-columns: minmax(0, 1fr);
  }

  .right-rail {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: none;
    overflow: visible;
  }

  .chart-header__primary,
  .chart-header__secondary {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .chart-header__modes {
    margin-left: auto;
  }

  .chart-lineage {
    width: 100%;
    flex: 1 1 100%;
    flex-wrap: wrap;
  }

  .chart-header__actions {
    width: 100%;
    justify-content: flex-end;
  }

  .quote-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .quote-strip > div {
    grid-column: span 1;
  }

  .kline-chart-host {
    min-height: 560px;
  }
}

@media (max-width: 760px) {
  .right-rail,
  .quote-strip {
    grid-template-columns: 1fr;
  }
}
</style>
