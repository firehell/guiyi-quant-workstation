<script setup lang="ts">
/** 回测中心：创建 vn.py 任务、报告详情、交易明细、K 线 marker 与 report_id deep-link。 */
import { computed, h, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { EChartsOption } from 'echarts'
import {
  NAlert,
  NButton,
  NDataTable,
  NDatePicker,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NTag,
  NTabs,
  NTabPane,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  createBacktestTask,
  describeBacktestApiError,
  exportBacktestReportTrades,
  fetchAllBacktestReportTrades,
  getBacktestReport,
  getBacktestTask,
  getBacktestValidationContextObservation,
  listBacktestReportOrders,
  listBacktestReportTrades,
  listBacktestReports,
  listBacktestTasks,
} from '@/api/backtestApi'
import { getMarketBarsForBacktestReport } from '@/api/market'
import { createReviewFromBacktestTrade, getReviewBacktestTrades } from '@/api/review'
import BaseChart from '@/components/charts/BaseChart.vue'
import KlineChart from '@/components/kline/KlineChart.vue'
import PageShell from '@/components/common/PageShell.vue'
import type {
  BacktestOrder,
  BacktestDrawdownPoint,
  BacktestEquityPoint,
  BacktestReport,
  BacktestTask,
  BacktestTaskCreateRequest,
  BacktestTaskForm,
  BacktestTrade,
  BacktestTradeExportFormat,
  BacktestTradeSortBy,
  BacktestTradeSortOrder,
} from '@/types/backtest'
import type { BacktestMarketBarsQueryDebug, BarData, KlineMarker } from '@/types/market'
import type { ReviewSourceTrade } from '@/types/review'
import type { BacktestValidationContextObservation } from '@/types/backtestValidation'
import JmV1bQuickTasks from '@/components/backtest/JmV1bQuickTasks.vue'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import { useBacktestStore } from '@/stores/backtest'
import { resolveChartTheme } from '@/styles/chartTheme'
import { formatTradeMarkerText } from '@/utils/tradeMarker'
import { buildBacktestReportPresentation } from '@/utils/backtestReportPresentation'
import { buildFormalBacktestRequest } from '@/utils/dataCoreV2Consumer'
import { buildChartResearchQuery, currentReturnRoute } from '@/utils/researchNavigation'

const DISCLAIMER = '回测结果不等于实盘结果，实盘前必须模拟和小资金验证。'
const REPORT_DISCLAIMER = '研究回测，不代表实盘结果。'
const DEFAULT_STRATEGY_CLASS =
  'guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy'
const JM_V1B_STRATEGY_CODE = 'jm_v1b_daily_direction_fast_entry'

type KlineChartExpose = {
  focusTime: (value: string) => void
}

const message = useMessage()
const backtestStore = useBacktestStore()
const router = useRouter()
const route = useRoute()
const chartTheme = resolveChartTheme()

const submitting = ref(false)
const loadingTasks = ref(false)
const loadingReports = ref(false)
const loadingReportDetail = ref(false)
const loadingTrades = ref(false)
const loadingKline = ref(false)
const error = ref<string | null>(null)
const tradeError = ref<string | null>(null)
const klineError = ref<string | null>(null)
const validationObservation = ref<BacktestValidationContextObservation | null>(null)
const tasks = ref<BacktestTask[]>([])
const reports = ref<BacktestReport[]>([])
const taskTotal = ref(0)
const taskPage = ref(1)
const taskPageSize = 20
const reportTotal = ref(0)
const reportPage = ref(1)
const reportPageSize = 20
const selectedReport = ref<BacktestReport | null>(null)
const reportOrders = ref<BacktestOrder[]>([])
const loadingOrders = ref(false)
const detailTab = ref<'trades' | 'orders'>('trades')
const reportTrades = ref<BacktestTrade[]>([])
const reportKlineTrades = ref<BacktestTrade[]>([])
const tradeTotal = ref(0)
const tradePage = ref(1)
const tradePageSize = ref(50)
const tradeSortBy = ref<BacktestTradeSortBy>('close_time')
const tradeSortOrder = ref<BacktestTradeSortOrder>('asc')
const exportingTradeFormat = ref<BacktestTradeExportFormat | null>(null)
const reviewSources = ref<ReviewSourceTrade[]>([])
const equityCurve = ref<BacktestEquityPoint[]>([])
const drawdownCurve = ref<BacktestDrawdownPoint[]>([])
const bars = ref<BarData[]>([])
const klineQueryItems = ref<Array<{ label: string; value: string }>>([])
const selectedTrade = ref<BacktestTrade | null>(null)
const activeMarkerId = ref<string | null>(null)
const klineChartRef = ref<KlineChartExpose | null>(null)
const reportIdInput = ref<number | null>(null)
/** 报告详情请求序号，用于丢弃过期响应（快速切换 report_id 时） */
let reportDetailRequestId = 0

const taskPagination = computed(() => ({
  page: taskPage.value,
  pageSize: taskPageSize,
  itemCount: taskTotal.value,
  onChange: (page: number) => {
    taskPage.value = page
    void loadTasks()
  },
}))
const reportPagination = computed(() => ({
  page: reportPage.value,
  pageSize: reportPageSize,
  itemCount: reportTotal.value,
  onChange: (page: number) => {
    reportPage.value = page
    void loadReports()
  },
}))

const now = Date.now()
const form = ref<BacktestTaskForm>({
  strategy_code: '',
  strategy_version: '',
  engine_type: 'vnpy',
  dataset_kind: 'actual_dominant',
  instrument_symbol: '',
  contract_or_series: '',
  exchange: '',
  interval: '60m',
  start: now - 90 * 24 * 60 * 60 * 1000,
  end: now,
  initial_capital: 100000,
  rate: 0.0001,
  slippage: 1,
  size: 10,
  pricetick: 1,
  margin_rate: 0.12,
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
const datasetKindOptions = [
  { label: '实际主力合约（actual_dominant）', value: 'actual_dominant' },
  { label: '连续序列（continuous）', value: 'continuous' },
]
const intervalOptions = [
  { label: '1分钟', value: '1m' },
  { label: '5分钟', value: '5m' },
  { label: '15分钟', value: '15m' },
  { label: '30分钟', value: '30m' },
  { label: '60分钟', value: '60m' },
  { label: '日线', value: '1d' },
]
const tradeSortOptions: Array<{ label: string; value: BacktestTradeSortBy }> = [
  { label: '开仓时间', value: 'open_time' },
  { label: '平仓时间', value: 'close_time' },
  { label: '净盈亏', value: 'net_pnl' },
  { label: '交易号', value: 'trade_no' },
  { label: '手数', value: 'volume' },
  { label: '手续费', value: 'commission' },
  { label: '滑点', value: 'slippage' },
  { label: '持仓K数', value: 'holding_bars' },
]
const tradeSortOrderOptions: Array<{ label: string; value: BacktestTradeSortOrder }> = [
  { label: '升序', value: 'asc' },
  { label: '降序', value: 'desc' },
]

const canSubmit = computed(() =>
  Boolean(
    form.value.strategy_code.trim() &&
      form.value.strategy_version.trim() &&
      form.value.instrument_symbol &&
      form.value.contract_or_series &&
      form.value.interval &&
      form.value.start &&
      form.value.end,
  ),
)
const dateRangeValue = computed<[number, number] | null>({
  get: () => [form.value.start, form.value.end] as [number, number],
  set: (value: [number, number] | null) => {
    if (!value) return
    form.value.start = value[0]
    form.value.end = value[1]
  },
})

const summary = computed(() => selectedReport.value?.summary || {})
const summaryUsesPercentUnits = computed(() => summaryHasPercentUnits(summary.value))
const metricItems = computed(() => [
  { label: '初始资金', value: formatMoneyOrLegacy(reportMetricValue('initial_capital', 'capital')) },
  {
    label: '最终权益',
    value: formatMoneyOrLegacy(reportMetricValue('final_equity', 'end_balance', 'ending_equity', 'balance')),
  },
  {
    label: '总收益率',
    value: formatPercentOrLegacy(reportMetricValue('total_return')),
    tone: pnlTone(reportMetric('total_return')),
  },
  {
    label: '年化收益',
    value: formatPercentOrLegacy(reportMetricValue('annual_return')),
    tone: pnlTone(reportMetric('annual_return')),
  },
  {
    label: '最大回撤金额',
    value: selectedReport.value ? formatDrawdownAmount(selectedReport.value) : legacyMissingText(),
    tone: 'risk',
  },
  {
    label: '最大回撤比例',
    value: selectedReport.value ? formatDrawdownPct(selectedReport.value) : legacyMissingText(),
    tone: 'risk',
  },
  { label: '总手续费', value: formatMoneyOrLegacy(reportMetricValue('total_commission')) },
  { label: '总滑点', value: formatMoneyOrLegacy(reportMetricValue('total_slippage')) },
  { label: '保证金峰值', value: formatMoneyOrLegacy(reportMetricValue('max_margin_required')) },
  { label: '保证金占用', value: formatPercentOrLegacy(reportMetricValue('max_margin_usage_pct')) },
  { label: '胜率', value: formatPercentOrLegacy(reportMetricValue('win_rate')) },
  { label: '盈亏比', value: formatNumberOrLegacy(reportMetricValue('profit_loss_ratio'), 2) },
  { label: '交易次数', value: formatIntegerOrLegacy(reportMetricValue('trade_count', 'total_trade_count', 'total_trades')) },
  { label: '最大连续亏损', value: formatIntegerOrLegacy(reportMetricValue('max_consecutive_losses')), tone: 'risk' },
  { label: '换月退出', value: formatIntegerOrLegacy(reportMetricValue('rollover_exit_count')) },
  { label: '交割风险退出', value: formatIntegerOrLegacy(reportMetricValue('delivery_risk_exit_count')), tone: 'risk' },
])
const reportMetaItems = computed(() => {
  if (!selectedReport.value) return []
  return [
    { label: '策略', value: selectedReport.value.strategy_code || summaryString(summary.value.report_metadata, 'strategy_code') || '-' },
    { label: '版本', value: selectedReport.value.strategy_version || summaryString(summary.value.report_metadata, 'strategy_version') || '-' },
    { label: '品种', value: selectedReport.value.symbol || '-' },
    { label: '周期', value: selectedReport.value.period || '-' },
    { label: '时间范围', value: reportDateRange(selectedReport.value) },
    { label: '引擎', value: selectedReport.value.engine_type || 'vnpy' },
    {
      label: 'Indicator Policy',
      value: formatIndicatorPolicyStatus(selectedReport.value.indicator_policy_status),
    },
    {
      label: 'Execution Timing',
      value: summaryString(summary.value.report_metadata, 'execution_timing') || '-',
    },
    { label: '研究用途', value: selectedReport.value.research_only ? '是' : '否' },
  ]
})
const reportPresentation = computed(() =>
  selectedReport.value
    ? buildBacktestReportPresentation(selectedReport.value, validationObservation.value)
    : null,
)

const klineMarkers = computed<KlineMarker[]>(() =>
  reportKlineTrades.value.flatMap((trade) => tradeToMarkers(trade)).sort((left, right) => markerTimeMs(left) - markerTimeMs(right)),
)
const equityOption = computed<EChartsOption>(() => buildEquityOption(equityCurve.value))
const drawdownOption = computed<EChartsOption>(() => buildDrawdownOption(drawdownCurve.value))
const jmV1bReports = computed(() =>
  reports.value.filter(
    (report) =>
      report.strategy_code === JM_V1B_STRATEGY_CODE ||
      summaryString(report.summary?.report_metadata, 'strategy_code') === JM_V1B_STRATEGY_CODE,
  ),
)
const reviewSourceByTradeId = computed(() => new Map(reviewSources.value.map((source) => [source.id, source])))
const canExportTrades = computed(
  () => Boolean(selectedReport.value) && tradeTotal.value > 0 && !loadingReportDetail.value && !loadingTrades.value,
)
const tradePagination = computed(() => ({
  page: tradePage.value,
  pageSize: tradePageSize.value,
  itemCount: tradeTotal.value,
  pageSizes: [20, 50, 100, 200],
  showSizePicker: true,
  prefix: ({ itemCount }: { itemCount?: number }) => `共 ${(itemCount || 0).toLocaleString('zh-CN')} 笔`,
  onUpdatePage: (page: number) => {
    tradePage.value = page
    void loadReportTrades()
  },
  onUpdatePageSize: (pageSize: number) => {
    tradePageSize.value = pageSize
    tradePage.value = 1
    void loadReportTrades()
  },
}))

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
  {
    title: '类型',
    key: 'report_kind',
    width: 126,
    render: (row) =>
      h(NTag, { size: 'small', type: reportKindType(row) }, { default: () => reportKindLabel(row) }),
  },
  { title: '策略', key: 'strategy_code', minWidth: 220, render: (row) => row.strategy_code || summaryString(row.summary?.report_metadata, 'strategy_code') || '-' },
  { title: '品种', key: 'symbol', width: 90, render: (row) => row.symbol || '-' },
  { title: '合约', key: 'contract', width: 112 },
  { title: '周期', key: 'period', width: 80 },
  { title: '时间范围', key: 'date_range', minWidth: 220, render: (row) => reportDateRange(row) },
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
    render: (row) => formatPercentOrLegacy(rowMetricValue(row, 'total_return'), summaryHasPercentUnits(row.summary || {})),
  },
  {
    title: '最大回撤',
    key: 'max_drawdown',
    width: 150,
    render: (row) => formatDrawdown(row),
  },
  {
    title: '胜率',
    key: 'win_rate',
    width: 96,
    render: (row) => formatRatioPct(rowMetric(row, 'win_rate')),
  },
  {
    title: '盈亏比',
    key: 'profit_loss_ratio',
    width: 96,
    render: (row) => formatNumber(rowMetric(row, 'profit_loss_ratio'), 2),
  },
  {
    title: '交易数',
    key: 'trade_count',
    width: 92,
    render: (row) => formatInteger(rowMetric(row, 'trade_count', 'total_trade_count', 'total_trades')),
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
        { size: 'small', type: tradeDirectionSide(row.direction) === 'long' ? 'error' : 'success' },
        { default: () => directionLabel(row.direction) },
      ),
  },
  { title: '开仓合约', key: 'entry_contract', width: 108, render: (row) => fieldOrLegacy(row.entry_contract) },
  { title: '平仓合约', key: 'exit_contract', width: 108, render: (row) => fieldOrLegacy(row.exit_contract) },
  { title: '乘数', key: 'contract_multiplier', width: 76, render: (row) => formatIntegerOrLegacy(optionalNumber(row.contract_multiplier)) },
  { title: '开仓时间', key: 'open_time', minWidth: 144, render: (row) => formatDateTime(row.open_time) },
  { title: '开仓价', key: 'open_price', width: 92, render: (row) => formatNumber(row.open_price, 2) },
  { title: '平仓时间', key: 'close_time', minWidth: 144, render: (row) => formatDateTime(row.close_time) },
  { title: '平仓价', key: 'close_price', width: 92, render: (row) => formatNumber(row.close_price, 2) },
  { title: '手数', key: 'volume', width: 76, render: (row) => formatInteger(row.volume) },
  { title: '入场周期', key: 'entry_interval', width: 96, render: (row) => tradeEntryInterval(row) || '-' },
  { title: '评分', key: 'entry_score', width: 92, render: (row) => tradeScoreNode(row) },
  { title: '条件', key: 'satisfied_conditions', minWidth: 220, render: (row) => renderTradeTags(tradeConditionTags(row)) },
  { title: '场景', key: 'scene_tags', minWidth: 180, render: (row) => renderTradeTags(tradeSceneTags(row), 'info') },
  {
    title: '净盈亏',
    key: 'net_pnl',
    width: 108,
    render: (row) =>
      h('span', { class: row.net_pnl >= 0 ? 'pnl-positive' : 'pnl-negative' }, formatMoney(row.net_pnl)),
  },
  { title: '手续费', key: 'commission', width: 96, render: (row) => formatMoney(row.commission) },
  { title: '滑点', key: 'slippage', width: 86, render: (row) => formatMoney(row.slippage) },
  { title: '保证金', key: 'margin_required', width: 108, render: (row) => formatMoneyOrLegacy(optionalNumber(row.margin_required)) },
  { title: '持仓K数', key: 'holding_bars', width: 92, render: (row) => formatIntegerOrLegacy(optionalNumber(tradeHoldBars(row))) },
  { title: '入场原因', key: 'entry_reason', minWidth: 180, render: (row) => row.entry_reason || tradeRawString(row, 'entry_reason') || legacyMissingText() },
  { title: '退出原因', key: 'exit_reason', minWidth: 180, render: (row) => exitReasonLabel(row) },
  {
    title: 'K线',
    key: 'kline',
    width: 108,
    render: (row) => h(NButton, { size: 'small', onClick: (event: MouseEvent) => openTradeInMarket(event, row) }, { default: () => '查看K线' }),
  },
  {
    title: '复盘',
    key: 'review',
    width: 118,
    render: (row) =>
      h(
        NButton,
        {
          size: 'small',
          type: reviewLabel(row) === '查看复盘' ? 'primary' : 'default',
          disabled: !row.id,
          onClick: (event: MouseEvent) => openTradeReview(event, row),
        },
        { default: () => reviewLabel(row) },
      ),
  },
]

watch(
  () => [route.query.report_id, route.query.trade_id],
  () => {
    void syncReportFromRoute()
  },
)

/** 挂载时加载任务/报告列表，再按 URL report_id 同步详情。 */
onMounted(async () => {
  await Promise.all([loadTasks(), loadReports()])
  await syncReportFromRoute()
})

async function submitTask() {
  error.value = null
  if (!canSubmit.value) {
    message.warning('请补全回测任务参数')
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
    const payload = buildFormalBacktestRequest({
      engine_type: 'vnpy',
      task_type: 'single',
      dataset_kind: form.value.dataset_kind,
      instrument_symbol: form.value.instrument_symbol,
      contract_or_series: form.value.contract_or_series,
      exchange: form.value.exchange,
      interval: form.value.interval,
      start: new Date(form.value.start).toISOString(),
      end: new Date(form.value.end).toISOString(),
      strategy_class_path: DEFAULT_STRATEGY_CLASS,
      strategy_code: form.value.strategy_code,
      strategy_version: form.value.strategy_version,
      strategy_parameters: strategyParameters,
      rate: form.value.rate,
      slippage: form.value.slippage,
      size: form.value.size,
      pricetick: form.value.pricetick,
      capital: form.value.initial_capital,
    } satisfies BacktestTaskCreateRequest)
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
    const page = await listBacktestTasks({ limit: taskPageSize, offset: (taskPage.value - 1) * taskPageSize })
    tasks.value = page.items
    taskTotal.value = page.total
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
    const page = await listBacktestReports({ limit: reportPageSize, offset: (reportPage.value - 1) * reportPageSize })
    reports.value = page.items
    reportTotal.value = page.total
  } catch (err) {
    error.value = apiError(err, '加载报告列表失败')
  } finally {
    loadingReports.value = false
  }
}

/** JM V1-B 快捷任务完成后刷新列表并打开新报告。 */
async function handleV1bTaskCompleted(task: BacktestTask) {
  await loadTasks()
  await loadReports()
  const reportId = Number(task.result_payload?.report_id)
  if (Number.isFinite(reportId) && reportId > 0) {
    backtestStore.setSelectedReportId(reportId)
    await openReport(reportId)
  }
}

/** 打开报告：写入 store 并 push query；同 ID 时 force 刷新详情。 */
async function openReport(reportId: number) {
  backtestStore.setSelectedReportId(reportId)
  reportIdInput.value = reportId
  if (parseReportId(route.query.report_id) === reportId) {
    await loadReportDetail(reportId, { force: true })
    return
  }
  await router.push({ name: 'backtest', query: { ...route.query, report_id: String(reportId) } })
}

async function openReportFromInput() {
  const reportId = Number(reportIdInput.value)
  if (!Number.isFinite(reportId) || reportId <= 0) {
    message.warning('请输入有效的 report_id')
    return
  }
  await openReport(reportId)
}

/** 从 route.query.report_id 同步详情；无 ID 时清空详情区。 */
async function syncReportFromRoute() {
  const reportId = parseReportId(route.query.report_id)
  if (!reportId) {
    reportIdInput.value = null
    reportDetailRequestId += 1
    clearReportDetailState()
    loadingReportDetail.value = false
    loadingTrades.value = false
    loadingKline.value = false
    return
  }
  reportIdInput.value = reportId
  if (selectedReport.value?.id === reportId && !error.value) {
    await loadReportTrades(reportId)
    return
  }
  await loadReportDetail(reportId)
}

/**
 * 加载报告详情：并行拉取分页交易与全量 K 线 trades；
 * 部分失败降级为 report.trades 并 warning，不阻断整页。
 */
async function loadReportDetail(reportId: number, options: { force?: boolean } = {}) {
  if (!options.force && selectedReport.value?.id === reportId && loadingReportDetail.value) return
  const requestId = ++reportDetailRequestId
  loadingReportDetail.value = true
  clearReportDetailState()
  reportIdInput.value = reportId
  tradePage.value = 1
  try {
    const report = await getBacktestReport(reportId)
    if (!isCurrentReportRequest(requestId)) return
    selectedReport.value = report
    equityCurve.value = report.equity_curve || []
    drawdownCurve.value = report.drawdown_curve || []

    const [tradesResult, klineTradesResult, validationResult] = await Promise.allSettled([
      loadReportTrades(reportId, requestId),
      fetchAllBacktestReportTrades(reportId, { sort_by: 'open_time', sort_order: 'asc' }),
      getBacktestValidationContextObservation(reportId),
    ])
    if (!isCurrentReportRequest(requestId)) return

    const loadedTrades = tradesResult.status === 'fulfilled' ? tradesResult.value : report.trades || []
    const klineTrades = klineTradesResult.status === 'fulfilled' ? klineTradesResult.value : loadedTrades
    validationObservation.value = validationResult.status === 'fulfilled'
      ? validationResult.value
      : {
          available: false,
          error_type: 'VALIDATION_CONTEXT_REQUEST_FAILED',
          error_message: apiError(validationResult.reason, '验证上下文暂不可用'),
        }
    reportKlineTrades.value = klineTrades
    if (tradesResult.status === 'rejected') {
      reportTrades.value = report.trades || []
      tradeTotal.value = reportTrades.value.length
    }

    if (tradesResult.status === 'rejected') message.warning(apiError(tradesResult.reason, '交易明细暂不可用'))
    if (klineTradesResult.status === 'rejected') message.warning(apiError(klineTradesResult.reason, 'K线成交标记暂不可用'))

    await loadReviewSources(reportId, requestId)
    await loadReportOrders(reportId)
    await loadReportBars(report, klineTrades, requestId)
  } catch (err) {
    if (!isCurrentReportRequest(requestId)) return
    clearReportDetailState()
    error.value = apiError(err, '加载报告详情失败')
    message.error(error.value)
  } finally {
    if (isCurrentReportRequest(requestId)) loadingReportDetail.value = false
  }
}

function clearReportDetailState() {
  selectedReport.value = null
  validationObservation.value = null
  reportTrades.value = []
  reportOrders.value = []
  reportKlineTrades.value = []
  tradeTotal.value = 0
  reviewSources.value = []
  equityCurve.value = []
  drawdownCurve.value = []
  bars.value = []
  klineQueryItems.value = []
  selectedTrade.value = null
  activeMarkerId.value = null
  error.value = null
  tradeError.value = null
  klineError.value = null
}

function isCurrentReportRequest(requestId: number) {
  return requestId === reportDetailRequestId
}

function parseReportId(value: unknown) {
  const reportId = Number(Array.isArray(value) ? value[0] : value)
  return Number.isFinite(reportId) && reportId > 0 ? reportId : null
}

async function loadReportOrders(reportId = selectedReport.value?.id, requestId = reportDetailRequestId) {
  if (!reportId) return
  loadingOrders.value = true
  try {
    const orders = await listBacktestReportOrders(reportId)
    if (!isCurrentReportRequest(requestId)) return
    reportOrders.value = orders
  } catch {
    if (isCurrentReportRequest(requestId)) reportOrders.value = []
  } finally {
    if (isCurrentReportRequest(requestId)) loadingOrders.value = false
  }
}

async function loadReportTrades(reportId = selectedReport.value?.id, requestId = reportDetailRequestId) {
  if (!reportId) return []
  const tradeId = parseReportId(route.query.report_id) === reportId ? parseReportId(route.query.trade_id) : null
  loadingTrades.value = true
  tradeError.value = null
  try {
    const page = await listBacktestReportTrades(reportId, {
      trade_id: tradeId,
      limit: tradePageSize.value,
      offset: (tradePage.value - 1) * tradePageSize.value,
      sort_by: tradeSortBy.value,
      sort_order: tradeSortOrder.value,
    })
    if (!isCurrentReportRequest(requestId)) return []
    reportTrades.value = page.items
    tradeTotal.value = page.total
    tradePageSize.value = page.limit
    tradePage.value = Math.floor(page.offset / Math.max(page.limit, 1)) + 1
    if (tradeId) {
      selectedTrade.value = page.items.find((trade) => trade.id === tradeId) || null
      activeMarkerId.value = selectedTrade.value ? markerId(selectedTrade.value, 'open') : null
    }
    if (selectedTrade.value && !page.items.some((trade) => sameTrade(trade, selectedTrade.value!))) {
      selectedTrade.value = null
      activeMarkerId.value = null
    }
    return page.items
  } catch (err) {
    if (!isCurrentReportRequest(requestId)) return []
    tradeError.value = apiError(err, '交易明细暂不可用')
    reportTrades.value = []
    tradeTotal.value = 0
    throw err
  } finally {
    if (isCurrentReportRequest(requestId)) loadingTrades.value = false
  }
}

function handleTradeSortChange() {
  tradePage.value = 1
  void loadReportTrades()
}

async function loadReviewSources(reportId: number, requestId = reportDetailRequestId) {
  try {
    const page = await getReviewBacktestTrades({ report_id: reportId, limit: 200, offset: 0 })
    if (isCurrentReportRequest(requestId)) reviewSources.value = page.items
  } catch (err) {
    if (!isCurrentReportRequest(requestId)) return
    reviewSources.value = []
    message.warning(apiError(err, '复盘状态暂不可用'))
  }
}

/** 为报告窗口拉取 K 线；空结果保留交易明细供复盘检查。 */
async function loadReportBars(report: BacktestReport, trades: BacktestTrade[], requestId = reportDetailRequestId) {
  loadingKline.value = true
  bars.value = []
  klineError.value = null
  try {
    const result = await getMarketBarsForBacktestReport(report, trades, { limit: 10000 })
    if (!isCurrentReportRequest(requestId)) return
    const response = result.response
    klineQueryItems.value = klineDebugItems(result.query)
    bars.value = response.bars || []
    if (bars.value.length === 0) {
      klineError.value = '未返回K线数据，交易明细仍可用于复盘检查。'
    }
  } catch (err) {
    if (!isCurrentReportRequest(requestId)) return
    klineError.value = apiError(err, 'K线数据暂不可用，交易明细仍可用于复盘检查。')
  } finally {
    if (isCurrentReportRequest(requestId)) loadingKline.value = false
  }
}

/** 选中交易并在 K 线图上 focus 到最近 bar 的开仓时间。 */
function selectTrade(trade: BacktestTrade) {
  selectedTrade.value = trade
  activeMarkerId.value = markerId(trade, 'open')
  nextTick(() => klineChartRef.value?.focusTime(nearestBarTime(trade.open_time)))
}

function tradeRowProps(row: BacktestTrade) {
  return {
    class: selectedTrade.value?.trade_no === row.trade_no ? 'trade-row-active' : '',
    onClick: () => selectTrade(row),
  }
}

function sameTrade(left: BacktestTrade, right: BacktestTrade) {
  if (left.id && right.id) return left.id === right.id
  return left.trade_no === right.trade_no
}

/** 跳转行情 K 线页，携带 report/trade/time deep-link。 */
function openTradeInMarket(event: MouseEvent, trade: BacktestTrade) {
  event.stopPropagation()
  const report = selectedReport.value
  if (!report) return
  const period = tradeEntryInterval(trade) || report.period
  void router.push({
    name: 'market-chart',
    query: buildChartResearchQuery({
      symbol: report.symbol,
      contract: report.contract,
      period,
      reportId: report.id,
      tradeId: trade.id,
      time: trade.open_time,
      dataMode: 'historical',
      returnRoute: currentReturnRoute(route.path, route.query as Record<string, string | string[] | null | undefined>),
    }),
    state: { researchScrollY: window.scrollY },
  })
}

async function downloadTradeExport(format: BacktestTradeExportFormat) {
  const report = selectedReport.value
  if (!report) return
  exportingTradeFormat.value = format
  try {
    const blob = await exportBacktestReportTrades(report.id, format, {
      sort_by: tradeSortBy.value,
      sort_order: tradeSortOrder.value,
    })
    saveBlob(blob, tradeExportFilename(report, format))
    message.success(`已导出 ${format.toUpperCase()} 成交明细`)
  } catch (err) {
    message.error(apiError(err, `导出 ${format.toUpperCase()} 失败`))
  } finally {
    exportingTradeFormat.value = null
  }
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function tradeExportFilename(report: BacktestReport, format: BacktestTradeExportFormat) {
  const parts = [
    'backtest_trades',
    `report_${report.id}`,
    safeFilePart(report.strategy_code || summaryString(report.summary?.report_metadata, 'strategy_code')),
    safeFilePart(report.symbol),
    safeFilePart(report.period),
  ].filter(Boolean)
  return `${parts.join('_')}.${format}`
}

function safeFilePart(value?: string | null) {
  return String(value || '')
    .trim()
    .replace(/[^\w.-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** 创建或打开复盘并跳转 review 页（deep-link）。 */
async function openTradeReview(event: MouseEvent, trade: BacktestTrade) {
  event.stopPropagation()
  if (!trade.id) {
    message.warning('该交易缺少 trade_id，无法创建复盘')
    return
  }
  try {
    const source = reviewSourceByTradeId.value.get(trade.id)
    const review = source?.review_id
      ? { id: source.review_id }
      : await createReviewFromBacktestTrade(trade.id)
    if (selectedReport.value) await loadReviewSources(selectedReport.value.id)
    await router.push({
      name: 'review',
      query: {
        review_id: String(review.id),
        trade_id: String(trade.id),
        report_id: selectedReport.value ? String(selectedReport.value.id) : undefined,
        return_route: currentReturnRoute(route.path, route.query as Record<string, string | string[] | null | undefined>),
      },
      state: { researchScrollY: window.scrollY },
    })
  } catch (err) {
    message.error(apiError(err, '创建或打开复盘失败'))
  }
}

function reviewLabel(trade: BacktestTrade) {
  if (!trade.id) return '无trade_id'
  return reviewSourceByTradeId.value.get(trade.id)?.reviewed ? '查看复盘' : '创建复盘'
}

/** 将单笔交易转为开/平 K 线 marker（含退出类型样式）。 */
function tradeToMarkers(trade: BacktestTrade): KlineMarker[] {
  const isLong = tradeDirectionSide(trade.direction) === 'long'
  const openMarkerTime = nearestBarTime(trade.open_time)
  const closeMarkerTime = trade.close_time ? nearestBarTime(trade.close_time) : ''
  const entryInterval = tradeEntryInterval(trade)
  const stopLoss = tradeStopLossPrice(trade)
  const exitStyle = exitMarkerStyle(trade)
  const markers: KlineMarker[] = [
    {
      id: markerId(trade, 'open'),
      time: openMarkerTime,
      label: formatTradeMarkerText(trade, 'open'),
      tooltip: `trade_id:${trade.id || trade.trade_no} ${isLong ? '开多' : '开空'}${entryInterval ? ` ${entryInterval}` : ''}${tradeScoreTooltip(trade)} 价:${formatNumber(trade.open_price, 2)} 净盈亏:${formatMoney(trade.net_pnl)} / ${trade.entry_reason || tradeRawString(trade, 'entry_reason') || '-'}`,
      color: isLong ? chartTheme.up : chartTheme.down,
      position: isLong ? 'belowBar' : 'aboveBar',
      shape: isLong ? 'arrowUp' : 'arrowDown',
    },
  ]
  if (closeMarkerTime) {
    markers.push(
    {
      id: markerId(trade, 'close'),
      time: closeMarkerTime,
      label: formatTradeMarkerText(trade, 'close'),
      tooltip: `trade_id:${trade.id || trade.trade_no} ${exitStyle.label} ${isLong ? '平多' : '平空'} 价:${formatNumber(trade.close_price, 2)} 净盈亏:${formatMoney(trade.net_pnl)} ${tradeHoldBars(trade)}K / ${rawExitReason(trade)}${stopLoss ? ` / SL ${formatNumber(stopLoss, 2)}` : ''}`,
      color: exitStyle.color,
      position: isLong ? 'aboveBar' : 'belowBar',
      shape: exitStyle.shape,
    },
    )
  }
  return markers
}

function markerId(trade: BacktestTrade, side: 'open' | 'close') {
  return `trade-${trade.trade_no}-${side}`
}

function markerTimeMs(marker: KlineMarker) {
  return exchangeLocalTimeMs(marker.time)
}

function tradeScoreNode(trade: BacktestTrade) {
  const score = tradeEntryScore(trade)
  if (!Number.isFinite(score)) return legacyMissingText()
  const grade = fieldOrLegacy(tradeRawValue(trade, 'entry_grade'))
  return h(
    NTag,
    { size: 'small', type: score >= 3 ? 'success' : 'warning' },
    { default: () => (grade === legacyMissingText() ? `score ${score}` : `score ${score} / ${grade}`) },
  )
}

function renderTradeTags(values: string[], type: 'default' | 'info' = 'default') {
  if (!values.length) return legacyMissingText()
  const visible = values.slice(0, 4)
  const extra = values.length - visible.length
  return h(
    'div',
    { class: 'trade-tag-list' },
    [
      ...visible.map((value) =>
        h(NTag, { size: 'small', type, bordered: false, class: 'trade-tag' }, { default: () => compactTag(value) }),
      ),
      extra > 0 ? h('span', { class: 'trade-tag-more' }, `+${extra}`) : null,
    ],
  )
}

function tradeEntryScore(trade: BacktestTrade) {
  return numberFrom(tradeRawValue(trade, 'entry_score'), Number.NaN)
}

function tradeScoreTooltip(trade: BacktestTrade) {
  const score = tradeEntryScore(trade)
  const scenes = tradeSceneTags(trade).slice(0, 2).join(',')
  const scorePart = Number.isFinite(score) ? ` score:${score}` : ''
  const scenePart = scenes ? ` tags:${scenes}` : ''
  return `${scorePart}${scenePart}`
}

function tradeConditionTags(trade: BacktestTrade) {
  const satisfied = tradeRawList(trade, 'satisfied_conditions')
  const failed = tradeRawList(trade, 'failed_conditions').map((item) => `!${item}`)
  return [...satisfied, ...failed]
}

function tradeSceneTags(trade: BacktestTrade) {
  return tradeRawList(trade, 'scene_tags')
}

function klineDebugItems(query: BacktestMarketBarsQueryDebug) {
  return [
    { label: 'symbol', value: query.symbol || '-' },
    { label: 'vt_symbol', value: query.vt_symbol || '-' },
    { label: 'contract', value: query.contract || '-' },
    { label: 'exchange', value: query.exchange || '-' },
    { label: 'interval', value: query.interval || '-' },
    { label: 'start', value: query.start || '-' },
    { label: 'end', value: query.end || '-' },
    { label: 'provider', value: query.provider || '-' },
    { label: 'data_role', value: query.data_role || '-' },
    { label: 'attempts', value: query.attempted.map((item) => `${item.contract}/${item.period}/${item.provider || '*'}`).join(' → ') },
  ]
}

function tradeEntryInterval(trade: BacktestTrade) {
  return tradeRawString(trade, 'entry_interval')
}

function tradeHoldBars(trade: BacktestTrade) {
  return numberFrom(trade.holding_bars ?? trade.raw_payload?.hold_bars ?? trade.raw_payload?.holding_bars)
}

function tradeStopLossPrice(trade: BacktestTrade) {
  return numberFrom(trade.raw_payload?.stop_loss_price, Number.NaN)
}

function exitMarkerStyle(trade: BacktestTrade) {
  const kind = tradeExitKind(trade)
  if (kind === 'delivery') return { label: '交割风险退出', color: chartTheme.ema, shape: 'square' as const }
  if (kind === 'rollover') return { label: '换月退出', color: chartTheme.atr, shape: 'square' as const }
  if (kind === 'stop') return { label: '止损退出', color: '#f97316', shape: 'circle' as const }
  if (kind === 'time') return { label: '时间退出', color: chartTheme.macdDif, shape: 'circle' as const }
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

function exitReasonLabel(trade: BacktestTrade) {
  const style = exitMarkerStyle(trade)
  return `${style.label} / ${rawExitReason(trade)}`
}

function rawExitReason(trade: BacktestTrade) {
  return trade.exit_reason || tradeRawString(trade, 'exit_reason') || legacyMissingText()
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

function compactTag(value: string) {
  return value.length > 28 ? `${value.slice(0, 25)}...` : value
}

function buildEquityOption(points: BacktestEquityPoint[]): EChartsOption {
  const data = points
    .map((point) => ({ time: pointTime(point), value: numberFrom(point.equity ?? point.balance ?? point.close, Number.NaN) }))
    .filter((point) => point.time && Number.isFinite(point.value))
  return lineOption({
    title: '资金曲线',
    times: data.map((point) => point.time),
    values: data.map((point) => point.value),
    color: chartTheme.macdDif,
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
      axisLine: { lineStyle: { color: chartTheme.axis } },
      axisLabel: { color: chartTheme.textMuted },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { lineStyle: { color: chartTheme.axis } },
      splitLine: { lineStyle: { color: chartTheme.grid } },
      axisLabel: { color: chartTheme.textMuted },
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
  return summaryUsesPercentUnits.value ? numeric : Math.abs(numeric) <= 1 ? numeric * 100 : numeric
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

function statusType(status: string) {
  if (['success', 'completed'].includes(status)) return 'success'
  if (['failed', 'cancelled'].includes(status)) return 'error'
  if (['running', 'queued'].includes(status)) return 'warning'
  return 'default'
}

function reportMetric(...keys: string[]) {
  return selectedReport.value ? rowMetric(selectedReport.value, ...keys) : 0
}

function reportMetricValue(...keys: string[]) {
  return selectedReport.value ? rowMetricValue(selectedReport.value, ...keys) : null
}

function rowMetric(row: BacktestReport, ...keys: string[]) {
  return rowMetricValue(row, ...keys) ?? 0
}

function rowMetricValue(row: BacktestReport, ...keys: string[]) {
  for (const key of keys) {
    const directValue = (row as unknown as Record<string, unknown>)[key]
    const summaryValue = row.summary?.[key]
    const numeric = numberFrom(directValue ?? summaryValue, Number.NaN)
    if (Number.isFinite(numeric)) return numeric
  }
  return null
}

function formatDrawdown(row: BacktestReport) {
  const pct = formatDrawdownPct(row)
  const amount = formatDrawdownAmount(row)
  if (pct !== legacyMissingText() && amount !== legacyMissingText()) return `${pct} / ${amount}`
  if (pct !== legacyMissingText()) return pct
  if (amount !== legacyMissingText()) return amount
  return legacyMissingText()
}

function formatDrawdownPct(row: BacktestReport) {
  const pct = rowDrawdownPct(row)
  if (Number.isFinite(pct)) return formatPerformancePct(pct, summaryHasPercentUnits(row.summary || {}))
  return legacyMissingText()
}

function formatDrawdownAmount(row: BacktestReport) {
  return formatMoneyOrLegacy(rowMetricValue(row, 'max_drawdown_amount'))
}

function rowDrawdownPct(row: BacktestReport) {
  for (const value of [
    row.max_drawdown_pct,
    row.summary?.max_drawdown_pct,
    row.summary?.max_ddpercent,
    row.summary?.ddpercent,
  ]) {
    const numeric = numberFrom(value, Number.NaN)
    if (Number.isFinite(numeric)) return numeric
  }
  return Number.NaN
}

function reportDateRange(row: BacktestReport) {
  const metadata = objectRecord(row.summary?.report_metadata)
  const start = summaryString(metadata, 'start') || row.started_at
  const end = summaryString(metadata, 'end') || row.finished_at
  if (!start && !end) return '-'
  return `${formatDateTime(start)} → ${formatDateTime(end)}`
}

function summaryString(value: unknown, key: string) {
  const record = objectRecord(value)
  const item = record?.[key]
  return item === undefined || item === null ? '' : String(item)
}

function objectRecord(value: unknown) {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null
}

function pnlTone(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return undefined
}

function reportKindLabel(row: BacktestReport) {
  const strategy = row.strategy_code || summaryString(row.summary?.report_metadata, 'strategy_code')
  if (isV1FinalReport(row)) return 'JM V1-B 研究'
  if (strategy === JM_V1B_STRATEGY_CODE) return 'JM V1-B 旧版'
  return 'Smoke / 通用'
}

function reportKindType(row: BacktestReport) {
  const kind = reportKindLabel(row)
  if (kind === 'JM V1-B 研究') return 'info'
  if (kind === 'JM V1-B 旧版') return 'warning'
  return 'default'
}

function formatIndicatorPolicyStatus(value?: string | null) {
  if (!value || value === 'unavailable') return '未绑定（非策略有效证明）'
  if (value === 'available') return '已记录（审计字段，非盈利/validated）'
  return `${value}（审计字段，非 validated）`
}

function isV1FinalReport(row: BacktestReport) {
  const strategy = row.strategy_code || summaryString(row.summary?.report_metadata, 'strategy_code')
  return strategy === JM_V1B_STRATEGY_CODE && Boolean(row.summary?.real_contract_enrichment)
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function formatPerformancePct(value: number, percentUnits = summaryUsesPercentUnits.value) {
  if (!Number.isFinite(value)) return '-'
  const percent = percentUnits ? value : value * 100
  return `${percent.toFixed(2)}%`
}

function formatPercentOrLegacy(value: number | null, percentUnits = summaryUsesPercentUnits.value) {
  return value === null ? legacyMissingText() : formatPerformancePct(value, percentUnits)
}

function formatRatioPct(value: number) {
  if (!Number.isFinite(value)) return '-'
  const percent = Math.abs(value) <= 1 ? value * 100 : value
  return `${percent.toFixed(2)}%`
}

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatMoneyOrLegacy(value: number | null) {
  return value === null ? legacyMissingText() : formatMoney(value)
}

function formatNumber(value: number, digits = 2) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatNumberOrLegacy(value: number | null, digits = 2) {
  return value === null ? legacyMissingText() : formatNumber(value, digits)
}

function formatInteger(value: number) {
  return Math.round(value).toLocaleString('zh-CN')
}

function formatIntegerOrLegacy(value: number | null) {
  return value === null ? legacyMissingText() : formatInteger(value)
}

function optionalNumber(value: unknown) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function fieldOrLegacy(value: unknown) {
  return value === undefined || value === null || value === '' ? legacyMissingText() : String(value)
}

function legacyMissingText() {
  return selectedReport.value && reportKindLabel(selectedReport.value) !== 'JM V1-B 研究' ? '旧报告无该字段' : '未记录'
}

function numberFrom(value: unknown, fallback = 0) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function summaryHasPercentUnits(value: Record<string, unknown>) {
  return ['capital', 'end_balance', 'total_net_pnl', 'total_trade_count', 'max_ddpercent'].some((key) => value[key] !== undefined)
}

function apiError(err: unknown, fallback: string) {
  return describeBacktestApiError(err, fallback)
}

function tradeDirectionSide(direction: string) {
  const normalized = String(direction).trim().toLowerCase()
  if (['long', 'buy', '多'].includes(normalized)) return 'long'
  if (['short', 'sell', '空'].includes(normalized)) return 'short'
  return normalized.includes('空') || normalized.includes('short') || normalized.includes('sell') ? 'short' : 'long'
}

function directionLabel(direction: string) {
  return tradeDirectionSide(direction) === 'long' ? '多' : '空'
}
</script>

<template>
  <PageShell title="回测中心" subtitle="研究回测、可信审计与报告复盘；报告可信不等于策略有效">
    <template #badges>
      <div class="backtest-page__badges">
        <CapabilityBadge kind="research-only" label="通用表单" />
        <CapabilityBadge kind="formal-research" label="JM 固定任务" />
      </div>
    </template>
    <div class="backtest-page">
    <JmV1bQuickTasks @task-completed="handleV1bTaskCompleted" />
    <section class="panel">
      <div class="panel__header">
        <div>
          <h2>回测任务</h2>
          <p>vn.py CTA 研究任务（使用明确的 canonical DatasetKey 请求）</p>
        </div>
        <div class="header-actions">
          <NInputNumber
            v-model:value="reportIdInput"
            class="report-id-input"
            placeholder="report_id"
            :min="1"
            :show-button="false"
            clearable
            @keyup.enter="openReportFromInput"
          />
          <NButton :loading="loadingReportDetail" @click="openReportFromInput">打开报告</NButton>
          <NButton quaternary @click="router.push({ name: 'backtest-batch' })">批量回测（Legacy）</NButton>
          <NButton :loading="loadingTasks" @click="loadTasks">刷新任务</NButton>
          <NButton type="primary" :loading="submitting" :disabled="!canSubmit" @click="submitTask">创建任务</NButton>
        </div>
      </div>

      <NAlert type="warning" :bordered="false" class="risk-alert">{{ DISCLAIMER }}</NAlert>
      <NAlert type="info" :bordered="false" class="risk-alert">
        任务只提交 DatasetKey 身份；后端返回 input_identity、Manifest 与 digest 供审计。Indicator Policy / trust 字段不代表策略有效。
      </NAlert>
      <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>

      <NForm class="task-form" label-placement="top">
        <NFormItem label="策略代码">
          <NInput v-model:value="form.strategy_code" placeholder="如 su_bing_ema21；必填" />
        </NFormItem>
        <NFormItem label="策略版本">
          <NInput v-model:value="form.strategy_version" placeholder="如 demo-0.1.0；必填" />
        </NFormItem>
        <NFormItem label="回测引擎">
          <NSelect v-model:value="form.engine_type" :options="engineOptions" disabled />
        </NFormItem>
        <NFormItem label="数据集类型">
          <NSelect v-model:value="form.dataset_kind" :options="datasetKindOptions" />
        </NFormItem>
        <NFormItem label="品种代码">
          <NInput v-model:value="form.instrument_symbol" placeholder="从 registry / coverage 选择，如 jm" />
        </NFormItem>
        <NFormItem label="合约或连续序列">
          <NInput v-model:value="form.contract_or_series" placeholder="如 jm2609 或 JM.MAIN；必须与数据集类型一致" />
        </NFormItem>
        <NFormItem label="交易所">
          <NInput v-model:value="form.exchange" placeholder="如 DCE / SHFE" />
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
        <NFormItem label="策略参数">
          <NInput v-model:value="form.strategy_params" type="textarea" :autosize="{ minRows: 7, maxRows: 12 }" />
        </NFormItem>
      </NForm>

      <NAlert type="info" :bordered="false">
        当前 active 数据入口仅使用 RQData / Local Standard Parquet 的 primary 数据。
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
        remote
        :pagination="taskPagination"
      />
    </section>

    <section class="panel">
      <div class="panel__header compact">
        <div class="panel__title">回测报告</div>
        <NButton size="small" :loading="loadingReports" @click="loadReports">刷新</NButton>
      </div>
      <div v-if="jmV1bReports.length" class="v1b-report-strip">
        <span>JM V1-B 研究报告（非 validated）</span>
        <NButton
          v-for="report in jmV1bReports"
          :key="report.id"
          size="small"
          secondary
          @click="openReport(report.id)"
        >
          #{{ report.id }} · {{ report.period }} entry · {{ reportDateRange(report) }}
        </NButton>
      </div>
      <NDataTable
        :columns="reportColumns"
        :data="reports"
        :loading="loadingReports"
        :bordered="false"
        size="small"
        remote
        :pagination="reportPagination"
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
      <NAlert v-if="selectedReport.error_message" type="error" :bordered="false">
        {{ selectedReport.error_message }}
      </NAlert>
      <NAlert v-if="selectedReport.warnings?.length" type="info" :bordered="false">
        {{ selectedReport.warnings.join('；') }}
      </NAlert>

      <section v-if="reportPresentation" class="report-evidence">
        <div class="subsection-title">报告身份与可信边界</div>
        <NAlert type="info" :bordered="false" class="risk-alert">
          {{ reportPresentation.boundary }}
        </NAlert>
        <NDescriptions :column="2" bordered size="small">
          <NDescriptionsItem label="报告身份"><code>{{ reportPresentation.identity }}</code></NDescriptionsItem>
          <NDescriptionsItem label="Trust audit">
            <NTag size="small" :type="reportPresentation.trustAudit === 'passed' ? 'success' : 'warning'">
              {{ reportPresentation.trustAudit }}
            </NTag>
          </NDescriptionsItem>
          <NDescriptionsItem label="Canonical request"><code>{{ reportPresentation.canonicalInput.request }}</code></NDescriptionsItem>
          <NDescriptionsItem label="Source DatasetKey" :span="2"><code>{{ reportPresentation.canonicalInput.sourceDatasets }}</code></NDescriptionsItem>
          <NDescriptionsItem label="Manifest digests" :span="2"><code>{{ reportPresentation.canonicalInput.manifestDigests }}</code></NDescriptionsItem>
          <NDescriptionsItem label="Requested window" :span="2"><code>{{ reportPresentation.canonicalInput.requestedWindow }}</code></NDescriptionsItem>
          <NDescriptionsItem label="Input digest" :span="2"><code>{{ reportPresentation.canonicalInput.digest }}</code></NDescriptionsItem>
          <NDescriptionsItem label="成本模型"><code>{{ reportPresentation.costModel }}</code></NDescriptionsItem>
          <NDescriptionsItem label="验证证据">{{ reportPresentation.validationEvidence }}</NDescriptionsItem>
          <NDescriptionsItem label="候选状态"><code>{{ reportPresentation.candidateStatus }}</code></NDescriptionsItem>
          <NDescriptionsItem label="OOS">{{ reportPresentation.oosWindow }} · {{ reportPresentation.oosGate }}</NDescriptionsItem>
          <NDescriptionsItem label="Hard reject" :span="2"><code>{{ reportPresentation.hardReject }}</code></NDescriptionsItem>
        </NDescriptions>
      </section>

      <div class="subsection-title result-heading">回测结果与成本</div>
      <div class="report-meta">
        <span v-for="item in reportMetaItems" :key="item.label">
          {{ item.label }}：<strong>{{ item.value }}</strong>
        </span>
      </div>

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

      <div class="kline-panel kline-panel--wide">
        <div class="kline-panel__header">
          <div>
            <div class="subsection-title">K线买卖点复盘</div>
            <small>成交 marker 会随交易明细选择定位到对应 K 线时间</small>
          </div>
        </div>
        <KlineChart
          ref="klineChartRef"
          :bars="bars"
          :markers="klineMarkers"
          :active-marker-id="activeMarkerId"
          :loading="loadingKline"
          :error="klineError"
        />
        <div v-if="!loadingKline && bars.length === 0" class="kline-query-state">
          <strong>当前 K线查询未返回数据</strong>
          <span v-for="item in klineQueryItems" :key="item.label">{{ item.label }}={{ item.value }}</span>
        </div>
      </div>

      <div class="trade-panel trade-panel--wide">
        <NTabs v-model:value="detailTab" type="line">
          <NTabPane name="trades" tab="交易明细">
        <div class="trade-panel__header">
          <div>
            <div class="subsection-title">交易明细</div>
            <small class="trade-total">共 {{ tradeTotal.toLocaleString('zh-CN') }} 笔</small>
          </div>
          <div class="trade-actions">
            <NSelect
              v-model:value="tradeSortBy"
              class="trade-sort-select"
              size="small"
              :options="tradeSortOptions"
              :disabled="loadingTrades"
              @update:value="handleTradeSortChange"
            />
            <NSelect
              v-model:value="tradeSortOrder"
              class="trade-order-select"
              size="small"
              :options="tradeSortOrderOptions"
              :disabled="loadingTrades"
              @update:value="handleTradeSortChange"
            />
            <NButton
              size="small"
              :disabled="!canExportTrades || exportingTradeFormat !== null"
              :loading="exportingTradeFormat === 'csv'"
              @click="downloadTradeExport('csv')"
            >
              导出 CSV
            </NButton>
            <NButton
              size="small"
              :disabled="!canExportTrades || exportingTradeFormat !== null"
              :loading="exportingTradeFormat === 'json'"
              @click="downloadTradeExport('json')"
            >
              导出 JSON
            </NButton>
          </div>
        </div>
        <NAlert v-if="tradeError" type="error" :bordered="false">{{ tradeError }}</NAlert>
        <div v-if="selectedTrade" class="selected-trade">
          <span>{{ selectedTrade.trade_no }}</span>
          <strong :class="selectedTrade.net_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'">
            {{ formatMoney(selectedTrade.net_pnl) }}
          </strong>
          <small>
            {{ tradeEntryInterval(selectedTrade) || selectedReport.period }} · {{ tradeHoldBars(selectedTrade) }}K ·
            {{ selectedTrade.entry_reason || tradeRawString(selectedTrade, 'entry_reason') || '-' }} /
            {{ selectedTrade.exit_reason || tradeRawString(selectedTrade, 'exit_reason') || '-' }}
          </small>
          <small>
            {{ Number.isFinite(tradeEntryScore(selectedTrade)) ? `score ${tradeEntryScore(selectedTrade)}` : 'score 未记录' }} ·
            {{ tradeConditionTags(selectedTrade).join(' / ') || '条件未记录' }} ·
            {{ tradeSceneTags(selectedTrade).join(' / ') || '场景未记录' }}
          </small>
        </div>
        <NDataTable
          :columns="tradeColumns"
          :data="reportTrades"
          :loading="loadingReportDetail || loadingTrades"
          :bordered="false"
          :row-props="tradeRowProps"
          size="small"
          remote
          :pagination="tradePagination"
          :scroll-x="1880"
        >
          <template #empty>
            <NEmpty description="暂无成交记录" />
          </template>
        </NDataTable>
          </NTabPane>
          <NTabPane name="orders" tab="委托明细">
            <NDataTable
              :columns="[
                { title: '订单号', key: 'order_no', minWidth: 120 },
                { title: '方向', key: 'direction', width: 80 },
                { title: '开平', key: 'offset', width: 80 },
                { title: '价格', key: 'price', width: 100 },
                { title: '数量', key: 'volume', width: 80 },
                { title: '时间', key: 'datetime', minWidth: 170 },
              ]"
              :data="reportOrders"
              :loading="loadingOrders"
              size="small"
              :bordered="false"
            />
          </NTabPane>
        </NTabs>
      </div>
    </section>
    </div>
  </PageShell>
</template>

<style scoped>
.backtest-page {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-4);
  min-width: 0;
}

.backtest-page__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gy-space-3);
}

.backtest-page__title {
  margin: 0;
  font-size: var(--gy-font-size-xl);
}

.backtest-page__subtitle {
  margin: 4px 0 0;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.backtest-page__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.panel {
  min-width: 0;
  padding: var(--gy-panel-padding);
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
}

.panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gy-space-3);
  margin-bottom: var(--gy-space-3);
}

.panel__header.compact {
  align-items: center;
}

.panel__header h2 {
  margin: 0;
  font-size: var(--gy-font-size-lg);
}

.panel__header p {
  margin: 4px 0 0;
  color: var(--gy-text-muted);
}

.panel__title,
.subsection-title {
  color: var(--gy-text-primary);
  font-weight: 600;
}

.subsection-title {
  margin-bottom: 10px;
  font-size: var(--gy-font-size-md);
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gy-space-2);
}

.report-id-input {
  width: 128px;
}

.risk-alert {
  margin-bottom: 12px;
}

.task-form {
  display: grid;
  grid-template-columns: repeat(4, minmax(160px, 1fr));
  gap: var(--gy-space-1) var(--gy-space-3);
}

.task-form :deep(.n-form-item:last-child) {
  grid-column: span 4;
}

.report-detail {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-4);
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gy-space-2) var(--gy-space-4);
  min-width: 0;
  padding: 8px 10px;
  color: var(--gy-text-muted);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
  font-size: var(--gy-font-size-sm);
}

.report-meta strong {
  color: var(--gy-text-primary);
  font-weight: 600;
}

.v1b-report-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 10px;
  color: var(--gy-text-secondary);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
  font-size: var(--gy-font-size-sm);
}

.v1b-report-strip span {
  color: var(--gy-text-muted);
  font-weight: 600;
}

.report-metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: var(--gy-space-3);
}

.report-evidence {
  margin: var(--gy-space-3) 0 var(--gy-space-4);
}

.result-heading {
  margin-top: var(--gy-space-4);
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 64px;
  padding: 10px;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.metric-card span {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.metric-card strong {
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-lg);
}

.metric-card.positive strong,
.pnl-positive {
  color: var(--gy-up);
}

.metric-card.negative strong,
.pnl-negative {
  color: var(--gy-down);
}

.metric-card.risk strong {
  color: var(--gy-status-warning);
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gy-space-3);
}

.chart-panel,
.kline-panel,
.trade-panel {
  min-width: 0;
  padding: 12px;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.kline-panel--wide,
.trade-panel--wide {
  width: 100%;
}

.kline-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.kline-panel__header .subsection-title {
  margin-bottom: 2px;
}

.kline-panel__header small {
  color: var(--gy-text-muted);
}

.kline-query-state {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-top: 10px;
  padding: 8px 10px;
  color: var(--gy-text-secondary);
  background: var(--gy-bg-canvas);
  border: 1px solid var(--gy-border-strong);
  border-radius: var(--gy-radius-md);
  font-size: var(--gy-font-size-sm);
}

.kline-query-state strong {
  color: #fecaca;
}

.kline-query-state span {
  color: var(--gy-text-muted);
}

.trade-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.trade-panel__header .subsection-title {
  margin-bottom: 2px;
}

.trade-total {
  color: var(--gy-text-muted);
}

.trade-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.trade-sort-select {
  width: 112px;
}

.trade-order-select {
  width: 82px;
}

.trade-panel :deep(.n-data-table) {
  min-width: 0;
}

.trade-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 100%;
}

.trade-tag {
  max-width: 132px;
}

.trade-tag-more {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
  line-height: 22px;
}

.selected-trade {
  display: grid;
  grid-template-columns: auto auto 1fr;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  margin-bottom: 8px;
  padding: 8px 10px;
  color: var(--gy-text-secondary);
  background: var(--gy-bg-canvas);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.selected-trade small {
  grid-column: 3;
  min-width: 0;
  overflow: hidden;
  color: var(--gy-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.trade-row-active td) {
  background: var(--gy-status-info-soft) !important;
}

@media (max-width: 1380px) {
  .report-metrics {
    grid-template-columns: repeat(4, minmax(120px, 1fr));
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

  .trade-panel__header {
    flex-direction: column;
  }

  .kline-panel__header {
    flex-direction: column;
  }

  .trade-actions {
    justify-content: flex-start;
  }
}
</style>
