<script setup lang="ts">
import type { HoverKlineContext } from '@/types/market'
import { formatChartTimeInShanghai } from '@/utils/barTime'
import { formatKlineHoverValue } from '@/utils/klineViewModel'

defineProps<{
  context: HoverKlineContext | null
  showMacd: boolean
}>()
</script>

<template>
  <div v-if="context" class="kline-hover-legend" aria-live="polite">
    <span data-testid="kline-hover-time">{{ formatChartTimeInShanghai(context.time) }}</span>
    <span>O {{ formatKlineHoverValue(context.bar.open) }}</span>
    <span>H {{ formatKlineHoverValue(context.bar.high) }}</span>
    <span>L {{ formatKlineHoverValue(context.bar.low) }}</span>
    <span>C {{ formatKlineHoverValue(context.bar.close) }}</span>
    <span>Vol {{ formatKlineHoverValue(context.bar.volume) }}</span>
    <span>OI {{ formatKlineHoverValue(context.bar.openInterest) }}</span>
    <span v-for="indicator in context.mainIndicators" :key="indicator.id">
      {{ indicator.displayName }} {{ formatKlineHoverValue(indicator.value) }}
    </span>
    <span v-if="context.marker?.tooltip" data-testid="kline-hover-marker">
      {{ context.marker.tooltip }}
    </span>
    <template v-if="showMacd">
      <span>DIF {{ formatKlineHoverValue(context.macd?.dif) }}</span>
      <span>DEA {{ formatKlineHoverValue(context.macd?.dea) }}</span>
      <span>HIST {{ formatKlineHoverValue(context.macd?.histogram) }}</span>
    </template>
  </div>
</template>

<style scoped>
.kline-hover-legend {
  position: absolute;
  z-index: 4;
  top: 10px;
  left: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  max-width: calc(100% - 24px);
  color: var(--gy-text-muted);
  font-size: 12px;
  line-height: 1.4;
  pointer-events: none;
}

.kline-hover-legend [data-testid='kline-hover-time'] {
  color: var(--gy-text-primary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
