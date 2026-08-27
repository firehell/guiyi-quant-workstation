<script setup lang="ts">
import { computed } from 'vue'
import { NSpin, NSwitch, NTag } from 'naive-ui'
import type { ProductAlertRuleState } from '@/api/alerts'
import type { MarketFrequency } from '@/types/market'
import { alertRuntimeLabel, type AlertRuntimeStatus } from '@/utils/alertControl'
import { ALERT_RULE_CODES, matchesAlertRuleCode } from '@/utils/alertRules'

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

const htdyRule = computed(() => (
  props.rules.find((rule) => matchesAlertRuleCode(rule, ALERT_RULE_CODES.HTDY)) ?? null
))
const label = computed(() => {
  const rule = htdyRule.value
  return rule ? `${rule.display_name} · ${props.frequency}` : '火天大有（不可用）'
})
const enabled = computed(() => htdyRule.value?.enabled_frequencies.includes(props.frequency) ?? false)
</script>

<template>
  <section class="product-alert-rules" data-testid="product-alert-rules">
    <NSpin :show="loading" size="small">
      <div class="product-alert-rules__row">
        <span>{{ label }}</span>
        <NSwitch
          :value="enabled"
          :disabled="!htdyRule || loading || savingRuleCodes.has(ALERT_RULE_CODES.HTDY)"
          :loading="savingRuleCodes.has(ALERT_RULE_CODES.HTDY)"
          @update:value="emit('toggle', ALERT_RULE_CODES.HTDY, $event)"
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
