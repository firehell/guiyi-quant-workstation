<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import {
  NAlert, NButton, NCard, NDescriptions, NDescriptionsItem, NForm, NFormItem,
  NInput, NModal, NSelect, NTable, NTag,
} from 'naive-ui'
import {
  correctDisposition,
  ExecutionReviewApiError,
  executionReviewErrorMessage,
  refreshDispositionCorrectionState,
  replaceExecutionTimeline,
  updateDecision,
  updateExecution,
} from '@/api/executionReview'
import ExecutionForm from '@/components/execution-review/ExecutionForm.vue'
import TradeReviewForm from '@/components/execution-review/TradeReviewForm.vue'
import type {
  Decision,
  EpisodeDetailResponse,
  Execution,
  ExecutionReviewState,
  ExecutionType,
  TimelineExecutionRequest,
} from '@/types/executionReview'
import { EXECUTION_REASONS, NOT_EXECUTED_REASONS, STOP_BASES, timelineForDisplay } from '@/utils/executionReview'

const props = defineProps<{ detail: EpisodeDetailResponse; workflowState: ExecutionReviewState }>()
const emit = defineEmits<{
  changed: [outcome: { state: ExecutionReviewState; eventId: number; episodeId: number | null; message: string }]
  stale: [eventId?: number]
}>()

const error = ref('')
const saving = ref(false)
const executionModal = ref(false)
const decisionModal = ref(false)
const timelineModal = ref(false)
const dispositionModal = ref(false)
const editingExecutionId = ref<number | null>(null)
const editingDecisionId = ref<number | null>(null)
const editingDecisionEventId = ref<number | null>(null)
const executionDraft = reactive({ executed_at: '', price: '', note: '' })
const decisionDraft = reactive({
  first_viewed_at: null as string | null,
  decided_at: '', primary_not_execute_reason: null as string | null,
  secondary_not_execute_reasons: [] as string[], note: '', execution_reason_tags: [] as string[],
  planned_stop_price: null as string | null, stop_basis: null as string | null,
})
const dispositionDraft = reactive({ primary_reason: '', secondary_reasons: [] as string[], note: '' })
const timelineRows = ref<TimelineExecutionRequest[]>([])
const option = (value: string) => ({ label: value, value })
const displayTimeline = computed(() => timelineForDisplay(props.detail.executions, props.detail.episode))

function formatTime(value: string | null) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isFinite(parsed.getTime())
    ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false, dateStyle: 'short', timeStyle: 'short' }).format(parsed)
    : value
}

function openExecutionEdit(row: Execution) {
  editingExecutionId.value = row.id
  executionDraft.executed_at = toLocalInput(row.executed_at)
  executionDraft.price = row.price
  executionDraft.note = row.note || ''
  executionModal.value = true
}

async function saveExecutionEdit() {
  if (editingExecutionId.value === null) return
  await mutate(async () => {
    await updateExecution(editingExecutionId.value!, {
      executed_at: new Date(executionDraft.executed_at).toISOString(),
      price: executionDraft.price,
      note: executionDraft.note || null,
    })
    executionModal.value = false
    changed(props.workflowState, '执行时间、价格与备注已更新')
  })
}

function openDecisionEdit(row: Decision) {
  editingDecisionId.value = row.id
  editingDecisionEventId.value = row.alert_event_id
  decisionDraft.first_viewed_at = row.first_viewed_at
  decisionDraft.decided_at = toLocalInput(row.decided_at)
  decisionDraft.primary_not_execute_reason = row.primary_not_execute_reason
  decisionDraft.secondary_not_execute_reasons = [...row.secondary_not_execute_reasons]
  decisionDraft.note = row.note || ''
  decisionDraft.execution_reason_tags = [...row.execution_reason_tags]
  decisionDraft.planned_stop_price = row.planned_stop_price
  decisionDraft.stop_basis = row.stop_basis
  decisionModal.value = true
}

async function saveDecisionEdit() {
  if (editingDecisionId.value === null) return
  await mutate(async () => {
    await updateDecision(editingDecisionId.value!, {
      first_viewed_at: decisionDraft.first_viewed_at,
      decided_at: new Date(decisionDraft.decided_at).toISOString(),
      primary_not_execute_reason: decisionDraft.primary_not_execute_reason,
      secondary_not_execute_reasons: decisionDraft.secondary_not_execute_reasons,
      note: decisionDraft.note || null,
      execution_reason_tags: decisionDraft.execution_reason_tags,
      planned_stop_price: decisionDraft.planned_stop_price || null,
      stop_basis: decisionDraft.planned_stop_price ? decisionDraft.stop_basis : null,
    })
    decisionModal.value = false
    changed(props.workflowState, 'Decision context 已更新')
  })
}

function openTimelineCorrection() {
  timelineRows.value = props.detail.executions.map((row) => ({
    execution_id: row.id,
    execution_type: row.execution_type,
    executed_at: toLocalInput(row.executed_at),
    price: row.price,
    quantity: row.quantity,
    note: row.note,
  }))
  timelineModal.value = true
}

function addTimelineClose() {
  timelineRows.value.push({
    execution_type: 'CLOSE', executed_at: '', price: '',
    quantity: props.detail.position.remaining_quantity, note: null,
  })
}

function moveTimelineRow(index: number, offset: -1 | 1) {
  const target = index + offset
  if (target < 0 || target >= timelineRows.value.length) return
  const rows = [...timelineRows.value]
  ;[rows[index], rows[target]] = [rows[target], rows[index]]
  timelineRows.value = rows
}

function removeTimelineRow(index: number) {
  if (isTriggeredTimelineRow(timelineRows.value[index])) return
  timelineRows.value = timelineRows.value.filter((_, rowIndex) => rowIndex !== index)
}

function isTriggeredTimelineRow(row: TimelineExecutionRequest) {
  if (!row.execution_id) return false
  return props.detail.executions.some((existing) => (
    existing.id === row.execution_id && existing.trigger_decision_id !== null
  ))
}

async function saveTimeline() {
  const items = timelineRows.value.map((row) => ({
    ...row,
    executed_at: new Date(row.executed_at).toISOString(),
  }))
  await mutate(async () => {
    const response = await replaceExecutionTimeline(props.detail.episode.id, { items })
    timelineModal.value = false
    changed(response.episode.closed_at ? 'pending_review' : 'open', '完整执行时间线已纠正')
  })
}

function openDispositionCorrection() {
  decisionModal.value = false
  dispositionDraft.primary_reason = ''
  dispositionDraft.secondary_reasons = []
  dispositionDraft.note = ''
  dispositionModal.value = true
}

async function saveDispositionCorrection() {
  if (editingDecisionId.value === null || !dispositionDraft.primary_reason) {
    error.value = '请选择纠正后的未执行主要原因'
    return
  }
  await mutate(async () => {
    const response = await correctDisposition(editingDecisionId.value!, {
      target_disposition: 'NOT_EXECUTED',
      primary_reason: dispositionDraft.primary_reason,
      secondary_reasons: dispositionDraft.secondary_reasons,
      note: dispositionDraft.note || null,
    })
    const eventState = await refreshDispositionCorrectionState(response)
    dispositionModal.value = false
    changed(
      eventState.state,
      '处理结果已纠正',
      eventState.episode_id,
      eventState.event_id,
    )
  }, editingDecisionEventId.value ?? props.detail.origin_event.id)
}

async function mutate(
  operation: () => Promise<void>,
  staleEventId: number = props.detail.origin_event.id,
) {
  saving.value = true
  error.value = ''
  try { await operation() }
  catch (reason) {
    error.value = executionReviewErrorMessage(reason)
    if (reason instanceof ExecutionReviewApiError && reason.httpStatus === 409) emit('stale', staleEventId)
  } finally { saving.value = false }
}

function changed(
  state: ExecutionReviewState,
  message: string,
  episodeId: number | null = props.detail.episode.id,
  eventId: number = props.detail.origin_event.id,
) {
  emit('changed', {
    state,
    eventId,
    episodeId,
    message,
  })
}

function handleChildChanged(outcome: { state: 'open' | 'pending_review' | 'done'; episodeId: number; message: string }) {
  changed(outcome.state, outcome.message)
}

function toLocalInput(value: string) {
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function setTimelineType(index: number, value: ExecutionType) {
  timelineRows.value[index].execution_type = value
}
</script>

<template>
  <div class="episode-detail" data-testid="episode-detail">
    <NAlert v-if="error" type="warning">{{ error }}</NAlert>
    <NCard size="small">
      <template #header><div class="episode-detail__title"><strong>手工执行记录</strong><NTag>{{ detail.episode.direction }} · {{ detail.episode.contract }}</NTag></div></template>
      <NDescriptions :column="2" label-placement="left" size="small">
        <NDescriptionsItem label="Episode">#{{ detail.episode.id }}</NDescriptionsItem>
        <NDescriptionsItem label="状态">{{ detail.episode.closed_at ? '已结束' : '进行中' }}</NDescriptionsItem>
        <NDescriptionsItem label="剩余手数">{{ detail.position.remaining_quantity }}</NDescriptionsItem>
        <NDescriptionsItem label="平均成本">{{ detail.position.average_cost ?? '—' }}</NDescriptionsItem>
        <NDescriptionsItem label="Realized points">{{ detail.position.realized_points }}</NDescriptionsItem>
        <NDescriptionsItem label="Estimated Gross PnL / 估算毛盈亏">
          <template v-if="detail.position.estimated_gross_pnl !== null">{{ detail.position.estimated_gross_pnl }}</template>
          <span v-else-if="detail.episode.contract_multiplier_snapshot === null" class="episode-detail__pnl-unavailable">
            <strong>人民币估算不可用</strong>
            <small>该品种 multiplier 尚未核验</small>
          </span>
          <template v-else>—</template>
        </NDescriptionsItem>
      </NDescriptions>
      <NAlert v-if="detail.episode.close_reason === 'DOMINANT_ROLL'" type="warning" class="episode-detail__roll">
        <strong>主力换月自动结束</strong>
        <span>系统估算 · 非真实成交</span>
        <span>参考退出价 {{ detail.episode.roll_reference_exit_price ?? '—' }}</span>
        <span>参考时间 {{ formatTime(detail.episode.roll_reference_bar_end) }}</span>
      </NAlert>
    </NCard>

    <NCard size="small" title="Signal-triggered lineage">
      <div class="episode-detail__lineage">
        <article v-for="row in detail.decisions" :key="row.id">
          <strong>Decision #{{ row.id }} · {{ row.disposition }}</strong>
          <span>Event #{{ row.alert_event_id }} · {{ formatTime(row.decided_at) }}</span>
          <span>{{ row.execution_reason_tags.join(', ') || row.primary_not_execute_reason || '—' }}</span>
          <NButton size="tiny" secondary @click="openDecisionEdit(row)">编辑 Decision context</NButton>
        </article>
      </div>
    </NCard>

    <NCard size="small">
      <template #header><div class="episode-detail__title"><strong>Execution timeline</strong><NButton size="small" secondary @click="openTimelineCorrection">纠正执行记录</NButton></div></template>
      <div data-testid="execution-timeline" class="episode-detail__table-wrap">
        <NTable size="small" :single-line="false">
          <thead><tr><th>#</th><th>类型</th><th>时间</th><th>价格</th><th>手数</th><th>Lineage</th><th></th></tr></thead>
          <tbody><tr v-for="row in displayTimeline" :key="row.id">
            <td>{{ row.sequence_no }}</td><td>{{ row.execution_type }}</td><td>{{ formatTime(row.executed_at) }}</td>
            <td>{{ row.price }}</td><td>{{ row.quantity }}</td><td>{{ row.trigger_decision_id ? `Decision #${row.trigger_decision_id}` : 'Manual' }}</td>
            <td>
              <NButton v-if="detail.episode.close_reason !== 'DOMINANT_ROLL'" size="tiny" quaternary @click="openExecutionEdit(row)">编辑</NButton>
              <span v-else>使用完整时间线纠错</span>
            </td>
          </tr></tbody>
        </NTable>
      </div>
    </NCard>

    <ExecutionForm
      v-if="!detail.episode.closed_at"
      :episode-id="detail.episode.id"
      :remaining-quantity="detail.position.remaining_quantity"
      @changed="handleChildChanged"
      @stale="emit('stale', detail.origin_event.id)"
    />
    <TradeReviewForm
      v-if="workflowState === 'pending_review' || detail.review"
      :episode-id="detail.episode.id"
      :review="detail.review"
      @changed="handleChildChanged"
      @stale="emit('stale', detail.origin_event.id)"
    />

    <NModal v-model:show="executionModal" preset="card" title="编辑执行时间 / 价格 / 备注" class="episode-detail__modal">
      <NForm label-placement="top">
        <NFormItem label="时间"><input v-model="executionDraft.executed_at" class="gy-native-input" type="datetime-local"></NFormItem>
        <NFormItem label="价格"><input v-model="executionDraft.price" class="gy-native-input" inputmode="decimal"></NFormItem>
        <NFormItem label="备注"><NInput v-model:value="executionDraft.note" /></NFormItem>
      </NForm>
      <NButton type="primary" :loading="saving" @click="saveExecutionEdit">保存修改</NButton>
    </NModal>

    <NModal v-model:show="decisionModal" preset="card" title="编辑 Decision context" class="episode-detail__modal">
      <NForm label-placement="top">
        <NFormItem label="决策时间"><input v-model="decisionDraft.decided_at" class="gy-native-input" type="datetime-local"></NFormItem>
        <NFormItem label="Execution reasons"><NSelect v-model:value="decisionDraft.execution_reason_tags" multiple :options="EXECUTION_REASONS.map(option)" /></NFormItem>
        <NFormItem label="计划止损价"><input v-model="decisionDraft.planned_stop_price" class="gy-native-input" inputmode="decimal"></NFormItem>
        <NFormItem label="止损依据"><NSelect v-model:value="decisionDraft.stop_basis" clearable :options="STOP_BASES.map(option)" /></NFormItem>
        <NFormItem label="备注"><NInput v-model:value="decisionDraft.note" /></NFormItem>
      </NForm>
      <div class="episode-detail__modal-actions">
        <NButton type="primary" :loading="saving" @click="saveDecisionEdit">保存修改</NButton>
        <NButton tertiary type="warning" @click="openDispositionCorrection">纠正处理结果</NButton>
      </div>
    </NModal>

    <NModal v-model:show="dispositionModal" preset="card" title="次级纠错：改为未执行" class="episode-detail__modal">
      <NAlert type="warning">该操作由后端验证完整 lineage，不会在前端删除事实。</NAlert>
      <NForm label-placement="top">
        <NFormItem label="Primary reason"><NSelect v-model:value="dispositionDraft.primary_reason" data-testid="disposition-primary" :options="NOT_EXECUTED_REASONS.map(option)" /></NFormItem>
        <NFormItem label="Secondary reasons"><NSelect v-model:value="dispositionDraft.secondary_reasons" multiple :options="NOT_EXECUTED_REASONS.map(option)" /></NFormItem>
        <NFormItem label="备注"><NInput v-model:value="dispositionDraft.note" /></NFormItem>
      </NForm>
      <NButton type="warning" :loading="saving" @click="saveDispositionCorrection">提交处理结果纠错</NButton>
    </NModal>

    <NModal v-model:show="timelineModal" preset="card" title="纠正完整执行时间线" class="episode-detail__timeline-modal">
      <NAlert type="warning">数量、类型和顺序一次整体提交；后端是 position topology 的唯一权威。</NAlert>
      <div class="episode-detail__timeline-editor">
        <div v-for="(row, index) in timelineRows" :key="row.execution_id ?? `new-${index}`" class="episode-detail__timeline-row">
          <NSelect :value="row.execution_type" :options="['OPEN', 'ADD', 'REDUCE', 'CLOSE'].map(option)" @update:value="(value) => setTimelineType(index, value)" />
          <input v-model="row.executed_at" :data-testid="`timeline-time-${index}`" class="gy-native-input" type="datetime-local">
          <input v-model="row.price" :data-testid="`timeline-price-${index}`" class="gy-native-input" inputmode="decimal" placeholder="价格">
          <input v-model.number="row.quantity" :data-testid="`timeline-quantity-${index}`" class="gy-native-input" min="1" step="1" type="number" placeholder="手数">
          <NInput v-model:value="row.note" placeholder="备注" />
          <div class="episode-detail__row-actions">
            <NButton size="tiny" :disabled="index === 0" @click="moveTimelineRow(index, -1)">上移</NButton>
            <NButton size="tiny" :disabled="index === timelineRows.length - 1" @click="moveTimelineRow(index, 1)">下移</NButton>
            <NButton size="tiny" type="error" :disabled="isTriggeredTimelineRow(row)" @click="removeTimelineRow(index)">删除</NButton>
          </div>
        </div>
      </div>
      <div class="episode-detail__modal-actions">
        <NButton secondary @click="addTimelineClose">{{ detail.episode.close_reason === 'DOMINANT_ROLL' ? '添加真实 CLOSE' : '添加 CLOSE' }}</NButton>
        <NButton type="primary" :loading="saving" @click="saveTimeline">提交完整执行时间线</NButton>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.episode-detail { display: grid; gap: 14px; }.episode-detail__title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.episode-detail__roll { margin-top: 14px; }.episode-detail__roll :deep(.n-alert-body__content) { display: flex; flex-wrap: wrap; gap: 8px 14px; }
.episode-detail__pnl-unavailable { display: grid; gap: 2px; }.episode-detail__pnl-unavailable small { color: var(--gy-text-secondary); }
.episode-detail__lineage { display: grid; gap: 8px; }.episode-detail__lineage article { display: grid; grid-template-columns: 1.2fr 1fr 1.5fr auto; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); font-size: var(--gy-font-size-sm); }
.episode-detail__table-wrap { overflow-x: auto; }.episode-detail__modal { width: min(560px, calc(100vw - 32px)); }.episode-detail__timeline-modal { width: min(1040px, calc(100vw - 32px)); }
.episode-detail__timeline-editor { display: grid; gap: 8px; margin: 14px 0; }.episode-detail__timeline-row { display: grid; grid-template-columns: 110px 170px 1fr 90px 1fr auto; gap: 8px; }.episode-detail__row-actions { display: flex; align-items: center; gap: 4px; }
.episode-detail__modal-actions { display: flex; justify-content: space-between; gap: 10px; margin-top: 12px; }.gy-native-input { width: 100%; height: 34px; box-sizing: border-box; padding: 0 10px; border: 1px solid var(--gy-border-strong); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: var(--gy-text-primary); }
@media (max-width: 900px) { .episode-detail__lineage article { grid-template-columns: 1fr; }.episode-detail__timeline-row { grid-template-columns: 1fr 1fr; } }
@media (max-width: 600px) { .episode-detail__timeline-row { grid-template-columns: 1fr; } }
</style>
