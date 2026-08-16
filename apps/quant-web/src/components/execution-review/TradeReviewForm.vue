<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NInput, NSelect } from 'naive-ui'
import { ExecutionReviewApiError, executionReviewErrorMessage, submitReview, updateReview } from '@/api/executionReview'
import type { Review, ReviewRequest } from '@/types/executionReview'
import {
  applyNeutralSelection,
  ENTRY_TAGS,
  EXIT_TAGS,
  HOLDING_TAGS,
  MARKET_CONTEXT_TAGS,
  PSYCHOLOGY_TAGS,
  SIGNAL_ADHERENCE,
  validateReviewDraft,
} from '@/utils/executionReview'

const props = defineProps<{ episodeId: number; review: Review | null }>()
const emit = defineEmits<{
  changed: [outcome: { state: 'done'; episodeId: number; message: string }]
  stale: []
}>()
const saving = ref(false)
const error = ref('')
const draft = reactive<ReviewRequest>(emptyDraft())
const option = (value: string) => ({ label: value, value })

watch(() => props.review, fillFromReview, { immediate: true })

function fillFromReview(value: Review | null) {
  Object.assign(draft, value ? {
    signal_execution_adherence: value.signal_execution_adherence,
    entry_tags: [...value.entry_tags], holding_tags: [...value.holding_tags],
    exit_tags: [...value.exit_tags], market_context_tags: [...value.market_context_tags],
    psychology_tags: [...value.psychology_tags], summary: value.summary,
  } : emptyDraft())
}

function updateGroup(
  key: 'entry_tags' | 'holding_tags' | 'exit_tags' | 'psychology_tags',
  values: string[],
  neutral: string,
) {
  const previous = draft[key]
  if (values.includes(neutral) && values.length > 1) {
    const selected = previous.includes(neutral)
      ? values.find((value) => value !== neutral && !previous.includes(value)) || values.at(-1)!
      : neutral
    draft[key] = applyNeutralSelection(previous, selected, neutral)
  } else {
    draft[key] = values
  }
}

async function submit() {
  const errors = validateReviewDraft(draft)
  if (errors.length) { error.value = errors[0]; return }
  saving.value = true
  error.value = ''
  try {
    if (props.review) await updateReview(props.review.id, draft)
    else await submitReview(props.episodeId, draft)
    emit('changed', { state: 'done', episodeId: props.episodeId, message: '复盘已保存' })
  } catch (reason) {
    error.value = executionReviewErrorMessage(reason)
    if (reason instanceof ExecutionReviewApiError && reason.httpStatus === 409) emit('stale')
  } finally {
    saving.value = false
  }
}

function emptyDraft(): ReviewRequest {
  return {
    signal_execution_adherence: '', entry_tags: [], holding_tags: [], exit_tags: [],
    market_context_tags: [], psychology_tags: [], summary: null,
  }
}
</script>

<template>
  <section class="trade-review-form" data-testid="trade-review-form">
    <div><h3>{{ review ? '编辑结构化复盘' : '结构化复盘' }}</h3><p>五组标签均为必选；不生成评分、胜率或 AI 结论。</p></div>
    <NAlert v-if="error" type="warning">{{ error }}</NAlert>
    <NForm label-placement="top" class="trade-review-form__grid">
      <NFormItem label="Signal execution adherence">
        <NSelect v-model:value="draft.signal_execution_adherence" data-testid="review-adherence" :options="SIGNAL_ADHERENCE.map(option)" />
      </NFormItem>
      <NFormItem label="Entry">
        <NSelect :value="draft.entry_tags" data-testid="review-entry" multiple :options="ENTRY_TAGS.map(option)" @update:value="(values) => updateGroup('entry_tags', values, 'REASONABLE')" />
      </NFormItem>
      <NFormItem label="Holding">
        <NSelect :value="draft.holding_tags" data-testid="review-holding" multiple :options="HOLDING_TAGS.map(option)" @update:value="(values) => updateGroup('holding_tags', values, 'NORMAL')" />
      </NFormItem>
      <NFormItem label="Exit / Risk">
        <NSelect :value="draft.exit_tags" data-testid="review-exit" multiple :options="EXIT_TAGS.map(option)" @update:value="(values) => updateGroup('exit_tags', values, 'NORMAL')" />
      </NFormItem>
      <NFormItem label="Market Context">
        <NSelect v-model:value="draft.market_context_tags" data-testid="review-market-context" multiple :options="MARKET_CONTEXT_TAGS.map(option)" />
      </NFormItem>
      <NFormItem label="Psychology">
        <NSelect :value="draft.psychology_tags" data-testid="review-psychology" multiple :options="PSYCHOLOGY_TAGS.map(option)" @update:value="(values) => updateGroup('psychology_tags', values, 'NONE')" />
      </NFormItem>
      <NFormItem label="总结" class="trade-review-form__wide"><NInput v-model:value="draft.summary" type="textarea" /></NFormItem>
    </NForm>
    <NButton type="primary" :loading="saving" @click="submit">{{ review ? '保存复盘修改' : '提交复盘' }}</NButton>
  </section>
</template>

<style scoped>
.trade-review-form { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); }
.trade-review-form h3, .trade-review-form p { margin: 0; }.trade-review-form p { margin-top: 4px; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.trade-review-form__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.trade-review-form__wide { grid-column: 1 / -1; }
@media (max-width: 760px) { .trade-review-form__grid { grid-template-columns: 1fr; }.trade-review-form__wide { grid-column: auto; } }
</style>
