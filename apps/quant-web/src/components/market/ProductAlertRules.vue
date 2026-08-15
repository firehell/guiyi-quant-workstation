<script setup lang="ts">
import { computed } from 'vue'
import { NSpin, NSwitch, NTag } from 'naive-ui'
import type { ProductAlertRuleState } from '@/api/alerts'
import { alertRuntimeLabel, type AlertRuntimeStatus } from '@/utils/alertControl'

const props = defineProps<{
  htdyRule: ProductAlertRuleState | null
  subingRule: ProductAlertRuleState | null
  runtimeStatus: AlertRuntimeStatus | null
  loading: boolean
  savingRuleCodes: Set<string>
}>()

const emit = defineEmits<{
  toggle: [ruleCode: string, enabled: boolean]
}>()

const runtimeLabel = computed(() => alertRuntimeLabel(props.runtimeStatus))
const runtimeTagType = computed(() => props.runtimeStatus === 'ok'
  ? 'success'
  : props.runtimeStatus === 'disabled' ? 'default' : 'warning')

const rows = computed(() => [
  { ruleCode: 'htdy_original_15m', label: '火天大有 · 15m', rule: props.htdyRule },
  { ruleCode: 'subing_entry_signal_v1', label: '苏冰入场信号', rule: props.subingRule },
])
</script>

<template>
  <section class="product-alert-rules" data-testid="product-alert-rules">
    <NSpin :show="loading" size="small">
      <div v-for="row in rows" :key="row.ruleCode" class="product-alert-rules__row">
        <span>{{ row.rule ? row.label : `${row.label}（不可用）` }}</span>
        <NSwitch
          :value="row.rule?.enabled_for_product || false"
          :disabled="!row.rule || loading || savingRuleCodes.has(row.ruleCode)"
          :loading="savingRuleCodes.has(row.ruleCode)"
          @update:value="emit('toggle', row.ruleCode, $event)"
        />
      </div>
      <div class="product-alert-rules__row">
        <span>Alert Runtime</span>
        <NTag size="small" :type="runtimeTagType">{{ runtimeLabel }}</NTag>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.product-alert-rules { display: grid; gap: 10px; }
.product-alert-rules__row { display: flex; justify-content: space-between; gap: 12px; align-items: center; font-size: var(--gy-font-size-sm); }
.product-alert-rules__row > span:first-child { color: var(--gy-text-muted); }
</style>
