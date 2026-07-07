<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NDataTable,
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
  NTabs,
  NTabPane,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  ackStrategySignal,
  getLatestStrategySignals,
  getSignalScanTask,
  getTaskStrategySignals,
  scanJmV1bSignals,
  scanStrategySignals,
  updateStrategySignalStatus,
} from '@/api/signal'
import { getWatchlistItems, getWatchlists } from '@/api/strategy'
import type { SignalLifecycleStatus, SignalScanTask, StrategySignalRecord } from '@/types/signal'
import type { WatchlistInfo, WatchlistItemInfo } from '@/types/strategy'
import { PERIODS } from '@/utils/constants'
import { WsClient } from '@/websocket/WsClient'
import { signalWsUrl } from '@/websocket'

const message = useMessage()
const router = useRouter()
const JM_V1B_WATCHLIST = 'jm_v1b'
const loadingMeta = ref(false)
const loadingSignals = ref(false)
const scanning = ref(false)
const error = ref<string | null>(null)
const watchlists = ref<WatchlistInfo[]>([])
const watchlistItems = ref<WatchlistItemInfo[]>([])
const signals = ref<StrategySignalRecord[]>([])
const currentTask = ref<SignalScanTask | null>(null)
const selectedSignal = ref<StrategySignalRecord | null>(null)
const detailVisible = ref(false)

const selectedWatchlist = ref('black')
const selectedSymbols = ref<string[]>([])
const selectedPeriods = ref(['5m'])
const selectedBucket = ref('all')
const accountEquity = ref(100000)
const riskPerTradePct = ref(1)
const maxMarginUsagePct = ref(35)
const minScoreBucket = ref(51)
const allowWarningQuality = ref(false)

let ws: WsClient | null = null
let pollTimer: number | null = null

const watchlistOptions = computed(() => {
  const options = watchlists.value.map((item) => ({ label: `${item.name} (${item.item_count})`, value: item.code }))
  return options.some((item) => item.value === JM_V1B_WATCHLIST)
    ? options
    : [{ label: 'JM V1-B 焦煤样板', value: JM_V1B_WATCHLIST }, ...options]
})
const symbolOptions = computed(() => watchlistItems.value.map((item) => ({ label: `${item.name || item.symbol} (${item.symbol})`, value: item.symbol })))
const periodOptions = PERIODS.map((item) => ({ label: item.label, value: item.value }))
const bucketOptions = [
  { label: '全部', value: 'all' },
  { label: '51 观察', value: '51' },
  { label: '60 有效', value: '60' },
  { label: '70 强信号', value: '70' },
  { label: '80 重点关注', value: '80' },
]

const filteredSignals = computed(() => {
  const bucket = selectedBucket.value === 'all' ? null : Number(selectedBucket.value)
  return signals.value
    .filter((item) => bucket === null || item.score_bucket === bucket)
    .sort((first, second) => second.score_bucket - first.score_bucket || new Date(second.signal_time).getTime() - new Date(first.signal_time).getTime())
})

const bucketCounts = computed(() => {
  const counts: Record<string, number> = { all: signals.value.length, 51: 0, 60: 0, 70: 0, 80: 0 }
  signals.value.forEach((item) => {
    counts[String(item.score_bucket)] = (counts[String(item.score_bucket)] || 0) + 1
  })
  return counts
})

const progressStatus = computed(() => {
  if (!currentTask.value) return 'default'
  if (currentTask.value.status === 'failed') return 'error'
  if (currentTask.value.status === 'completed') return 'success'
  if (currentTask.value.status === 'partial_failed') return 'warning'
  return 'info'
})

const signalColumns: DataTableColumns<StrategySignalRecord> = [
  {
    title: '品种',
    key: 'symbol',
    width: 92,
    render: (row) => h('strong', row.symbol),
  },
  { title: '合约', key: 'contract', width: 110 },
  { title: '周期', key: 'interval', width: 70, render: (row) => row.interval || row.period },
  { title: '日线方向', key: 'daily_direction', width: 96, render: (row) => row.daily_direction || '-' },
  {
    title: '方向',
    key: 'direction',
    width: 74,
    render: (row) => h(NTag, { size: 'small', type: directionType(row.direction) }, { default: () => directionText(row.direction) }),
  },
  { title: '策略阶段', key: 'strategy_status', width: 112, render: (row) => row.strategy_status || '-' },
  {
    title: '状态',
    key: 'status',
    width: 92,
    render: (row) => h(NTag, { size: 'small', type: signalStatusType(row.status) }, { default: () => signalStatusText(row.status) }),
  },
  {
    title: '分层',
    key: 'score_bucket',
    width: 108,
    render: (row) => h(NTag, { size: 'small', type: bucketType(row.score_bucket) }, { default: () => `${row.score_bucket || '-'} ${row.bucket_label}` }),
  },
  { title: '强度', key: 'strength_score', width: 76, render: (row) => row.strength_score ?? row.score_bucket },
  { title: '价格', key: 'price', render: (row) => formatNumber(row.signal_price ?? row.price ?? row.current_price) },
  { title: '目标价', key: 'target_price', render: (row) => nullableNumber(row.target_price) },
  { title: '止损价', key: 'stop_loss_price', render: (row) => nullableNumber(row.stop_loss_price) },
  {
    title: '操作',
    key: 'actions',
    width: 176,
    render: (row) =>
      h('div', { class: 'action-cell' }, [
        h(NButton, { size: 'small', onClick: () => openSignal(row) }, { default: () => '详情' }),
        h(NButton, { size: 'small', disabled: row.status === 'viewed', onClick: () => ackSignal(row) }, { default: () => '已看' }),
        h(NButton, { size: 'small', disabled: row.status === 'watching', onClick: () => setSignalStatus(row, 'watching') }, { default: () => '关注' }),
        h(NButton, { size: 'small', disabled: row.status === 'ignored', onClick: () => setSignalStatus(row, 'ignored') }, { default: () => '忽略' }),
      ]),
  },
]

onMounted(async () => {
  await loadMeta()
  await refreshSignals()
  connectSignals()
})

onUnmounted(() => {
  ws?.disconnect()
  if (pollTimer !== null) window.clearInterval(pollTimer)
})

async function loadMeta() {
  loadingMeta.value = true
  error.value = null
  try {
    watchlists.value = await getWatchlists()
    await loadWatchlistItems()
  } catch (err) {
    error.value = apiError(err, '加载信号元数据失败')
  } finally {
    loadingMeta.value = false
  }
}

async function loadWatchlistItems() {
  if (selectedWatchlist.value === JM_V1B_WATCHLIST) {
    watchlistItems.value = [{ symbol: 'jm', name: '焦煤', exchange_code: 'DCE', default_contract: 'jm.MAIN', available_periods: ['15m', '5m'] }]
    selectedSymbols.value = ['jm']
    selectedPeriods.value = ['15m', '5m']
    return
  }
  watchlistItems.value = await getWatchlistItems(selectedWatchlist.value)
  selectedSymbols.value = watchlistItems.value.filter((item) => item.available_periods.some((period) => selectedPeriods.value.includes(period))).map((item) => item.symbol)
}

async function startScan() {
  scanning.value = true
  error.value = null
  try {
    const task = await scanStrategySignals({
      watchlist_code: selectedWatchlist.value,
      periods: selectedPeriods.value,
      symbols: selectedSymbols.value.length ? selectedSymbols.value : undefined,
      data_role: 'primary',
      research_only: false,
      account_equity: accountEquity.value,
      risk_per_trade_pct: riskPerTradePct.value / 100,
      max_margin_usage_pct: maxMarginUsagePct.value / 100,
      min_score_bucket: minScoreBucket.value,
      allow_warning_quality: allowWarningQuality.value,
    })
    currentTask.value = task
    watchTask(task.task_no)
  } catch (err) {
    error.value = apiError(err, '启动信号扫描失败')
    scanning.value = false
  }
}

async function startJmV1bScan() {
  scanning.value = true
  error.value = null
  selectedWatchlist.value = JM_V1B_WATCHLIST
  await loadWatchlistItems()
  try {
    const task = await scanJmV1bSignals(true)
    currentTask.value = task
    await refreshTaskSignals(task.task_no)
    await refreshSignals()
  } catch (err) {
    error.value = apiError(err, '启动 JM V1-B 信号扫描失败')
  } finally {
    scanning.value = false
  }
}

function watchTask(taskNo: string) {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    const task = await getSignalScanTask(taskNo)
    currentTask.value = task
    await refreshTaskSignals(taskNo)
    if (['completed', 'partial_failed', 'failed'].includes(task.status)) {
      scanning.value = false
      if (pollTimer !== null) window.clearInterval(pollTimer)
      pollTimer = null
      await refreshSignals()
    }
  }, 2000)
}

function connectSignals() {
  ws = new WsClient(signalWsUrl())
  const refresh = (data: unknown) => {
    if (Array.isArray(data)) {
      signals.value = data as StrategySignalRecord[]
      return
    }
    const record = data as StrategySignalRecord
    if (record && typeof record.id === 'number') {
      const index = signals.value.findIndex((item) => item.id === record.id)
      if (index >= 0) signals.value[index] = record
      else signals.value.unshift(record)
      message.info(`${record.symbol} ${record.interval || record.period} ${record.bucket_label}: ${signalStatusText(record.status)}`)
    }
  }
  ws.on('snapshot', refresh)
  ws.on('signal_created', refresh)
  ws.on('signal_changed', refresh)
  ws.connect()
}

async function refreshSignals() {
  loadingSignals.value = true
  try {
    signals.value = await getLatestStrategySignals({ watchlist_code: selectedWatchlist.value, limit: 200 })
  } finally {
    loadingSignals.value = false
  }
}

async function refreshTaskSignals(taskNo: string) {
  signals.value = await getTaskStrategySignals(taskNo)
}

function openSignal(row: StrategySignalRecord) {
  selectedSignal.value = row
  detailVisible.value = true
}

function openSignalKline(row: StrategySignalRecord) {
  detailVisible.value = false
  void router.push({
    name: 'market-chart',
    query: {
      symbol: row.symbol,
      contract: row.contract,
      period: row.interval || row.period,
      time: row.signal_time,
      strategy: `${row.strategy_id || row.strategy_name} ${row.strategy_version_id || row.strategy_version}`,
    },
  })
}

async function ackSignal(row: StrategySignalRecord) {
  const updated = await ackStrategySignal(row.id)
  const index = signals.value.findIndex((item) => item.id === row.id)
  if (index >= 0) signals.value[index] = updated
  selectedSignal.value = selectedSignal.value?.id === row.id ? updated : selectedSignal.value
}

async function setSignalStatus(row: StrategySignalRecord, status: SignalLifecycleStatus) {
  const updated = await updateStrategySignalStatus(row.id, status)
  const index = signals.value.findIndex((item) => item.id === row.id)
  if (index >= 0) signals.value[index] = updated
  selectedSignal.value = selectedSignal.value?.id === row.id ? updated : selectedSignal.value
}

function directionText(direction: string) {
  if (direction === 'long') return '多'
  if (direction === 'short') return '空'
  return '中性'
}

function directionType(direction: string) {
  if (direction === 'long') return 'error'
  if (direction === 'short') return 'success'
  return 'default'
}

function bucketType(bucket: number) {
  if (bucket >= 80) return 'error'
  if (bucket >= 70) return 'warning'
  if (bucket >= 60) return 'info'
  if (bucket >= 51) return 'default'
  return 'default'
}

function statusText(status: string) {
  const labels: Record<string, string> = {
    pending: '等待',
    running: '扫描中',
    completed: '完成',
    partial_failed: '部分失败',
    failed: '失败',
  }
  return labels[status] || status
}

function signalStatusText(status: string) {
  const labels: Record<string, string> = {
    new: '新信号',
    viewed: '已看',
    ignored: '忽略',
    watching: '观察中',
    expired: '过期',
  }
  return labels[status] || status
}

function signalStatusType(status: string) {
  if (status === 'watching') return 'warning'
  if (status === 'viewed') return 'success'
  if (status === 'ignored' || status === 'expired') return 'default'
  return 'info'
}

function formatDateTime(value: string) {
  return value.replace('T', ' ').slice(0, 16)
}

function formatNumber(value: number, digits = 2) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function nullableNumber(value: number | null | undefined) {
  return value == null ? '-' : formatNumber(value)
}

function formatMoney(value: number) {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
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
  <div class="signal-page">
    <section class="panel toolbar-panel">
      <div class="panel__header">
        <div>
          <h2>信号扫描</h2>
          <p>苏冰 EMA21 多品种多周期研究提醒，不自动下单</p>
        </div>
        <div class="actions">
          <NButton :loading="loadingSignals" @click="refreshSignals">刷新</NButton>
          <NButton :loading="scanning" @click="startJmV1bScan">扫描 JM V1-B</NButton>
          <NButton type="primary" :loading="scanning" @click="startScan">开始扫描</NButton>
        </div>
      </div>

      <NAlert type="warning" :bordered="false" class="observe-alert">信号仅供观察，不自动下单。</NAlert>

      <NForm class="toolbar" label-placement="top">
        <NFormItem label="品种池">
          <NSelect v-model:value="selectedWatchlist" :options="watchlistOptions" :loading="loadingMeta" @update:value="loadWatchlistItems" />
        </NFormItem>
        <NFormItem label="品种">
          <NSelect v-model:value="selectedSymbols" multiple filterable :options="symbolOptions" :max-tag-count="2" />
        </NFormItem>
        <NFormItem label="周期">
          <NSelect v-model:value="selectedPeriods" multiple :options="periodOptions" />
        </NFormItem>
        <NFormItem label="最小分层">
          <NSelect v-model:value="minScoreBucket" :options="bucketOptions.filter((item) => item.value !== 'all')" />
        </NFormItem>
        <NFormItem label="账户权益">
          <NInputNumber v-model:value="accountEquity" :min="10000" :step="10000" />
        </NFormItem>
        <NFormItem label="单笔风险%">
          <NInputNumber v-model:value="riskPerTradePct" :min="0.1" :max="10" :step="0.1" />
        </NFormItem>
        <NFormItem label="保证金上限%">
          <NInputNumber v-model:value="maxMarginUsagePct" :min="1" :max="100" :step="1" />
        </NFormItem>
        <NFormItem label="允许警告数据">
          <NSwitch v-model:value="allowWarningQuality" />
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
      <NProgress :percentage="currentTask?.progress || 0" :status="progressStatus" :height="10" :border-radius="4" />
      <div class="progress-stats">
        <span>总数 {{ currentTask?.total_items || 0 }}</span>
        <span>完成 {{ currentTask?.completed_items || 0 }}</span>
        <span>跳过 {{ currentTask?.skipped_items || 0 }}</span>
        <span>失败 {{ currentTask?.failed_items || 0 }}</span>
      </div>
    </section>

    <section class="metrics">
      <div class="metric">
        <span>全部信号</span>
        <strong>{{ bucketCounts.all }}</strong>
      </div>
      <div class="metric">
        <span>51 观察</span>
        <strong>{{ bucketCounts[51] }}</strong>
      </div>
      <div class="metric">
        <span>60 有效</span>
        <strong>{{ bucketCounts[60] }}</strong>
      </div>
      <div class="metric">
        <span>70 强信号</span>
        <strong>{{ bucketCounts[70] }}</strong>
      </div>
      <div class="metric">
        <span>80 重点</span>
        <strong class="text-up">{{ bucketCounts[80] }}</strong>
      </div>
    </section>

    <section class="panel">
      <NTabs v-model:value="selectedBucket" type="line" animated>
        <NTabPane v-for="option in bucketOptions" :key="option.value" :name="option.value" :tab="`${option.label} (${bucketCounts[option.value] || 0})`" />
      </NTabs>
      <NDataTable
        :columns="signalColumns"
        :data="filteredSignals"
        :loading="loadingSignals"
        :bordered="false"
        :single-line="false"
        size="small"
        :pagination="{ pageSize: 12 }"
      />
    </section>

    <NDrawer v-model:show="detailVisible" width="620">
      <NDrawerContent title="信号详情">
        <div v-if="selectedSignal" class="drawer-content">
          <div class="drawer-actions">
            <NButton type="primary" size="small" @click="openSignalKline(selectedSignal)">打开K线</NButton>
          </div>
          <NDescriptions :column="2" bordered size="small">
            <NDescriptionsItem label="品种">{{ selectedSignal.symbol }}</NDescriptionsItem>
            <NDescriptionsItem label="合约">{{ selectedSignal.contract }}</NDescriptionsItem>
            <NDescriptionsItem label="周期">{{ selectedSignal.interval || selectedSignal.period }}</NDescriptionsItem>
            <NDescriptionsItem label="入场周期">{{ selectedSignal.entry_interval || selectedSignal.interval || selectedSignal.period }}</NDescriptionsItem>
            <NDescriptionsItem label="时间">{{ formatDateTime(selectedSignal.signal_time) }}</NDescriptionsItem>
            <NDescriptionsItem label="信号状态">{{ signalStatusText(selectedSignal.status) }}</NDescriptionsItem>
            <NDescriptionsItem label="策略阶段">{{ selectedSignal.strategy_status }}</NDescriptionsItem>
            <NDescriptionsItem label="策略">{{ selectedSignal.strategy_code || selectedSignal.strategy_id }}</NDescriptionsItem>
            <NDescriptionsItem label="日线方向">{{ selectedSignal.daily_direction || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="方向">{{ directionText(selectedSignal.direction) }}</NDescriptionsItem>
            <NDescriptionsItem label="信号类型">{{ selectedSignal.signal_type }}</NDescriptionsItem>
            <NDescriptionsItem label="分层">{{ selectedSignal.score_bucket }} {{ selectedSignal.bucket_label }}</NDescriptionsItem>
            <NDescriptionsItem label="强度">{{ selectedSignal.strength_score }}</NDescriptionsItem>
            <NDescriptionsItem label="价格">{{ formatNumber(selectedSignal.signal_price ?? selectedSignal.price ?? selectedSignal.current_price) }}</NDescriptionsItem>
            <NDescriptionsItem label="目标价">{{ nullableNumber(selectedSignal.target_price) }}</NDescriptionsItem>
            <NDescriptionsItem label="止损价">{{ nullableNumber(selectedSignal.stop_loss_price) }}</NDescriptionsItem>
            <NDescriptionsItem label="可开手数">{{ selectedSignal.open_volume }}</NDescriptionsItem>
            <NDescriptionsItem label="保证金">{{ formatMoney(selectedSignal.margin_required) }}</NDescriptionsItem>
            <NDescriptionsItem label="风险金额">{{ formatMoney(selectedSignal.risk_amount) }}</NDescriptionsItem>
            <NDescriptionsItem label="盈亏比">{{ nullableNumber(selectedSignal.risk_reward_ratio) }}</NDescriptionsItem>
            <NDescriptionsItem label="数据角色">{{ selectedSignal.data_role }}</NDescriptionsItem>
            <NDescriptionsItem label="合约规格">{{ selectedSignal.spec_source || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="研究合约">{{ selectedSignal.research_contract ? '是' : '否' }}</NDescriptionsItem>
            <NDescriptionsItem label="最长持有">{{ selectedSignal.max_hold_bars ?? '-' }} K</NDescriptionsItem>
          </NDescriptions>

          <div class="reason-block">
            <h3>信号理由</h3>
            <p v-if="selectedSignal.entry_reason">入场：{{ selectedSignal.entry_reason }}</p>
            <p v-if="selectedSignal.no_signal_reason">无信号：{{ selectedSignal.no_signal_reason }}</p>
            <p v-if="selectedSignal.reason">{{ selectedSignal.reason }}</p>
            <p v-for="reason in selectedSignal.reasons" :key="reason">{{ reason }}</p>
          </div>

          <div class="reason-block">
            <h3>特征值</h3>
            <pre>{{ JSON.stringify(selectedSignal.features, null, 2) }}</pre>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.signal-page {
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

.panel__header,
.progress-head,
.actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.actions {
  align-items: center;
}

.panel__header h2 {
  margin: 0;
  font-size: 18px;
}

.panel__header p,
.muted {
  margin: 4px 0 0;
  color: #94a3b8;
}

.toolbar {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 4px 12px;
}

.observe-alert {
  margin-bottom: 12px;
}

.progress-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-head strong {
  display: block;
  margin-top: 4px;
  color: #e2e8f0;
}

.progress-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  color: #94a3b8;
  font-size: 12px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(110px, 1fr));
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

.text-up {
  color: #ef4444;
}

.action-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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

.reason-block {
  padding: 10px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.reason-block h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

.reason-block p {
  margin: 4px 0;
  color: #cbd5e1;
}

.reason-block pre {
  margin: 0;
  white-space: pre-wrap;
  color: #94a3b8;
}

@media (max-width: 1100px) {
  .toolbar {
    grid-template-columns: repeat(2, minmax(150px, 1fr));
  }

  .metrics {
    grid-template-columns: repeat(2, minmax(110px, 1fr));
  }
}
</style>
