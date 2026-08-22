<script setup lang="ts">
import { computed } from 'vue'
import type { MarketRadarItem, MarketRadarResponse } from '@/types/market'
import { selectMarketFocus } from '@/utils/marketFocus'

const props = defineProps<{
  radar: MarketRadarResponse
}>()

const emit = defineEmits<{
  open: [item: MarketRadarItem]
}>()

const items = computed(() => (
  props.radar.freshness_state === 'degraded' ? [] : selectMarketFocus(props.radar.items)
))

const meta = computed(() => {
  const participation = `${props.radar.participant_count}/${props.radar.active_count}`
  if (props.radar.freshness_state === 'pending_after_market') {
    return `基于 ${props.radar.data_as_of} 完整日线 · ${props.radar.target_as_of} 盘后更新待完成 · ${participation}`
  }
  if (props.radar.freshness_state === 'degraded') {
    return `${props.radar.freshness_message} · ${participation}`
  }
  return `基于 ${props.radar.data_as_of} 完整日线 · ${participation}`
})

const remainingCount = computed(() => Math.max(0, props.radar.participant_count - items.value.length))
</script>

<template>
  <section class="market-focus" aria-labelledby="market-focus-heading" data-testid="market-focus">
    <header class="market-focus__heading">
      <div>
        <span>Decision Focus</span>
        <h2 id="market-focus-heading">优先检查</h2>
      </div>
      <small>{{ meta }}</small>
    </header>

    <div v-if="radar.freshness_state === 'degraded'" class="market-focus__empty market-focus__empty--warning">
      <strong>优先检查暂不可用：Radar 数据不完整。</strong>
      <span>请以页面上方的 stale / unavailable 信息为准。</span>
    </div>

    <div v-else-if="items.length === 0" class="market-focus__empty">
      <strong>当前没有同时满足趋势与参与条件的优先检查品种。</strong>
      <span>不用主动遍历全市场；等待后续市场变化或正式提醒。</span>
    </div>

    <div v-else class="market-focus__cards">
      <article v-for="entry in items" :key="entry.item.symbol" class="market-focus__card" data-testid="market-focus-card">
        <div class="market-focus__card-heading">
          <div>
            <strong>{{ entry.item.symbol.toUpperCase() }} {{ entry.item.product_name }}</strong>
            <span :class="`market-focus__direction market-focus__direction--${entry.direction}`">
              {{ entry.direction === 'long' ? '多头观察' : '空头观察' }}
            </span>
          </div>
          <button type="button" @click="emit('open', entry.item)">检查详情</button>
        </div>
        <div class="market-focus__reasons">
          <span v-for="reason in entry.reasonLabels" :key="reason">{{ reason }}</span>
          <span v-if="entry.riskLabel" class="market-focus__risk">风险：{{ entry.riskLabel }}</span>
        </div>
      </article>
    </div>

    <footer v-if="radar.freshness_state !== 'degraded'">
      其余 {{ remainingCount }} 个当前不优先检查
    </footer>
  </section>
</template>

<style scoped>
.market-focus { display: flex; flex-direction: column; gap: 12px; padding: 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-panel); }
.market-focus__heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
.market-focus__heading > div { min-width: 0; }
.market-focus__heading span, .market-focus__heading small, .market-focus footer { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.market-focus__heading h2 { margin: 3px 0 0; font-size: var(--gy-font-size-lg); }
.market-focus__heading small { text-align: right; }
.market-focus__cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.market-focus__card { min-width: 0; padding: 12px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-app); }
.market-focus__card-heading, .market-focus__card-heading > div { display: flex; align-items: center; gap: 9px; }
.market-focus__card-heading { justify-content: space-between; }
.market-focus__card-heading > div { min-width: 0; flex-wrap: wrap; }
.market-focus__card-heading strong { color: var(--gy-text-primary); }
.market-focus__direction { font-size: var(--gy-font-size-xs); font-weight: 500; }
.market-focus__direction--long { color: var(--gy-up); }
.market-focus__direction--short { color: var(--gy-down); }
.market-focus__card button { flex: 0 0 auto; padding: 4px 2px; border: 0; background: none; color: var(--gy-accent); cursor: pointer; }
.market-focus__card button:hover { color: var(--gy-accent-hover); text-decoration: underline; }
.market-focus__reasons { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.market-focus__reasons span { padding: 2px 7px; border-radius: var(--gy-radius-pill); background: var(--gy-accent-soft); color: var(--gy-blue-700); font-size: var(--gy-font-size-xs); }
.market-focus__reasons .market-focus__risk { background: var(--gy-status-warning-soft); color: var(--gy-status-warning); }
.market-focus__empty { display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: var(--gy-radius-md); background: var(--gy-bg-app); color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.market-focus__empty--warning { background: var(--gy-status-warning-soft); }
@media (max-width: 1100px) { .market-focus__cards { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .market-focus__heading { align-items: flex-start; flex-direction: column; } .market-focus__heading small { text-align: left; } }
</style>
