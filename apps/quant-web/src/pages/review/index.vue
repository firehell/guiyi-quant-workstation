<script setup lang="ts">
/** 复盘中心：保留 Signal/手工来源，不依赖已退役回测实体。 */
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
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
import KlineChart from '@/components/kline/KlineChart.vue'
import PageShell from '@/components/common/PageShell.vue'
import {
  addReviewAttachment,
  createReviewFromSignalEvent,
  createReviewFromStrategySignal,
  getReview,
  getReviewBars,
  getReviewStats,
  getReviewTags,
  getReviews,
  updateReview,
} from '@/api/review'
import { getSignalEvent } from '@/api/signal'
import type { BarData } from '@/types/market'
import type { ReviewFormalLineage, ReviewNote, ReviewStats, ReviewTag } from '@/types/review'
import type { SignalEventRecord } from '@/types/signal'
import { toSafeApiError } from '@/utils/errorRedaction'
import { presentReviewLineage } from '@/utils/reviewLineagePresentation'
import { parseReviewDeepLinkQuery, reviewSourceIdentity } from '@/utils/reviewPresentation'
import { signalSourceDataMode } from '@/utils/signalSourceMode'
import {
  buildChartResearchQuery,
  parseResearchContext,
  safeReturnRoute,
  type ResearchSourceType,
} from '@/utils/researchNavigation'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const loading = ref(false)
const loadingBars = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const klineError = ref<string | null>(null)
const reviews = ref<ReviewNote[]>([])
const tags = ref<ReviewTag[]>([])
const stats = ref<ReviewStats | null>(null)
const selectedReview = ref<ReviewNote | null>(null)
const selectedSignalEvent = ref<SignalEventRecord | null>(null)
const pendingSourceType = ref<ResearchSourceType | null>(null)
const pendingSourceId = ref<number | null>(null)
const bars = ref<BarData[]>([])
const lineage = ref<ReviewFormalLineage | null>(null)
const attachmentPath = ref('')
const savedReviewSnapshot = ref('')
let selectionRequestId = 0

const tagOptions = computed(() => {
  const byType = (type: ReviewTag['tag_type']) => tags.value
    .filter((tag) => tag.tag_type === type)
    .map((tag) => ({ label: tag.name, value: tag.name }))
  return {
    mistake: byType('mistake'),
    phase: byType('market_phase'),
    rule: [...byType('entry_rule'), ...byType('exit_rule')],
    emotion: byType('emotion'),
  }
})

const hasUnsavedChanges = computed(() => Boolean(
  selectedReview.value && reviewSnapshot(selectedReview.value) !== savedReviewSnapshot.value,
))
const returnRoute = computed(() => safeReturnRoute(
  Array.isArray(route.query.return_route) ? route.query.return_route[0] : route.query.return_route,
))
const pendingSourceLabel = computed(() => {
  if (pendingSourceType.value === 'signal_event' && selectedSignalEvent.value) {
    return `SignalEvent #${selectedSignalEvent.value.id} · ${selectedSignalEvent.value.source_mode}`
  }
  if (pendingSourceType.value === 'strategy_signal') return `StrategySignal #${pendingSourceId.value}`
  return ''
})
const lineagePresentation = computed(() => lineage.value ? presentReviewLineage(lineage.value) : null)

const reviewColumns: DataTableColumns<ReviewNote> = [
  {
    title: '复盘',
    key: 'id',
    width: 86,
    render: (row) => h('button', { class: 'link-button', onClick: () => void openReviewById(row.id) }, `#${row.id}`),
  },
  { title: '来源', key: 'source_type', minWidth: 140 },
  { title: '品种', key: 'symbol', width: 80, render: (row) => row.symbol || '-' },
  { title: '周期', key: 'period', width: 76, render: (row) => row.entry_interval || row.period || '-' },
  {
    title: '状态',
    key: 'ai_status',
    width: 90,
    render: (row) => h(NTag, { size: 'small' }, { default: () => row.ai_status || 'manual' }),
  },
]

onMounted(async () => {
  await loadAll()
  await applyRouteSelection()
})

watch(
  () => [route.query.review_id, route.query.source_type, route.query.source_id, route.query.signal_id, route.query.signal_event_id],
  () => void applyRouteSelection(),
)

async function loadAll() {
  loading.value = true
  error.value = null
  try {
    const [reviewRows, tagRows, statRows] = await Promise.all([
      getReviews({ limit: 100, offset: 0 }),
      getReviewTags(),
      getReviewStats(),
    ])
    reviews.value = reviewRows.items.map(normalizeReview)
    tags.value = tagRows
    stats.value = statRows
  } catch (err) {
    error.value = toSafeApiError(err, '加载复盘数据失败')
  } finally {
    loading.value = false
  }
}

async function applyRouteSelection() {
  const requestId = ++selectionRequestId
  const deepLink = parseReviewDeepLinkQuery(route.query as Record<string, string | string[] | null | undefined>)
  if (deepLink.review_id) {
    await openReviewById(deepLink.review_id, requestId)
    return
  }
  const research = parseResearchContext(route.query as Record<string, string | string[] | null | undefined>)
  const sourceType = research.sourceType
    || (research.signalEventId ? 'signal_event' : research.signalId ? 'strategy_signal' : null)
  const sourceId = research.sourceId || research.signalEventId || research.signalId
  if (sourceType && sourceId) {
    await openSignalSource(sourceType, sourceId, requestId)
    return
  }
  clearSelection()
}

async function openReviewById(reviewId: number, requestId = ++selectionRequestId) {
  try {
    const review = normalizeReview(await getReview(reviewId))
    if (requestId !== selectionRequestId) return
    selectedReview.value = review
    pendingSourceType.value = null
    pendingSourceId.value = null
    selectedSignalEvent.value = review.source_type === 'signal_event' && review.source_id
      ? await getSignalEvent(review.source_id)
      : null
    if (requestId !== selectionRequestId) return
    markReviewSaved(review)
    await loadBars(review, requestId)
  } catch (err) {
    if (requestId === selectionRequestId) error.value = toSafeApiError(err, '打开复盘记录失败')
  }
}

async function openSignalSource(sourceType: ResearchSourceType, sourceId: number, requestId: number) {
  try {
    const [existing, event] = await Promise.all([
      getReviews({ source_type: sourceType, source_id: sourceId }),
      sourceType === 'signal_event' ? getSignalEvent(sourceId) : Promise.resolve(null),
    ])
    if (requestId !== selectionRequestId) return
    selectedSignalEvent.value = event
    if (existing.items[0]) {
      await openReviewById(existing.items[0].id, requestId)
      return
    }
    selectedReview.value = null
    bars.value = []
    lineage.value = null
    pendingSourceType.value = sourceType
    pendingSourceId.value = sourceId
  } catch (err) {
    if (requestId === selectionRequestId) error.value = toSafeApiError(err, '打开信号复盘来源失败')
  }
}

async function createPendingReview() {
  if (!pendingSourceType.value || !pendingSourceId.value) return
  saving.value = true
  try {
    const review = pendingSourceType.value === 'signal_event'
      ? await createReviewFromSignalEvent(pendingSourceId.value)
      : await createReviewFromStrategySignal(pendingSourceId.value)
    selectedReview.value = normalizeReview(review)
    pendingSourceType.value = null
    pendingSourceId.value = null
    markReviewSaved(selectedReview.value)
    await Promise.all([loadBars(selectedReview.value), loadAll()])
    void router.replace({ query: { review_id: String(selectedReview.value.id) } })
  } catch (err) {
    error.value = toSafeApiError(err, '创建复盘失败')
  } finally {
    saving.value = false
  }
}

async function loadBars(review: ReviewNote, requestId = selectionRequestId) {
  loadingBars.value = true
  klineError.value = null
  bars.value = []
  lineage.value = null
  try {
    const result = await getReviewBars(review.id)
    if (requestId !== selectionRequestId) return
    bars.value = result.bars || []
    lineage.value = result.lineage
    if (!bars.value.length) klineError.value = '该复盘来源窗口未返回 K 线数据'
  } catch (err) {
    if (requestId === selectionRequestId) klineError.value = toSafeApiError(err, '加载复盘 K 线失败')
  } finally {
    if (requestId === selectionRequestId) loadingBars.value = false
  }
}

async function saveReview() {
  if (!selectedReview.value) return
  saving.value = true
  try {
    const current = selectedReview.value
    selectedReview.value = normalizeReview(await updateReview(current.id, {
      entry_reason: current.entry_reason,
      exit_reason: current.exit_reason,
      market_phase: current.market_phase,
      is_system_compliant: current.is_system_compliant,
      mistake_tags: current.mistake_tags,
      setup_tags: current.setup_tags,
      emotion_tags: current.emotion_tags,
      execution_note: current.execution_note,
      improvement_note: current.improvement_note,
      screenshot_path: current.screenshot_path,
      review_score: current.review_score,
    }))
    markReviewSaved(selectedReview.value)
    message.success('复盘已保存')
    await loadAll()
  } catch (err) {
    error.value = toSafeApiError(err, '保存复盘失败')
  } finally {
    saving.value = false
  }
}

async function addAttachment() {
  if (!selectedReview.value || !attachmentPath.value.trim()) return
  await addReviewAttachment(selectedReview.value.id, {
    file_path: attachmentPath.value.trim(),
    file_type: 'image',
  })
  selectedReview.value = normalizeReview(await getReview(selectedReview.value.id))
  markReviewSaved(selectedReview.value)
  attachmentPath.value = ''
}

function openMarket() {
  const review = selectedReview.value
  if (!review) return
  const sourceId = review.source_id || null
  void router.push({
    name: 'market-chart',
    query: buildChartResearchQuery({
      symbol: review.symbol,
      contract: review.contract,
      period: review.entry_interval || review.period,
      time: review.kline_focus_time || review.entry_time || review.open_time,
      signalId: review.source_type === 'strategy_signal' ? sourceId : selectedSignalEvent.value?.signal_id,
      signalEventId: review.source_type === 'signal_event' ? sourceId : null,
      dataMode: signalSourceDataMode(selectedSignalEvent.value?.source_mode),
      returnRoute: route.fullPath,
    }),
  })
}

function clearSelection() {
  selectedReview.value = null
  selectedSignalEvent.value = null
  pendingSourceType.value = null
  pendingSourceId.value = null
  bars.value = []
  lineage.value = null
  klineError.value = null
}

function normalizeReview(review: ReviewNote) {
  review.setup_tags = review.setup_tags || review.rule_tags || []
  review.improvement_note = review.improvement_note || review.lesson || null
  review.screenshot_path = review.screenshot_path || review.screenshot_paths?.[0] || ''
  review.entry_interval = review.entry_interval || review.period
  review.entry_time = review.entry_time || review.open_time
  review.exit_time = review.exit_time || review.close_time
  return review
}

function reviewSnapshot(review: ReviewNote) {
  return JSON.stringify({
    entry_reason: review.entry_reason,
    exit_reason: review.exit_reason,
    market_phase: review.market_phase,
    is_system_compliant: review.is_system_compliant,
    mistake_tags: review.mistake_tags,
    setup_tags: review.setup_tags,
    emotion_tags: review.emotion_tags,
    execution_note: review.execution_note,
    improvement_note: review.improvement_note,
    screenshot_path: review.screenshot_path,
    review_score: review.review_score,
  })
}

function markReviewSaved(review: ReviewNote) {
  savedReviewSnapshot.value = reviewSnapshot(review)
}

function displayAttachmentLabel(path: string | null | undefined) {
  const normalized = path?.trim()
  if (!normalized) return ''
  return normalized.split(/[/\\]/).at(-1) || 'attachment'
}

function formatDateTime(value: string | null | undefined) {
  return value ? value.replace('T', ' ').slice(0, 16) : '-'
}
</script>

<template>
  <PageShell title="复盘中心" subtitle="Signal 与手工复盘；冻结来源事实与个人判断分层记录">
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <NAlert v-if="pendingSourceType" type="info" :bordered="false" class="review-alert">
      <strong>{{ pendingSourceLabel }}</strong>：尚无复盘；只有点击“创建复盘”才会写入。
    </NAlert>

    <section class="stats-grid">
      <div class="metric"><span>复盘数</span><strong>{{ stats?.total_reviews || 0 }}</strong></div>
      <div class="metric"><span>最常见错误</span><strong>{{ stats?.mistake_tags[0]?.name || '-' }}</strong></div>
      <div class="metric"><span>最有效规则</span><strong>{{ stats?.rule_effectiveness[0]?.name || '-' }}</strong></div>
      <div class="metric"><span>主要行情阶段</span><strong>{{ stats?.market_phase[0]?.name || '-' }}</strong></div>
    </section>

    <section class="review-grid">
      <aside class="panel">
        <div class="panel-head">
          <div><h2>已有复盘</h2><p>Signal / 手工来源</p></div>
          <NButton size="small" :loading="loading" @click="loadAll">刷新</NButton>
        </div>
        <NDataTable :columns="reviewColumns" :data="reviews" :loading="loading" :pagination="false" size="small" />
      </aside>

      <main class="panel">
        <div class="panel-head">
          <div><h2>K 线与 Lineage</h2><p>{{ selectedReview ? reviewSourceIdentity(selectedReview) : '选择一条复盘记录' }}</p></div>
          <NButton size="small" :disabled="!selectedReview?.symbol" @click="openMarket">行情 K 线</NButton>
        </div>
        <KlineChart :bars="bars" :markers="[]" :loading="loadingBars" :error="klineError" />
        <div v-if="lineagePresentation" class="lineage-summary">
          <strong>{{ lineagePresentation.kind === 'canonical' ? 'Canonical review lineage' : lineagePresentation.label }}</strong>
          <span>source_window={{ lineagePresentation.sourceWindow }}</span>
          <span v-if="lineagePresentation.kind === 'canonical'">input_digest={{ lineagePresentation.inputDigest }}</span>
          <span v-if="lineagePresentation.kind === 'observation'">source_mode={{ lineagePresentation.sourceMode }}</span>
        </div>
      </main>

      <aside class="panel">
        <div class="panel-head">
          <div><h2>复盘卡</h2><p>仅人工确认后写入</p></div>
          <div class="actions">
            <NButton v-if="returnRoute" size="small" @click="router.push(returnRoute)">返回来源</NButton>
            <NButton v-if="pendingSourceType" type="primary" size="small" :loading="saving" @click="createPendingReview">创建复盘</NButton>
            <NButton v-else type="primary" size="small" :disabled="!selectedReview" :loading="saving" @click="saveReview">
              保存{{ hasUnsavedChanges ? ' *' : '' }}
            </NButton>
          </div>
        </div>

        <div v-if="!selectedReview" class="empty-block">{{ pendingSourceType ? '等待显式创建复盘。' : '请选择左侧复盘。' }}</div>
        <template v-else>
          <NDescriptions :column="2" bordered size="small">
            <NDescriptionsItem label="来源身份" :span="2"><code>{{ reviewSourceIdentity(selectedReview) }}</code></NDescriptionsItem>
            <NDescriptionsItem label="品种">{{ selectedReview.symbol || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="周期">{{ selectedReview.entry_interval || selectedReview.period || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="方向">{{ selectedReview.direction || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="来源时间">{{ formatDateTime(selectedReview.entry_time || selectedReview.open_time) }}</NDescriptionsItem>
          </NDescriptions>
          <NForm class="review-form" label-placement="top">
            <NFormItem label="是否符合研究规则">
              <NSwitch :value="selectedReview.is_system_compliant ?? false" @update:value="(value: boolean) => selectedReview && (selectedReview.is_system_compliant = value)" />
            </NFormItem>
            <NFormItem label="行情阶段"><NSelect v-model:value="selectedReview.market_phase" clearable :options="tagOptions.phase" /></NFormItem>
            <NFormItem label="错误标签"><NSelect v-model:value="selectedReview.mistake_tags" multiple filterable :options="tagOptions.mistake" /></NFormItem>
            <NFormItem label="形态/场景标签"><NSelect v-model:value="selectedReview.setup_tags" multiple filterable :options="tagOptions.rule" /></NFormItem>
            <NFormItem label="情绪标签"><NSelect v-model:value="selectedReview.emotion_tags" multiple filterable :options="tagOptions.emotion" /></NFormItem>
            <NFormItem label="观察依据"><NInput v-model:value="selectedReview.entry_reason" type="textarea" /></NFormItem>
            <NFormItem label="结果依据"><NInput v-model:value="selectedReview.exit_reason" type="textarea" /></NFormItem>
            <NFormItem label="执行备注"><NInput v-model:value="selectedReview.execution_note" type="textarea" /></NFormItem>
            <NFormItem label="改进计划"><NInput v-model:value="selectedReview.improvement_note" type="textarea" /></NFormItem>
            <NFormItem label="复盘评分"><NInputNumber v-model:value="selectedReview.review_score" :min="0" :max="100" /></NFormItem>
            <NFormItem label="截图登记">
              <div class="attachment-row">
                <NInput :value="displayAttachmentLabel(selectedReview.screenshot_path)" readonly />
                <NInput v-model:value="attachmentPath" placeholder="文件名或相对路径" />
                <NButton @click="addAttachment">登记</NButton>
              </div>
            </NFormItem>
          </NForm>
        </template>
      </aside>
    </section>
  </PageShell>
</template>

<style scoped>
.review-alert { margin-bottom: var(--gy-space-4); }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--gy-space-3); margin-bottom: var(--gy-space-4); }
.metric, .panel { border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.metric { padding: var(--gy-space-3); display: flex; justify-content: space-between; gap: var(--gy-space-2); }
.metric span, .panel p { color: var(--gy-text-muted); }
.review-grid { display: grid; grid-template-columns: minmax(280px, .8fr) minmax(420px, 1.2fr) minmax(320px, 1fr); gap: var(--gy-space-4); }
.panel { min-width: 0; padding: var(--gy-space-4); }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--gy-space-3); margin-bottom: var(--gy-space-3); }
.panel-head h2, .panel-head p { margin: 0; }
.panel-head p { margin-top: 4px; font-size: 12px; }
.actions, .attachment-row { display: flex; gap: var(--gy-space-2); }
.review-form { margin-top: var(--gy-space-4); }
.empty-block, .lineage-summary { padding: var(--gy-space-4); color: var(--gy-text-muted); }
.lineage-summary { display: flex; flex-direction: column; gap: 4px; font-family: var(--gy-font-mono); font-size: 12px; }
.link-button { border: 0; background: transparent; color: var(--gy-accent); cursor: pointer; }
@media (max-width: 1280px) { .review-grid { grid-template-columns: 1fr; } }
</style>
