<script setup lang="ts">
import type { Time } from 'lightweight-charts'
import type { HoverKlineContext } from '@/types/market'
import { formatChartTimeInShanghai, toKlineDisplayTimeForPeriod } from '@/utils/barTime'
import { formatKlineHoverValue } from '@/utils/klineViewModel'

const props = defineProps<{
  context: HoverKlineContext | null
  period: string
  showMacd: boolean
}>()

function displayTime(context: HoverKlineContext): string {
  return formatChartTimeInShanghai(
    toKlineDisplayTimeForPeriod(context.bar, props.period) as Time,
  )
}
</script>

<template>
  <div v-if="context" class="kline-hover-legend" aria-live="polite">
    <span data-testid="kline-hover-time">{{ displayTime(context) }}</span>
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
    <template v-if="context.rangeDetector">
      <span data-testid="kline-hover-range-detector">
        箱体 上沿 {{ formatKlineHoverValue(context.rangeDetector.upper) }} / 中线 {{ formatKlineHoverValue(context.rangeDetector.mid) }} / 下沿 {{ formatKlineHoverValue(context.rangeDetector.lower) }} / 状态 {{ context.rangeDetector.state }}
      </span>
      <span>箱体起点为回画展示；策略自确认时刻起才可使用</span>
    </template>
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
