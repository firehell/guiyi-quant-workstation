<script setup lang="ts">
import { NSpin, NTag } from 'naive-ui'
import type { CurrentFormalSignalItem } from '@/api/alerts'
import type { EventState } from '@/types/executionReview'
import { executionReviewActionLabel } from '@/utils/executionReview'

const props = defineProps<{
  loading: boolean
  status: 'ready' | 'unavailable' | null
  tradingDay: string | null
  items: CurrentFormalSignalItem[]
  eventStates?: Record<number, EventState>
}>()

const emit = defineEmits<{
  open: [item: CurrentFormalSignalItem, state?: EventState]
}>()

function direction(item: CurrentFormalSignalItem) {
  if (item.result_codes.length === 1 && item.result_codes[0] === 'buy') return { label: '买入信号', tone: 'buy' }
  if (item.result_codes.length === 1 && item.result_codes[0] === 'sell') return { label: '卖出信号', tone: 'sell' }
  return { label: '信号', tone: 'neutral' }
}

function barTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}

function stateFor(item: CurrentFormalSignalItem) {
  return props.eventStates?.[item.id]
}

function actionLabel(item: CurrentFormalSignalItem) {
  const state = stateFor(item)
  return state ? executionReviewActionLabel(state.state) : '查看 →'
}
</script>

<template>
  <section class="market-formal-signals" aria-label="需要处理" data-testid="market-formal-signals">
    <header class="market-formal-signals__heading">
      <h2>需要处理</h2>
      <p>只显示当前交易日的正式信号</p>
    </header>
    <NSpin :show="loading">
      <p v-if="loading" class="market-formal-signals__state">正在读取正式信号…</p>
      <div v-else-if="status === 'unavailable'" class="market-formal-signals__unavailable">
        <NTag type="warning" size="small" :bordered="false">暂不可用</NTag>
        <span>正式信号暂不可用</span>
      </div>
      <p v-else-if="status === 'ready' && items.length === 0" class="market-formal-signals__state">当前交易日暂无正式信号</p>
      <div v-else-if="status === 'ready'" class="market-formal-signals__cards">
        <article
          v-for="item in items"
          :key="item.id"
          :class="['market-formal-signals__card', `market-formal-signals__card--${direction(item).tone}`]"
        >
          <div class="market-formal-signals__main">
            <div class="market-formal-signals__title">
              {{ item.symbol.toUpperCase() }} {{ item.product_name }} ·
              <span :class="['market-formal-signals__direction', `market-formal-signals__direction--${direction(item).tone}`]">{{ direction(item).label }}</span>
            </div>
            <div class="market-formal-signals__meta">
              {{ item.display_name }} · {{ item.frequency }} · {{ barTime(item.bar_end) }} 确认 · {{ item.contract }}<template v-if="item.lower_tf_confirmation"> · 5m 同向确认</template>
            </div>
          </div>
          <button class="market-formal-signals__open" @click="emit('open', item, stateFor(item))">{{ actionLabel(item) }}</button>
        </article>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.market-formal-signals { display: flex; flex-direction: column; gap: 10px; padding: 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-panel); }
.market-formal-signals__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.market-formal-signals h2 { margin: 0; font-size: var(--gy-font-size-lg); }
.market-formal-signals__heading p, .market-formal-signals__state { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.market-formal-signals__unavailable { display: flex; align-items: center; gap: 8px; color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.market-formal-signals__cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.market-formal-signals__card { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-left: 3px solid var(--gy-border-strong); border-radius: var(--gy-radius-md); background: var(--gy-bg-app); }
.market-formal-signals__card--buy { border-left-color: var(--gy-up); background: var(--gy-up-soft); }
.market-formal-signals__card--sell { border-left-color: var(--gy-down); background: var(--gy-down-soft); }
.market-formal-signals__main { min-width: 0; }
.market-formal-signals__title { font-size: var(--gy-font-size-md); font-weight: 500; color: var(--gy-text-primary); }
.market-formal-signals__direction { font-weight: 500; }
.market-formal-signals__direction--buy { color: var(--gy-up); }
.market-formal-signals__direction--sell { color: var(--gy-down); }
.market-formal-signals__direction--neutral { color: var(--gy-text); }
.market-formal-signals__meta { margin-top: 3px; color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); }
.market-formal-signals__open { flex: 0 0 auto; padding: 4px 2px; border: 0; background: none; color: var(--gy-accent); font-size: var(--gy-font-size-sm); cursor: pointer; white-space: nowrap; }
.market-formal-signals__open:hover { color: var(--gy-accent-hover); text-decoration: underline; }
@media (max-width: 979px) { .market-formal-signals__cards { grid-template-columns: 1fr; } }
</style>
