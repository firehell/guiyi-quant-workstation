<script setup lang="ts">
/** 信号事件列表：Stage9 企业微信 Preview（would_send=false）。 */
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  type DataTableColumns,
} from 'naive-ui'
import { getStage9WechatPreview, listSignalEvents } from '@/api/signal'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import type { SignalEventRecord, Stage9WechatPreview } from '@/types/signal'
import { toSafeApiError } from '@/utils/errorRedaction'
import {
  buildHtDyFirstSeenPresentation,
  type HtDyFirstSeenPresentation,
} from '@/utils/htdyFirstSeenPresentation'
import { resolveEventSourceMode, signalSourceDataMode, sourceModeBadge } from '@/utils/signalSourceMode'
import { buildSignalEventReviewQuery, currentReturnRoute } from '@/utils/researchNavigation'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref<string | null>(null)
const events = ref<SignalEventRecord[]>([])
const eventTotal = ref(0)
const eventPage = ref(1)
const eventPageSize = 10
const expandedEventId = ref<number | null>(null)
const previewByEventId = ref<Record<number, Stage9WechatPreview>>({})
const htdyEvidenceVisible = ref(false)
const selectedHtDyEvidence = ref<HtDyFirstSeenPresentation | null>(null)
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
        ...(buildHtDyFirstSeenPresentation(row)
          ? [
              h(
                NButton,
                {
                  size: 'small',
                  onClick: () => openHtDyEvidence(row),
                },
                { default: () => '查看 HTDY 证据' },
              ),
            ]
          : []),
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
  try {
    previewByEventId.value[eventId] = await getStage9WechatPreview(eventId)
  } catch (err) {
    error.value = toSafeApiError(err, '加载 Stage9 preview 失败')
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
      data_mode: signalSourceDataMode(event.source_mode),
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

function openHtDyEvidence(event: SignalEventRecord) {
  selectedHtDyEvidence.value = buildHtDyFirstSeenPresentation(event)
  htdyEvidenceVisible.value = selectedHtDyEvidence.value !== null
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
        <NAlert type="warning" :bordered="false">
          观察提醒 · 非交易指令 · would_send={{ expandedPreview.would_send }}（禁止真实发送）
        </NAlert>
        <pre class="signal-events__markdown">{{ JSON.stringify(expandedPreview.wechat_payload, null, 2) }}</pre>
      </template>
    </div>

    <NDrawer v-model:show="htdyEvidenceVisible" width="680">
      <NDrawerContent title="HTDY first-seen 冻结证据">
        <template v-if="selectedHtDyEvidence">
          <NAlert type="warning" :bordered="false">
            仅供观察，不是交易指令；事件首次出现后不因重绘、反向、消失或 revision 撤回。
          </NAlert>
          <NDescriptions :column="2" bordered size="small" class="htdy-evidence">
            <NDescriptionsItem label="观察身份">{{ selectedHtDyEvidence.identity }}</NDescriptionsItem>
            <NDescriptionsItem label="source_mode">{{ selectedHtDyEvidence.sourceMode }}</NDescriptionsItem>
            <NDescriptionsItem label="实际主力">{{ selectedHtDyEvidence.actualContract }}</NDescriptionsItem>
            <NDescriptionsItem label="周期">{{ selectedHtDyEvidence.period }}</NDescriptionsItem>
            <NDescriptionsItem label="first-seen">{{ selectedHtDyEvidence.firstSeenAt }}</NDescriptionsItem>
            <NDescriptionsItem label="冻结 lineage">{{ selectedHtDyEvidence.lineageSchema }}</NDescriptionsItem>
            <NDescriptionsItem label="观察桶开始">{{ selectedHtDyEvidence.bucketStart }}</NDescriptionsItem>
            <NDescriptionsItem label="观察桶结束">{{ selectedHtDyEvidence.bucketEnd }}</NDescriptionsItem>
            <NDescriptionsItem label="未来引用">future-looking={{ selectedHtDyEvidence.futureLooking }}</NDescriptionsItem>
            <NDescriptionsItem label="重绘">repainting={{ selectedHtDyEvidence.repaintingAccepted }}</NDescriptionsItem>
            <NDescriptionsItem label="首次语义">first-seen 不撤回</NDescriptionsItem>
            <NDescriptionsItem label="通知">notification={{ selectedHtDyEvidence.notificationReady }}</NDescriptionsItem>
            <NDescriptionsItem label="自动执行">auto-order={{ selectedHtDyEvidence.autoOrder }}</NDescriptionsItem>
          </NDescriptions>
        </template>
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

.htdy-evidence {
  margin-top: 12px;
}
</style>
