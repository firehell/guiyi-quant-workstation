<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NDatePicker, NSelect, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import { describeBacktestApiError, fetchAllBacktestReportTrades, getBacktestReport } from '@/api/backtestApi'
import { getMarketBars, getMarketWorkbenchCoverage } from '@/api/market'
import type { BacktestReport, BacktestTrade } from '@/types/backtest'
import type {
  BarData,
  ChartOverlay,
  HoverKlineContext,
  KlineMarker,
  MarketBarsCoverage,
  MarketBarsQuality,
  MarketCoverageItem,
  MarketWorkbenchCoverage,
} from '@/types/market'
import { calculateATR, calculateEMA } from '@/utils/indicators'
import { PERIODS } from '@/utils/constants'
import { formatTradeMarkerText } from '@/utils/tradeMarker'

const route = useRoute()
const router = useRouter()
const message = useMessage()

type KlineChartExpose = {
  focusTime: (value: string) => void
}

const loadingMeta = ref(false)
const loadingBars = ref(false)
const loadingLinkedReport = ref(false)
const error = ref<string | null>(null)
const coverage = ref<MarketWorkbenchCoverage | null>(null)
const bars = ref<BarData[]>([])
const quality = ref<MarketBarsQuality | null>(null)
const barsCoverage = ref<MarketBarsCoverage | null>(null)
const hoverContext = ref<HoverKlineContext | null>(null)

const selectedSymbol = ref<string | null>(null)
const selectedContract = ref<string | null>(null)
const selectedPeriod = ref<string | null>(null)
const dateRange = ref<[number, number] | null>(null)
const klineChartRef = ref<KlineChartExpose | null>(null)
const linkedReport = ref<BacktestReport | null>(null)
const linkedTrades = ref<BacktestTrade[]>([])
const activeMarkerId = ref<string | null>(null)
let marketRouteRequestId = 0
let syncingQueryFromState = false

const coverageItems = computed(() => coverage.value?.items || [])
const selectedItem = computed(() =>
  coverageItems.value.find(
    (item) => item.symbol === selectedSymbol.value && item.contract === selectedContract.value && item.period === selectedPeriod.value,
  ),
)
const selectedInstrument = computed(() => coverage.value?.instruments.find((item) => item.symbol === selectedSymbol.value))
const selectedContractInfo = computed(() => selectedInstrument.value?.contracts.find((item) => item.contract === selectedContract.value))

const instrumentOptions = computed(() =>
  (coverage.value?.instruments || []).map((item) => ({
    label: `${item.name || item.symbol} (${item.symbol})`,
    value: item.symbol,
  })),
)

const contractOptions = computed(() =>
  (selectedInstrument.value?.contracts || []).map((item) => ({
    label: `${item.name || item.contract} · ${item.exchange || '-'}`,
    value: item.contract,
  })),
)

const periodOptions = computed(() =>
  (selectedContractInfo.value?.periods || []).map((item) => ({
    label: periodLabel(item.period),
    value: item.period,
  })),
)

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
const priceChange = computed(() => (latestBar.value && previousBar.value ? latestBar.value.close - previousBar.value.close : null))
const priceChangePercent = computed(() => {
  if (!latestBar.value || !previousBar.value || previousBar.value.close === 0) return null
  return ((latestBar.value.close - previousBar.value.close) / previousBar.value.close) * 100
})

const chartOverlays = computed<ChartOverlay[]>(() => {
  if (!latestBar.value) return []
  const recent = bars.value.slice(-20)
  const ema21 = calculateEMA(bars.value, 21).at(-1)?.value
  const high20 = recent.length ? Math.max(...recent.map((bar) => bar.high)) : null
  const low20 = recent.length ? Math.min(...recent.map((bar) => bar.low)) : null
  const overlays: ChartOverlay[] = [
    { id: 'last-close', type: 'price_line', price: latestBar.value.close, label: '最新价', color: '#ef4444', lineStyle: 'dashed' },
  ]
  if (ema21) overlays.push({ id: 'ema21', type: 'price_line', price: ema21, label: 'EMA21', color: '#f59e0b', lineStyle: 'dotted' })
  if (high20) overlays.push({ id: 'high20', type: 'price_line', price: high20, label: '20高', color: '#ec4899', lineStyle: 'dotted' })
  if (low20) overlays.push({ id: 'low20', type: 'price_line', price: low20, label: '20低', color: '#22c55e', lineStyle: 'dotted' })
  return overlays
})

const strategyStatus = computed(() => {
  if (!latestBar.value) return { label: '等待数据', type: 'default' as const, text: '选择品种和周期后加载 K 线。' }
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

onMounted(async () => {
  await loadCoverage()
})

watch(
  () => [
    route.query.report_id,
    route.query.trade_id,
    route.query.trade_no,
    route.query.symbol,
    route.query.contract,
    route.query.period,
    route.query.interval,
    route.query.time,
    route.query.datetime,
  ],
  () => {
    if (syncingQueryFromState || !coverage.value) return
    void applyRouteSelectionAndLoad()
  },
)

async function loadCoverage() {
  loadingMeta.value = true
  error.value = null
  try {
    coverage.value = await getMarketWorkbenchCoverage()
    await applyRouteSelectionAndLoad()
  } catch (err) {
    error.value = apiError(err, '加载行情工作台元数据失败')
  } finally {
    loadingMeta.value = false
  }
}

async function applyRouteSelectionAndLoad() {
  const requestId = ++marketRouteRequestId
  const linkedSelectionApplied = await applyLinkedReportSelection(requestId)
  if (!isCurrentMarketRoute(requestId)) return
  if (!linkedSelectionApplied) applyInitialSelection()
  await loadBars(requestId)
}

async function loadBars(requestId = marketRouteRequestId) {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) {
    bars.value = []
    return
  }
  loadingBars.value = true
  error.value = null
  try {
    const response = await getMarketBars({
      symbol: selectedSymbol.value,
      contract: selectedContract.value,
      period: selectedPeriod.value,
      provider: selectedItem.value?.provider,
      start: dateRange.value ? formatDate(dateRange.value[0]) : undefined,
      end: dateRange.value ? formatDate(dateRange.value[1]) : undefined,
      limit: 10000,
    })
    if (!isCurrentMarketRoute(requestId)) return
    bars.value = response.bars
    quality.value = response.quality
    barsCoverage.value = response.coverage || null
    hoverContext.value = response.bars.at(-1)
      ? {
          time: response.bars.at(-1)!.time,
          bar: response.bars.at(-1)!,
        }
      : null
    syncQuery()
    await focusLinkedTradeMarker()
    if (response.bars.length === 0) message.warning(response.message || '当前选择没有可展示的 K 线')
  } catch (err) {
    if (!isCurrentMarketRoute(requestId)) return
    error.value = apiError(err, 'K 线加载失败')
    bars.value = []
    quality.value = null
    barsCoverage.value = null
  } finally {
    if (isCurrentMarketRoute(requestId)) loadingBars.value = false
  }
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
    selectedContract.value = report.contract
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
  const querySelection = findCoverageItem(
    stringQuery(route.query.symbol),
    stringQuery(route.query.contract),
    queryPeriod(),
  )
  const defaults = coverage.value?.default_selection
  const fallback = defaults ? findCoverageItem(defaults.symbol, defaults.contract, defaults.period) : coverageItems.value[0]
  const selected = querySelection || fallback
  if (!selected) return
  selectedSymbol.value = selected.symbol
  selectedContract.value = selected.contract
  selectedPeriod.value = selected.period
  syncDateRange(selected)
  const focusTime = queryTime()
  if (focusTime) {
    const focus = new Date(focusTime).getTime()
    if (!Number.isNaN(focus)) dateRange.value = [focus - 3 * dayMs(), focus + 3 * dayMs()]
  }
}

async function focusLinkedTradeMarker() {
  if (!linkedTrade.value) return
  activeMarkerId.value = markerId(linkedTrade.value, 'open')
  await nextTick()
  klineChartRef.value?.focusTime(nearestBarTime(linkedTrade.value.open_time))
}

function handleSymbolUpdate(value: string) {
  marketRouteRequestId += 1
  selectedSymbol.value = value
  const firstContract = selectedInstrument.value?.contracts[0]
  selectedContract.value = firstContract?.contract || null
  selectedPeriod.value = firstContract?.periods.find((item) => item.period === '5m')?.period || firstContract?.periods[0]?.period || null
  syncDateRange(selectedItem.value)
  void loadBars()
}

function handleContractUpdate(value: string) {
  marketRouteRequestId += 1
  selectedContract.value = value
  selectedPeriod.value = selectedContractInfo.value?.periods.find((item) => item.period === '5m')?.period || selectedContractInfo.value?.periods[0]?.period || null
  syncDateRange(selectedItem.value)
  void loadBars()
}

function handlePeriodUpdate(value: string) {
  marketRouteRequestId += 1
  selectedPeriod.value = value
  syncDateRange(selectedItem.value)
  void loadBars()
}

function refreshBars() {
  marketRouteRequestId += 1
  void loadBars()
}

function syncDateRange(item: MarketCoverageItem | null | undefined) {
  if (!item) return
  const end = new Date(item.end_time).getTime()
  const start = Math.max(new Date(item.start_time).getTime(), end - 90 * dayMs())
  dateRange.value = [start, end]
}

function findCoverageItem(symbol?: string | null, contract?: string | null, period?: string | null) {
  if (!symbol || !contract || !period) return null
  return coverageItems.value.find((item) => item.symbol === symbol && item.contract === contract && item.period === period) || null
}

function queryPeriod() {
  return stringQuery(route.query.period) || stringQuery(route.query.interval)
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
      tooltip: `${isLong ? '开多' : '开空'} ${trade.trade_no}${interval ? ` ${interval}` : ''} @ ${formatNumber(trade.open_price)} / ${trade.entry_reason || tradeRawString(trade, 'entry_reason') || '-'}`,
      color: isLong ? '#ef4444' : '#22c55e',
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

function markerId(trade: BacktestTrade, side: 'open' | 'close') {
  return `trade-${trade.trade_no}-${side}`
}

function tradeEntryInterval(trade: BacktestTrade) {
  return tradeRawString(trade, 'entry_interval')
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
  return { label: '普通退出', color: tradeDirectionSide(trade.direction) === 'long' ? '#22c55e' : '#ef4444', shape: tradeDirectionSide(trade.direction) === 'long' ? 'arrowDown' as const : 'arrowUp' as const }
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
  const value = trade.raw_payload?.[key]
  return value === undefined || value === null ? '' : String(value)
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

function syncQuery() {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) return
  syncingQueryFromState = true
  void router.replace({
    name: 'market',
    query: {
      symbol: selectedSymbol.value,
      contract: selectedContract.value,
      period: selectedPeriod.value,
      strategy: stringQuery(route.query.strategy) || undefined,
      report_id: stringQuery(route.query.report_id) || undefined,
      trade_id: stringQuery(route.query.trade_id) || undefined,
      trade_no: stringQuery(route.query.trade_no) || undefined,
      time: stringQuery(route.query.time) || undefined,
    },
  }).finally(() => {
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

function periodLabel(period: string) {
  return PERIODS.find((item) => item.value === period)?.label || period
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
    const response = (err as { response?: { data?: { detail?: string } } }).response
    return response?.data?.detail || fallback
  }
  return err instanceof Error ? err.message : fallback
}
</script>

<template>
  <div class="market-workbench">
    <aside class="left-rail">
      <div class="rail-title">
        <strong>K线工作台</strong>
        <span>数据 · 策略 · 复盘</span>
      </div>
      <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
      <div class="control-block">
        <label>品种</label>
        <NSelect
          :value="selectedSymbol"
          :options="instrumentOptions"
          :loading="loadingMeta"
          filterable
          placeholder="选择品种"
          @update:value="handleSymbolUpdate"
        />
      </div>
      <div class="control-block">
        <label>合约</label>
        <NSelect
          :value="selectedContract"
          :options="contractOptions"
          :loading="loadingMeta"
          placeholder="选择合约"
          @update:value="handleContractUpdate"
        />
      </div>
      <div class="control-block">
        <label>周期</label>
        <NSelect :value="selectedPeriod" :options="periodOptions" placeholder="选择周期" @update:value="handlePeriodUpdate" />
      </div>
      <div class="control-block">
        <label>日期窗口</label>
        <NDatePicker v-model:value="dateRange" type="daterange" clearable />
      </div>
      <NButton type="primary" block :loading="loadingBars" @click="refreshBars">刷新 K 线</NButton>

      <div class="data-card">
        <span>数据质量</span>
        <NTag size="small" :type="qualityType(quality?.status || selectedItem?.quality_status)">
          {{ quality?.status || selectedItem?.quality_status || '-' }}
        </NTag>
        <small>{{ barsCoverage?.provider || selectedItem?.provider || '-' }} · {{ barsCoverage?.data_type || selectedItem?.data_type || '-' }}</small>
        <small>覆盖 {{ selectedItem ? formatDate(new Date(selectedItem.start_time).getTime()) : '-' }} → {{ selectedItem ? formatDate(new Date(selectedItem.end_time).getTime()) : '-' }}</small>
        <small>行数 {{ (barsCoverage?.row_count || selectedItem?.row_count || 0).toLocaleString('zh-CN') }}</small>
      </div>
    </aside>

    <main class="center-stage">
      <section class="quote-strip">
        <div>
          <span class="quote-strip__name">{{ selectedContractInfo?.name || selectedItem?.name || selectedSymbol || '-' }}</span>
          <span class="quote-strip__code">{{ selectedContract }} · {{ selectedContractInfo?.exchange || selectedItem?.exchange || '-' }}</span>
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

      <KlineChart
        ref="klineChartRef"
        :bars="bars"
        :markers="backtestMarkers"
        :active-marker-id="activeMarkerId"
        :overlays="chartOverlays"
        :loading="loadingBars || loadingMeta || loadingLinkedReport"
        :error="error"
        @hover="hoverContext = $event"
      />
    </main>

    <aside class="right-rail">
      <section class="side-panel">
        <div class="side-panel__title">
          <span>策略状态</span>
          <NTag size="small" :type="strategyStatus.type">{{ strategyStatus.label }}</NTag>
        </div>
        <p>{{ strategyStatus.text }}</p>
        <div class="signal-row">
          <span>策略</span>
          <strong>{{ stringQuery(route.query.strategy) || '苏冰 EMA21 V1' }}</strong>
        </div>
        <div class="signal-row">
          <span>K线数量</span>
          <strong>{{ bars.length.toLocaleString('zh-CN') }}</strong>
        </div>
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
          <span>入场原因</span><strong>{{ linkedTrade?.entry_reason || (linkedTrade ? tradeRawString(linkedTrade, 'entry_reason') : '-') }}</strong>
          <span>退出原因</span><strong>{{ linkedTrade?.exit_reason || (linkedTrade ? tradeRawString(linkedTrade, 'exit_reason') : '-') }}</strong>
        </div>
        <NButton size="small" secondary block @click="router.push({ name: 'backtest', query: { report_id: String(linkedReport.id) } })">
          返回报告详情
        </NButton>
      </section>

      <section class="side-panel">
        <div class="side-panel__title">十字线快照</div>
        <template v-if="hoverContext">
          <div class="snapshot-grid">
            <span>时间</span><strong>{{ hoverContext.time.replace('T', ' ').slice(0, 16) }}</strong>
            <span>开高低收</span><strong>{{ formatNumber(hoverContext.bar.open) }} / {{ formatNumber(hoverContext.bar.high) }} / {{ formatNumber(hoverContext.bar.low) }} / {{ formatNumber(hoverContext.bar.close) }}</strong>
            <span>EMA21</span><strong>{{ formatNumber(hoverContext.ema21) }}</strong>
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
.market-workbench {
  display: grid;
  grid-template-columns: 280px minmax(680px, 1fr) 300px;
  gap: 12px;
  min-width: 0;
}

.left-rail,
.right-rail,
.center-stage {
  min-width: 0;
}

.left-rail,
.right-rail {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.left-rail,
.side-panel,
.quote-strip {
  background: #11151c;
  border: 1px solid #252b36;
  border-radius: 6px;
}

.left-rail {
  padding: 14px;
}

.rail-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rail-title strong,
.quote-strip__name {
  color: #f3f4f6;
  font-weight: 700;
}

.rail-title span,
.quote-strip__code,
.control-block label,
.data-card small,
.side-panel p,
.empty-note,
.side-panel small {
  color: #8f9aaa;
}

.control-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.control-block label {
  font-size: 12px;
}

.data-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: #171b22;
  border: 1px solid #28303b;
  border-radius: 6px;
}

.center-stage {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quote-strip {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 120px 130px repeat(3, minmax(110px, auto));
  align-items: center;
  gap: 12px;
  min-height: 74px;
  padding: 12px 14px;
  color: #a8b3c4;
}

.quote-strip > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quote-strip strong {
  font-size: 28px;
  font-variant-numeric: tabular-nums;
}

.text-up {
  color: #ef4444;
}

.text-down {
  color: #22c55e;
}

.side-panel {
  padding: 12px;
}

.side-panel__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  color: #e5e7eb;
  font-weight: 700;
}

.signal-row,
.snapshot-grid {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 8px;
  color: #9aa4b2;
  font-size: 12px;
}

.signal-row {
  padding-top: 8px;
}

.snapshot-grid strong,
.signal-row strong {
  min-width: 0;
  color: #e5e7eb;
  font-weight: 600;
}

@media (max-width: 1280px) {
  .market-workbench {
    grid-template-columns: 260px minmax(620px, 1fr);
  }

  .right-rail {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
