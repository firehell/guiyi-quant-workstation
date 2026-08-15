<script setup lang="ts">
import { NButton, NCard, NEmpty, NSpin } from 'naive-ui'
import type { CurrentFormalSignalItem } from '@/api/alerts'

const props = defineProps<{
  loading: boolean
  status: 'ready' | 'unavailable' | null
  tradingDay: string | null
  items: CurrentFormalSignalItem[]
}>()

const emit = defineEmits<{
  open: [item: CurrentFormalSignalItem]
}>()

function direction(item: CurrentFormalSignalItem) {
  if (item.result_codes.length === 1 && item.result_codes[0] === 'buy') return { label: '买入信号', className: 'market-formal-signals__direction--buy' }
  if (item.result_codes.length === 1 && item.result_codes[0] === 'sell') return { label: '卖出信号', className: 'market-formal-signals__direction--sell' }
  return { label: '信号', className: 'market-formal-signals__direction--neutral' }
}

function barTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai',
  }).format(new Date(value))
}
</script>

<template>
  <section class="market-formal-signals" aria-label="需要处理" data-testid="market-formal-signals">
    <h2>需要处理</h2>
    <NSpin :show="loading">
      <p v-if="loading" class="market-formal-signals__state">正在读取正式信号…</p>
      <p v-else-if="status === 'unavailable'" class="market-formal-signals__state">正式信号暂不可用</p>
      <NEmpty v-else-if="status === 'ready' && items.length === 0" description="当前没有需要处理的正式信号" />
      <div v-else-if="status === 'ready'" class="market-formal-signals__cards">
        <NCard v-for="item in items" :key="item.id" size="small" class="market-formal-signals__card">
          <div class="market-formal-signals__name">{{ item.display_name }}</div>
          <div>{{ item.symbol.toUpperCase() }} {{ item.product_name }} · {{ item.contract }}</div>
          <div :class="['market-formal-signals__direction', direction(item).className]">
            {{ item.frequency }} {{ direction(item).label }} · {{ barTime(item.bar_end) }}
          </div>
          <div v-if="item.lower_tf_confirmation" class="market-formal-signals__confirmation">{{ item.frequency }} 同向确认</div>
          <NButton size="small" @click="emit('open', item)">查看 K 线</NButton>
        </NCard>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.market-formal-signals { display: flex; flex-direction: column; gap: 10px; }.market-formal-signals h2 { margin: 0; font-size: var(--gy-font-size-lg); }.market-formal-signals__state { margin: 0; color: var(--gy-text-muted); }.market-formal-signals__cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }.market-formal-signals__card :deep(.n-card__content) { display: flex; flex-direction: column; gap: 7px; }.market-formal-signals__name { font-weight: 600; }.market-formal-signals__direction { font-weight: 600; }.market-formal-signals__direction--buy { color: var(--gy-up); }.market-formal-signals__direction--sell { color: var(--gy-down); }.market-formal-signals__direction--neutral { color: var(--gy-text); }.market-formal-signals__confirmation { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
