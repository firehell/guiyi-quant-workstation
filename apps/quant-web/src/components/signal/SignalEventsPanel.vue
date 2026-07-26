<script setup lang="ts">
/** 信号事件列表：Stage9 企业微信 Preview（would_send=false）与 Live Evaluator 只读预览。 */
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import { getStage9WechatPreview, listSignalEvents, previewLiveEvaluator } from '@/api/signal'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import type { LiveSignalEvaluationResponse, SignalEventRecord, Stage9WechatPreview } from '@/types/signal'
import { toSafeApiError } from '@/utils/errorRedaction'
import {
  HTDY_REALTIME_RISK_COPY,
  isLiveObservationSourceMode,
  resolveEventSourceMode,
  sourceModeBadge,
} from '@/utils/signalSourceMode'
import { buildSignalEventReviewQuery, currentReturnRoute } from '@/utils/researchNavigation'

const message = useMessage()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const loadingPreview = ref(false)
const loadingEvaluator = ref(false)
const error = ref<string | null>(null)
const events = ref<SignalEventRecord[]>([])
const eventTotal = ref(0)
const eventPage = ref(1)
const eventPageSize = 10
const expandedEventId = ref<number | null>(null)
const previewByEventId = ref<Record<number, Stage9WechatPreview>>({})
const evaluatorVisible = ref(false)
const evaluatorResult = ref<LiveSignalEvaluationResponse | null>(null)
let eventListController: AbortController | null = null
const eventPagination = computed(() => ({
  page: eventPage.value,
  pageSize: eventPageSize,
  itemCount: eventTotal.value,
  onChange: (page: number) => {
    eventPage.value = page
    void loadEvents()
  },
}))

const columns: DataTableColumns<SignalEventRecord> = [
  { title: '时间', key: 'created_at', width: 170, render: (row) => row.created_at || row.signal_time || '-' },
  {
    title: 'source_mode',
    key: 'source_mode',
    width: 150,
    render: (row) => {
      const badge = sourceModeBadge(resolveEventSourceMode(row))
      return h(CapabilityBadge, { kind: badge.kind, label: badge.label, title: badge.title })
    },
  },
  { title: '事件', key: 'event_type', width: 120 },
  { title: '品种', key: 'product', width: 70, render: (row) => row.product || row.symbol },
  { title: '主连', key: 'continuous_contract', width: 100, render: (row) => row.continuous_contract || '-' },
  { title: '真实合约', key: 'actual_contract', width: 100, render: (row) => row.actual_contract || '-' },
  {
    title: '触发价',
    key: 'trigger_price',
    width: 90,
    render: (row) => (row.trigger_price != null ? row.trigger_price.toFixed(2) : '-'),
  },
  { title: 'bar_end', key: 'bar_end', width: 170, render: (row) => row.bar_end || '-' },
  {
    title: '质量',
    key: 'quality_status',
    width: 90,
    render: (row) => h(StatusTag, { status: String(row.quality_status?.status || 'unknown') }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 300,
    render: (row) =>
      h('div', { class: 'signal-events__actions' }, [
        h(
          NButton,
          { size: 'small', onClick: () => togglePreview(row.id) },
          { default: () => (expandedEventId.value === row.id ? '收起 Preview' : 'Preview') },
        ),
        h(NButton, { size: 'small', type: 'primary', ghost: true, onClick: () => openEventChart(row) }, { default: () => '打开K线' }),
        h(NButton, { size: 'small', onClick: () => openEventReview(row) }, { default: () => '进入复盘' }),
      ]),
  },
]

const expandedPreview = computed(() => {
  if (expandedEventId.value == null) return null
  return previewByEventId.value[expandedEventId.value] || null
})

function previewRiskCopy(preview: Stage9WechatPreview) {
  return preview.payload_basis.htdy_realtime_observation === true
    ? HTDY_REALTIME_RISK_COPY
    : null
}

async function loadEvents() {
  eventListController?.abort()
  const controller = new AbortController()
  eventListController = controller
  loading.value = true
  error.value = null
  try {
    const page = await listSignalEvents({ limit: eventPageSize, offset: (eventPage.value - 1) * eventPageSize }, controller.signal)
    if (controller.signal.aborted) return
    events.value = page.items
    eventTotal.value = page.total
  } catch (err) {
    if (!isCanceledRequest(err)) error.value = toSafeApiError(err, '加载信号事件失败')
  } finally {
    if (eventListController === controller) {
      eventListController = null
      loading.value = false
    }
  }
}

async function togglePreview(eventId: number) {
  if (expandedEventId.value === eventId) {
    expandedEventId.value = null
    return
  }
  expandedEventId.value = eventId
  void router.replace({ query: { ...route.query, tab: 'events', event_id: String(eventId) } })
  if (previewByEventId.value[eventId]) return
  loadingPreview.value = true
  try {
    previewByEventId.value[eventId] = await getStage9WechatPreview(eventId)
  } catch (err) {
    message.error(toSafeApiError(err, '加载 Stage9 preview 失败'))
  } finally {
    loadingPreview.value = false
  }
}

function openEventChart(event: SignalEventRecord) {
  const returnRoute = currentReturnRoute(route.path, {
    ...route.query,
    tab: 'events',
    event_id: String(event.id),
  } as Record<string, string | string[] | null | undefined>)
  void router.push({
    name: 'market-chart',
    query: {
      symbol: event.product || event.symbol,
      contract: event.actual_contract || event.contract,
      period: event.period,
      time: event.bar_end || event.signal_time || undefined,
      signal_id: event.signal_id ? String(event.signal_id) : undefined,
      signal_event_id: String(event.id),
      data_mode: isLiveObservationSourceMode(event.source_mode) ? 'live' : 'historical',
      return_route: returnRoute,
    },
    state: { researchScrollY: window.scrollY },
  })
}

function openEventReview(event: SignalEventRecord) {
  const returnRoute = currentReturnRoute(route.path, {
    ...route.query,
    tab: 'events',
    event_id: String(event.id),
  } as Record<string, string | string[] | null | undefined>)
  void router.push({
    name: 'review',
    query: buildSignalEventReviewQuery(event.id, event.signal_id, returnRoute),
    state: { researchScrollY: window.scrollY },
  })
}

async function openEvaluatorPreview() {
  loadingEvaluator.value = true
  try {
    evaluatorResult.value = await previewLiveEvaluator()
    evaluatorVisible.value = true
  } catch (err) {
    message.error(toSafeApiError(err, 'Live evaluator preview 失败'))
  } finally {
    loadingEvaluator.value = false
  }
}

onMounted(() => {
  void loadEvents()
})

onUnmounted(() => eventListController?.abort())

function isCanceledRequest(err: unknown) {
  return Boolean(err && typeof err === 'object' && 'code' in err && (err as { code?: string }).code === 'ERR_CANCELED')
}
</script>

<template>
  <div class="signal-events">
    <div class="signal-events__toolbar">
      <NButton size="small" :loading="loading" @click="loadEvents">刷新事件</NButton>
      <NButton size="small" :loading="loadingEvaluator" @click="openEvaluatorPreview">Live Evaluator Preview</NButton>
    </div>
    <NAlert type="warning" :bordered="false">
      企业微信仅 Preview；would_send=false，非交易指令；jm_v1b_historical_replay 为测试/回放。
    </NAlert>
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <NDataTable :columns="columns" :data="events" :loading="loading" size="small" :bordered="false" remote :pagination="eventPagination" />

    <div v-if="expandedEventId && expandedPreview" class="signal-events__preview">
      <NAlert v-if="!expandedPreview.allowed" type="error" :bordered="false">
        Gate 阻断：{{ expandedPreview.blocked_reasons.join(' · ') }}
      </NAlert>
      <template v-else>
        <NAlert
          v-if="previewRiskCopy(expandedPreview)"
          type="warning"
          :bordered="false"
        >
          {{ previewRiskCopy(expandedPreview) }}
        </NAlert>
        <NAlert type="warning" :bordered="false">
          观察提醒 · 非交易指令 · would_send={{ expandedPreview.would_send }}（禁止真实发送）
        </NAlert>
        <pre class="signal-events__markdown">{{ JSON.stringify(expandedPreview.wechat_payload, null, 2) }}</pre>
      </template>
    </div>

    <NDrawer v-model:show="evaluatorVisible" width="640">
      <NDrawerContent title="Live Evaluator Preview（只读）">
        <NAlert type="info" :bordered="false">Preview only，不写 SignalEvent，不自动下单，不发送通知。</NAlert>
        <div v-if="evaluatorResult" class="evaluator-body">
          <div class="evaluator-meta">
            <NTag size="small">{{ evaluatorResult.contract }}</NTag>
            <span>actual {{ evaluatorResult.actual_contract || '—' }}</span>
            <span>主连 {{ evaluatorResult.continuous_contract || '—' }}</span>
          </div>
          <div v-for="item in evaluatorResult.results" :key="item.entry_interval" class="evaluator-item">
            <div class="evaluator-item__heading">
              <strong>{{ item.entry_interval }}</strong>
              <NTag size="small" :type="item.context?.status === 'ready' ? 'success' : 'error'">
                context {{ item.context?.status || 'missing' }}
              </NTag>
            </div>
            <span>{{ item.status }} / {{ item.direction }}</span>
            <span v-if="item.trigger_price">触发价 {{ item.trigger_price }}</span>
            <span v-if="item.no_signal_reason">{{ item.no_signal_reason }}</span>
            <template v-if="item.context">
              <span v-if="item.context.historical_context_file_id">
                historical #{{ item.context.historical_context_file_id }} · {{ item.context.historical_context_data_version }}
              </span>
              <span v-if="item.context.live_bar_id">
                live #{{ item.context.live_bar_id }} r{{ item.context.live_bar_revision }} · {{ item.context.confirmed_at }}
              </span>
              <span v-if="item.context.blocked_reason">{{ item.context.blocked_reason }}</span>
            </template>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.signal-events__toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.signal-events__actions {
  display: flex;
  gap: 6px;
}

.signal-events__preview {
  margin-top: 12px;
  padding: 12px;
  background: var(--gy-bg-elevated);
  border-radius: 8px;
}

.signal-events__markdown {
  margin-top: 8px;
  white-space: pre-wrap;
  font-size: 12px;
  color: var(--gy-text-muted);
}

.evaluator-body {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evaluator-item__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.evaluator-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 13px;
}

.evaluator-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--gy-border);
  border-radius: 8px;
}
</style>
