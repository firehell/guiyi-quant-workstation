<script setup lang="ts">
import type { MarketRadarItem } from '@/types/market'

defineProps<{ items: MarketRadarItem[] }>()
const emit = defineEmits<{ open: [item: MarketRadarItem] }>()

const labels: Record<string, string> = {
  price_move_up: '价格上涨', price_move_down: '价格下跌', volume_expansion: '放量',
  oi_increase: '增仓', oi_decrease: '减仓', high_volatility: '高波动',
  near_20d_high: '近20日高位', near_20d_low: '近20日低位', ema21_up: 'EMA21上行', ema21_down: 'EMA21下行',
}
</script>

<template>
  <section class="market-attention" aria-labelledby="market-attention-heading">
    <header><div><span>系统透明规则</span><h2 id="market-attention-heading">值得关注</h2></div><small>至少满足 2 个观察原因</small></header>
    <ol v-if="items.length">
      <li v-for="item in items" :key="item.symbol">
        <button :aria-label="`${item.symbol.toUpperCase()} ${item.product_name}`" @click="emit('open', item)">
          <strong>{{ item.symbol.toUpperCase() }} {{ item.product_name }}</strong><span>{{ item.sector }}</span>
        </button>
        <div><small v-for="reason in item.reason_codes" :key="reason">{{ labels[reason] || reason }}</small></div>
      </li>
    </ol>
    <p v-else>当前没有满足固定阈值的品种。</p>
  </section>
</template>

<style scoped>
.market-attention { padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }.market-attention header { display: flex; justify-content: space-between; gap: 16px; align-items: start; }.market-attention header span, .market-attention small { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-attention h2 { margin: 3px 0 0; font-size: var(--gy-font-size-md); }.market-attention ol { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin: 14px 0 0; padding: 0; list-style: none; }.market-attention li { padding: 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-app); }.market-attention button { display: flex; width: 100%; justify-content: space-between; gap: 8px; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; text-align: left; }.market-attention button span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-attention li > div { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }.market-attention li > div small { padding: 2px 5px; border-radius: 3px; background: rgba(56,189,248,.12); color: #38bdf8; }
</style>
