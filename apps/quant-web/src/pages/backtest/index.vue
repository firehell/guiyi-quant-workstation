<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  getBacktestTask,
  listBacktestReports,
  listBacktestTasks,
} from '@/api/backtestApi'
import type { BacktestReport, BacktestTask, BacktestTaskCreateRequest, BacktestTaskForm } from '@/types/backtest'

const DISCLAIMER = '回测结果不等于实盘结果，实盘前必须模拟和小资金验证。'
const DEFAULT_STRATEGY_CLASS =
  'guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy'

const message = useMessage()
const router = useRouter()
const route = useRoute()

const submitting = ref(false)
const loadingTasks = ref(false)
const loadingReports = ref(false)
const loadingReportDetail = ref(false)
const error = ref<string | null>(null)
const tasks = ref<BacktestTask[]>([])
const reports = ref<BacktestReport[]>([])
const selectedReport = ref<BacktestReport | null>(null)

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
    render: (row) => formatPct(Number(row.summary?.total_return || 0)),
  },
  {
    title: '最大回撤',
    key: 'max_drawdown',
    width: 112,
    render: (row) => formatPct(Number(row.summary?.max_drawdown || 0)),
  },
  {
    title: '详情',
    key: 'actions',
    width: 118,
    render: (row) => h(NButton, { size: 'small', onClick: () => openReport(row.id) }, { default: () => '查看报告' }),
  },
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
  try {
    selectedReport.value = await getBacktestReport(reportId)
  } catch (err) {
    message.error(apiError(err, '加载报告详情失败'))
  } finally {
    loadingReportDetail.value = false
  }
}

function statusType(status: string) {
  if (['success', 'completed'].includes(status)) return 'success'
  if (['failed', 'cancelled'].includes(status)) return 'error'
  if (['running', 'queued'].includes(status)) return 'warning'
  return 'default'
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function formatPct(value: number) {
  return `${(value * 100).toFixed(2)}%`
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

    <section v-if="selectedReport" class="panel">
      <div class="panel__header compact">
        <div>
          <div class="panel__title">报告详情 #{{ selectedReport.id }}</div>
          <p>{{ selectedReport.report_no }} · {{ selectedReport.contract }} · {{ selectedReport.period }}</p>
        </div>
        <NTag size="small" :type="statusType(selectedReport.status)">{{ selectedReport.status }}</NTag>
      </div>
      <NAlert type="warning" :bordered="false">{{ selectedReport.disclaimer || DISCLAIMER }}</NAlert>
      <div class="report-metrics" :class="{ loading: loadingReportDetail }">
        <div>
          <span>总收益</span>
          <strong>{{ formatPct(Number(selectedReport.summary?.total_return || 0)) }}</strong>
        </div>
        <div>
          <span>最大回撤</span>
          <strong>{{ formatPct(Number(selectedReport.summary?.max_drawdown || 0)) }}</strong>
        </div>
        <div>
          <span>胜率</span>
          <strong>{{ formatPct(Number(selectedReport.summary?.win_rate || 0)) }}</strong>
        </div>
        <div>
          <span>交易数</span>
          <strong>{{ selectedReport.summary?.trade_count || selectedReport.summary?.total_trades || 0 }}</strong>
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

.panel__title {
  color: #e2e8f0;
  font-weight: 600;
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

.report-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.report-metrics > div {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 64px;
  padding: 10px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.report-metrics span {
  color: #94a3b8;
  font-size: 12px;
}

.report-metrics strong {
  color: #e2e8f0;
  font-size: 18px;
}

@media (max-width: 1180px) {
  .task-form {
    grid-template-columns: repeat(2, minmax(160px, 1fr));
  }

  .task-form :deep(.n-form-item:last-child) {
    grid-column: span 2;
  }

  .report-metrics {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}

@media (max-width: 720px) {
  .panel__header {
    flex-direction: column;
  }

  .task-form,
  .report-metrics {
    grid-template-columns: 1fr;
  }

  .task-form :deep(.n-form-item:last-child) {
    grid-column: span 1;
  }
}
</style>
