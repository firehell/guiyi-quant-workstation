<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NEmpty, NInput, NSelect, NSpin, NTabPane, NTabs, NTag, useMessage } from 'naive-ui'
import DecisionForm from '@/components/execution-review/DecisionForm.vue'
import DispositionCorrectionForm from '@/components/execution-review/DispositionCorrectionForm.vue'
import EpisodeDetail from '@/components/execution-review/EpisodeDetail.vue'
import ExecutionStats from '@/components/execution-review/ExecutionStats.vue'
import ReconstructionPanel from '@/components/execution-review/ReconstructionPanel.vue'
import { executionReviewErrorMessage, getEpisodeDetail, getEventStates, getStats, listItems } from '@/api/executionReview'
import type { Direction, EpisodeDetailResponse, EventState, ExecutionReviewFrequency, ExecutionReviewState, ExecutionReviewStatsResponse, ReviewItem } from '@/types/executionReview'
import { buildReviewItemFilters, buildStatsFilters } from '@/utils/executionReview'

const STATES: ExecutionReviewState[] = ['pending_decision', 'open', 'pending_review', 'done']
const labels: Record<ExecutionReviewState, string> = {
  pending_decision: '待决策', open: '进行中', pending_review: '待复盘', done: '已完成',
}
const route = useRoute()
const router = useRouter()
const message = useMessage()
const currentState = ref<ExecutionReviewState>(validState(route.query.state) ? route.query.state : 'pending_decision')
const itemsByState = ref<Record<ExecutionReviewState, ReviewItem[]>>({
  pending_decision: [], open: [], pending_review: [], done: [],
})
const filters = reactive({
  symbol: '', direction: null as Direction | null, frequency: null as ExecutionReviewFrequency | null,
  start_trading_day: '', end_trading_day: '',
})
const loading = ref(false)
const statsLoading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const statsError = ref('')
const stats = ref<ExecutionReviewStatsResponse | null>(null)
const detail = ref<EpisodeDetailResponse | null>(null)
const fallbackItem = ref<ReviewItem | null>(null)
let listGeneration = 0
let statsGeneration = 0
let detailGeneration = 0

const currentItems = computed(() => itemsByState.value[currentState.value])
const selectedItem = computed(() => {
  const eventId = positiveId(route.query.event_id)
  const episodeId = positiveId(route.query.episode_id)
  return currentItems.value.find((row) => (
    (eventId !== null && row.event_id === eventId)
    || (episodeId !== null && row.episode_id === episodeId)
  )) || (fallbackItem.value?.state === currentState.value ? fallbackItem.value : null)
})

onMounted(() => void loadAll())

watch(() => route.query.state, (value) => {
  const next = validState(value) ? value : 'pending_decision'
  if (currentState.value !== next) currentState.value = next
})

watch(currentState, () => void loadStats())

watch(() => selectedItem.value?.episode_id, (episodeId) => {
  detail.value = null
  if (episodeId) void loadDetail(episodeId)
})

async function loadAll() {
  void loadStats()
  const current = ++listGeneration
  loading.value = true
  error.value = ''
  try {
    const responses = await Promise.all(STATES.map((state) => listItems(buildReviewItemFilters(state, filters))))
    if (current !== listGeneration) return
    itemsByState.value = Object.fromEntries(STATES.map((state, index) => [state, responses[index].items])) as Record<ExecutionReviewState, ReviewItem[]>
    await recoverAuthoritativeSelection()
    if (
      selectedItem.value?.episode_id
      && detail.value?.episode.id !== selectedItem.value.episode_id
    ) await loadDetail(selectedItem.value.episode_id)
  } catch (reason) {
    if (current === listGeneration) error.value = executionReviewErrorMessage(reason)
  } finally {
    if (current === listGeneration) loading.value = false
  }
}

async function loadStats() {
  const current = ++statsGeneration
  statsLoading.value = true
  statsError.value = ''
  try {
    const next = await getStats(buildStatsFilters(currentState.value, filters))
    if (current === statsGeneration) stats.value = next
  } catch (reason) {
    if (current === statsGeneration) statsError.value = executionReviewErrorMessage(reason)
  } finally {
    if (current === statsGeneration) statsLoading.value = false
  }
}

async function recoverAuthoritativeSelection() {
  fallbackItem.value = null
  const eventId = positiveId(route.query.event_id)
  const episodeId = positiveId(route.query.episode_id)
  if (eventId === null && episodeId === null) return
  const authoritativeState = STATES.find((state) => itemsByState.value[state].some((row) => (
    (eventId !== null && row.event_id === eventId)
    || (episodeId !== null && row.episode_id === episodeId)
  )))
  if (authoritativeState && authoritativeState !== currentState.value) {
    currentState.value = authoritativeState
    await router.replace(selectionQuery(authoritativeState, itemsByState.value[authoritativeState].find((row) => (
      (eventId !== null && row.event_id === eventId) || (episodeId !== null && row.episode_id === episodeId)
    ))!))
    return
  }
  if (!authoritativeState && eventId !== null) {
    const response = await getEventStates([eventId])
    const eventState = response.items[0]
    if (!eventState?.episode_id) return
    const resolved = await getEpisodeDetail(eventState.episode_id)
    detail.value = resolved
    fallbackItem.value = {
      item_kind: 'episode',
      state: eventState.state,
      event_id: eventId,
      decision_id: eventState.decision_id,
      episode_id: eventState.episode_id,
      symbol: resolved.episode.symbol,
      contract: resolved.episode.contract,
      direction: resolved.episode.direction,
      trading_day: resolved.origin_event.trading_day,
    }
    if (currentState.value !== eventState.state) {
      currentState.value = eventState.state
      await router.replace(selectionQuery(eventState.state, fallbackItem.value))
    }
  }
}

async function loadDetail(episodeId: number) {
  const current = ++detailGeneration
  detailLoading.value = true
  try {
    const next = await getEpisodeDetail(episodeId)
    if (current === detailGeneration) detail.value = next
  } catch (reason) {
    if (current === detailGeneration) error.value = executionReviewErrorMessage(reason)
  } finally {
    if (current === detailGeneration) detailLoading.value = false
  }
}

async function setState(value: ExecutionReviewState) {
  currentState.value = value
  detail.value = null
  await router.replace({ name: 'trade-records', query: { state: value } })
}

async function selectItem(row: ReviewItem) {
  await router.replace(selectionQuery(row.state, row))
  if (row.episode_id) await loadDetail(row.episode_id)
}

function selectionQuery(state: ExecutionReviewState, row: ReviewItem) {
  const useEpisode = state === 'open' || state === 'pending_review'
  return {
    name: 'trade-records',
    query: {
      state,
      event_id: useEpisode ? undefined : String(row.event_id),
      episode_id: useEpisode && row.episode_id ? String(row.episode_id) : undefined,
    },
  }
}

async function handleChanged(outcome: {
  state: ExecutionReviewState
  eventId?: number
  episodeId: number | null
  message: string
}) {
  message.success(outcome.message)
  currentState.value = outcome.state
  await router.replace({
    name: 'trade-records',
    query: {
      state: outcome.state,
      event_id: outcome.state === 'done' && outcome.eventId ? String(outcome.eventId) : undefined,
      episode_id: outcome.state !== 'done' && outcome.episodeId ? String(outcome.episodeId) : undefined,
    },
  })
  await loadAll()
}

async function handleStale(eventId?: number) {
  const authoritativeEpisodeId = selectedItem.value?.episode_id ?? detail.value?.episode.id ?? null
  if (eventId) {
    try {
      const response = await getEventStates([eventId])
      const eventState = response.items.find((item) => item.event_id === eventId)
      if (eventState) {
        currentState.value = eventState.state
        detail.value = null
        fallbackItem.value = null
        await router.replace(eventStateSelectionQuery(eventState))
      }
    } catch (reason) {
      error.value = executionReviewErrorMessage(reason)
    }
  }
  await loadAll()
  if (!eventId && authoritativeEpisodeId) await loadDetail(authoritativeEpisodeId)
  message.warning('已刷新后端最新状态')
}

function eventStateSelectionQuery(eventState: EventState) {
  const useEpisode = eventState.state === 'open' || eventState.state === 'pending_review'
  return {
    name: 'trade-records',
    query: {
      state: eventState.state,
      event_id: useEpisode ? undefined : String(eventState.event_id),
      episode_id: useEpisode && eventState.episode_id ? String(eventState.episode_id) : undefined,
    },
  }
}

function validState(value: unknown): value is ExecutionReviewState {
  return typeof value === 'string' && STATES.includes(value as ExecutionReviewState)
}
function positiveId(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = typeof raw === 'string' ? Number(raw) : NaN
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}
const directionOptions = [{ label: 'LONG', value: 'LONG' }, { label: 'SHORT', value: 'SHORT' }]
const frequencyOptions = [{ label: '5m', value: '5m' }, { label: '15m', value: '15m' }]
</script>

<template>
  <main class="trade-records-page">
    <header class="trade-records-page__intro">
      <div><h1>交易记录</h1><p>人工决策、手工执行记录与结构化复盘；不连接账户，仅记录人工研究事实。</p></div>
      <NButton secondary :loading="loading" @click="loadAll">刷新</NButton>
    </header>
    <NAlert v-if="error" type="warning">{{ error }}</NAlert>
    <NCard size="small">
      <div class="trade-records-page__filters">
        <NInput v-model:value="filters.symbol" clearable placeholder="品种，例如 jm" />
        <NSelect v-model:value="filters.direction" clearable placeholder="方向" :options="directionOptions" />
        <NSelect v-model:value="filters.frequency" clearable placeholder="周期" :options="frequencyOptions" />
        <template v-if="currentState === 'done'">
          <label>开始交易日<input v-model="filters.start_trading_day" class="gy-native-input" type="date"></label>
          <label>结束交易日<input v-model="filters.end_trading_day" class="gy-native-input" type="date"></label>
        </template>
        <NButton @click="loadAll">应用筛选</NButton>
      </div>
    </NCard>
    <ExecutionStats :stats="stats" :loading="statsLoading" :error="statsError" />
    <NTabs :value="currentState" type="line" animated @update:value="setState">
      <NTabPane v-for="state in STATES" :key="state" :name="state" :tab="`${labels[state]} ${itemsByState[state].length}`" />
    </NTabs>
    <div class="trade-records-page__workspace">
      <NCard size="small" class="trade-records-page__list">
        <NSpin :show="loading">
          <NEmpty v-if="!loading && currentItems.length === 0" description="当前状态暂无记录" />
          <button
            v-for="row in currentItems"
            :key="`${row.state}-${row.event_id}`"
            :class="['trade-records-page__item', { 'trade-records-page__item--active': selectedItem?.event_id === row.event_id }]"
            @click="selectItem(row)"
          >
            <span><strong>{{ row.symbol.toUpperCase() }} · {{ row.contract }}</strong><small>{{ row.trading_day }} · Event #{{ row.event_id }}</small></span>
            <NTag size="small" :type="row.direction === 'LONG' ? 'error' : 'success'">{{ row.direction }}</NTag>
          </button>
        </NSpin>
      </NCard>
      <section class="trade-records-page__detail">
        <NEmpty v-if="!selectedItem" description="选择一条记录查看和处理" />
        <template v-else>
          <ReconstructionPanel :event-id="selectedItem.event_id" :direction="selectedItem.direction" />
          <DecisionForm
            v-if="selectedItem.state === 'pending_decision'"
            :event-id="selectedItem.event_id"
            :direction="selectedItem.direction"
            @changed="handleChanged"
            @stale="handleStale"
          />
          <NSpin v-else-if="selectedItem.episode_id" :show="detailLoading">
            <EpisodeDetail
              v-if="detail"
              :detail="detail"
              :workflow-state="selectedItem.state"
              @changed="handleChanged"
              @stale="handleStale"
            />
          </NSpin>
          <div v-else class="trade-records-page__done-decision">
            <NAlert type="info">
              已记录为未执行。当前 API 未提供独立 Decision read contract，本页不猜测或缓存原因明细。
            </NAlert>
            <DispositionCorrectionForm
              v-if="selectedItem.decision_id"
              :decision-id="selectedItem.decision_id"
              :event-id="selectedItem.event_id"
              :direction="selectedItem.direction"
              @changed="handleChanged"
              @stale="handleStale"
            />
          </div>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.trade-records-page { display: grid; gap: 16px; min-width: 0; }.trade-records-page__intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }.trade-records-page__intro h1, .trade-records-page__intro p { margin: 0; }.trade-records-page__intro p { margin-top: 6px; color: var(--gy-text-muted); }
.trade-records-page__filters { display: grid; grid-template-columns: minmax(140px, 1fr) 140px 120px repeat(2, minmax(150px, auto)) auto; align-items: end; gap: 10px; }.trade-records-page__filters label { display: grid; gap: 5px; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.trade-records-page__workspace { display: grid; grid-template-columns: minmax(280px, .75fr) minmax(0, 2fr); align-items: start; gap: 16px; }.trade-records-page__list { position: sticky; top: 0; }.trade-records-page__list :deep(.n-card__content) { display: grid; gap: 8px; }
.trade-records-page__item { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 11px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); color: var(--gy-text-primary); text-align: left; cursor: pointer; }.trade-records-page__item:hover, .trade-records-page__item--active { border-color: var(--gy-accent); background: var(--gy-accent-soft); }.trade-records-page__item span { display: grid; gap: 3px; }.trade-records-page__item small { color: var(--gy-text-muted); }
.trade-records-page__detail { min-width: 0; display: grid; gap: 14px; }.gy-native-input { width: 100%; height: 34px; box-sizing: border-box; padding: 0 8px; border: 1px solid var(--gy-border-strong); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: var(--gy-text-primary); }
.trade-records-page__done-decision { display: grid; gap: 14px; }
@media (max-width: 1180px) { .trade-records-page__filters { grid-template-columns: repeat(3, minmax(0, 1fr)); }.trade-records-page__workspace { grid-template-columns: 260px minmax(0, 1fr); } }
@media (max-width: 820px) { .trade-records-page__filters, .trade-records-page__workspace { grid-template-columns: 1fr; }.trade-records-page__list { position: static; }.trade-records-page__intro { flex-direction: column; } }
</style>
