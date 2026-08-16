<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NAlert, NButton, NButtonGroup, NForm, NFormItem, NInput, NSelect, NTag } from 'naive-ui'
import {
  ExecutionReviewApiError,
  executionReviewErrorMessage,
  recordExecuted,
  recordNotExecuted,
} from '@/api/executionReview'
import type { Direction, ExecutedRequest, NotExecutedRequest } from '@/types/executionReview'
import {
  EXECUTION_REASONS,
  NOT_EXECUTED_REASONS,
  STOP_BASES,
  validateExecutedDraft,
  validateNotExecutedDraft,
} from '@/utils/executionReview'

const props = defineProps<{ eventId: number; direction: Direction }>()
const emit = defineEmits<{
  changed: [outcome: { state: 'open' | 'done'; eventId: number; episodeId: number | null; message: string }]
  stale: []
}>()

const disposition = ref<'NOT_EXECUTED' | 'EXECUTED'>('NOT_EXECUTED')
const saving = ref(false)
const error = ref('')
const notExecuted = reactive({ primary_reason: '', secondary_reasons: [] as string[], note: '' })
const executed = reactive({
  executed_at: '', price: '', quantity: null as number | null,
  execution_reason_tags: [] as string[], planned_stop_price: null as string | null,
  stop_basis: null as string | null, note: '',
})

const option = (value: string) => ({ label: value, value })

async function submitNotExecuted() {
  const errors = validateNotExecutedDraft(notExecuted)
  if (errors.length) return setError(errors[0])
  const body: NotExecutedRequest = {
    primary_reason: notExecuted.primary_reason,
    secondary_reasons: notExecuted.secondary_reasons,
    note: notExecuted.note || null,
  }
  await mutate(async () => {
    await recordNotExecuted(props.eventId, body)
    emit('changed', { state: 'done', eventId: props.eventId, episodeId: null, message: '已记录为未执行' })
  })
}

async function submitExecuted() {
  const errors = validateExecutedDraft(executed)
  if (errors.length) return setError(errors[0])
  const body: ExecutedRequest = {
    executed_at: toIso(executed.executed_at),
    price: executed.price,
    quantity: executed.quantity!,
    execution_reason_tags: executed.execution_reason_tags,
    planned_stop_price: executed.planned_stop_price || null,
    stop_basis: executed.planned_stop_price ? executed.stop_basis : null,
    note: executed.note || null,
  }
  await mutate(async () => {
    const response = await recordExecuted(props.eventId, body)
    emit('changed', {
      state: 'open',
      eventId: props.eventId,
      episodeId: response.episode.id,
      message: response.execution.execution_type === 'ADD' ? '已记录为同方向加仓' : '已记录开仓',
    })
  })
}

async function mutate(operation: () => Promise<void>) {
  saving.value = true
  error.value = ''
  try {
    await operation()
  } catch (reason) {
    error.value = executionReviewErrorMessage(reason)
    if (reason instanceof ExecutionReviewApiError && reason.httpStatus === 409) emit('stale')
  } finally {
    saving.value = false
  }
}

function setError(message: string) { error.value = message }

function toIso(value: string) {
  return new Date(value).toISOString()
}
</script>

<template>
  <section class="decision-form" data-testid="decision-form">
    <div class="decision-form__heading">
      <div><h3>人工决策</h3><p>仅记录手工执行事实，最终 OPEN / ADD 由后端返回。</p></div>
      <NTag :type="direction === 'LONG' ? 'error' : 'success'">方向 {{ direction }}（只读）</NTag>
    </div>
    <NButtonGroup>
      <NButton :type="disposition === 'NOT_EXECUTED' ? 'primary' : 'default'" @click="disposition = 'NOT_EXECUTED'">未执行</NButton>
      <NButton :type="disposition === 'EXECUTED' ? 'primary' : 'default'" @click="disposition = 'EXECUTED'">已执行</NButton>
    </NButtonGroup>
    <NAlert v-if="error" type="warning" class="decision-form__error">{{ error }}</NAlert>
    <NForm v-if="disposition === 'NOT_EXECUTED'" label-placement="top" class="decision-form__grid">
      <NFormItem label="Primary reason（必填）">
        <NSelect v-model:value="notExecuted.primary_reason" data-testid="not-executed-primary" :options="NOT_EXECUTED_REASONS.map(option)" />
      </NFormItem>
      <NFormItem label="Secondary reasons">
        <NSelect v-model:value="notExecuted.secondary_reasons" multiple :options="NOT_EXECUTED_REASONS.map(option)" />
      </NFormItem>
      <NFormItem label="备注" class="decision-form__wide"><NInput v-model:value="notExecuted.note" type="textarea" /></NFormItem>
      <div class="decision-form__wide"><NButton type="primary" :loading="saving" @click="submitNotExecuted">记录未执行</NButton></div>
    </NForm>
    <NForm v-else label-placement="top" class="decision-form__grid">
      <NFormItem label="成交时间（必填）"><input v-model="executed.executed_at" data-testid="decision-executed-at" class="gy-native-input" type="datetime-local"></NFormItem>
      <NFormItem label="成交价（必填）"><input v-model="executed.price" data-testid="decision-price" class="gy-native-input" inputmode="decimal"></NFormItem>
      <NFormItem label="手数（必填）"><input v-model.number="executed.quantity" data-testid="decision-quantity" class="gy-native-input" min="1" step="1" type="number"></NFormItem>
      <NFormItem label="Execution reasons（至少一个）"><NSelect v-model:value="executed.execution_reason_tags" data-testid="decision-execution-reasons" multiple :options="EXECUTION_REASONS.map(option)" /></NFormItem>
      <NFormItem label="计划止损价"><input v-model="executed.planned_stop_price" class="gy-native-input" inputmode="decimal"></NFormItem>
      <NFormItem label="止损依据"><NSelect v-model:value="executed.stop_basis" clearable :options="STOP_BASES.map(option)" /></NFormItem>
      <NFormItem label="备注" class="decision-form__wide"><NInput v-model:value="executed.note" type="textarea" /></NFormItem>
      <div class="decision-form__wide"><NButton type="primary" :loading="saving" @click="submitExecuted">记录实际执行</NButton></div>
    </NForm>
  </section>
</template>

<style scoped>
.decision-form { display: grid; gap: 14px; padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); }
.decision-form__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.decision-form h3, .decision-form p { margin: 0; }.decision-form p { margin-top: 4px; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.decision-form__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 14px; }
.decision-form__wide { grid-column: 1 / -1; }.decision-form__error { margin: 0; }
.gy-native-input { width: 100%; height: 34px; box-sizing: border-box; padding: 0 10px; border: 1px solid var(--gy-border-strong); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: var(--gy-text-primary); }
@media (max-width: 760px) { .decision-form__heading { flex-direction: column; }.decision-form__grid { grid-template-columns: 1fr; }.decision-form__wide { grid-column: auto; } }
</style>
