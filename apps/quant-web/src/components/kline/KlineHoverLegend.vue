<script setup lang="ts">
import type { HoverKlineContext } from '@/types/market'
import { formatKlineHoverValue } from '@/utils/klineViewModel'

function futuresAvailabilityLabel(details: NonNullable<HoverKlineContext['mainForceFutures']>): string {
  if (!details.valid) return '输入不可用'
  if (!details.stateReady) return '状态预热'
  if (!details.cautionReady) return '小心预热'
  if (details.cautionAvailabilityReason === 'MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT') return '方向冲突'
  if (!details.ready) return '不可用'
  return '就绪'
}

defineProps<{
  context: HoverKlineContext | null
  showMacd: boolean
  showMainForceFutures: boolean
}>()
</script>

<template>
  <div v-if="context" class="kline-hover-legend" aria-live="polite">
    <span>{{ context.time }}</span>
    <span>O {{ formatKlineHoverValue(context.bar.open) }}</span>
    <span>H {{ formatKlineHoverValue(context.bar.high) }}</span>
    <span>L {{ formatKlineHoverValue(context.bar.low) }}</span>
    <span>C {{ formatKlineHoverValue(context.bar.close) }}</span>
    <span>Vol {{ formatKlineHoverValue(context.bar.volume) }}</span>
    <span>OI {{ formatKlineHoverValue(context.bar.openInterest) }}</span>
    <span v-for="indicator in context.mainIndicators" :key="indicator.id">
      {{ indicator.displayName }} {{ formatKlineHoverValue(indicator.value) }}
    </span>
    <template v-if="showMacd">
      <span>DIF {{ formatKlineHoverValue(context.macd?.dif) }}</span>
      <span>DEA {{ formatKlineHoverValue(context.macd?.dea) }}</span>
      <span>HIST {{ formatKlineHoverValue(context.macd?.histogram) }}</span>
    </template>
    <template v-if="showMainForceFutures && context.mainForceFutures">
      <span>合约 {{ context.mainForceFutures.physicalContract || '—' }}</span>
      <span>状态 {{ context.mainForceFutures.state || '—' }}</span>
      <span>可用性 {{ futuresAvailabilityLabel(context.mainForceFutures) }}</span>
      <span>强度 {{ formatKlineHoverValue(context.mainForceFutures.strength) }}</span>
      <span>价冲 {{ formatKlineHoverValue(context.mainForceFutures.priceImpulse) }}</span>
      <span>CLV {{ formatKlineHoverValue(context.mainForceFutures.clv) }}</span>
      <span>量比 {{ formatKlineHoverValue(context.mainForceFutures.volumeRatio) }}</span>
      <span>ΔOI {{ formatKlineHoverValue(context.mainForceFutures.deltaOi) }}</span>
      <span>OI冲 {{ formatKlineHoverValue(context.mainForceFutures.oiImpulse) }}</span>
      <span>区间 {{ formatKlineHoverValue(context.mainForceFutures.rangePosition) }}</span>
      <span>多分 {{ formatKlineHoverValue(context.mainForceFutures.longScore) }}</span>
      <span>空分 {{ formatKlineHoverValue(context.mainForceFutures.shortScore) }}</span>
      <span>原因 {{ context.mainForceFutures.reasonCodes.join('、') || '—' }}</span>
      <span>不可用原因 {{ context.mainForceFutures.availabilityReason || context.mainForceFutures.cautionAvailabilityReason || '—' }}</span>
    </template>
  </div>
</template>

<style scoped>
.kline-hover-legend {
  position: absolute;
  z-index: 1;
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
</style>
