<script setup lang="ts">
import { NSpin } from 'naive-ui'
import type { AlertEvent } from '@/types/market'

defineProps<{
  loading: boolean
  status: 'ready' | 'unavailable' | null
  items: AlertEvent[]
}>()

function ruleLabel(ruleCode: string) {
  if (ruleCode === 'subing_entry_signal_v1') return '苏冰'
  if (ruleCode === 'htdy_original_15m') return '火天大有'
  return '未知提醒'
}

function resultLabel(event: AlertEvent) {
  const direction = event.result_codes.length === 1 ? event.result_codes[0] : null
  if (direction === 'buy') return event.rule_code === 'htdy_original_15m' ? '买入观察' : '买入信号'
  if (direction === 'sell') return event.rule_code === 'htdy_original_15m' ? '卖出观察' : '卖出信号'
  return '提醒记录'
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
    <h3>今日记录</h3>
    <NSpin :show="loading" size="small">
      <p v-if="loading">读取今日提醒…</p>
      <p v-else-if="status === 'unavailable'">今日提醒暂不可用</p>
      <p v-else-if="status === 'ready' && items.length === 0">今日暂无提醒记录</p>
      <div v-else-if="status === 'ready'" class="product-today-alert-events__rows">
        <div v-for="item in items" :key="item.id" class="product-today-alert-events__row">
          <time>{{ barTime(item.bar_end) }}</time>
          <strong>{{ ruleLabel(item.rule_code) }}</strong>
          <span>{{ resultLabel(item) }}</span>
        </div>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.product-today-alert-events { display: grid; gap: 8px; }
.product-today-alert-events h3 { margin: 0; font-size: var(--gy-font-size-sm); }
.product-today-alert-events p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.product-today-alert-events__rows { display: grid; gap: 8px; }
.product-today-alert-events__row { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; gap: 8px; font-size: var(--gy-font-size-sm); }
.product-today-alert-events__row time { color: var(--gy-text-muted); font-family: var(--gy-font-mono); }
</style>
