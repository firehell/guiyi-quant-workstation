<script setup lang="ts">
import { computed } from 'vue'
import type { ProductAlertRuleState } from '@/api/alerts'
import type { AlertEvent } from '@/types/market'
import {
  alertDirectionalTone,
  alertResultLabel,
  alertRuleShortLabel,
} from '@/utils/alertRules'

const props = defineProps<{
  items: AlertEvent[]
  rules: ProductAlertRuleState[]
}>()

const displayNames = computed(() => new Map(
  props.rules.map((rule) => [rule.rule_code, rule.display_name]),
))

function ruleLabel(ruleCode: string) {
  return displayNames.value.get(ruleCode) ?? alertRuleShortLabel(ruleCode)
}

function resultLabel(event: AlertEvent) {
  return alertResultLabel(event.rule_code, event.result_codes)
}

function resultClass(event: AlertEvent) {
  const direction = alertDirectionalTone(event.rule_code, event.result_codes)
  return direction === 'buy' ? 'product-today-alert-events__result--buy'
    : direction === 'sell' ? 'product-today-alert-events__result--sell'
      : ''
}

function barTime(value: string) {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '--:--'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
</script>

<template>
  <section class="product-today-alert-events" data-testid="product-today-alert-events">
    <h3>苏冰今日记录</h3>
    <p v-if="items.length === 0">当前无可展示的苏冰 Event 记录</p>
    <div v-else class="product-today-alert-events__rows">
      <div v-for="item in items" :key="item.id" class="product-today-alert-events__row">
        <time>{{ barTime(item.bar_end) }}</time>
        <strong>{{ ruleLabel(item.rule_code) }}</strong>
        <span :class="resultClass(item)">{{ resultLabel(item) }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.product-today-alert-events { display: grid; gap: 8px; }
.product-today-alert-events h3 { margin: 0; font-size: var(--gy-font-size-sm); }
.product-today-alert-events p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.product-today-alert-events__rows { display: grid; gap: 8px; }
.product-today-alert-events__row { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; gap: 8px; font-size: var(--gy-font-size-sm); }
.product-today-alert-events__row time { color: var(--gy-text-muted); font-family: var(--gy-font-mono); }
.product-today-alert-events__result--buy { color: var(--gy-up); font-weight: 600; }.product-today-alert-events__result--sell { color: var(--gy-down); font-weight: 600; }
</style>
