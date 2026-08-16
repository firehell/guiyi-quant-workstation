<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { NAlert, NButton, NButtonGroup, NForm, NFormItem, NInput } from 'naive-ui'
import { appendExecution, ExecutionReviewApiError, executionReviewErrorMessage } from '@/api/executionReview'
import type { ManualExecutionType } from '@/types/executionReview'
import { defaultExecutionQuantity, isPositiveDecimal, MANUAL_EXECUTION_TYPES } from '@/utils/executionReview'

const props = defineProps<{ episodeId: number; remainingQuantity: number }>()
const emit = defineEmits<{
  changed: [outcome: { state: 'open' | 'pending_review'; episodeId: number; message: string }]
  stale: []
}>()

const executionType = ref<ManualExecutionType>('ADD')
const draft = reactive({ executed_at: '', price: '', quantity: null as number | null, note: '' })
const saving = ref(false)
const error = ref('')

watch(executionType, (value) => {
  draft.quantity = defaultExecutionQuantity(value, props.remainingQuantity, draft.quantity)
})
watch(() => props.remainingQuantity, (value) => {
  if (executionType.value === 'CLOSE') draft.quantity = value
})

async function submit() {
  if (!draft.executed_at) return setError('请填写执行时间')
  if (!isPositiveDecimal(draft.price)) return setError('请填写有效执行价')
  if (!Number.isInteger(draft.quantity) || (draft.quantity ?? 0) <= 0) return setError('请填写有效手数')
  if (executionType.value === 'REDUCE' && draft.quantity! >= props.remainingQuantity) return setError('REDUCE 手数必须小于当前剩余手数')
  saving.value = true
  error.value = ''
  try {
    const response = await appendExecution(props.episodeId, {
      execution_type: executionType.value,
      executed_at: new Date(draft.executed_at).toISOString(),
      price: draft.price,
      quantity: draft.quantity!,
      note: draft.note || null,
    })
    emit('changed', {
      state: response.episode.closed_at ? 'pending_review' : 'open',
      episodeId: response.episode.id,
      message: executionType.value === 'CLOSE' ? '实际结束记录已保存' : `${executionType.value} 记录已保存`,
    })
  } catch (reason) {
    error.value = executionReviewErrorMessage(reason)
    if (reason instanceof ExecutionReviewApiError && reason.httpStatus === 409) emit('stale')
  } finally {
    saving.value = false
  }
}

function choose(value: ManualExecutionType) {
  executionType.value = value
}
function setError(message: string) { error.value = message }
</script>

<template>
  <section class="execution-form" data-testid="execution-form">
    <div><h3>新增手工执行记录</h3><p>只记录 ADD / REDUCE / CLOSE；后端校验完整仓位 topology。</p></div>
    <NButtonGroup>
      <NButton v-for="value in MANUAL_EXECUTION_TYPES" :key="value" :type="executionType === value ? 'primary' : 'default'" @click="choose(value)">{{ value }}</NButton>
    </NButtonGroup>
    <NAlert v-if="error" type="warning">{{ error }}</NAlert>
    <NForm label-placement="top" class="execution-form__grid">
      <NFormItem label="执行时间"><input v-model="draft.executed_at" data-testid="execution-at" class="gy-native-input" type="datetime-local"></NFormItem>
      <NFormItem label="执行价"><input v-model="draft.price" data-testid="execution-price" class="gy-native-input" inputmode="decimal"></NFormItem>
      <NFormItem :label="executionType === 'REDUCE' ? `手数（小于 ${remainingQuantity}）` : '手数'">
        <input v-model.number="draft.quantity" data-testid="execution-quantity" class="gy-native-input" min="1" step="1" type="number">
      </NFormItem>
      <NFormItem label="备注"><NInput v-model:value="draft.note" /></NFormItem>
    </NForm>
    <NButton type="primary" :loading="saving" @click="submit">保存执行记录</NButton>
  </section>
</template>

<style scoped>
.execution-form { display: grid; gap: 12px; padding: 14px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-app); }
.execution-form h3, .execution-form p { margin: 0; }.execution-form p { margin-top: 4px; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.execution-form__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.gy-native-input { width: 100%; height: 34px; box-sizing: border-box; padding: 0 10px; border: 1px solid var(--gy-border-strong); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: var(--gy-text-primary); }
@media (max-width: 760px) { .execution-form__grid { grid-template-columns: 1fr; } }
</style>
