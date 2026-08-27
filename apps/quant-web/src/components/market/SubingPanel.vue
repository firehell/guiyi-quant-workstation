<script setup lang="ts">
import { computed } from 'vue'
import { NSpin, NSwitch, NTag } from 'naive-ui'
import ProductTodayAlertEvents from '@/components/market/ProductTodayAlertEvents.vue'
import SubingStrategyRecords from '@/components/market/SubingStrategyRecords.vue'
import type { AlertRuntimeStatus, ProductAlertRuleState } from '@/api/alerts'
import {
  subingLifecycleProgressLabel,
  subingLifecycleStageLabel,
  subingSignalLabel,
  type AlertEvent,
  type SubingFactorSnapshot,
  type SubingResearchResponse,
  type SubingStrategyEpisode,
  type SubingStrategyCurrentResponse,
  type SubingSignal,
} from '@/types/market'
import { alertRuntimeLabel } from '@/utils/alertControl'
import {
  ALERT_RULE_CODES,
  isSubingStrategyAlertEvent,
  matchesAlertRuleCode,
  strategyActionLabel,
} from '@/utils/alertRules'
import { buildSubingLifecyclePivotFacts } from '@/utils/subingLifecycleFacts'

const props = defineProps<{
  snapshot: SubingResearchResponse | null
  supported: boolean
  loading: boolean
  error: boolean
  eventLoading: boolean
  eventStatus: 'ready' | 'unavailable' | null
  currentEvents: AlertEvent[]
  rules: ProductAlertRuleState[]
  runtimeStatus: AlertRuntimeStatus | null
  alertLoading: boolean
  savingRuleCodes: Set<string>
  strategyEpisodes: SubingStrategyEpisode[]
  strategyLoading: boolean
  strategyError: string | null
  strategySupported: boolean
  strategyCurrent: SubingStrategyCurrentResponse | null
  strategyCurrentLoading: boolean
  strategyCurrentError: string | null
  strategyReconciliationErrors: string[]
  showInternalProcess: boolean
}>()

const emit = defineEmits<{
  'toggle-subing-alert': [ruleCode: string, enabled: boolean]
}>()

const subingEvents = computed(() => props.currentEvents.filter(isSubingStrategyAlertEvent))
const strategyEvent = computed(() => [...subingEvents.value]
  .filter((event) => event.strategy_action !== null)
  .sort((left, right) => Date.parse(right.bar_end) - Date.parse(left.bar_end))[0] ?? null)
const remainingEvents = computed(() => {
  const selectedId = strategyEvent.value?.id
  return selectedId === undefined
    ? []
    : subingEvents.value.filter((event) => event.id !== selectedId)
})
const subingRule = computed(() => (
  props.rules.find((rule) => matchesAlertRuleCode(rule, ALERT_RULE_CODES.SUBING)) ?? null
))
const displayedSignal = computed(() => props.snapshot?.resolved_signal ?? props.snapshot?.primary_signal ?? null)
const runtimeLabel = computed(() => alertRuntimeLabel(props.runtimeStatus))
const runtimeTagType = computed(() => props.runtimeStatus === 'ok'
  ? 'success'
  : props.runtimeStatus === 'disabled' ? 'default' : 'warning')
const lifecycle = computed(() => props.snapshot?.lifecycle ?? null)
const lifecycleDirection = computed(() => {
  if (lifecycle.value?.direction === 'long') return '向上研究'
  if (lifecycle.value?.direction === 'short') return '向下研究'
  return '暂无方向'
})
const lifecyclePivotFacts = computed(() => (
  lifecycle.value ? buildSubingLifecyclePivotFacts(lifecycle.value) : []
))
const lifecycleTriggerLabel = computed(() => {
  if (lifecycle.value?.trigger_kind === 'pivot_break') {
    return lifecycle.value.direction === 'short' ? '前低突破' : '前高突破'
  }
  if (lifecycle.value?.trigger_kind === 'macd_cross') return 'MACD 交叉观察'
  return lifecycle.value?.trigger_kind || '—'
})
const lifecycleSourceLabel = computed(() => {
  switch (lifecycle.value?.confirmation_source) {
    case 'formal_v1': return 'Formal V1 研究对照'
    case 'momentum_hold': return '动量保持'
    case 'pivot_break_hold': return 'Pivot 突破保持'
    case 'pivot_retest_rebreak': return 'Pivot 回测再突破'
    default: return '—'
  }
})
const lifecycleTransitionLabel = computed(() => {
  const transition = lifecycle.value?.latest_transition
  return transition
    ? `${subingLifecycleStageLabel(transition.from_stage)} → ${subingLifecycleStageLabel(transition.to_stage)}`
    : '—'
})

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
  return `${value.timeframe} · ${direction(value.price_side)} · S5 ${value.slope_5_bps_per_bar.toFixed(1)} bps/bar · MACD ${cross(value.macd_cross)}`
}

function signal(value: SubingSignal) {
  const timeframe = value.trigger_timeframe ?? props.snapshot?.frequency ?? '—'
  const confirmation = value.lower_tf_confirmation ? ' · 低周期确认' : ''
  return `${timeframe} · ${subingSignalLabel(value)}${confirmation}`
}

function toggleSubing(ruleCode: string, enabled: boolean) {
  if (ruleCode !== ALERT_RULE_CODES.SUBING) return
  emit('toggle-subing-alert', ruleCode, enabled)
}
</script>

<template>
  <section class="subing-panel" data-testid="subing-panel">
    <header class="subing-panel__header">
      <div><span>苏冰</span><h3>品种研究面板</h3></div>
      <NTag size="small" type="info">Research only</NTag>
    </header>

    <SubingStrategyRecords
      v-if="strategySupported"
      :episodes="strategyEpisodes"
      :loading="strategyLoading"
      :error="strategyError"
      :current-episode="strategyCurrent?.current_episode ?? null"
      :latest-completed-episode="strategyCurrent?.latest_completed_episode ?? null"
      :current-loading="strategyCurrentLoading"
      :current-error="strategyCurrentError"
    />
    <p v-else data-testid="subing-strategy-guidance" class="subing-panel__warning">
      当前 5m 仅保留苏冰观察；历史策略投影仅支持真实主力 15m。
    </p>

    <section class="subing-panel__section" data-testid="subing-strategy-event">
      <h4>苏冰策略事件</h4>
      <p v-if="eventLoading">正在读取苏冰策略事件…</p>
      <p v-else-if="eventStatus === 'unavailable'" class="subing-panel__warning">苏冰策略事件暂不可用</p>
      <p v-else-if="eventStatus !== 'ready'">苏冰策略事件尚未读取</p>
      <div
        v-else-if="strategyEvent"
        class="subing-panel__formal-summary"
        :data-strategy-event-id="String(strategyEvent.id)"
      >
        <strong>{{ strategyActionLabel(strategyEvent.strategy_action!.kind) }}</strong>
        <p>不可变通知事实 · {{ strategyEvent.strategy_action!.contract }}</p>
      </div>
      <p v-else>当前无可展示的苏冰策略事件记录</p>
      <p v-if="strategyReconciliationErrors.includes('STRATEGY_ACTION_FACT_MISMATCH')" class="subing-panel__warning">
        STRATEGY_ACTION_FACT_MISMATCH · 图表采用 Canonical Historical 事实
      </p>
      <ProductTodayAlertEvents
        v-if="eventStatus === 'ready' && remainingEvents.length > 0"
        :items="remainingEvents"
        :rules="subingRule ? [subingRule] : []"
      />
    </section>

    <section class="subing-panel__section" data-testid="subing-current-research">
      <p v-if="!supported" class="subing-panel__warning">苏冰公开当前观察仅支持 5m / 15m；D1 / 60m 请查看每日观察。</p>
      <p v-else-if="loading">苏冰观察加载中</p>
      <p v-else-if="error || !snapshot" class="subing-panel__warning">苏冰观察暂不可用；K 线保留当前展示行情</p>
      <details v-else class="subing-panel__details" data-testid="subing-research-details">
        <summary>当前研究 / 数据身份 / 详细信息</summary>
        <p v-if="snapshot.primary.status !== 'ready' || !snapshot.primary.snapshot" class="subing-panel__warning">
          指标 warm-up 中 / 数据不足
        </p>
        <dl class="subing-panel__facts">
          <div v-if="displayedSignal"><dt>{{ snapshot.resolved_signal ? 'Resolved Signal' : 'Primary Signal' }}</dt><dd>{{ signal(displayedSignal) }}</dd></div>
          <div v-if="snapshot.resolved_signal"><dt>Primary Signal</dt><dd>{{ signal(snapshot.primary_signal) }}</dd></div>
          <div><dt>Primary 确认</dt><dd>{{ snapshot.primary.snapshot ? confirmed(snapshot.primary.snapshot.bar_end) : '—' }}</dd></div>
          <div class="subing-panel__factor"><dt>Primary Factor</dt><dd>{{ factor(snapshot.primary.snapshot) }}</dd></div>
          <template v-if="snapshot.companion">
            <div><dt>Companion 确认</dt><dd>{{ snapshot.companion.snapshot ? confirmed(snapshot.companion.snapshot.bar_end) : '—' }}</dd></div>
            <div class="subing-panel__factor"><dt>Companion Factor</dt><dd>{{ factor(snapshot.companion.snapshot) }}</dd></div>
          </template>
        </dl>

        <section v-if="showInternalProcess && lifecycle" data-testid="subing-lifecycle-panel" class="subing-panel__lifecycle">
          <div class="subing-panel__lifecycle-header">
            <div><span>苏冰生命周期 V2</span><strong>研究生命周期</strong></div>
            <NTag size="small" type="info">Research only</NTag>
          </div>
          <p class="subing-panel__funnel">准备 → 研究确认 → 延续 → 退出风险 → 本轮结束</p>
          <p v-if="lifecycle.availability !== 'ready'" class="subing-panel__warning">
            生命周期当前不可用{{ lifecycle.unavailable_reason ? ` · ${lifecycle.unavailable_reason}` : '' }}
          </p>
          <dl v-else class="subing-panel__facts">
            <div><dt>方向</dt><dd>{{ lifecycleDirection }}</dd></div>
            <div><dt>阶段</dt><dd>{{ subingLifecycleStageLabel(lifecycle.stage) }}</dd></div>
            <div><dt>触发来源</dt><dd>{{ lifecycleTriggerLabel }} · {{ lifecycleSourceLabel }}</dd></div>
            <div><dt>确认进度</dt><dd>{{ subingLifecycleProgressLabel(lifecycle) }}</dd></div>
            <div v-for="pivotFact in lifecyclePivotFacts" :key="pivotFact.role"><dt>{{ pivotFact.label }}</dt><dd>{{ pivotFact.price }}</dd></div>
            <div v-if="lifecycle.rebreak_reference_price !== null"><dt>再突破参考</dt><dd>{{ lifecycle.rebreak_reference_price }}</dd></div>
            <div><dt>风险 codes</dt><dd>{{ lifecycle.current_risk_codes.length ? lifecycle.current_risk_codes.join(' · ') : '—' }}</dd></div>
            <div><dt>最近状态转换</dt><dd>{{ lifecycleTransitionLabel }}</dd></div>
          </dl>
        </section>
        <dl class="subing-panel__facts subing-panel__identity">
          <div><dt>当前合约</dt><dd>{{ snapshot.actual_contract }}</dd></div>
          <div><dt>段起始</dt><dd>{{ snapshot.segment_start_trading_day }}</dd></div>
          <div><dt>数据模式</dt><dd>{{ snapshot.source_mode === 'canonical_live' ? 'Canonical + completed Live' : 'Canonical' }}</dd></div>
          <div><dt>MACD Policy</dt><dd>{{ snapshot.signal_macd_policy_id }}</dd></div>
        </dl>
      </details>
    </section>

    <section class="subing-panel__section" data-testid="subing-alert-scope">
      <h4>苏冰品种提醒</h4>
      <NSpin :show="alertLoading" size="small">
        <p v-if="alertLoading">正在读取苏冰提醒 Scope…</p>
        <div class="subing-panel__switch-row">
          <span>{{ subingRule ? `${subingRule.display_name} · 品种 Scope` : alertLoading ? '苏冰策略 · 品种 Scope' : '苏冰策略（不可用）' }}</span>
          <NSwitch
            :value="subingRule ? subingRule.enabled_for_product : false"
            :disabled="!subingRule || alertLoading || savingRuleCodes.has(ALERT_RULE_CODES.SUBING)"
            :loading="alertLoading || savingRuleCodes.has(ALERT_RULE_CODES.SUBING)"
            @update:value="toggleSubing(ALERT_RULE_CODES.SUBING, $event)"
          />
        </div>
        <template v-if="!alertLoading">
          <div class="subing-panel__switch-row">
            <span>Alert Runtime</span>
            <NTag size="small" :type="runtimeTagType">{{ runtimeLabel }}</NTag>
          </div>
        </template>
      </NSpin>
    </section>

  </section>
</template>

<style scoped>
.subing-panel { display: grid; gap: 12px; min-width: 0; }
.subing-panel__header, .subing-panel__lifecycle-header, .subing-panel__switch-row { display: flex; align-items: start; justify-content: space-between; gap: 10px; }
.subing-panel__formal-summary { display: grid; gap: 8px; }
.subing-panel__header span, .subing-panel__lifecycle-header span { display: block; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.subing-panel__header h3, .subing-panel__section h4 { margin: 2px 0 0; font-size: var(--gy-font-size-sm); }
.subing-panel__section { display: grid; gap: 8px; padding-top: 11px; border-top: 1px solid var(--gy-border); }
.subing-panel__section p, .subing-panel__details p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); line-height: 1.45; }
.subing-panel__warning { color: var(--gy-status-warning) !important; }
.subing-panel__facts { display: grid; gap: 8px; margin: 0; }
.subing-panel__facts > div { display: flex; align-items: start; justify-content: space-between; gap: 10px; min-width: 0; }
.subing-panel__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.subing-panel__facts dd { margin: 0; min-width: 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); overflow-wrap: anywhere; text-align: right; }
.subing-panel__factor { display: grid !important; gap: 4px !important; }
.subing-panel__factor dd { text-align: left; line-height: 1.45; }
.subing-panel__lifecycle { display: grid; gap: 9px; padding: 11px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-app); }
.subing-panel__lifecycle-header strong { display: block; margin-top: 2px; font-size: var(--gy-font-size-sm); }
.subing-panel__funnel { font-size: var(--gy-font-size-xs) !important; }
.subing-panel__switch-row { align-items: center; font-size: var(--gy-font-size-sm); }
.subing-panel__switch-row + .subing-panel__switch-row { margin-top: 8px; }
.subing-panel__details { border-top: 1px solid var(--gy-border); }
.subing-panel__details summary { padding-top: 11px; color: var(--gy-accent); font-size: var(--gy-font-size-sm); cursor: pointer; }
.subing-panel__details[open] summary { margin-bottom: 9px; }
.subing-panel__identity { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--gy-border); }
</style>
