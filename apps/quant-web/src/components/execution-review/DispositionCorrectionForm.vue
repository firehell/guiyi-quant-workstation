<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NInput, NSelect, NTag } from 'naive-ui'
import {
  correctDisposition,
  ExecutionReviewApiError,
  executionReviewErrorMessage,
  refreshDispositionCorrectionState,
} from '@/api/executionReview'
import type { Direction, ExecutionReviewState } from '@/types/executionReview'
import {
  buildExecutedDispositionCorrectionRequest,
  EXECUTION_REASONS,
  STOP_BASES,
  validateExecutedDraft,
} from '@/utils/executionReview'

const props = defineProps<{ decisionId: number; eventId: number; direction: Direction }>()
const emit = defineEmits<{
  changed: [outcome: {
    state: ExecutionReviewState
    eventId: number
    episodeId: number | null
    message: string
  }]
  stale: [eventId: number]
}>()

const expanded = ref(false)
const saving = ref(false)
const error = ref('')
const draft = reactive({
  executed_at: '',
  price: '',
  quantity: null as number | null,
  execution_reason_tags: [] as string[],
  planned_stop_price: null as string | null,
  stop_basis: null as string | null,
  note: '',
})
const option = (value: string) => ({ label: value, value })

async function submitCorrection() {
  const errors = validateExecutedDraft(draft)
  if (errors.length) {
    error.value = errors[0]
    return
  }
  saving.value = true
  error.value = ''
  try {
    const response = await correctDisposition(
      props.decisionId,
      buildExecutedDispositionCorrectionRequest({
        executed_at: new Date(draft.executed_at).toISOString(),
        price: draft.price,
        quantity: draft.quantity!,
        execution_reason_tags: draft.execution_reason_tags,
        planned_stop_price: draft.planned_stop_price || null,
        stop_basis: draft.planned_stop_price ? draft.stop_basis : null,
        note: draft.note || null,
      }),
    )
    const eventState = await refreshDispositionCorrectionState(response)
    const message = response.execution?.execution_type === 'ADD'
      ? '处理结果已纠正，已记录为同方向加仓'
      : response.execution?.execution_type === 'OPEN'
        ? '处理结果已纠正，已记录开仓'
        : '处理结果已纠正'
    emit('changed', {
      state: eventState.state,
      eventId: eventState.event_id,
      episodeId: eventState.episode_id,
      message,
    })
  } catch (reason) {
    error.value = executionReviewErrorMessage(reason)
    if (reason instanceof ExecutionReviewApiError && reason.httpStatus === 409) emit('stale', props.eventId)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="disposition-correction" data-testid="disposition-correction-form">
    <div class="disposition-correction__heading">
      <div>
        <strong>次级纠错</strong>
        <p>只补录实际执行事实；OPEN / ADD 与最终状态均由后端决定。</p>
      </div>
      <NTag :type="direction === 'LONG' ? 'error' : 'success'">方向 {{ direction }}（只读）</NTag>
    </div>
    <NButton size="small" tertiary type="warning" @click="expanded = !expanded">纠错：改为已执行</NButton>
    <template v-if="expanded">
      <NAlert v-if="error" type="warning">{{ error }}</NAlert>
      <NForm label-placement="top" class="disposition-correction__grid">
        <NFormItem label="成交时间（必填）">
          <input v-model="draft.executed_at" data-testid="correction-executed-at" class="gy-native-input" type="datetime-local">
        </NFormItem>
        <NFormItem label="成交价（必填）">
          <input v-model="draft.price" data-testid="correction-price" class="gy-native-input" inputmode="decimal">
        </NFormItem>
        <NFormItem label="手数（必填）">
          <input v-model.number="draft.quantity" data-testid="correction-quantity" class="gy-native-input" min="1" step="1" type="number">
        </NFormItem>
        <NFormItem label="Execution reasons（至少一个）">
          <NSelect v-model:value="draft.execution_reason_tags" data-testid="correction-execution-reasons" multiple :options="EXECUTION_REASONS.map(option)" />
        </NFormItem>
        <NFormItem label="计划止损价">
          <input v-model="draft.planned_stop_price" class="gy-native-input" inputmode="decimal">
        </NFormItem>
        <NFormItem label="止损依据">
          <NSelect v-model:value="draft.stop_basis" clearable :options="STOP_BASES.map(option)" />
        </NFormItem>
        <NFormItem label="备注" class="disposition-correction__wide">
          <NInput v-model:value="draft.note" type="textarea" />
        </NFormItem>
        <div class="disposition-correction__wide">
          <NButton type="warning" :loading="saving" @click="submitCorrection">提交处理结果纠错</NButton>
        </div>
      </NForm>
    </template>
  </section>
</template>

<style scoped>
.disposition-correction { display: grid; gap: 12px; padding: 14px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); }
.disposition-correction__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.disposition-correction__heading p { margin: 4px 0 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.disposition-correction__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 14px; }
.disposition-correction__wide { grid-column: 1 / -1; }
.gy-native-input { width: 100%; height: 34px; box-sizing: border-box; padding: 0 10px; border: 1px solid var(--gy-border-strong); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: var(--gy-text-primary); }
@media (max-width: 760px) { .disposition-correction__heading { flex-direction: column; }.disposition-correction__grid { grid-template-columns: 1fr; }.disposition-correction__wide { grid-column: auto; } }
</style>
