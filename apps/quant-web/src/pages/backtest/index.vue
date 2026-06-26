<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import {
  NAlert,
  NButton,
  NDataTable,
  NDatePicker,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInputNumber,
  NSelect,
  NSwitch,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import BaseChart from '@/components/charts/BaseChart.vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getContracts, getCoverage } from '@/api/data'
import { getKlines } from '@/api/market'
import { runBacktest } from '@/api/strategy'
import type { ContractInfo, CoverageInfo } from '@/types/data'
import type { BarData, KlineMarker } from '@/types/market'
import type { BacktestFill, BacktestReportPayload, BacktestTrade } from '@/types/strategy'
import { PERIODS } from '@/utils/constants'

interface CoverageOption {
  symbol: string
  contract: string
  exchange: string
  period: string
  startTime: string
  endTime: string
  rowCount: number
  qualityStatus: string
}

interface KlineChartExpose {
  focusTime: (time: string) => void
}

const message = useMessage()
const router = useRouter()
const chartRef = ref<KlineChartExpose | null>(null)
const loadingMeta = ref(false)
const running = ref(false)
const loadingBars = ref(false)
const error = ref<string | null>(null)
const contracts = ref<ContractInfo[]>([])
const coverage = ref<CoverageOption[]>([])
const bars = ref<BarData[]>([])
const report = ref<BacktestReportPayload | null>(null)
const selectedTrade = ref<BacktestTrade | null>(null)
const detailVisible = ref(false)
const activeMarkerId = ref<string | null>(null)

const selectedSymbol = ref<string | null>(null)
const selectedContract = ref<string | null>(null)
const selectedPeriod = ref<string | null>(null)
const dateRange = ref<[number, number] | null>(null)
const initialCapital = ref(100000)
const riskPerTradePct = ref(1)
const maxMarginUsagePct = ref(35)
const slippageTicks = ref(1)
const enableTakeProfit = ref(true)
const allowWarningQuality = ref(false)

const instrumentOptions = computed(() => {
  const symbols = new Map<string, CoverageOption>()
  coverage.value.forEach((item) => {
    if (!symbols.has(item.symbol)) symbols.set(item.symbol, item)
  })
  return [...symbols.values()].map((item) => ({
    label: `${contractName(item.contract) || item.symbol} (${item.symbol})`,
    value: item.symbol,
  }))
})

const contractOptions = computed(() => {
  const items = coverage.value.filter((item) => item.symbol === selectedSymbol.value)
  const contractsByCode = new Map<string, CoverageOption>()
  items.forEach((item) => {
    if (!contractsByCode.has(item.contract)) contractsByCode.set(item.contract, item)
  })
  return [...contractsByCode.values()].map((item) => ({
    label: `${contractName(item.contract) || item.contract} · ${item.exchange}`,
    value: item.contract,
  }))
})

const periodOptions = computed(() => {
  const available = new Set(
    coverage.value
      .filter((item) => item.symbol === selectedSymbol.value && item.contract === selectedContract.value)
      .map((item) => item.period),
  )
  return PERIODS.filter((period) => available.has(period.value)).map((period) => ({
    label: period.label,
    value: period.value,
  }))
})

const selectedCoverage = computed(() =>
  coverage.value.find(
    (item) =>
      item.symbol === selectedSymbol.value &&
      item.contract === selectedContract.value &&
      item.period === selectedPeriod.value,
  ),
)

const markerData = computed<KlineMarker[]>(() => {
  if (!report.value) return []
  return report.value.fills.map((fill) => ({
    id: fill.fill_id,
    time: fill.time,
    label: markerLabel(fill),
    color: markerColor(fill),
    position: markerPosition(fill),
    shape: markerShape(fill),
  }))
})

const equityOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 24, right: 28, bottom: 32, left: 54 },
  xAxis: {
    type: 'category',
    data: report.value?.equity_curve.map((point) => shortTime(point.time)) || [],
    axisLabel: { color: '#94a3b8' },
  },
  yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1f2937' } } },
  series: [
    {
      type: 'line',
      name: '权益',
      smooth: true,
      showSymbol: false,
      data: report.value?.equity_curve.map((point) => round(point.equity)) || [],
      areaStyle: { color: 'rgba(56, 189, 248, 0.14)' },
      lineStyle: { color: '#38bdf8', width: 2 },
    },
  ],
}))

const drawdownOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 24, right: 28, bottom: 32, left: 54 },
  xAxis: {
    type: 'category',
    data: report.value?.drawdown_curve.map((point) => shortTime(point.time)) || [],
    axisLabel: { color: '#94a3b8' },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#94a3b8', formatter: (value: number) => `${(value * 100).toFixed(1)}%` },
    splitLine: { lineStyle: { color: '#1f2937' } },
  },
  series: [
    {
      type: 'line',
      name: '回撤',
      showSymbol: false,
      data: report.value?.drawdown_curve.map((point) => round(point.drawdown_pct)) || [],
      areaStyle: { color: 'rgba(248, 113, 113, 0.12)' },
      lineStyle: { color: '#f87171', width: 2 },
    },
  ],
}))

const marginOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 24, right: 28, bottom: 32, left: 54 },
  xAxis: {
    type: 'category',
    data: report.value?.equity_curve.map((point) => shortTime(point.time)) || [],
    axisLabel: { color: '#94a3b8' },
  },
  yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1f2937' } } },
  series: [
    {
      type: 'bar',
      name: '保证金占用',
      data: report.value?.equity_curve.map((point) => round(point.margin_used)) || [],
      itemStyle: { color: '#a78bfa' },
    },
  ],
}))

const selectedOpenFill = computed(() => findNearestFill(selectedTrade.value?.open_time, ['open', 'add']))
const selectedCloseFill = computed(() => findNearestFill(selectedTrade.value?.close_time, ['reduce', 'exit']))

const tradeColumns: DataTableColumns<BacktestTrade> = [
  {
    title: '交易',
    key: 'trade_no',
    width: 112,
    render: (row) => h('button', { class: 'link-button', onClick: () => openTrade(row) }, row.trade_no),
  },
  {
    title: '方向',
    key: 'direction',
    width: 72,
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.direction === 'long' ? 'error' : 'success' },
        { default: () => (row.direction === 'long' ? '多' : '空') },
      ),
  },
  { title: '开仓时间', key: 'open_time', render: (row) => formatDateTime(row.open_time) },
  { title: '平仓时间', key: 'close_time', render: (row) => formatDateTime(row.close_time) },
  { title: '手数', key: 'volume', width: 70 },
  { title: '开仓价', key: 'open_price', render: (row) => formatNumber(row.open_price) },
  { title: '平仓价', key: 'close_price', render: (row) => formatNumber(row.close_price) },
  {
    title: '净盈亏',
    key: 'net_pnl',
    render: (row) => h('span', { class: row.net_pnl >= 0 ? 'text-up' : 'text-down' }, formatMoney(row.net_pnl)),
  },
  { title: '手续费', key: 'commission', render: (row) => formatMoney(row.commission) },
  { title: '滑点', key: 'slippage', render: (row) => formatMoney(row.slippage) },
]

onMounted(async () => {
  await loadMeta()
})

async function loadMeta() {
  loadingMeta.value = true
  error.value = null
  try {
    const [contractRows, coverageRows] = await Promise.all([getContracts(), getCoverage()])
    contracts.value = contractRows
    coverage.value = normalizeCoverage(coverageRows)
    pickDefaultSelection()
  } catch (err) {
    error.value = apiError(err, '加载回测元数据失败')
  } finally {
    loadingMeta.value = false
  }
}

async function runReport() {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value || !dateRange.value) {
    message.warning('请先选择完整回测参数')
    return
  }
  running.value = true
  loadingBars.value = true
  error.value = null
  selectedTrade.value = null
  activeMarkerId.value = null
  try {
    const start = formatDate(dateRange.value[0])
    const end = formatDate(dateRange.value[1])
    const [backtestRows, klineRows] = await Promise.all([
      runBacktest({
        symbol: selectedSymbol.value,
        contract: selectedContract.value,
        period: selectedPeriod.value,
        start,
        end,
        initial_capital: initialCapital.value,
        risk_per_trade_pct: riskPerTradePct.value / 100,
        max_margin_usage_pct: maxMarginUsagePct.value / 100,
        slippage_ticks: slippageTicks.value,
        take_profit_r: 2,
        enable_take_profit: enableTakeProfit.value,
        allow_warning_quality: allowWarningQuality.value,
      }),
      getKlines({
        symbol: selectedSymbol.value,
        contract: selectedContract.value,
        period: selectedPeriod.value,
        start,
        end,
        limit: 10000,
      }),
    ])
    report.value = backtestRows
    bars.value = klineRows
    if (backtestRows.trades.length === 0) message.info('本次回测没有形成闭合交易')
  } catch (err) {
    error.value = apiError(err, '回测运行失败')
    report.value = null
  } finally {
    running.value = false
    loadingBars.value = false
  }
}

function normalizeCoverage(rows: CoverageInfo[]): CoverageOption[] {
  return rows
    .filter((row) => row.file_path.includes('/canonical/bars/') && row.quality_status !== 'failed')
    .map((row) => ({
      symbol: row.instrument_symbol || '',
      contract: row.contract_code || '',
      exchange: extractPartition(row.file_path, 'exchange') || '',
      period: row.period || '',
      startTime: row.start_time,
      endTime: row.end_time,
      rowCount: row.row_count || 0,
      qualityStatus: row.quality_status,
    }))
    .filter((row) => row.symbol && row.contract && row.period)
    .sort((first, second) => {
      if (first.symbol !== second.symbol) return first.symbol.localeCompare(second.symbol)
      if (first.contract !== second.contract) return first.contract.localeCompare(second.contract)
      return periodRank(first.period) - periodRank(second.period)
    })
}

function pickDefaultSelection() {
  if (coverage.value.length === 0) return
  const rb5m = coverage.value.find((item) => item.symbol === 'rb' && item.contract === 'rb.MAIN' && item.period === '5m')
  const preferred = rb5m || coverage.value.find((item) => item.period === '5m') || coverage.value[0]
  selectedSymbol.value = preferred.symbol
  selectedContract.value = preferred.contract
  selectedPeriod.value = preferred.period
  syncDateRange()
}

function handleSymbolUpdate(value: string) {
  selectedSymbol.value = value
  const nextContract = contractOptions.value[0]?.value || null
  selectedContract.value = nextContract
  selectedPeriod.value = pickPeriod(nextContract)
  syncDateRange()
}

function handleContractUpdate(value: string) {
  selectedContract.value = value
  selectedPeriod.value = pickPeriod(value)
  syncDateRange()
}

function handlePeriodUpdate(value: string) {
  selectedPeriod.value = value
  syncDateRange()
}

function syncDateRange() {
  const currentCoverage = selectedCoverage.value
  if (!currentCoverage) return
  const end = new Date(currentCoverage.endTime).getTime()
  const start = Math.max(new Date(currentCoverage.startTime).getTime(), end - 90 * 24 * 60 * 60 * 1000)
  dateRange.value = [start, end]
}

function pickPeriod(contract: string | null) {
  if (!contract) return null
  const periods = coverage.value
    .filter((item) => item.symbol === selectedSymbol.value && item.contract === contract)
    .map((item) => item.period)
  return periods.includes('5m') ? '5m' : periods[0] || null
}

function openTrade(trade: BacktestTrade) {
  selectedTrade.value = trade
  detailVisible.value = true
  focusTrade(trade, 'open')
}

function focusTrade(trade: BacktestTrade, side: 'open' | 'close') {
  const time = side === 'open' ? trade.open_time : trade.close_time
  const fill = side === 'open' ? findNearestFill(trade.open_time, ['open', 'add']) : findNearestFill(trade.close_time, ['reduce', 'exit'])
  activeMarkerId.value = fill?.fill_id || null
  chartRef.value?.focusTime(time)
}

function findNearestFill(time: string | undefined, actions: BacktestFill['action'][]): BacktestFill | null {
  if (!time || !report.value) return null
  const target = new Date(time).getTime()
  return (
    report.value.fills
      .filter((fill) => actions.includes(fill.action))
      .sort((first, second) => Math.abs(new Date(first.time).getTime() - target) - Math.abs(new Date(second.time).getTime() - target))[0] || null
  )
}

function markerLabel(fill: BacktestFill) {
  if (fill.reason === 'stop_loss') return '止损'
  if (fill.reason === 'take_profit') return '止盈'
  const labels: Record<BacktestFill['action'], string> = {
    open: fill.direction === 'long' ? '开多' : '开空',
    add: fill.direction === 'long' ? '加多' : '加空',
    reduce: fill.direction === 'long' ? '减多' : '减空',
    exit: fill.direction === 'long' ? '平多' : '平空',
  }
  return labels[fill.action]
}

function markerColor(fill: BacktestFill) {
  if (fill.reason === 'stop_loss') return '#ef4444'
  if (fill.reason === 'take_profit') return '#22c55e'
  if (fill.action === 'add') return '#f97316'
  if (fill.action === 'reduce') return '#f59e0b'
  if (fill.action === 'exit') return '#64748b'
  return fill.direction === 'long' ? '#ef4444' : '#22c55e'
}

function markerPosition(fill: BacktestFill): KlineMarker['position'] {
  if (fill.action === 'open' || fill.action === 'add') return fill.direction === 'long' ? 'belowBar' : 'aboveBar'
  return fill.direction === 'long' ? 'aboveBar' : 'belowBar'
}

function markerShape(fill: BacktestFill): KlineMarker['shape'] {
  if (fill.reason === 'stop_loss') return 'square'
  if (fill.action === 'open' || fill.action === 'add') return fill.direction === 'long' ? 'arrowUp' : 'arrowDown'
  return fill.direction === 'long' ? 'arrowDown' : 'arrowUp'
}

function contractName(contract: string) {
  return contracts.value.find((item) => item.contract_code === contract)?.name
}

function extractPartition(path: string, key: string) {
  const match = path.match(new RegExp(`${key}=([^/]+)`))
  return match?.[1]
}

function periodRank(period: string) {
  const order = ['5m', '15m', '30m', '60m', '1d']
  const index = order.indexOf(period)
  return index === -1 ? 99 : index
}

function formatDate(value: number) {
  const item = new Date(value)
  const year = item.getFullYear()
  const month = String(item.getMonth() + 1).padStart(2, '0')
  const day = String(item.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatDateTime(value: string) {
  return value.replace('T', ' ').slice(0, 16)
}

function shortTime(value: string) {
  return value.replace('T', ' ').slice(5, 16)
}

function formatNumber(value: number, digits = 2) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

function formatPct(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function round(value: number) {
  return Number(value.toFixed(6))
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
  <div class="backtest-page">
    <section class="panel toolbar-panel">
      <div class="panel__header">
        <div>
          <h2>回测报告</h2>
          <p>苏冰 EMA21 单品种即时回测</p>
        </div>
        <div class="header-actions">
          <NButton @click="router.push({ name: 'backtest-batch' })">批量回测</NButton>
          <NButton type="primary" :loading="running" @click="runReport">开始回测</NButton>
        </div>
      </div>

      <NForm class="toolbar" label-placement="top">
        <NFormItem label="品种">
          <NSelect
            :value="selectedSymbol"
            :options="instrumentOptions"
            :loading="loadingMeta"
            filterable
            placeholder="品种"
            @update:value="handleSymbolUpdate"
          />
        </NFormItem>
        <NFormItem label="合约">
          <NSelect
            :value="selectedContract"
            :options="contractOptions"
            :loading="loadingMeta"
            placeholder="合约"
            @update:value="handleContractUpdate"
          />
        </NFormItem>
        <NFormItem label="周期">
          <NSelect :value="selectedPeriod" :options="periodOptions" placeholder="周期" @update:value="handlePeriodUpdate" />
        </NFormItem>
        <NFormItem label="区间">
          <NDatePicker v-model:value="dateRange" type="daterange" clearable />
        </NFormItem>
        <NFormItem label="初始资金">
          <NInputNumber v-model:value="initialCapital" :min="10000" :step="10000" />
        </NFormItem>
        <NFormItem label="单笔风险%">
          <NInputNumber v-model:value="riskPerTradePct" :min="0.1" :max="10" :step="0.1" />
        </NFormItem>
        <NFormItem label="保证金上限%">
          <NInputNumber v-model:value="maxMarginUsagePct" :min="1" :max="100" :step="1" />
        </NFormItem>
        <NFormItem label="滑点Tick">
          <NInputNumber v-model:value="slippageTicks" :min="0" :max="20" :step="1" />
        </NFormItem>
        <NFormItem label="止盈">
          <NSwitch v-model:value="enableTakeProfit" />
        </NFormItem>
        <NFormItem label="允许警告数据">
          <NSwitch v-model:value="allowWarningQuality" />
        </NFormItem>
      </NForm>
    </section>

    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <NAlert v-for="warning in report?.warnings || []" :key="warning" type="warning" :bordered="false">{{ warning }}</NAlert>

    <section class="metrics">
      <div class="metric">
        <span>总收益</span>
        <strong :class="(report?.summary.total_return || 0) >= 0 ? 'text-up' : 'text-down'">
          {{ report ? formatPct(report.summary.total_return) : '-' }}
        </strong>
      </div>
      <div class="metric">
        <span>年化收益</span>
        <strong>{{ report ? formatPct(report.summary.annual_return) : '-' }}</strong>
      </div>
      <div class="metric">
        <span>最大回撤</span>
        <strong class="text-down">{{ report ? formatPct(report.summary.max_drawdown) : '-' }}</strong>
      </div>
      <div class="metric">
        <span>胜率</span>
        <strong>{{ report ? formatPct(report.summary.win_rate) : '-' }}</strong>
      </div>
      <div class="metric">
        <span>盈亏比</span>
        <strong>{{ report ? formatNumber(report.summary.profit_loss_ratio) : '-' }}</strong>
      </div>
      <div class="metric">
        <span>期望值</span>
        <strong>{{ report ? formatMoney(report.summary.expectancy) : '-' }}</strong>
      </div>
      <div class="metric">
        <span>最大连亏</span>
        <strong>{{ report?.summary.max_consecutive_losses ?? '-' }}</strong>
      </div>
      <div class="metric">
        <span>交易次数</span>
        <strong>{{ report?.summary.total_trades ?? '-' }}</strong>
      </div>
      <div class="metric">
        <span>手续费</span>
        <strong>{{ report ? formatMoney(report.summary.total_commission) : '-' }}</strong>
      </div>
      <div class="metric">
        <span>滑点</span>
        <strong>{{ report ? formatMoney(report.summary.total_slippage) : '-' }}</strong>
      </div>
    </section>

    <section class="chart-grid">
      <div class="panel">
        <div class="panel__title">收益曲线</div>
        <BaseChart :option="equityOption" height="280px" />
      </div>
      <div class="panel">
        <div class="panel__title">回撤曲线</div>
        <BaseChart :option="drawdownOption" height="280px" />
      </div>
      <div class="panel">
        <div class="panel__title">保证金占用</div>
        <BaseChart :option="marginOption" height="280px" />
      </div>
    </section>

    <section class="review-grid">
      <div class="panel kline-panel">
        <div class="panel__title">K线复盘</div>
        <KlineChart
          ref="chartRef"
          :bars="bars"
          :markers="markerData"
          :active-marker-id="activeMarkerId"
          :loading="loadingBars"
          :error="error"
        />
      </div>
      <aside class="panel trade-cards">
        <div class="panel__title">每笔交易卡片</div>
        <div v-if="!report || report.trades.length === 0" class="empty-block">暂无闭合交易</div>
        <button
          v-for="trade in report?.trades || []"
          :key="trade.trade_no"
          class="trade-card"
          :class="{ 'trade-card--active': selectedTrade?.trade_no === trade.trade_no }"
          @click="openTrade(trade)"
        >
          <span class="trade-card__top">
            <strong>{{ trade.trade_no }}</strong>
            <NTag size="small" :type="trade.net_pnl >= 0 ? 'error' : 'success'">{{ formatMoney(trade.net_pnl) }}</NTag>
          </span>
          <span>{{ trade.direction === 'long' ? '多' : '空' }} {{ trade.volume }} 手 · {{ trade.holding_bars }} bars</span>
          <span>{{ formatDateTime(trade.open_time) }} → {{ formatDateTime(trade.close_time) }}</span>
        </button>
      </aside>
    </section>

    <section class="panel">
      <div class="panel__title">交易明细</div>
      <NDataTable
        :columns="tradeColumns"
        :data="report?.trades || []"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="{ pageSize: 10 }"
      />
    </section>

    <NDrawer v-model:show="detailVisible" width="520">
      <NDrawerContent title="交易详情">
        <div v-if="selectedTrade" class="drawer-content">
          <NDescriptions :column="2" bordered size="small">
            <NDescriptionsItem label="交易">{{ selectedTrade.trade_no }}</NDescriptionsItem>
            <NDescriptionsItem label="方向">{{ selectedTrade.direction === 'long' ? '多' : '空' }}</NDescriptionsItem>
            <NDescriptionsItem label="开仓">{{ formatDateTime(selectedTrade.open_time) }}</NDescriptionsItem>
            <NDescriptionsItem label="平仓">{{ formatDateTime(selectedTrade.close_time) }}</NDescriptionsItem>
            <NDescriptionsItem label="开仓价">{{ formatNumber(selectedTrade.open_price) }}</NDescriptionsItem>
            <NDescriptionsItem label="平仓价">{{ formatNumber(selectedTrade.close_price) }}</NDescriptionsItem>
            <NDescriptionsItem label="手数">{{ selectedTrade.volume }}</NDescriptionsItem>
            <NDescriptionsItem label="持仓bar">{{ selectedTrade.holding_bars }}</NDescriptionsItem>
            <NDescriptionsItem label="手续费">{{ formatMoney(selectedTrade.commission) }}</NDescriptionsItem>
            <NDescriptionsItem label="滑点">{{ formatMoney(selectedTrade.slippage) }}</NDescriptionsItem>
            <NDescriptionsItem label="成交额">{{ formatMoney(selectedTrade.turnover) }}</NDescriptionsItem>
            <NDescriptionsItem label="净盈亏">{{ formatMoney(selectedTrade.net_pnl) }}</NDescriptionsItem>
          </NDescriptions>

          <div class="reason-block">
            <h3>开仓依据</h3>
            <p>{{ selectedTrade.entry_reason }}</p>
            <NButton size="small" @click="focusTrade(selectedTrade, 'open')">定位开仓K线</NButton>
          </div>

          <div class="reason-block">
            <h3>平仓依据</h3>
            <p>{{ selectedTrade.exit_reason }}</p>
            <NButton size="small" @click="focusTrade(selectedTrade, 'close')">定位平仓K线</NButton>
          </div>

          <div class="reason-block">
            <h3>成交记录</h3>
            <p v-if="selectedOpenFill">开仓成交：{{ selectedOpenFill.fill_id }} · {{ formatNumber(selectedOpenFill.price) }} · 保证金 {{ formatMoney(selectedOpenFill.margin) }}</p>
            <p v-if="selectedCloseFill">平仓成交：{{ selectedCloseFill.fill_id }} · {{ formatNumber(selectedCloseFill.price) }} · {{ selectedCloseFill.reason }}</p>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.backtest-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.panel {
  min-width: 0;
  padding: 14px;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
}

.panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel__header h2 {
  margin: 0;
  font-size: 18px;
}

.panel__header p {
  margin: 4px 0 0;
  color: #94a3b8;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.panel__title {
  margin-bottom: 10px;
  color: #e2e8f0;
  font-weight: 600;
}

.toolbar {
  display: grid;
  grid-template-columns: repeat(5, minmax(140px, 1fr));
  gap: 4px 12px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(10, minmax(88px, 1fr));
  gap: 10px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 64px;
  padding: 10px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.metric span {
  color: #94a3b8;
  font-size: 12px;
}

.metric strong {
  color: #e2e8f0;
  font-size: 18px;
}

.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 14px;
}

.review-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
}

.kline-panel {
  overflow: hidden;
}

.trade-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 820px;
  overflow: auto;
}

.trade-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  padding: 10px;
  color: #cbd5e1;
  text-align: left;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
  cursor: pointer;
}

.trade-card--active {
  border-color: #fbbf24;
}

.trade-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.empty-block {
  display: flex;
  min-height: 120px;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  background: #111827;
  border: 1px dashed #334155;
  border-radius: 6px;
}

.link-button {
  padding: 0;
  color: #38bdf8;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.drawer-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.reason-block {
  padding: 12px;
  background: #0f172a;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.reason-block h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

.reason-block p {
  margin: 0 0 10px;
  color: #cbd5e1;
  line-height: 1.6;
}

.text-up {
  color: #ef4444;
}

.text-down {
  color: #22c55e;
}

@media (max-width: 1280px) {
  .toolbar {
    grid-template-columns: repeat(3, minmax(140px, 1fr));
  }

  .metrics {
    grid-template-columns: repeat(5, minmax(88px, 1fr));
  }

  .chart-grid {
    grid-template-columns: 1fr;
  }

  .review-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .toolbar,
  .metrics {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
