<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NDescriptions, NDescriptionsItem, NTag } from 'naive-ui'
import type { ReviewFoundationContext } from '@/types/reviewFoundation'
import { foundationFieldLabel } from '@/utils/reviewFoundation'
import type { FoundationField } from '@/types/reviewFoundation'

const props = defineProps<{
  context: ReviewFoundationContext | null
}>()

const rows = computed(() => {
  const ctx = props.context
  if (!ctx) return []
  return [
    { key: 'strategy_code', label: '策略', field: ctx.strategy_code },
    { key: 'strategy_version', label: '版本', field: ctx.strategy_version },
    { key: 'indicator_policy_status', label: 'Indicator Policy', field: ctx.indicator_policy_status },
    { key: 'indicator_policy_summary', label: 'Policy Snapshot', field: ctx.indicator_policy_summary },
    { key: 'profile_id', label: 'Profile', field: ctx.profile_id },
    { key: 'binding_snapshot_present', label: 'Profile Binding', field: ctx.binding_snapshot_present },
    { key: 'signal_bar', label: 'Signal Bar', field: ctx.signal_bar },
    { key: 'next_bar_fill', label: 'Next Bar Fill', field: ctx.next_bar_fill },
    { key: 'cost_model', label: 'Cost Model', field: ctx.cost_model },
    { key: 'execution_timing', label: 'Execution Timing', field: ctx.execution_timing },
    { key: 'oos_window_id', label: 'OOS Window', field: ctx.oos_window_id },
    { key: 'walk_forward_fold_id', label: 'WF Fold', field: ctx.walk_forward_fold_id },
    { key: 'candidate_status', label: 'Candidate Status', field: ctx.candidate_status },
    { key: 'hard_reject_reason', label: 'Hard Reject', field: ctx.hard_reject_reason },
    { key: 'review_skip_status', label: 'Skip Status', field: ctx.review_skip_status },
    { key: 'lineage_status', label: 'Lineage', field: ctx.lineage_status },
  ]
})

const skipAlert = computed(() => {
  const field = props.context?.review_skip_status
  return field?.status === 'available' && field.value === 'SKIPPED_BY_FROZEN_HARD_REJECT'
})

const hardRejectAlert = computed(() => {
  const field = props.context?.hard_reject_reason
  return field?.status === 'available' && Boolean(field.value)
})

const lineageUnavailable = computed(() => props.context?.lineage_status.status === 'unavailable')

function tagType(field: FoundationField): 'default' | 'success' | 'warning' | 'error' {
  if (field.status === 'available') return 'success'
  if (field.status === 'warning') return 'warning'
  return 'error'
}
</script>

<template>
  <div class="review-foundation-panel">
    <div class="panel__header">
      <div>
        <h2>正式上下文</h2>
        <p>只读展示；缺失字段为 unavailable，不伪造</p>
      </div>
    </div>

    <NAlert v-if="!context" type="default" :bordered="false" style="margin-bottom: 8px">
      未选择复盘或报告上下文不可用
    </NAlert>
    <NAlert v-else-if="skipAlert" type="warning" :bordered="false" style="margin-bottom: 8px" title="SKIPPED_BY_FROZEN_HARD_REJECT">
      因冻结 hard reject 跳过后续验证步骤；不得用诊断翻盘。
    </NAlert>
    <NAlert v-else-if="hardRejectAlert" type="error" :bordered="false" style="margin-bottom: 8px" title="Hard Reject">
      {{ foundationFieldLabel(context.hard_reject_reason) }}
    </NAlert>
    <NAlert v-if="context && lineageUnavailable" type="warning" :bordered="false" style="margin-bottom: 8px" title="Lineage unavailable">
      {{ foundationFieldLabel(context.lineage_status) }}
    </NAlert>

    <NDescriptions v-if="context" label-placement="left" size="small" :column="1" bordered>
      <NDescriptionsItem v-for="row in rows" :key="row.key" :label="row.label">
        <NTag size="small" :type="tagType(row.field)" :bordered="false">{{ row.field.status }}</NTag>
        <span class="field-value">{{ foundationFieldLabel(row.field) }}</span>
      </NDescriptionsItem>
    </NDescriptions>
  </div>
</template>

<style scoped>
.review-foundation-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}
.panel__header h2 {
  margin: 0;
  font-size: 15px;
}
.panel__header p {
  margin: 2px 0 0;
  opacity: 0.7;
  font-size: 12px;
}
.field-value {
  margin-left: 8px;
  font-size: 12px;
  word-break: break-all;
}
</style>
