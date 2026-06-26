<script setup lang="ts">
import { computed, h, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import {
  NAlert,
  NButton,
  NDataTable,
  NDatePicker,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  createBacktestTask,
  getBacktestReport,
  getBacktestReportDrawdownCurve,
  getBacktestReportEquityCurve,
  getBacktestTask,
  listBacktestReportTrades,
  listBacktestReports,
  listBacktestTasks,
} from '@/api/backtestApi'
import { getMarketBars } from '@/api/market'
import BaseChart from '@/components/charts/BaseChart.vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import type {
  BacktestDrawdownPoint,
  BacktestEquityPoint,
  BacktestReport,
  BacktestTask,
  BacktestTaskCreateRequest,
  BacktestTaskForm,
  BacktestTrade,
} from '@/types/backtest'
import type { BarData, KlineMarker } from '@/types/market'

const DISCLAIMER = '回测结果不等于实盘结果，实盘前必须模拟和小资金验证。'
const REPORT_DISCLAIMER = '研究回测，不代表实盘结果。'
const DEFAULT_STRATEGY_CLASS =
  'guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy'

type KlineChartExpose = {
  focusTime: (value: string) => void
}

const message = useMessage()
const router = useRouter()
const route = useRoute()

const submitting = ref(false)
const loadingTasks = ref(false)
const loadingReports = ref(false)
const loadingReportDetail = ref(false)
const loadingKline = ref(false)
const error = ref<string | null>(null)
const klineError = ref<string | null>(null)
const tasks = ref<BacktestTask[]>([])
const reports = ref<BacktestReport[]>([])
const selectedReport = ref<BacktestReport | null>(null)
const reportTrades = ref<BacktestTrade[]>([])
const equityCurve = ref<BacktestEquityPoint[]>([])
const drawdownCurve = ref<BacktestDrawdownPoint[]>([])
const bars = ref<BarData[]>([])
const selectedTrade = ref<BacktestTrade | null>(null)
const activeMarkerId = ref<string | null>(null)
const klineChartRef = ref<KlineChartExpose | null>(null)

const now = Date.now()
const form = ref<BacktestTaskForm>({
  strategy_code: 'su_bing_ema21',
  strategy_version: 'demo-0.1.0',
  engine_type: 'vnpy',
  symbol: 'rb2405',
  exchange: 'SHFE',
  interval: '60m',
  start: now - 90 * 24 * 60 * 60 * 1000,
  end: now,
  initial_capital: 100000,
  rate: 0.0001,
  slippage: 1,
  size: 10,
  pricetick: 1,
  margin_rate: 0.12,
  data_role: 'primary',
  research_only: false,
  strategy_params: JSON.stringify(
    {
      ema_period: 21,
      macd_fast: 12,
      macd_slow: 26,
      macd_signal: 9,
      atr_period: 14,
      stop_atr_multiple: 2.0,
    },
    null,
    2,
  ),
})

const engineOptions = [{ label: 'vn.py CTA', value: 'vnpy' }]
const intervalOptions = [
  { label: '1分钟', value: '1m' },
  { label: '5分钟', value: '5m' },
  { label: '15分钟', value: '15m' },
  { label: '30分钟', value: '30m' },
  { label: '60分钟', value: '60m' },
  { label: '日线', value: '1d' },
]
const dataRoleOptions = [
  { label: 'primary', value: 'primary' },
  { label: 'validation', value: 'validation' },
  { label: 'legacy_reference', value: 'legacy_reference' },
]

const roleRequiresResearchOnly = computed(() => form.value.data_role !== 'primary')
const canSubmit = computed(() => Boolean(form.value.symbol && form.value.interval && form.value.start && form.value.end))
const dateRangeValue = computed<[number, number] | null>({
  get: () => [form.value.start, form.value.end] as [number, number],
  set: (value: [number, number] | null) => {
    if (!value) return
    form.value.start = value[0]
    form.value.end = value[1]
  },
})

const summary = computed(() => selectedReport.value?.summary || {})
const metricItems = computed(() => [
  { label: '初始资金', value: formatMoney(numberFrom(summary.value.initial_capital)) },
  {
    label: '最终权益',
    value: formatMoney(numberFrom(summary.value.final_equity ?? summary.value.ending_equity)),
  },
  { label: '总收益率', value: formatPct(numberFrom(summary.value.total_return)), tone: pnlTone(numberFrom(summary.value.total_return)) },
  { label: '年化收益', value: formatPct(numberFrom(summary.value.annual_return)), tone: pnlTone(numberFrom(summary.value.annual_return)) },
  { label: '最大回撤', value: formatPct(numberFrom(summary.value.max_drawdown)), tone: 'risk' },
  { label: '胜率', value: formatPct(numberFrom(summary.value.win_rate)) },
  { label: '盈亏比', value: formatNumber(numberFrom(summary.value.profit_loss_ratio), 2) },
  { label: '交易次数', value: formatInteger(numberFrom(summary.value.trade_count ?? summary.value.total_trades)) },
  { label: '最大连续亏损', value: formatInteger(numberFrom(summary.value.max_consecutive_losses)), tone: 'risk' },
  { label: '总手续费', value: formatMoney(numberFrom(summary.value.total_commission)) },
  { label: '总滑点', value: formatMoney(numberFrom(summary.value.total_slippage)) },
])

const klineMarkers = computed<KlineMarker[]>(() => reportTrades.value.flatMap((trade) => tradeToMarkers(trade)))
const equityOption = computed<EChartsOption>(() => buildEquityOption(equityCurve.value))
const drawdownOption = computed<EChartsOption>(() => buildDrawdownOption(drawdownCurve.value))

const taskColumns: DataTableColumns<BacktestTask> = [
  { title: 'ID', key: 'id', width: 72 },
  { title: '任务号', key: 'task_no', minWidth: 190 },
  {
    title: '状态',
    key: 'status',
    width: 110,
    render: (row) => h(NTag, { size: 'small', type: statusType(row.status) }, { default: () => row.status }),
  },
  { title: '引擎', key: 'engine_type', width: 92 },
  { title: '数据角色', key: 'data_role', width: 132 },
  {
    title: '研究标记',
    key: 'research_only',
    width: 96,
    render: (row) => (row.research_only ? '是' : '否'),
  },
  { title: '创建时间', key: 'created_at', render: (row) => formatDateTime(row.created_at) },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    render: (row) => h(NButton, { size: 'small', onClick: () => refreshTask(row.id) }, { default: () => '刷新' }),
  },
]

const reportColumns: DataTableColumns<BacktestReport> = [
  { title: '报告ID', key: 'id', width: 86 },
  { title: '任务号', key: 'task_no', minWidth: 180 },
  { title: '合约', key: 'contract', width: 110 },
  { title: '周期', key: 'period', width: 80 },
  {
    title: '状态',
    key: 'status',
    width: 104,
    render: (row) => h(NTag, { size: 'small', type: statusType(row.status) }, { default: () => row.status }),
  },
  {
    title: '总收益',
    key: 'total_return',
    width: 112,
    render: (row) => formatPct(numberFrom(row.summary?.total_return)),
  },
  {
    title: '最大回撤',
    key: 'max_drawdown',
    width: 112,
    render: (row) => formatPct(numberFrom(row.summary?.max_drawdown)),
  },
  {
    title: '详情',
    key: 'actions',
    width: 118,
    render: (row) => h(NButton, { size: 'small', onClick: () => openReport(row.id) }, { default: () => '查看报告' }),
  },
]

const tradeColumns: DataTableColumns<BacktestTrade> = [
  {
    title: '交易号',
    key: 'trade_no',
    minWidth: 130,
    render: (row) =>
      h(
        NButton,
        {
          text: true,
          type: selectedTrade.value?.trade_no === row.trade_no ? 'primary' : 'default',
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            selectTrade(row)
          },
        },
        { default: () => row.trade_no },
      ),
  },
  {
    title: '方向',
    key: 'direction',
    width: 82,
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.direction === 'long' ? 'error' : 'success' },
        { default: () => (row.direction === 'long' ? '多' : '空') },
      ),
  },
  { title: '开仓时间', key: 'open_time', minWidth: 144, render: (row) => formatDateTime(row.open_time) },
  { title: '开仓价', key: 'open_price', width: 92, render: (row) => formatNumber(row.open_price, 2) },
  { title: '平仓时间', key: 'close_time', minWidth: 144, render: (row) => formatDateTime(row.close_time) },
  { title: '平仓价', key: 'close_price', width: 92, render: (row) => formatNumber(row.close_price, 2) },
  { title: '手数', key: 'volume', width: 76, render: (row) => formatInteger(row.volume) },
  {
    title: '净盈亏',
    key: 'net_pnl',
    width: 108,
    render: (row) =>
      h('span', { class: row.net_pnl >= 0 ? 'pnl-positive' : 'pnl-negative' }, formatMoney(row.net_pnl)),
  },
  { title: '手续费', key: 'commission', width: 96, render: (row) => formatMoney(row.commission) },
  { title: '滑点', key: 'slippage', width: 86, render: (row) => formatMoney(row.slippage) },
  { title: '持仓K数', key: 'holding_bars', width: 92, render: (row) => formatInteger(numberFrom(row.holding_bars)) },
]

watch(
  () => form.value.data_role,
  (role) => {
    if (role !== 'primary') {
      form.value.research_only = true
    }
  },
)

onMounted(async () => {
  await Promise.all([loadTasks(), loadReports()])
  const reportId = Number(route.query.report_id)
  if (Number.isFinite(reportId) && reportId > 0) await loadReportDetail(reportId)
})

async function submitTask() {
  error.value = null
  if (!canSubmit.value) {
    message.warning('请补全回测任务参数')
    return
  }
  if (roleRequiresResearchOnly.value && !form.value.research_only) {
    message.warning('validation / legacy_reference 必须标记 research_only')
    return
  }

  let strategyParameters: Record<string, unknown>
  try {
    strategyParameters = JSON.parse(form.value.strategy_params || '{}')
  } catch {
    message.error('策略参数 JSON 格式不正确')
    return
  }

  submitting.value = true
  try {
    const payload: BacktestTaskCreateRequest = {
      engine_type: 'vnpy',
      task_type: 'single',
      symbol: form.value.symbol,
      exchange: form.value.exchange,
      interval: form.value.interval,
      start: new Date(form.value.start).toISOString(),
      end: new Date(form.value.end).toISOString(),
      strategy_class_path: DEFAULT_STRATEGY_CLASS,
      strategy_parameters: strategyParameters,
      rate: form.value.rate,
      slippage: form.value.slippage,
      size: form.value.size,
      pricetick: form.value.pricetick,
      capital: form.value.initial_capital,
      data_role: form.value.data_role,
      research_only: form.value.research_only,
      quality_status: 'passed',
      request_payload: {
        strategy_code: form.value.strategy_code,
        strategy_version: form.value.strategy_version,
        margin_rate: form.value.margin_rate,
      },
    }
    const task = await createBacktestTask(payload)
    message.success(`任务已创建：${task.task_no}`)
    await loadTasks()
  } catch (err) {
    error.value = apiError(err, '创建回测任务失败')
  } finally {
    submitting.value = false
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    tasks.value = await listBacktestTasks()
  } catch (err) {
    error.value = apiError(err, '加载任务列表失败')
  } finally {
    loadingTasks.value = false
  }
}

async function refreshTask(taskId: number) {
  try {
    const task = await getBacktestTask(taskId)
    const index = tasks.value.findIndex((item) => item.id === task.id)
    if (index >= 0) tasks.value[index] = task
    else tasks.value.unshift(task)
  } catch (err) {
    message.error(apiError(err, '刷新任务失败'))
  }
}

async function loadReports() {
  loadingReports.value = true
  try {
    reports.value = await listBacktestReports()
  } catch (err) {
    error.value = apiError(err, '加载报告列表失败')
  } finally {
    loadingReports.value = false
  }
}

async function openReport(reportId: number) {
  await router.push({ name: 'backtest', query: { report_id: String(reportId) } })
  await loadReportDetail(reportId)
}

async function loadReportDetail(reportId: number) {
  loadingReportDetail.value = true
  selectedTrade.value = null
  activeMarkerId.value = null
  klineError.value = null
  try {
    const report = await getBacktestReport(reportId)
    selectedReport.value = report

    const [tradesResult, equityResult, drawdownResult] = await Promise.allSettled([
      listBacktestReportTrades(reportId),
      getBacktestReportEquityCurve(reportId),
      getBacktestReportDrawdownCurve(reportId),
    ])

    reportTrades.value = tradesResult.status === 'fulfilled' ? tradesResult.value : report.trades || []
    equityCurve.value = equityResult.status === 'fulfilled' ? equityResult.value : report.equity_curve || []
    drawdownCurve.value = drawdownResult.status === 'fulfilled' ? drawdownResult.value : report.drawdown_curve || []

    if (tradesResult.status === 'rejected') message.warning(apiError(tradesResult.reason, '交易明细暂不可用'))
    if (equityResult.status === 'rejected') message.warning(apiError(equityResult.reason, '资金曲线暂不可用'))
    if (drawdownResult.status === 'rejected') message.warning(apiError(drawdownResult.reason, '回撤曲线暂不可用'))

    await loadReportBars(report, reportTrades.value)
  } catch (err) {
    message.error(apiError(err, '加载报告详情失败'))
  } finally {
    loadingReportDetail.value = false
  }
}

async function loadReportBars(report: BacktestReport, trades: BacktestTrade[]) {
  loadingKline.value = true
  bars.value = []
  klineError.value = null
  try {
    const times = trades.flatMap((trade) => [trade.open_time, trade.close_time]).filter(Boolean)
    const start = times.length > 0 ? minIsoTime(times) : report.started_at || undefined
    const end = times.length > 0 ? maxIsoTime(times) : report.finished_at || undefined
    const response = await getMarketBars({
      symbol: report.symbol,
      contract: report.contract,
      period: report.period,
      start,
      end,
      limit: 5000,
    })
    bars.value = response.bars || []
    if (bars.value.length === 0) {
      klineError.value = '未返回K线数据，交易明细仍可用于复盘检查。'
    }
  } catch (err) {
    klineError.value = apiError(err, 'K线数据暂不可用，交易明细仍可用于复盘检查。')
  } finally {
    loadingKline.value = false
  }
}

function selectTrade(trade: BacktestTrade) {
  selectedTrade.value = trade
  activeMarkerId.value = markerId(trade, 'open')
  nextTick(() => klineChartRef.value?.focusTime(trade.open_time))
}

function tradeRowProps(row: BacktestTrade) {
  return {
    class: selectedTrade.value?.trade_no === row.trade_no ? 'trade-row-active' : '',
    onClick: () => selectTrade(row),
  }
}

function tradeToMarkers(trade: BacktestTrade): KlineMarker[] {
  const isLong = trade.direction === 'long'
  return [
    {
      id: markerId(trade, 'open'),
      time: trade.open_time,
      label: `${isLong ? '开多' : '开空'} ${trade.trade_no}`,
      color: isLong ? '#ef4444' : '#22c55e',
      position: isLong ? 'belowBar' : 'aboveBar',
      shape: isLong ? 'arrowUp' : 'arrowDown',
    },
    {
      id: markerId(trade, 'close'),
      time: trade.close_time,
      label: `${isLong ? '平多' : '平空'} ${trade.trade_no}`,
      color: isLong ? '#22c55e' : '#ef4444',
      position: isLong ? 'aboveBar' : 'belowBar',
      shape: isLong ? 'arrowDown' : 'arrowUp',
    },
  ]
}

function markerId(trade: BacktestTrade, side: 'open' | 'close') {
  return `trade-${trade.trade_no}-${side}`
}

function buildEquityOption(points: BacktestEquityPoint[]): EChartsOption {
  const data = points
    .map((point) => ({ time: pointTime(point), value: numberFrom(point.equity ?? point.balance ?? point.close, Number.NaN) }))
    .filter((point) => point.time && Number.isFinite(point.value))
  return lineOption({
    title: '资金曲线',
    times: data.map((point) => point.time),
    values: data.map((point) => point.value),
    color: '#38bdf8',
    valueFormatter: (value) => formatMoney(value),
  })
}

function buildDrawdownOption(points: BacktestDrawdownPoint[]): EChartsOption {
  const data = points
    .map((point) => ({ time: pointTime(point), value: percentAxisValue(point.drawdown_pct ?? point.drawdown) }))
    .filter((point) => point.time && Number.isFinite(point.value))
  return lineOption({
    title: '回撤曲线',
    times: data.map((point) => point.time),
    values: data.map((point) => point.value),
    color: '#f97316',
    valueFormatter: (value) => `${value.toFixed(2)}%`,
  })
}

function lineOption(args: {
  title: string
  times: string[]
  values: number[]
  color: string
  valueFormatter: (value: number) => string
}): EChartsOption {
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const item = Array.isArray(params) ? params[0] : params
        const point = item as { axisValue?: string; value?: unknown } | undefined
        const value = Number(point?.value ?? 0)
        return `${point?.axisValue || ''}<br/>${args.title}: ${args.valueFormatter(value)}`
      },
    },
    grid: { left: 46, right: 18, top: 18, bottom: 28 },
    xAxis: {
      type: 'category',
      data: args.times,
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: { color: '#94a3b8' },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { lineStyle: { color: '#334155' } },
      splitLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#94a3b8' },
    },
    series: [
      {
        name: args.title,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: args.values,
        lineStyle: { color: args.color, width: 2 },
        areaStyle: { color: `${args.color}22` },
      },
    ],
  }
}

function pointTime(point: BacktestEquityPoint | BacktestDrawdownPoint) {
  return String(point.datetime || point.time || point.date || '')
}

function percentAxisValue(value: unknown) {
  const numeric = numberFrom(value, Number.NaN)
  if (!Number.isFinite(numeric)) return Number.NaN
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric
}

function minIsoTime(values: string[]) {
  return values.reduce((min, item) => (item < min ? item : min), values[0])
}

function maxIsoTime(values: string[]) {
  return values.reduce((max, item) => (item > max ? item : max), values[0])
}

function statusType(status: string) {
  if (['success', 'completed'].includes(status)) return 'success'
  if (['failed', 'cancelled'].includes(status)) return 'error'
  if (['running', 'queued'].includes(status)) return 'warning'
  return 'default'
}

function pnlTone(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return undefined
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function formatPct(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatNumber(value: number, digits = 2) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatInteger(value: number) {
  return Math.round(value).toLocaleString('zh-CN')
}

function numberFrom(value: unknown, fallback = 0) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function apiError(err: unknown, fallback: string) {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string | { msg?: string }[] } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) return detail.map((item) => item.msg).join('；')
  }
  return err instanceof Error ? err.message : fallback
}
</script>

<template>
  <div class="backtest-page">
    <section class="panel">
      <div class="panel__header">
        <div>
          <h2>回测任务</h2>
          <p>vn.py CTA 研究任务</p>
        </div>
        <div class="header-actions">
          <NButton @click="router.push({ name: 'backtest-batch' })">批量回测</NButton>
          <NButton :loading="loadingTasks" @click="loadTasks">刷新任务</NButton>
          <NButton type="primary" :loading="submitting" :disabled="!canSubmit" @click="submitTask">创建任务</NButton>
        </div>
      </div>

      <NAlert type="warning" :bordered="false" class="risk-alert">{{ DISCLAIMER }}</NAlert>
      <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>

      <NForm class="task-form" label-placement="top">
        <NFormItem label="策略代码">
          <NInput v-model:value="form.strategy_code" />
        </NFormItem>
        <NFormItem label="策略版本">
          <NInput v-model:value="form.strategy_version" />
        </NFormItem>
        <NFormItem label="回测引擎">
          <NSelect v-model:value="form.engine_type" :options="engineOptions" disabled />
        </NFormItem>
        <NFormItem label="合约">
          <NInput v-model:value="form.symbol" placeholder="rb2405" />
        </NFormItem>
        <NFormItem label="交易所">
          <NInput v-model:value="form.exchange" placeholder="SHFE" />
        </NFormItem>
        <NFormItem label="周期">
          <NSelect v-model:value="form.interval" :options="intervalOptions" />
        </NFormItem>
        <NFormItem label="起止时间">
          <NDatePicker v-model:value="dateRangeValue" type="datetimerange" clearable />
        </NFormItem>
        <NFormItem label="初始资金">
          <NInputNumber v-model:value="form.initial_capital" :min="10000" :step="10000" />
        </NFormItem>
        <NFormItem label="手续费率">
          <NInputNumber v-model:value="form.rate" :min="0" :step="0.00001" />
        </NFormItem>
        <NFormItem label="滑点">
          <NInputNumber v-model:value="form.slippage" :min="0" :step="1" />
        </NFormItem>
        <NFormItem label="合约乘数">
          <NInputNumber v-model:value="form.size" :min="1" :step="1" />
        </NFormItem>
        <NFormItem label="最小跳动">
          <NInputNumber v-model:value="form.pricetick" :min="0.0001" :step="1" />
        </NFormItem>
        <NFormItem label="保证金率">
          <NInputNumber v-model:value="form.margin_rate" :min="0" :max="1" :step="0.01" />
        </NFormItem>
        <NFormItem label="数据角色">
          <NSelect v-model:value="form.data_role" :options="dataRoleOptions" />
        </NFormItem>
        <NFormItem label="研究标记">
          <NSwitch v-model:value="form.research_only" :disabled="roleRequiresResearchOnly" />
        </NFormItem>
        <NFormItem label="策略参数">
          <NInput v-model:value="form.strategy_params" type="textarea" :autosize="{ minRows: 7, maxRows: 12 }" />
        </NFormItem>
      </NForm>

      <NAlert v-if="roleRequiresResearchOnly" type="info" :bordered="false">
        validation / legacy_reference 数据只允许研究用途，提交时必须保持 research_only=true。
      </NAlert>
    </section>

    <section class="panel">
      <div class="panel__header compact">
        <div class="panel__title">任务状态</div>
        <NButton size="small" :loading="loadingTasks" @click="loadTasks">刷新</NButton>
      </div>
      <NDataTable
        :columns="taskColumns"
        :data="tasks"
        :loading="loadingTasks"
        :bordered="false"
        size="small"
        :pagination="{ pageSize: 8 }"
      />
    </section>

    <section class="panel">
      <div class="panel__header compact">
        <div class="panel__title">回测报告</div>
        <NButton size="small" :loading="loadingReports" @click="loadReports">刷新</NButton>
      </div>
      <NDataTable
        :columns="reportColumns"
        :data="reports"
        :loading="loadingReports"
        :bordered="false"
        size="small"
        :pagination="{ pageSize: 8 }"
      />
    </section>

    <section v-if="selectedReport" class="panel report-detail">
      <div class="panel__header compact">
        <div>
          <div class="panel__title">报告详情 #{{ selectedReport.id }}</div>
          <p>{{ selectedReport.report_no }} · {{ selectedReport.contract }} · {{ selectedReport.period }}</p>
        </div>
        <NTag size="small" :type="statusType(selectedReport.status)">{{ selectedReport.status }}</NTag>
      </div>

      <NAlert type="warning" :bordered="false" class="risk-alert">
        {{ selectedReport.disclaimer || REPORT_DISCLAIMER }}
      </NAlert>

      <div class="report-metrics" :class="{ loading: loadingReportDetail }">
        <div v-for="item in metricItems" :key="item.label" :class="['metric-card', item.tone]">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <div class="chart-grid">
        <div class="chart-panel">
          <div class="subsection-title">资金曲线</div>
          <BaseChart :option="equityOption" height="280px" />
        </div>
        <div class="chart-panel">
          <div class="subsection-title">回撤曲线</div>
          <BaseChart :option="drawdownOption" height="280px" />
        </div>
      </div>

      <div class="review-grid">
        <div class="kline-panel">
          <div class="subsection-title">K线买卖点</div>
          <KlineChart
            ref="klineChartRef"
            :bars="bars"
            :markers="klineMarkers"
            :active-marker-id="activeMarkerId"
            :loading="loadingKline"
            :error="klineError"
          />
        </div>
        <div class="trade-panel">
          <div class="subsection-title">交易明细</div>
          <div v-if="selectedTrade" class="selected-trade">
            <span>{{ selectedTrade.trade_no }}</span>
            <strong :class="selectedTrade.net_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'">
              {{ formatMoney(selectedTrade.net_pnl) }}
            </strong>
            <small>{{ selectedTrade.entry_reason || '-' }} / {{ selectedTrade.exit_reason || '-' }}</small>
          </div>
          <NDataTable
            :columns="tradeColumns"
            :data="reportTrades"
            :loading="loadingReportDetail"
            :bordered="false"
            :row-props="tradeRowProps"
            size="small"
            :pagination="{ pageSize: 10 }"
          />
        </div>
      </div>
    </section>
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

.panel__header.compact {
  align-items: center;
}

.panel__header h2 {
  margin: 0;
  font-size: 18px;
}

.panel__header p {
  margin: 4px 0 0;
  color: #94a3b8;
}

.panel__title,
.subsection-title {
  color: #e2e8f0;
  font-weight: 600;
}

.subsection-title {
  margin-bottom: 10px;
  font-size: 14px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.risk-alert {
  margin-bottom: 12px;
}

.task-form {
  display: grid;
  grid-template-columns: repeat(4, minmax(160px, 1fr));
  gap: 4px 12px;
}

.task-form :deep(.n-form-item:last-child) {
  grid-column: span 4;
}

.report-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.report-metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 10px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 64px;
  padding: 10px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.metric-card span {
  color: #94a3b8;
  font-size: 12px;
}

.metric-card strong {
  color: #e2e8f0;
  font-size: 18px;
}

.metric-card.positive strong,
.pnl-positive {
  color: #ef4444;
}

.metric-card.negative strong,
.pnl-negative {
  color: #22c55e;
}

.metric-card.risk strong {
  color: #f97316;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.chart-panel,
.kline-panel,
.trade-panel {
  min-width: 0;
  padding: 12px;
  background: #101827;
  border: 1px solid #1e293b;
  border-radius: 6px;
}

.review-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(420px, 0.65fr);
  gap: 12px;
  align-items: start;
}

.selected-trade {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  margin-bottom: 8px;
  padding: 8px 10px;
  color: #cbd5e1;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
}

.selected-trade small {
  min-width: 0;
  overflow: hidden;
  color: #94a3b8;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.trade-row-active td) {
  background: rgba(56, 189, 248, 0.12) !important;
}

@media (max-width: 1380px) {
  .report-metrics {
    grid-template-columns: repeat(4, minmax(120px, 1fr));
  }

  .review-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1180px) {
  .task-form {
    grid-template-columns: repeat(2, minmax(160px, 1fr));
  }

  .task-form :deep(.n-form-item:last-child) {
    grid-column: span 2;
  }

  .report-metrics,
  .chart-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}

@media (max-width: 720px) {
  .panel__header {
    flex-direction: column;
  }

  .task-form,
  .report-metrics,
  .chart-grid {
    grid-template-columns: 1fr;
  }

  .task-form :deep(.n-form-item:last-child) {
    grid-column: span 1;
  }

  .selected-trade {
    grid-template-columns: 1fr;
  }
}
</style>
