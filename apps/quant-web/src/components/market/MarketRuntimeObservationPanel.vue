<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NDescriptions, NDescriptionsItem, NTag } from 'naive-ui'
import type { MarketRuntimeObservationContext, ObservationField } from '@/types/marketRuntimeObservation'
import { observationFieldLabel } from '@/utils/marketRuntimeObservation'
import { runtimeStatusType } from '@/utils/runtimeHealth'

const props = defineProps<{
  context: MarketRuntimeObservationContext | null
}>()

const rows = computed(() => {
  const ctx = props.context
  if (!ctx) return []
  return [
    { key: 'source_badge', label: 'Source', field: ctx.source_badge },
    { key: 'data_mode', label: 'Data Mode', field: ctx.data_mode },
    { key: 'actual_contract', label: 'Actual Contract', field: ctx.actual_contract },
    { key: 'latest_live_1m', label: 'Latest Live 1m', field: ctx.latest_live_1m },
    { key: 'confirmed_count', label: 'Confirmed', field: ctx.confirmed_count },
    { key: 'partial_count', label: 'Partial', field: ctx.partial_count },
    { key: 'runtime_health_status', label: 'Runtime Health', field: ctx.runtime_health_status },
    { key: 'checkpoint_status', label: 'Checkpoint', field: ctx.checkpoint_status },
    { key: 'checkpoint_lag_seconds', label: 'Checkpoint Lag', field: ctx.checkpoint_lag_seconds },
    { key: 'latency_ms', label: 'Latency', field: ctx.latency_ms },
    { key: 'archived_trading_day', label: 'Archived Day', field: ctx.archived_trading_day },
    { key: 'active_data_version', label: 'Data Version', field: ctx.active_data_version },
    { key: 'quality_status', label: 'Quality', field: ctx.quality_status },
    { key: 'profile_id', label: 'Profile', field: ctx.profile_id },
  ]
})

const mixWarning = computed(() => props.context?.data_mode.status === 'warning')
const notHealthy = computed(() => {
  const status = props.context?.runtime_health_status.value
  return status === 'degraded' || status === 'failed'
})

function rowTagType(field: ObservationField<unknown>) {
  if (typeof field.value === 'string' && (field.value === 'ok' || field.value === 'degraded' || field.value === 'failed')) {
    return runtimeStatusType(field.value)
  }
  if (field.status === 'available') return 'success' as const
  if (field.status === 'warning') return 'warning' as const
  return 'error' as const
}
</script>

<template>
  <div class="market-runtime-observation-panel">
    <div class="panel-head">
      <strong>Runtime Observation</strong>
      <small>只读；缺失为 unavailable；degraded ≠ healthy</small>
    </div>

    <NAlert v-if="!context" type="default" :bordered="false" size="small">无观察上下文</NAlert>
    <NAlert v-else-if="mixWarning" type="warning" :bordered="false" size="small" title="historical/live boundary">
      历史与 Live 不得静默混合。
    </NAlert>
    <NAlert v-else-if="notHealthy" type="warning" :bordered="false" size="small" title="Runtime not healthy">
      {{ observationFieldLabel(context.runtime_health_status) }}
    </NAlert>

    <NDescriptions v-if="context" label-placement="left" size="small" :column="1" bordered>
      <NDescriptionsItem v-for="row in rows" :key="row.key" :label="row.label">
        <NTag size="small" :type="rowTagType(row.field)" :bordered="false">{{ row.field.status }}</NTag>
        <span class="field-value">{{ observationFieldLabel(row.field) }}</span>
      </NDescriptionsItem>
    </NDescriptions>
  </div>
</template>

<style scoped>
.market-runtime-observation-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.panel-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.panel-head strong {
  font-size: 14px;
}
.panel-head small {
  opacity: 0.7;
  font-size: 12px;
}
.field-value {
  margin-left: 8px;
  font-size: 12px;
  word-break: break-all;
}
</style>
