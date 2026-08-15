<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'
import type { SubingFactorSnapshot, SubingResearchResponse, SubingSignal } from '@/types/market'

const props = defineProps<{
  snapshot: SubingResearchResponse | null
}>()

const signal = computed(() => {
  const candidate = props.snapshot?.resolved_signal
  return candidate?.status === 'matched' && (candidate.direction === 'long' || candidate.direction === 'short')
    ? candidate
    : null
})
const signalSnapshot = computed(() => snapshotFor(signal.value))

function snapshotFor(candidate: SubingSignal | null): SubingFactorSnapshot | null {
  if (!candidate || !props.snapshot) return null
  if (props.snapshot.primary.snapshot?.timeframe === candidate.trigger_timeframe) return props.snapshot.primary.snapshot
  if (props.snapshot.companion?.snapshot?.timeframe === candidate.trigger_timeframe) return props.snapshot.companion.snapshot
  return null
}

function directionLabel(candidate: SubingSignal) {
  return candidate.direction === 'long' ? '买入信号' : '卖出信号'
}

function time(value: string | undefined) {
  if (!value) return '--:--'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '--:--'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
</script>

<template>
  <section :class="['product-formal-signal', signal ? `product-formal-signal--${signal.direction}` : 'product-formal-signal--empty']" data-testid="product-formal-signal">
    <h3>正式信号</h3>
    <template v-if="signal">
      <strong :class="signal.direction === 'long' ? 'product-formal-signal--buy' : 'product-formal-signal--sell'">
        苏冰 / {{ signal.trigger_timeframe }} {{ directionLabel(signal) }} · {{ time(signalSnapshot?.bar_end) }}
      </strong>
      <NTag v-if="signal.lower_tf_confirmation" size="small" :bordered="false">5m 同向确认</NTag>
    </template>
    <p v-else>当前无正式入场信号</p>
  </section>
</template>

<style scoped>
.product-formal-signal { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--gy-border-strong); border-left: 4px solid var(--gy-border-strong); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); }
.product-formal-signal--long { border-left-color: var(--gy-up); }.product-formal-signal--short { border-left-color: var(--gy-down); }
.product-formal-signal h3 { margin: 0; font-size: var(--gy-font-size-sm); }
.product-formal-signal strong { font-size: var(--gy-font-size-sm); }
.product-formal-signal p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.product-formal-signal--buy { color: var(--gy-up); }
.product-formal-signal--sell { color: var(--gy-down); }
</style>
