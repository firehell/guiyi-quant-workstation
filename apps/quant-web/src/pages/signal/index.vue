<script setup lang="ts">
/** 信号监控：多品种扫描、WebSocket 实时推送、分层筛选与 K 线 deep-link。 */
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NDropdown,
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
  getStage9WechatPreview,
  getTaskStrategySignals,
  listSignalEvents,
  scanJmV1bSignals,
  scanStrategySignals,
  updateStrategySignalStatus,
} from '@/api/signal'
import { getWatchlistItems, getWatchlists } from '@/api/strategy'
import type { SignalLifecycleStatus, SignalScanTask, SignalEventRecord, StrategySignalRecord } from '@/types/signal'
import type { WatchlistInfo, WatchlistItemInfo } from '@/types/strategy'
import SignalEventsPanel from '@/components/signal/SignalEventsPanel.vue'
import LiveTargetPanel from '@/components/market/LiveTargetPanel.vue'
import DirectionTag from '@/components/common/DirectionTag.vue'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageShell from '@/components/common/PageShell.vue'
import { PERIODS } from '@/utils/constants'
import { toSafeApiError } from '@/utils/errorRedaction'
import { resolveSignalSourceMode, sourceModeBadge } from '@/utils/signalSourceMode'
import { currentReturnRoute } from '@/utils/researchNavigation'
import { WsClient } from '@/websocket/WsClient'
import { signalWsUrl } from '@/websocket'

const message = useMessage()
const router = useRouter()
const route = useRoute()
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
const scanPanelExpanded = ref<Array<string | number>>([])
const notificationEvents = ref<SignalEventRecord[]>([])
const loadingNotifications = ref(false)

const selectedWatchlist = ref('black')
const selectedSymbols = ref<string[]>([])
const selectedPeriods = ref(['5m'])
const selectedBucket = ref('all')
const accountEquity = ref(100000)
const riskPerTradePct = ref(1)
const maxMarginUsagePct = ref(35)
const minScoreBucket = ref(51)
const allowWarningQuality = ref(false)
const selectedMainTab = ref(route.query.tab === 'events' || route.query.tab === 'notification' ? String(route.query.tab) : 'latest')

let ws: WsClient | null = null
/** 扫描任务轮询（2s），终态后刷新信号列表 */
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
    fixed: 'left',
    render: (row) => h('strong', row.symbol),
  },
  { title: '合约', key: 'contract', width: 110 },
  { title: '周期', key: 'interval', width: 70, render: (row) => row.interval || row.period },
  {
    title: '来源',
    key: 'source_mode',
    width: 130,
    render: (row) => {
      const mode = resolveSignalSourceMode(row)
      const badge = sourceModeBadge(mode)
      return h(CapabilityBadge, { kind: badge.kind, label: badge.label, title: badge.title })
    },
  },
  { title: '日线方向', key: 'daily_direction', width: 96, render: (row) => row.daily_direction || '-' },
  {
    title: '方向',
    key: 'direction',
    width: 74,
    render: (row) => h(DirectionTag, { direction: row.direction, label: directionText(row.direction) }),
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
    width: 130,
    fixed: 'right',
    render: (row) =>
      h('div', { class: 'action-cell' }, [
        h(NButton, { size: 'small', type: 'primary', ghost: true, onClick: () => openSignal(row) }, { default: () => '详情' }),
        h(
          NDropdown,
          {
            trigger: 'click',
            options: signalActionOptions(row),
            onSelect: (key: string) => handleSignalAction(row, key),
          },
          { default: () => h(NButton, { size: 'small' }, { default: () => '更多' }) },
        ),
      ]),
  },
]

function signalActionOptions(row: StrategySignalRecord) {
  return [
    { label: '标记已看', key: 'viewed', disabled: row.status === 'viewed' },
    { label: '加入关注', key: 'watching', disabled: row.status === 'watching' },
    { label: '忽略信号', key: 'ignored', disabled: row.status === 'ignored' },
  ]
}

function handleSignalAction(row: StrategySignalRecord, key: string) {
  if (key === 'viewed') {
    void ackSignal(row)
    return
  }
  void setSignalStatus(row, key as SignalLifecycleStatus)
}

onMounted(async () => {
  await loadMeta()
  await refreshSignals()
  connectSignals()
})

watch(selectedMainTab, (tab) => {
  if (tab === 'notification') void loadNotificationEvents()
  void router.replace({ query: { ...route.query, tab: tab === 'latest' ? undefined : tab } })
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
    error.value = toSafeApiError(err, '加载信号元数据失败')
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

/** 启动通用品种池信号扫描，创建任务后进入 watchTask。 */
async function startScan() {
  scanning.value = true
  error.value = null
  try {
    const task = await scanStrategySignals({
      profile_id: 'intraday_research_v1',
      watchlist_code: selectedWatchlist.value,
      periods: selectedPeriods.value,
      symbols: selectedSymbols.value.length ? selectedSymbols.value : undefined,
      account_equity: accountEquity.value,
      risk_per_trade_pct: riskPerTradePct.value / 100,
      max_margin_usage_pct: maxMarginUsagePct.value / 100,
      min_score_bucket: minScoreBucket.value,
    })
    currentTask.value = task
    watchTask(task.task_no)
  } catch (err) {
    error.value = toSafeApiError(err, '启动信号扫描失败')
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
    error.value = toSafeApiError(err, '启动历史研究扫描失败')
  } finally {
    scanning.value = false
  }
}

/** 轮询扫描任务进度；完成/失败后停止并刷新最新信号。 */
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

/** 连接信号 WebSocket：snapshot 全量替换，created/changed 增量更新。 */
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
  void router.replace({ query: { ...route.query, signal_id: String(row.id) } })
}

/** 跳转行情 K 线并定位 signal_time（deep-link）。 */
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
      signal_id: String(row.id),
      data_mode: row.source_mode === 'live_confirmed' ? 'live' : 'historical',
      return_route: currentReturnRoute(route.path, route.query as Record<string, string | string[] | null | undefined>),
    },
    state: { researchScrollY: window.scrollY },
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

async function loadNotificationEvents() {
  loadingNotifications.value = true
  try {
    notificationEvents.value = await listSignalEvents({ limit: 50 })
  } catch (err) {
    error.value = toSafeApiError(err, '加载通知事件失败')
  } finally {
    loadingNotifications.value = false
  }
}

async function previewNotification(eventId: number) {
  try {
    const preview = await getStage9WechatPreview(eventId)
    message.info(
      preview.allowed
        ? `Preview only · would_send=${preview.would_send}`
        : `Gate 阻断：${preview.blocked_reasons.join(' · ') || 'unknown'}`,
    )
  } catch (err) {
    message.error(toSafeApiError(err, '加载通知 Preview 失败'))
  }
}

function signalSourceModeLabel(row: StrategySignalRecord) {
  return sourceModeBadge(resolveSignalSourceMode(row)).label
}

const notificationColumns: DataTableColumns<SignalEventRecord> = [
  { title: '时间', key: 'created_at', width: 170, render: (row) => row.created_at || '-' },
  {
    title: 'source_mode',
    key: 'source_mode',
    width: 150,
    render: (row) => {
      const badge = sourceModeBadge(row.source_mode)
      return h(CapabilityBadge, { kind: badge.kind, label: badge.label, title: badge.title })
    },
  },
  { title: '事件', key: 'event_type', width: 120 },
  { title: '品种', key: 'product', width: 80, render: (row) => row.product || row.symbol },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    render: (row) =>
      h(NButton, { size: 'small', onClick: () => previewNotification(row.id) }, { default: () => 'Preview' }),
  },
]
</script>

<template>
  <PageShell title="信号监控" subtitle="Latest / 事件流 / 通知 Preview；历史扫描与 Live 强分 source_mode" :error="error">
    <template #badges>
      <CapabilityBadge kind="research-only" label="非自动下单" />
    </template>

    <LiveTargetPanel compact class="signal-live-target" />

    <NTabs v-model:value="selectedMainTab" type="line">
      <NTabPane name="latest" tab="Latest 信号">
        <section class="panel toolbar-panel">
          <div class="panel__header">
            <div>
              <h2>最新信号</h2>
              <p>苏冰 EMA21 多品种多周期研究提醒；source_mode 标签区分历史扫描 / replay / live</p>
            </div>
            <div class="actions">
              <NButton :loading="loadingSignals" @click="refreshSignals">刷新</NButton>
              <NButton :loading="scanning" @click="startJmV1bScan">历史研究扫描（JM）</NButton>
              <NButton type="primary" :loading="scanning" @click="startScan">开始历史扫描</NButton>
            </div>
          </div>

          <NAlert type="warning" :bordered="false" class="observe-alert">
            信号仅供观察，不构成交易指令；无真实发送按钮，系统不自动下单。
          </NAlert>

          <NCollapse v-model:expanded-names="scanPanelExpanded" arrow-placement="right" class="scan-config-collapse">
            <NCollapseItem name="config" title="扫描参数（次级）">
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
            </NCollapseItem>
          </NCollapse>
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

    <section class="metrics" aria-label="信号分层统计">
      <MetricCard label="全部信号" :value="bucketCounts.all" />
      <MetricCard label="51 观察" :value="bucketCounts[51]" />
      <MetricCard label="60 有效" :value="bucketCounts[60]" tone="info" />
      <MetricCard label="70 强信号" :value="bucketCounts[70]" tone="warning" />
      <MetricCard label="80 重点" :value="bucketCounts[80]" tone="up" />
    </section>

    <section class="panel">
      <NTabs v-model:value="selectedBucket" type="line" default-value="all">
        <NTabPane v-for="option in bucketOptions" :key="option.value" :name="option.value" display-directive="show">
          <template #tab>{{ option.label }} ({{ bucketCounts[option.value] || 0 }})</template>
        </NTabPane>
      </NTabs>
      <NDataTable
        :columns="signalColumns"
        :data="filteredSignals"
        :loading="loadingSignals"
        :bordered="false"
        :single-line="false"
        :scroll-x="1460"
        size="small"
        :pagination="{ pageSize: 12 }"
      />
    </section>

      </NTabPane>
      <NTabPane name="events" tab="Event timeline">
        <SignalEventsPanel />
      </NTabPane>
      <NTabPane name="notification" tab="Notification Preview">
        <section class="panel">
          <div class="panel__header">
            <div>
              <h2>通知 Preview</h2>
              <p>只读 Stage9 wechat preview；would_send=false，禁止真实发送</p>
            </div>
            <NButton size="small" :loading="loadingNotifications" @click="loadNotificationEvents">刷新</NButton>
          </div>
          <NAlert type="warning" :bordered="false">企业微信仅 Preview；本页不提供发送按钮。</NAlert>
          <NDataTable
            size="small"
            :bordered="false"
            :loading="loadingNotifications"
            :columns="notificationColumns"
            :data="notificationEvents"
            :pagination="{ pageSize: 10 }"
          />
        </section>
      </NTabPane>
    </NTabs>

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
            <NDescriptionsItem label="来源模式">{{ signalSourceModeLabel(selectedSignal) }}</NDescriptionsItem>
            <NDescriptionsItem label="策略阶段">{{ selectedSignal.strategy_status }}</NDescriptionsItem>
            <NDescriptionsItem label="策略">{{ selectedSignal.strategy_code || selectedSignal.strategy_id }}</NDescriptionsItem>
            <NDescriptionsItem label="日线方向">{{ selectedSignal.daily_direction || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="方向"><DirectionTag :direction="selectedSignal.direction" /></NDescriptionsItem>
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
  </PageShell>
</template>

<style scoped>
.signal-live-target {
  margin-bottom: var(--gy-space-4);
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
.actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gy-space-3);
}

.actions {
  align-items: center;
}

.panel__header h2 {
  margin: 0;
  font-size: var(--gy-font-size-lg);
}

.panel__header p,
.muted {
  margin: 4px 0 0;
  color: var(--gy-text-muted);
}

.toolbar {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: var(--gy-space-1) var(--gy-space-3);
}

.observe-alert {
  margin: var(--gy-space-3) 0 var(--gy-space-2);
}

.scan-config-collapse {
  padding: 0 var(--gy-space-1);
}

.progress-panel {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
}

.progress-head strong {
  display: block;
  margin-top: 4px;
  color: var(--gy-text-primary);
}

.progress-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gy-space-4);
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(110px, 1fr));
  gap: var(--gy-space-3);
}

.action-cell {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gy-space-1);
  flex-wrap: nowrap;
}

.drawer-content {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-4);
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
}

.reason-block {
  padding: var(--gy-space-3);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.reason-block h3 {
  margin: 0 0 8px;
  font-size: var(--gy-font-size-md);
}

.reason-block p {
  margin: 4px 0;
  color: var(--gy-text-secondary);
}

.reason-block pre {
  margin: 0;
  white-space: pre-wrap;
  color: var(--gy-text-muted);
}

@media (max-width: 1199px) {
  .panel__header {
    flex-direction: column;
  }

  .actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .toolbar {
    grid-template-columns: repeat(2, minmax(150px, 1fr));
  }

  .metrics {
    grid-template-columns: repeat(2, minmax(110px, 1fr));
  }
}
</style>
