<script setup lang="ts">
/**
 * 行情 K 线工作台：canonical 历史模式、viewport 懒加载与主图指标。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCheckbox, NDatePicker, NPopover, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import MarketContextBar from '@/components/market/MarketContextBar.vue'
import MarketDataQualityCard from '@/components/market/MarketDataQualityCard.vue'
import MarketEvidenceDrawer from '@/components/market/MarketEvidenceDrawer.vue'
import MarketEvidenceStrip from '@/components/market/MarketEvidenceStrip.vue'
import { getCanonicalMarketCoverage, getMarketBars, getMarketDominants, getMarketIndicators, getMarketMacdIndicator } from '@/api/market'
import type {
  BarData,
  ChartOverlay,
  DominantContractItem,
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
  MAX_BARS_PER_REQUEST,
  dedupeBarsByPeriod,
  mergeBarsByTime,
  resolveContractForView,
  resolveInitialBarsQuery,
  trimBarsToMaxCount,
  type ViewportLoadRequest,
} from '@/utils/marketChartWindow'
import { applyRouteSelectionFromQuery } from '@/utils/marketChartInit'
import {
  buildMarketQualityImpact,
  type MarketQualityAction,
} from '@/utils/marketQualityPresentation'
import { resolveActualContract } from '@/utils/marketContract'
import { resolveChartTheme } from '@/styles/chartTheme'
import {
  buildMarketChartRouteQuery,
  safeMarketApiError,
} from '@/utils/marketChartQuery'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const chartTheme = resolveChartTheme()

type MarketDataQualityCardExpose = {
  focus: () => void
}

type BarsLoadMode = 'viewport' | 'explicit'

interface LoadBarsOptions {
  viewportWindow?: ViewportLoadRequest
  merge?: boolean
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
const quality = ref<MarketBarsQuality | null>(null)
const barsCoverage = ref<MarketBarsCoverage | null>(null)
const barsLineage = ref<MarketReadLineage | null>(null)
const macdOverride = ref<MarketMacdIndicatorResponse | null>(null)
const macdError = ref<string | null>(null)

const selectedSymbol = ref<string | null>(null)
const selectedActualContract = ref<string | null>(null)
const contractView = ref<ContractViewMode>('actual')
const selectedPeriod = ref<string | null>(null)
const accessMode = ref<MarketAccessMode>(route.query.access_mode === 'research' ? 'research' : 'browser')
const chartPreferences = loadMainChartPreferences()
const visibleMainIndicators = ref<MainIndicatorId[]>(
  filterVisibleMainIndicatorsForMode(chartPreferences.visibleMainIndicators, {
    dataMode: 'historical',
    accessMode: accessMode.value,
  }),
)
const mainIndicatorSeries = ref<MainIndicatorSeries[]>([])
const realtimeFollowPreference = ref(Boolean(chartPreferences.realtimeFollow))
const dateRange = ref<[number, number] | null>(null)
const barsLoadMode = ref<BarsLoadMode>('viewport')
const chartFitContent = ref(true)
const viewportLoadEnabled = ref(false)
const qualityCardRef = ref<MarketDataQualityCardExpose | null>(null)
const evidenceDrawerOpen = ref(false)
/** 路由/K 线请求序号，丢弃过期异步结果 */
let marketRouteRequestId = 0
let macdRequestId = 0
let syncingQueryFromState = false
let viewportLoadTimer: ReturnType<typeof setTimeout> | null = null

const coverageItems = computed(() => coverage.value?.items || [])
const canonicalDatasetKind = computed<'continuous' | 'actual_dominant'>(() =>
  isContinuousView.value ? 'continuous' : 'actual_dominant',
)
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
      (available.size > 0 ? !available.has(item.value) : false),
  }))
})

const latestBar = computed(() => bars.value.at(-1) || null)
const previousBar = computed(() => (bars.value.length >= 2 ? bars.value.at(-2) || null : null))
const chartMarkers = computed(() => [])
const priceChange = computed(() => (latestBar.value && previousBar.value ? latestBar.value.close - previousBar.value.close : null))
const priceChangePercent = computed(() => {
  if (!latestBar.value || !previousBar.value || previousBar.value.close === 0) return null
  return ((latestBar.value.close - previousBar.value.close) / previousBar.value.close) * 100
})
const mainIndicatorDefinitions = MAIN_INDICATOR_DEFINITIONS
const mainIndicatorLatestValues = computed(() => latestMainIndicatorValues(mainIndicatorSeries.value, visibleMainIndicators.value))
const visibleMainIndicatorSet = computed(() => new Set(visibleMainIndicators.value))
const mainIndicatorModeContext = computed(() => ({
  dataMode: 'historical' as const,
  accessMode: accessMode.value,
}))
const mainIndicatorStatusText = computed(() => {
  if (loadingIndicators.value) return '统一 EMA 计算中（前端展示计算 · 非 StrategySignal）'
  if (indicatorError.value) return '统一 EMA 加载失败'
  if (!visibleMainIndicators.value.length) return '主图指标已关闭'
  return '统一 EMA · 前端展示计算 · 非 StrategySignal'
})
const crossFileConflictCount = computed(() =>
  'cross_file_conflicts' in (quality.value || {})
    ? (quality.value as MarketBarsQuality).cross_file_conflicts || 0
    : 0,
)
const qualityImpact = computed(() => {
  const historicalQuality = quality.value
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
    canonicalIdentity: true,
    strictResearchReady: Boolean(barsLineage.value?.strict_research_ready),
    contractView: contractView.value,
    dataMode: 'historical',
    lineageReady: !hasHistoricalResponse ? null : Boolean(barsLineage.value),
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
  // 缺少 symbol 时回列表页；actual contract 可由既有 dominant resolver 解析。
  if (!route.query.symbol) {
    void router.replace({ name: 'market' })
    return
  }
  void initializeChartPage()
})

onBeforeUnmount(() => {
  if (viewportLoadTimer) clearTimeout(viewportLoadTimer)
})

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
    route.query.time,
    route.query.datetime,
  ],
  () => {
    if (syncingQueryFromState) return
    if (selectionMatchesRoute()) return
    const requestId = ++marketRouteRequestId
    applyRouteSelectionFromQueryToState()
    void loadScopedCoverage()
    void applyRouteSelectionAndLoad(requestId)
  },
)

async function loadScopedCoverage() {
  loadingMeta.value = true
  metaWarning.value = null
  try {
    coverage.value = await getCanonicalMarketCoverage(selectedSymbol.value || 'jm')
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
 * 核心 K 线加载：支持 viewport 合并、lineage 冲突 fail-closed。
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
    const historicalParams = buildBarsRequest(options.viewportWindow)
    if (!historicalParams) {
      bars.value = []
      clearMarketMacd()
      return
    }
    const response = await getMarketBars(historicalParams)
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
      response.quality?.status === 'warning' || crossFileConflictCount > 0
        ? response.message || '数据质量 warning，仅供观察，不可用于严格研究/回测/信号'
        : null
    if (!options.merge) {
      await loadMarketIndicators(requestId)
      if (bars.value.length > 0) {
        const macdParams = buildMacdRequestParams()
        if (macdParams) await loadMarketMacdIndicator(requestId, macdParams)
      }
    }
    if (!options.merge) {
      syncQuery()
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
    }
  } finally {
    if (isCurrentMarketRoute(requestId)) loadingBars.value = false
  }
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
    (routeView === contractView.value || (!routeView && contractView.value === defaultContractViewForPeriod(selectedPeriod.value || ''))) &&
    queryPeriod() === selectedPeriod.value
  )
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
      },
      {
        strategy: stringQuery(route.query.strategy),
        time: stringQuery(route.query.time),
        datetime: stringQuery(route.query.datetime),
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

function formatBarsRequestTime(value: number) {
  return new Date(value).toISOString()
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return '-'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
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
          :contract-view="contractView"
          @back="goBackToList"
          @update:contract-view="handleContractViewUpdate"
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
          :bars="bars"
          :markers="chartMarkers"
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
          @visible-range-change="handleVisibleRangeChange"
          @quality-details="focusQualityCard"
        />
      </div>
    </main>

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
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
  min-width: 0;
  min-height: calc(100vh - var(--gy-header-height) - (var(--gy-content-padding) * 2));
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

.quote-strip__code {
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

@media (min-width: 1200px) and (max-width: 1439px) {
  .quote-strip {
    grid-template-columns: minmax(138px, 1fr) minmax(132px, auto) repeat(3, minmax(68px, auto));
  }
}

@media (max-width: 1199px) {
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
