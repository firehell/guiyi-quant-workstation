<script setup lang="ts">
import type { ProductAlertRuleState } from '@/api/alerts'
import type { AlertEvent } from '@/types/market'
import {
  alertEventDirectionalTone,
  alertEventResultLabel,
  alertEventRuleShortLabel,
  findAlertRuleForEvent,
  strategyActionLabel,
} from '@/utils/alertRules'

const props = defineProps<{
  items: AlertEvent[]
  rules: ProductAlertRuleState[]
}>()

function ruleLabel(event: AlertEvent) {
  return findAlertRuleForEvent(props.rules, event)?.display_name
    ?? alertEventRuleShortLabel(event)
}

function resultLabel(event: AlertEvent) {
  if (event.strategy_action) return strategyActionLabel(event.strategy_action.kind)
  return alertEventResultLabel(
    event,
    event.result_codes.filter((item): item is 'buy' | 'sell' => item === 'buy' || item === 'sell'),
  )
}

function resultClass(event: AlertEvent) {
  const strategyKind = event.strategy_action?.kind
  if (strategyKind) {
    return strategyKind.endsWith('_long')
      ? 'product-today-alert-events__result--buy'
      : 'product-today-alert-events__result--sell'
  }
  const direction = alertEventDirectionalTone(
    event,
    event.result_codes.filter((item): item is 'buy' | 'sell' => item === 'buy' || item === 'sell'),
  )
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
    <h3>苏冰策略事件</h3>
    <div class="product-today-alert-events__rows">
      <div
        v-for="item in items"
        :key="item.id"
        class="product-today-alert-events__row"
        :data-event-id="String(item.id)"
      >
        <time>{{ barTime(item.bar_end) }}</time>
        <strong>{{ ruleLabel(item) }}</strong>
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
