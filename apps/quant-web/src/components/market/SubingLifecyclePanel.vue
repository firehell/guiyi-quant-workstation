<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'
import {
  subingLifecycleStageLabel,
  type SubingLifecycleSnapshot,
} from '@/types/market'

const props = defineProps<{
  lifecycle: SubingLifecycleSnapshot
}>()

const direction = computed(() => {
  if (props.lifecycle.direction === 'long') return '向上研究'
  if (props.lifecycle.direction === 'short') return '向下研究'
  return '暂无方向'
})
const progress = computed(() => props.lifecycle.hold_required > 0
  ? `${props.lifecycle.hold_count}/${props.lifecycle.hold_required}`
  : '—')
const pivotLabel = computed(() => props.lifecycle.bound_reference_pivot?.kind === 'low' ? '绑定前低' : '绑定前高')
const triggerLabel = computed(() => {
  if (props.lifecycle.trigger_kind === 'pivot_break') {
    return props.lifecycle.direction === 'short' ? '前低突破' : '前高突破'
  }
  if (props.lifecycle.trigger_kind === 'macd_cross') return 'MACD 交叉观察'
  return props.lifecycle.trigger_kind || '—'
})
const sourceLabel = computed(() => {
  switch (props.lifecycle.confirmation_source) {
    case 'formal_v1': return 'Formal V1 研究对照'
    case 'momentum_hold': return '动量保持'
    case 'pivot_break_hold': return 'Pivot 突破保持'
    case 'pivot_retest_rebreak': return 'Pivot 回测再突破'
    default: return '—'
  }
})
const transitionLabel = computed(() => {
  const transition = props.lifecycle.latest_transition
  if (!transition) return '—'
  return `${subingLifecycleStageLabel(transition.from_stage)} → ${subingLifecycleStageLabel(transition.to_stage)}`
})
</script>

<template>
  <section data-testid="subing-lifecycle-panel" class="subing-lifecycle-panel">
    <div class="subing-lifecycle-panel__header">
      <div>
        <span class="subing-lifecycle-panel__eyebrow">SuBing Lifecycle V2</span>
        <strong>研究生命周期</strong>
      </div>
      <NTag size="small" type="info">Research only</NTag>
    </div>
    <p class="subing-lifecycle-panel__funnel" aria-label="研究漏斗">准备 → 研究确认 → 延续 → 退出风险 → 本轮结束</p>
    <p v-if="lifecycle.availability !== 'ready'" class="subing-lifecycle-panel__unavailable">
      生命周期当前不可用{{ lifecycle.unavailable_reason ? ` · ${lifecycle.unavailable_reason}` : '' }}
    </p>
    <dl v-else class="subing-lifecycle-panel__facts">
      <div><dt>方向</dt><dd>{{ direction }}</dd></div>
      <div><dt>阶段</dt><dd>{{ subingLifecycleStageLabel(lifecycle.stage) }}</dd></div>
      <div><dt>触发来源</dt><dd>{{ triggerLabel }} · {{ sourceLabel }}</dd></div>
      <div><dt>确认进度</dt><dd>{{ progress }}</dd></div>
      <div v-if="lifecycle.bound_reference_pivot"><dt>{{ pivotLabel }}</dt><dd>{{ lifecycle.bound_reference_pivot.price }}</dd></div>
      <div v-if="lifecycle.rebreak_reference_price !== null"><dt>再突破参考</dt><dd>{{ lifecycle.rebreak_reference_price }}</dd></div>
      <div><dt>风险 codes</dt><dd>{{ lifecycle.current_risk_codes.length ? lifecycle.current_risk_codes.join(' · ') : '—' }}</dd></div>
      <div><dt>最近状态转换</dt><dd>{{ transitionLabel }}</dd></div>
    </dl>
  </section>
</template>

<style scoped>
.subing-lifecycle-panel { display: grid; gap: 10px; margin-top: 14px; padding: 12px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-app); min-width: 0; }
.subing-lifecycle-panel__header { display: flex; justify-content: space-between; gap: 8px; align-items: start; }
.subing-lifecycle-panel__header strong { display: block; margin-top: 2px; font-size: var(--gy-font-size-sm); }
.subing-lifecycle-panel__eyebrow { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.subing-lifecycle-panel__funnel { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); line-height: 1.5; }
.subing-lifecycle-panel__facts { display: grid; gap: 8px; margin: 0; }
.subing-lifecycle-panel__facts > div { display: flex; justify-content: space-between; align-items: start; gap: 12px; min-width: 0; }
.subing-lifecycle-panel__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); flex: 0 0 auto; }
.subing-lifecycle-panel__facts dd { margin: 0; min-width: 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); overflow-wrap: anywhere; text-align: right; }
.subing-lifecycle-panel__unavailable { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); overflow-wrap: anywhere; }
</style>
