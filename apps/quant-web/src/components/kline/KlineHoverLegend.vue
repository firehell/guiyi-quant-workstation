<script setup lang="ts">
import type { HoverKlineContext } from '@/types/market'
import { formatKlineHoverValue } from '@/utils/klineViewModel'
import { MAIN_FORCE_MEMBER_RELATION_LABELS } from '@/utils/mainForceMirrorV2Presentation'

defineProps<{
  context: HoverKlineContext | null
  showMacd: boolean
  showMainForceMirrorV2: boolean
}>()
</script>

<template>
  <div v-if="context" class="kline-hover-legend" aria-live="polite">
    <span data-testid="mfm-hover-time">{{ context.time }}</span>
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
    <template v-if="showMainForceMirrorV2 && context.mainForceMirrorV2">
      <span data-testid="mfm-v2-hover-contract">合约 {{ context.mainForceMirrorV2.physicalContract }}</span>
      <span>状态 {{ context.mainForceMirrorV2.state || '—' }}</span>
      <span>瞬时 {{ formatKlineHoverValue(context.mainForceMirrorV2.instantPressure) }}</span>
      <span>累积 EMA5 {{ formatKlineHoverValue(context.mainForceMirrorV2.accumulatedPressure) }}</span>
      <span>多分 {{ formatKlineHoverValue(context.mainForceMirrorV2.longScore) }}</span>
      <span>空分 {{ formatKlineHoverValue(context.mainForceMirrorV2.shortScore) }}</span>
      <span>席位日期 {{ context.mainForceMirrorV2.memberTradeDate || '—' }}</span>
      <span>席位方向 {{ context.mainForceMirrorV2.memberDirection || '—' }}</span>
      <span>席位强度 {{ formatKlineHoverValue(context.mainForceMirrorV2.memberStrength) }}</span>
      <span>{{ MAIN_FORCE_MEMBER_RELATION_LABELS[context.mainForceMirrorV2.relationToAccumulated] }}</span>
      <span>警戒关系 {{ MAIN_FORCE_MEMBER_RELATION_LABELS[context.mainForceMirrorV2.relationToCaution] }}</span>
      <span>不可用原因 {{ context.mainForceMirrorV2.unavailableReason || '—' }}</span>
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
