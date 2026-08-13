<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NTag } from 'naive-ui'
import type { SubingFactorSnapshot, SubingResearchResponse } from '@/types/market'

const props = defineProps<{
  snapshot: SubingResearchResponse | null
  loading: boolean
  error: boolean
  supported: boolean
}>()

const primary = computed(() => props.snapshot?.primary.snapshot ?? null)
const companion = computed(() => props.snapshot?.companion?.snapshot ?? null)
const ready = computed(() => props.snapshot?.primary.status === 'ready' && !!primary.value)
const directions = computed(() => {
  if (!primary.value) return ''
  const primaryLabel = `${primary.value.timeframe} ${direction(primary.value)}`
  if (!companion.value) return primaryLabel
  const companionLabel = `${companion.value.timeframe} ${direction(companion.value)}`
  const resonance = primary.value.price_side === companion.value.price_side ? ' · 同向' : ' · 分歧'
  return `${primaryLabel} / ${companionLabel}${resonance}`
})

function direction(snapshot: SubingFactorSnapshot) {
  return snapshot.price_side === 'above' ? '↑' : snapshot.price_side === 'below' ? '↓' : '→'
}

function crossLabel(value: SubingFactorSnapshot['macd_cross']) {
  return value === 'golden' ? '金叉' : value === 'dead' ? '死叉' : value === 'none' ? '无新交叉' : '不可用'
}

function ratio(value: number | null) {
  return value === null ? '—' : `${value.toFixed(2)}x`
}

function confirmedTime(value: string) {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(timestamp)
}
</script>

<template>
  <NAlert v-if="!supported" type="warning" :show-icon="false" class="subing-strip">
    苏冰 Factor V1 当前周期不可用，仅支持 5m / 15m / 1d
  </NAlert>
  <NAlert v-else-if="loading" type="info" :show-icon="false" class="subing-strip">
    苏冰 Factor 快照加载中
  </NAlert>
  <NAlert v-else-if="error || !snapshot" type="warning" :show-icon="false" class="subing-strip">
    苏冰 Factor 快照不可用
  </NAlert>
  <NAlert v-else-if="!ready" type="warning" :show-icon="false" class="subing-strip">
    <div class="subing-strip__row">
      <strong>苏冰 Factor · 当前主力已切换</strong>
      <NTag v-if="snapshot.live_observation === 'unavailable'" size="small" type="warning">Live observation unavailable</NTag>
    </div>
    <div>指标 warm-up 中 · 暂无 Factor 判断</div>
  </NAlert>
  <NAlert v-else type="success" :show-icon="false" class="subing-strip">
    <div class="subing-strip__row">
      <strong>苏冰 Factor · {{ primary?.bar_source === 'live' ? 'Live观察' : 'Historical观察' }} · {{ confirmedTime(primary!.bar_end) }}</strong>
      <NTag v-if="snapshot.live_observation === 'unavailable'" size="small" type="warning">Live observation unavailable</NTag>
    </div>
    <div>{{ directions }}</div>
    <div>MACD {{ crossLabel(primary!.macd_cross) }} · 距零轴 {{ primary!.macd_zero_distance_bps.toFixed(1) }} bps · 量 {{ ratio(primary!.volume_ratio_prev) }}</div>
    <div>Factor 条件观察 · <span>研究参数待冻结</span></div>
  </NAlert>
</template>

<style scoped>
.subing-strip { margin-bottom: 8px; }
.subing-strip :deep(.n-alert-body__content) { display: grid; gap: 4px; font-size: var(--gy-font-size-sm); }
.subing-strip__row { display: flex; justify-content: space-between; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
