<script setup lang="ts">
import {
  subingSignalLabel,
  type SubingFactorSnapshot,
  type SubingResearchResponse,
  type SubingSignal,
} from '@/types/market'

defineProps<{
  snapshot: SubingResearchResponse | null
  loading: boolean
  error: boolean
  supported: boolean
}>()

function direction(value: SubingFactorSnapshot['price_side']) {
  return value === 'above' ? 'EMA21 上方' : value === 'below' ? 'EMA21 下方' : 'EMA21 附近'
}

function cross(value: SubingFactorSnapshot['macd_cross']) {
  return value === 'golden' ? '金叉' : value === 'dead' ? '死叉' : value === 'none' ? '无新交叉' : '不可用'
}

function confirmed(value: string) {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(timestamp)
}

function factor(value: SubingFactorSnapshot | null | undefined) {
  if (!value) return 'warm-up 中'
  return `${direction(value.price_side)} · S5 ${value.slope_5_bps_per_bar.toFixed(1)} bps/bar · MACD ${cross(value.macd_cross)}`
}

function signal(value: SubingSignal) {
  const timeframe = value.trigger_timeframe ?? '—'
  const confirmation = value.lower_tf_confirmation ? ' · 低周期确认' : ''
  return `${timeframe} · ${subingSignalLabel(value)}${confirmation}`
}
</script>

<template>
  <section class="subing-research">
    <h3>苏冰研究明细</h3>
    <p v-if="!supported" class="subing-research__unavailable">V1 仅支持 5m / 15m / 1d</p>
    <p v-else-if="loading" class="subing-research__unavailable">读取 Factor 快照…</p>
    <p v-else-if="error || !snapshot" class="subing-research__unavailable">Factor 快照暂不可用</p>
    <dl v-else class="subing-research__facts">
      <div><dt>当前合约</dt><dd>{{ snapshot.actual_contract }}</dd></div>
      <div><dt>段起始</dt><dd>{{ snapshot.segment_start_trading_day }}</dd></div>
      <div><dt>数据模式</dt><dd>{{ snapshot.source_mode === 'canonical_live' ? 'Canonical + completed Live' : 'Canonical' }}</dd></div>
      <div><dt>Primary Signal</dt><dd>{{ signal(snapshot.primary_signal) }}</dd></div>
      <div v-if="snapshot.resolved_signal"><dt>Resolved Signal</dt><dd>{{ signal(snapshot.resolved_signal) }}</dd></div>
      <div><dt>Primary 确认</dt><dd>{{ snapshot.primary.snapshot ? confirmed(snapshot.primary.snapshot.bar_end) : '—' }}</dd></div>
      <div class="subing-research__factor"><dt>Primary Factor</dt><dd>{{ factor(snapshot.primary.snapshot) }}</dd></div>
      <template v-if="snapshot.companion">
        <div><dt>Companion 确认</dt><dd>{{ snapshot.companion.snapshot ? confirmed(snapshot.companion.snapshot.bar_end) : '—' }}</dd></div>
        <div class="subing-research__factor"><dt>Companion Factor</dt><dd>{{ factor(snapshot.companion.snapshot) }}</dd></div>
      </template>
    </dl>
  </section>
</template>

<style scoped>
.subing-research h3 { margin: 0; font-size: var(--gy-font-size-sm); }
.subing-research__facts { margin: 16px 0 0; display: grid; gap: 10px; }
.subing-research__facts > div { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
.subing-research__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.subing-research__facts dd { margin: 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); text-align: right; }
.subing-research__factor { display: grid !important; gap: 4px !important; }
.subing-research__factor dd { text-align: left; line-height: 1.45; }
.subing-research__unavailable { margin: 12px 0 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
