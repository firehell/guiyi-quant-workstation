<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
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
import StatusTag from '@/components/common/StatusTag.vue'
import type { LiveSignalEvaluationResponse, SignalEventRecord, Stage9WechatPreview } from '@/types/signal'

const message = useMessage()
const loading = ref(false)
const loadingPreview = ref(false)
const loadingEvaluator = ref(false)
const error = ref<string | null>(null)
const events = ref<SignalEventRecord[]>([])
const expandedEventId = ref<number | null>(null)
const previewByEventId = ref<Record<number, Stage9WechatPreview>>({})
const evaluatorVisible = ref(false)
const evaluatorResult = ref<LiveSignalEvaluationResponse | null>(null)

const columns: DataTableColumns<SignalEventRecord> = [
  { title: '时间', key: 'created_at', width: 170, render: (row) => row.created_at || row.signal_time || '-' },
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
    width: 120,
    render: (row) =>
      h(
        NButton,
        { size: 'small', onClick: () => togglePreview(row.id) },
        { default: () => (expandedEventId.value === row.id ? '收起' : 'Preview') },
      ),
  },
]

const expandedPreview = computed(() => {
  if (expandedEventId.value == null) return null
  return previewByEventId.value[expandedEventId.value] || null
})

async function loadEvents() {
  loading.value = true
  error.value = null
  try {
    events.value = await listSignalEvents({ limit: 100 })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载信号事件失败'
  } finally {
    loading.value = false
  }
}

async function togglePreview(eventId: number) {
  if (expandedEventId.value === eventId) {
    expandedEventId.value = null
    return
  }
  expandedEventId.value = eventId
  if (previewByEventId.value[eventId]) return
  loadingPreview.value = true
  try {
    previewByEventId.value[eventId] = await getStage9WechatPreview(eventId)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载 Stage9 preview 失败')
  } finally {
    loadingPreview.value = false
  }
}

async function openEvaluatorPreview() {
  loadingEvaluator.value = true
  try {
    evaluatorResult.value = await previewLiveEvaluator()
    evaluatorVisible.value = true
  } catch (err) {
    message.error(err instanceof Error ? err.message : 'Live evaluator preview 失败')
  } finally {
    loadingEvaluator.value = false
  }
}

onMounted(() => {
  void loadEvents()
})
</script>

<template>
  <div class="signal-events">
    <div class="signal-events__toolbar">
      <NButton size="small" :loading="loading" @click="loadEvents">刷新事件</NButton>
      <NButton size="small" :loading="loadingEvaluator" @click="openEvaluatorPreview">Live Evaluator Preview</NButton>
    </div>
    <NAlert type="warning" :bordered="false">企业微信仅 Preview；would_send=false，非交易指令。</NAlert>
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <NDataTable :columns="columns" :data="events" :loading="loading" size="small" :bordered="false" />

    <div v-if="expandedEventId && expandedPreview" class="signal-events__preview">
      <NAlert v-if="!expandedPreview.allowed" type="error" :bordered="false">
        Gate 阻断：{{ expandedPreview.blocked_reasons.join(' · ') }}
      </NAlert>
      <template v-else>
        <NAlert type="warning" :bordered="false">
          观察提醒 · 非交易指令 · would_send={{ expandedPreview.would_send }}
        </NAlert>
        <pre class="signal-events__markdown">{{ JSON.stringify(expandedPreview.wechat_payload, null, 2) }}</pre>
      </template>
    </div>

    <NDrawer v-model:show="evaluatorVisible" width="640">
      <NDrawerContent title="Live Evaluator Preview（只读）">
        <NAlert type="info" :bordered="false">Preview only，不写 SignalEvent，不自动下单。</NAlert>
        <div v-if="evaluatorResult" class="evaluator-body">
          <div class="evaluator-meta">
            <NTag size="small">{{ evaluatorResult.contract }}</NTag>
            <span>actual {{ evaluatorResult.actual_contract || '—' }}</span>
            <span>主连 {{ evaluatorResult.continuous_contract || '—' }}</span>
          </div>
          <div v-for="item in evaluatorResult.results" :key="item.entry_interval" class="evaluator-item">
            <strong>{{ item.entry_interval }}</strong>
            <span>{{ item.status }} / {{ item.direction }}</span>
            <span v-if="item.trigger_price">触发价 {{ item.trigger_price }}</span>
            <span v-if="item.no_signal_reason">{{ item.no_signal_reason }}</span>
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
