<script setup lang="ts">
import { computed } from 'vue'
import type { CanonicalBarDto } from '@/types/market'

const props = defineProps<{ daily: CanonicalBarDto[] }>()

const hasOi = computed(() => props.daily.some((bar) => bar.open_interest !== null))
const points = computed(() => props.daily.map((bar, index) => ({
  index,
  price: normalize(bar.close, props.daily.map((item) => item.close)),
  oi: bar.open_interest === null ? null : normalize(bar.open_interest, props.daily.flatMap((item) => item.open_interest === null ? [] : [item.open_interest])),
  volume: normalize(bar.volume, props.daily.map((item) => item.volume)),
})))

function normalize(value: number, values: number[]): number {
  const min = Math.min(...values)
  const max = Math.max(...values)
  return max === min ? 50 : 8 + ((value - min) / (max - min)) * 84
}

function line(key: 'price' | 'oi') {
  return points.value.flatMap((point) => {
    const value = point[key]
    return value === null ? [] : [`${(point.index / Math.max(points.value.length - 1, 1)) * 100},${100 - value}`]
  }).join(' ')
}
</script>

<template>
  <section class="price-volume-oi">
    <div class="price-volume-oi__heading">
      <div><span>研究区</span><h3>Price / Volume / OI</h3></div>
      <small>日线归一化观察</small>
    </div>
    <template v-if="daily.length">
      <svg class="price-volume-oi__chart" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="归一化价格、成交量和持仓观察">
        <polyline :points="line('price')" class="price" />
        <polyline v-if="hasOi" :points="line('oi')" class="oi" />
        <rect v-for="point in points" :key="point.index" :x="(point.index / Math.max(points.length, 1)) * 100" :y="100 - point.volume" :width="Math.max(0.5, 88 / points.length)" :height="point.volume" class="volume" />
      </svg>
      <div class="price-volume-oi__legend"><span>价格</span><span>成交量</span><span v-if="hasOi">OI</span><span v-else>OI 暂无可用数据</span></div>
    </template>
    <p v-else>暂无可用日线研究数据</p>
  </section>
</template>

<style scoped>
.price-volume-oi { padding: 14px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.price-volume-oi__heading { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
.price-volume-oi__heading span, .price-volume-oi__heading small { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.price-volume-oi h3 { margin: 2px 0 0; font-size: var(--gy-font-size-md); }.price-volume-oi__chart { width: 100%; height: 150px; margin-top: 12px; background: var(--gy-bg-app); }
.price { fill: none; stroke: var(--gy-chart-ema); stroke-width: 1.3; vector-effect: non-scaling-stroke; }.oi { fill: none; stroke: var(--gy-chart-macd-dif); stroke-width: 1.1; vector-effect: non-scaling-stroke; }.volume { fill: rgba(13, 148, 136, .3); }
.price-volume-oi__legend { display: flex; gap: 12px; margin-top: 8px; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
