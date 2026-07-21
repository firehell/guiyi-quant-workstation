<script setup lang="ts">
/** 批量回测：按品种池 × 参数模板并行跑苏冰策略，WebSocket + 轮询跟踪进度。 */
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
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
  NProgress,
  NSelect,
  NSwitch,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import BaseChart from '@/components/charts/BaseChart.vue'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import { resolveChartTheme } from '@/styles/chartTheme'
import {
  getBacktestReport,
  getBacktestTask,
  getBacktestTaskReports,
  getWatchlistItems,
  getWatchlists,
  runBatchBacktest,
} from '@/api/strategy'
import type {
  BacktestReportPayload,
  BacktestTaskEvent,
  BatchBacktestReport,
  BatchBacktestTask,
  BatchBacktestParameterTemplate,
  WatchlistInfo,
  WatchlistItemInfo,
} from '@/types/strategy'
import { PERIODS } from '@/utils/constants'
import { WsClient } from '@/websocket/WsClient'
import { backtestTaskWsUrl } from '@/websocket'

const BATCH_FORMAL_GATE = 'BATCH_BACKTEST_FORMAL_READY'
const BATCH_GATE_STATUS = 'BATCH_BACKTEST_RESEARCH_ONLY'
/** 缺少 formal Gate：默认禁止新启动，仅保留历史查询。 */
const canStartBatch = false

const router = useRouter()
const message = useMessage()
const chartTheme = resolveChartTheme()
const loadingMeta = ref(false)
const running = ref(false)
const loadingReports = ref(false)
const error = ref<string | null>(null)
const watchlists = ref<WatchlistInfo[]>([])
const watchlistItems = ref<WatchlistItemInfo[]>([])
const reports = ref<BatchBacktestReport[]>([])
const currentTask = ref<BatchBacktestTask | null>(null)
const detailReport = ref<(BacktestReportPayload & BatchBacktestReport) | null>(null)
const detailVisible = ref(false)
const selectedLabel = ref('all')

const selectedWatchlist = ref('black')
const selectedSymbols = ref<string[]>([])
const selectedPeriod = ref('5m')
const dateRange = ref<[number, number] | null>([new Date('2021-01-01').getTime(), new Date('2026-06-05').getTime()])
const initialCapital = ref(100000)
const riskPerTradePct = ref(1)
const maxMarginUsagePct = ref(35)
const slippageTicks = ref(1)
const enableTakeProfit = ref(true)
const selectedTemplates = ref(['default', 'strict', 'loose'])
const periodOptions = PERIODS.map((item) => ({ label: item.label, value: item.value }))

let ws: WsClient | null = null
/** 轮询兜底定时器（WS 断线时仍能刷新任务状态） */
let pollTimer: number | null = null

const parameterTemplates: BatchBacktestParameterTemplate[] = [
  { name: 'default', label: '默认', strategy_params: {}, overrides: {} },
  {
    name: 'strict',
    label: '严格共振',
    strategy_params: { confluence_threshold: 4, max_distance_from_ema_atr: 1.2 },
    overrides: { risk_per_trade_pct: 0.008 },
  },
  {
    name: 'loose',
    label: '宽松试单',
    strategy_params: { confluence_threshold: 2, max_distance_from_ema_atr: 2.0 },
    overrides: { risk_per_trade_pct: 0.006 },
  },
]

const watchlistOptions = computed(() => watchlists.value.map((item) => ({ label: `${item.name} (${item.item_count})`, value: item.code })))
const symbolOptions = computed(() =>
  watchlistItems.value.map((item) => ({
    label: `${item.name || item.symbol} (${item.symbol})`,
    value: item.symbol,
  })),
)
const templateOptions = computed(() => parameterTemplates.map((item) => ({ label: item.label || item.name, value: item.name })))
const labelOptions = [
  { label: '全部', value: 'all' },
  { label: '适合', value: '适合' },
  { label: '观察', value: '观察' },
  { label: '不适合', value: '不适合' },
  { label: '数据不足', value: '数据不足' },
]

const filteredReports = computed(() => {
  const rows = selectedLabel.value !== 'all' ? reports.value.filter((report) => report.suitability_label === selectedLabel.value) : reports.value
  return [...rows].sort((first, second) => second.suitability_score - first.suitability_score)
})

const completedReports = computed(() => reports.value.filter((report) => report.status === 'completed'))
const suitableCount = computed(() => reports.value.filter((report) => report.suitability_label === '适合').length)
const progressStatus = computed(() => {
  if (!currentTask.value) return 'default'
  if (currentTask.value.status === 'failed') return 'error'
  if (currentTask.value.status === 'completed') return 'success'
  if (currentTask.value.status === 'partial_failed') return 'warning'
  return 'info'
})

const contributionOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 24, right: 28, bottom: 48, left: 54 },
  xAxis: {
    type: 'category',
    data: filteredReports.value.slice(0, 20).map((report) => `${report.symbol}/${report.template_name}`),
    axisLabel: { color: chartTheme.textMuted, rotate: 35 },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: chartTheme.textMuted, formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
    splitLine: { lineStyle: { color: chartTheme.grid } },
  },
  series: [
    {
      type: 'bar',
      name: '总收益',
      data: filteredReports.value.slice(0, 20).map((report) => ({
        value: round(report.summary.total_return || 0),
        itemStyle: { color: (report.summary.total_return || 0) >= 0 ? chartTheme.up : chartTheme.down },
      })),
    },
  ],
}))

const templateOption = computed<EChartsOption>(() => {
  const stats = currentTask.value?.result_payload.template_stats || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { top: 24, right: 28, bottom: 32, left: 54 },
    xAxis: { type: 'category', data: stats.map((item) => item.template_name), axisLabel: { color: chartTheme.textMuted } },
    yAxis: { type: 'value', axisLabel: { color: chartTheme.textMuted }, splitLine: { lineStyle: { color: chartTheme.grid } } },
    series: [
      {
        type: 'bar',
        name: '平均评分',
        data: stats.map((item) => round(item.average_score)),
        itemStyle: { color: chartTheme.macdDif },
      },
    ],
  }
})

const reportColumns: DataTableColumns<BatchBacktestReport> = [
  {
    title: '品种',
    key: 'symbol',
    width: 100,
    render: (row) => h('strong', `${row.symbol}`),
  },
  { title: '合约', key: 'contract', width: 110 },
  { title: '模板', key: 'template_name', width: 100 },
  {
    title: '状态',
    key: 'status',
    width: 96,
    render: (row) => h(NTag, { size: 'small', type: statusType(row.status) }, { default: () => statusText(row.status) }),
  },
  {
    title: '适配',
    key: 'suitability_label',
    width: 96,
    render: (row) => h(NTag, { size: 'small', type: labelType(row.suitability_label) }, { default: () => row.suitability_label }),
  },
  { title: '评分', key: 'suitability_score', width: 82, render: (row) => formatNumber(row.suitability_score, 1) },
  {
    title: '总收益',
    key: 'total_return',
    render: (row) =>
      h('span', { class: (row.summary.total_return || 0) >= 0 ? 'text-up' : 'text-down' }, formatPct(row.summary.total_return || 0)),
  },
  { title: '最大回撤', key: 'max_drawdown', render: (row) => formatPct(row.summary.max_drawdown || 0) },
  { title: '胜率', key: 'win_rate', render: (row) => formatPct(row.summary.win_rate || 0) },
  { title: '盈亏比', key: 'profit_loss_ratio', render: (row) => formatNumber(row.summary.profit_loss_ratio || 0) },
  { title: '交易', key: 'total_trades', width: 70, render: (row) => row.summary.total_trades || 0 },
  {
    title: '操作',
    key: 'actions',
    width: 96,
    render: (row) =>
      h(
        NButton,
        { size: 'small', disabled: row.status !== 'completed', onClick: () => openReport(row) },
        { default: () => '详情' },
      ),
  },
]

watch(selectedWatchlist, async () => {
  await loadWatchlistItems()
})

onMounted(async () => {
  await loadMeta()
})

onUnmounted(() => {
  stopProgressWatch()
})

async function loadMeta() {
  loadingMeta.value = true
  error.value = null
  try {
    watchlists.value = await getWatchlists()
    await loadWatchlistItems()
  } catch (err) {
    error.value = apiError(err, '加载品种池失败')
  } finally {
    loadingMeta.value = false
  }
}

async function loadWatchlistItems() {
  if (!selectedWatchlist.value) return
  watchlistItems.value = await getWatchlistItems(selectedWatchlist.value)
  selectedSymbols.value = watchlistItems.value.filter((item) => item.available_periods.includes(selectedPeriod.value)).map((item) => item.symbol)
}

/** 提交批量回测任务，成功后进入进度监听。 */
async function startBatch() {
  if (!canStartBatch) {
    message.warning(`批量回测处于 ${BATCH_GATE_STATUS}；缺少 ${BATCH_FORMAL_GATE}，禁止启动新任务`)
    return
  }
  if (!dateRange.value || selectedTemplates.value.length === 0) {
    message.warning('请先设置区间和参数模板')
    return
  }
  running.value = true
  error.value = null
  reports.value = []
  currentTask.value = null
  try {
    const task = await runBatchBacktest({
      watchlist_code: selectedWatchlist.value,
      period: selectedPeriod.value,
      start: formatDate(dateRange.value[0]),
      end: formatDate(dateRange.value[1]),
      symbols: selectedSymbols.value.length ? selectedSymbols.value : undefined,
      initial_capital: initialCapital.value,
      risk_per_trade_pct: riskPerTradePct.value / 100,
      max_margin_usage_pct: maxMarginUsagePct.value / 100,
      slippage_ticks: slippageTicks.value,
      take_profit_r: 2,
      enable_take_profit: enableTakeProfit.value,
      parameter_templates: parameterTemplates.filter((item) => selectedTemplates.value.includes(item.name)),
    })
    currentTask.value = task
    watchProgress(task.task_no)
  } catch (err) {
    error.value = apiError(err, '批量回测启动失败')
    running.value = false
  }
}

/**
 * 通过 WebSocket 订阅任务事件，并以 2.5s 轮询兜底；
 * 终态时停止监听并刷新报告列表。
 */
function watchProgress(taskNo: string) {
  stopProgressWatch()
  ws = new WsClient(backtestTaskWsUrl(taskNo))
  const update = (data: unknown) => {
    currentTask.value = { ...(currentTask.value as BatchBacktestTask), ...(data as BacktestTaskEvent) }
    if (['completed', 'partial_failed', 'failed'].includes(currentTask.value.status)) {
      running.value = false
      refreshReports(taskNo)
    }
  }
  ws.on('snapshot', update)
  ws.on('started', update)
  ws.on('progress', update)
  ws.on('item_completed', update)
  ws.on('item_failed', update)
  ws.on('completed', update)
  ws.on('failed', update)
  ws.connect()
  pollTimer = window.setInterval(async () => {
    const task = await getBacktestTask(taskNo)
    currentTask.value = task
    await refreshReports(taskNo)
    if (['completed', 'partial_failed', 'failed'].includes(task.status)) {
      running.value = false
      stopProgressWatch(false)
    }
  }, 2500)
}

/** 断开 WS 并清除轮询；可选重置 running 标志。 */
function stopProgressWatch(clearTask = true) {
  ws?.disconnect()
  ws = null
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
  if (clearTask) running.value = false
}

async function refreshReports(taskNo: string) {
  loadingReports.value = true
  try {
    reports.value = await getBacktestTaskReports(taskNo)
  } finally {
    loadingReports.value = false
  }
}

async function openReport(row: BatchBacktestReport) {
  detailReport.value = await getBacktestReport(row.id)
  detailVisible.value = true
}

function jumpSingleBacktest(row: BatchBacktestReport) {
  router.push({ name: 'backtest', query: { symbol: row.symbol, contract: row.contract, period: row.period } })
}

function statusText(status: BatchBacktestReport['status'] | BatchBacktestTask['status']) {
  const labels: Record<string, string> = {
    pending: '等待',
    running: '运行中',
    completed: '完成',
    partial_failed: '部分失败',
    failed: '失败',
    skipped: '跳过',
    cancelled: '取消',
  }
  return labels[status] || status
}

function statusType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'skipped' || status === 'partial_failed') return 'warning'
  return 'info'
}

function labelType(label: string) {
  if (label === '适合') return 'success'
  if (label === '观察') return 'warning'
  if (label === '不适合') return 'error'
  return 'default'
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
  <div class="batch-page">
    <section class="panel toolbar-panel">
      <div class="panel__header">
        <div>
          <div class="batch-title-row">
            <h2>批量回测</h2>
            <CapabilityBadge kind="unavailable" label="Legacy" />
          </div>
          <p>苏冰模板 × 品种池 suitability 研究；裁定 {{ BATCH_GATE_STATUS }}，非 formal validated</p>
        </div>
        <div class="actions">
          <NButton @click="router.push({ name: 'backtest' })">单品种回测</NButton>
          <NButton type="primary" :loading="running" :disabled="!canStartBatch" @click="startBatch">启动批量任务</NButton>
        </div>
      </div>

      <NAlert type="error" :bordered="false">
        Gate {{ BATCH_GATE_STATUS }}：后端虽有 Profile binding（passed_only），但入口为 SuBing 模板 + suitability 标签，
        无完整 formal research 闭环契约；默认禁用新启动。可查看下方历史任务/报告。
        解除需 {{ BATCH_FORMAL_GATE }} 证据。
      </NAlert>

      <NForm class="toolbar" label-placement="top">
        <NFormItem label="品种池">
          <NSelect v-model:value="selectedWatchlist" :options="watchlistOptions" :loading="loadingMeta" />
        </NFormItem>
        <NFormItem label="品种">
          <NSelect v-model:value="selectedSymbols" multiple filterable :options="symbolOptions" :max-tag-count="2" />
        </NFormItem>
        <NFormItem label="周期">
          <NSelect v-model:value="selectedPeriod" :options="periodOptions" />
        </NFormItem>
        <NFormItem label="区间">
          <NDatePicker v-model:value="dateRange" type="daterange" clearable />
        </NFormItem>
        <NFormItem label="参数模板">
          <NSelect v-model:value="selectedTemplates" multiple :options="templateOptions" />
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
      </NForm>
    </section>

    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>

    <section class="panel progress-panel">
      <div class="progress-head">
        <div>
          <span class="muted">任务</span>
          <strong>{{ currentTask?.task_no || '尚未启动' }}</strong>
        </div>
        <NTag :type="progressStatus">{{ currentTask ? statusText(currentTask.status) : '等待' }}</NTag>
      </div>
      <NProgress
        type="line"
        :percentage="currentTask?.progress || 0"
        :status="progressStatus"
        :height="10"
        :border-radius="4"
      />
      <div class="progress-stats">
        <span>总数 {{ currentTask?.total_items || 0 }}</span>
        <span>完成 {{ currentTask?.completed_items || 0 }}</span>
        <span>跳过 {{ currentTask?.skipped_items || 0 }}</span>
        <span>失败 {{ currentTask?.failed_items || 0 }}</span>
      </div>
    </section>

    <section class="metrics">
      <div class="metric">
        <span>报告数</span>
        <strong>{{ reports.length }}</strong>
      </div>
      <div class="metric">
        <span>完成报告</span>
        <strong>{{ completedReports.length }}</strong>
      </div>
      <div class="metric">
        <span>适合品种</span>
        <strong class="text-up">{{ suitableCount }}</strong>
      </div>
      <div class="metric">
        <span>最高评分</span>
        <strong>{{ reports.length ? formatNumber(Math.max(...reports.map((item) => item.suitability_score)), 1) : '-' }}</strong>
      </div>
    </section>

    <section class="chart-grid">
      <div class="panel">
        <div class="panel__title">品种贡献排行</div>
        <BaseChart :option="contributionOption" height="300px" />
      </div>
      <div class="panel">
        <div class="panel__title">参数模板对比</div>
        <BaseChart :option="templateOption" height="300px" />
      </div>
    </section>

    <section class="panel">
      <div class="table-head">
        <div class="panel__title">品种表现</div>
        <NSelect v-model:value="selectedLabel" class="label-filter" :options="labelOptions" />
      </div>
      <NDataTable
        :columns="reportColumns"
        :data="filteredReports"
        :loading="loadingReports"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="{ pageSize: 12 }"
      />
    </section>

    <NDrawer v-model:show="detailVisible" width="620">
      <NDrawerContent title="批量报告详情">
        <div v-if="detailReport" class="drawer-content">
          <NDescriptions :column="2" bordered size="small">
            <NDescriptionsItem label="品种">{{ detailReport.symbol }}</NDescriptionsItem>
            <NDescriptionsItem label="合约">{{ detailReport.contract }}</NDescriptionsItem>
            <NDescriptionsItem label="模板">{{ detailReport.template_name }}</NDescriptionsItem>
            <NDescriptionsItem label="适配">{{ detailReport.suitability_label }} / {{ formatNumber(detailReport.suitability_score, 1) }}</NDescriptionsItem>
            <NDescriptionsItem label="总收益">{{ formatPct(detailReport.summary.total_return || 0) }}</NDescriptionsItem>
            <NDescriptionsItem label="最大回撤">{{ formatPct(detailReport.summary.max_drawdown || 0) }}</NDescriptionsItem>
            <NDescriptionsItem label="胜率">{{ formatPct(detailReport.summary.win_rate || 0) }}</NDescriptionsItem>
            <NDescriptionsItem label="交易次数">{{ detailReport.summary.total_trades || 0 }}</NDescriptionsItem>
            <NDescriptionsItem label="手续费">{{ formatMoney(detailReport.summary.total_commission || 0) }}</NDescriptionsItem>
            <NDescriptionsItem label="滑点">{{ formatMoney(detailReport.summary.total_slippage || 0) }}</NDescriptionsItem>
          </NDescriptions>

          <div class="drawer-actions">
            <NButton size="small" @click="jumpSingleBacktest(detailReport)">打开单品种复盘</NButton>
          </div>

          <div class="trade-list">
            <h3>交易明细</h3>
            <div v-if="detailReport.trades.length === 0" class="empty-block">暂无闭合交易</div>
            <div v-for="trade in detailReport.trades.slice(0, 20)" :key="trade.trade_no" class="trade-row">
              <div>
                <strong>{{ trade.trade_no }}</strong>
                <span>{{ trade.direction === 'long' ? '多' : '空' }} {{ trade.volume }} 手</span>
              </div>
              <div :class="trade.net_pnl >= 0 ? 'text-up' : 'text-down'">{{ formatMoney(trade.net_pnl) }}</div>
              <p>{{ formatDateTime(trade.open_time) }} → {{ formatDateTime(trade.close_time) }}</p>
              <p>开仓依据：{{ trade.entry_reason }}</p>
              <p>平仓依据：{{ trade.exit_reason }}</p>
            </div>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.batch-page {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-4);
  min-width: 0;
}

.panel {
  min-width: 0;
  padding: var(--gy-panel-padding);
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
}

.panel__header,
.progress-head,
.table-head,
.actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.actions {
  align-items: center;
}

.batch-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-title-row h2 {
  margin: 0;
}

.panel__header h2 {
  margin: 0;
  font-size: 18px;
}

.panel__header p,
.muted {
  margin: 4px 0 0;
  color: var(--gy-text-muted);
}

.panel__title {
  margin-bottom: 10px;
  color: var(--gy-text-primary);
  font-weight: 600;
}

.toolbar {
  display: grid;
  grid-template-columns: repeat(5, minmax(140px, 1fr));
  gap: 4px 12px;
}

.progress-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-head strong {
  display: block;
  margin-top: 4px;
  color: var(--gy-text-primary);
}

.progress-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 64px;
  padding: 10px;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.metric span {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.metric strong {
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-lg);
}

.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.label-filter {
  width: 140px;
}

.text-up {
  color: var(--gy-up);
}

.text-down {
  color: var(--gy-down);
}

.drawer-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
}

.trade-list h3 {
  margin: 0 0 10px;
}

.trade-row {
  padding: 10px 0;
  border-bottom: 1px solid var(--gy-border);
}

.trade-row div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.trade-row span,
.trade-row p,
.empty-block {
  color: var(--gy-text-muted);
}

.trade-row p {
  margin: 6px 0 0;
}

@media (max-width: 1200px) {
  .toolbar {
    grid-template-columns: repeat(3, minmax(140px, 1fr));
  }

  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
