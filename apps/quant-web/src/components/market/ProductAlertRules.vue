<script setup lang="ts">
import { computed } from 'vue'
import { NSpin, NSwitch, NTag } from 'naive-ui'
import type { ProductAlertRuleState } from '@/api/alerts'
import type { MarketFrequency } from '@/types/market'
import { alertRuntimeLabel, type AlertRuntimeStatus } from '@/utils/alertControl'
import { ALERT_RULE_CODES, ALERT_RULE_PRESENTATIONS } from '@/utils/alertRules'

const props = defineProps<{
  rules: ProductAlertRuleState[]
  runtimeStatus: AlertRuntimeStatus | null
  loading: boolean
  savingRuleCodes: Set<string>
  frequency: MarketFrequency
}>()

const emit = defineEmits<{
  toggle: [ruleCode: string, enabled: boolean]
}>()

const runtimeLabel = computed(() => alertRuntimeLabel(props.runtimeStatus))
const runtimeTagType = computed(() => props.runtimeStatus === 'ok'
  ? 'success'
  : props.runtimeStatus === 'disabled' ? 'default' : 'warning')

const rows = computed(() => ALERT_RULE_PRESENTATIONS.map((presentation) => {
  const rule = props.rules.find((item) => item.rule_code === presentation.ruleCode) ?? null
  const htdy = presentation.ruleCode === ALERT_RULE_CODES.HTDY
  return {
    ruleCode: presentation.ruleCode,
    label: rule
      ? htdy
        ? `${rule.display_name} · ${props.frequency}`
        : `${rule.display_name} · ${rule.input_frequencies.join('/')}`
      : presentation.shortLabel,
    value: rule
      ? htdy
        ? rule.enabled_frequencies.includes(props.frequency)
        : rule.enabled_for_product
      : false,
    rule,
  }
}))
</script>

<template>
  <section class="product-alert-rules" data-testid="product-alert-rules">
    <NSpin :show="loading" size="small">
      <div v-for="row in rows" :key="row.ruleCode" class="product-alert-rules__row">
        <span>{{ row.rule ? row.label : `${row.label}（不可用）` }}</span>
        <NSwitch
          :value="row.value"
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
.product-alert-rules { display: grid; gap: 10px; }.product-alert-rules__row { display: flex; justify-content: space-between; gap: 12px; align-items: center; font-size: var(--gy-font-size-sm); }.product-alert-rules__row > span:first-child { color: var(--gy-text-secondary); }.product-alert-rules :deep(.n-switch.n-switch--disabled) { opacity: .68; }
</style>
