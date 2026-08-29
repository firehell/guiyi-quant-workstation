<script setup lang="ts">
import { computed, ref } from 'vue'
import { NTag } from 'naive-ui'
import PriceVolumeOiPanel from '@/components/market/PriceVolumeOiPanel.vue'
import ProductAlertRules from '@/components/market/ProductAlertRules.vue'
import SubingPanel from '@/components/market/SubingPanel.vue'
import type { AlertRuntimeStatus, ProductAlertRuleState } from '@/api/alerts'
import {
  type AlertEvent,
  type DominantContractItem,
  type KlineMarker,
  type MarketFrequency,
  type ProductResearchResponse,
  type ResearchOverlayId,
  type SeriesKind,
  type SubingResearchResponse,
  type SubingStrategyEpisode,
  type SubingStrategyCurrentResponse,
} from '@/types/market'
import {
  ALERT_RULE_CODES,
  isSubingStrategyAlertEvent,
  matchesAlertRuleCode,
} from '@/utils/alertRules'
import { summarizeMarketBackground } from '@/utils/productCheck'

const props = defineProps<{
  dominant: DominantContractItem | undefined
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract: string
  live: boolean
  phase: string
  hasMoreBefore: boolean
  canonicalCoverage: { start: string; end: string } | null
  research: ProductResearchResponse | null
  researchLoading: boolean
  researchError: boolean
  selectedOverlay: ResearchOverlayId
  subing: SubingResearchResponse | null
  subingLoading: boolean
  subingError: boolean
  subingSupported: boolean
  alertRules: ProductAlertRuleState[]
  alertRuntimeStatus: AlertRuntimeStatus | null
  alertLoading: boolean
  savingRuleCodes: Set<string>
  currentEventsLoading: boolean
  currentEventsStatus: 'ready' | 'unavailable' | null
  currentEvents: AlertEvent[]
  htdyObservation: KlineMarker | null
  subingStrategyEpisodes: SubingStrategyEpisode[]
  subingStrategyLoading: boolean
  subingStrategyError: string | null
  subingStrategySupported: boolean
  subingStrategyCurrent: SubingStrategyCurrentResponse | null
  subingStrategyCurrentLoading: boolean
  subingStrategyCurrentError: string | null
  subingStrategyReconciliationErrors: string[]
  showSubingInternalProcess: boolean
  focusedActionId?: string | null
}>()

const emit = defineEmits<{
  'toggle-subing-alert': [ruleCode: string, enabled: boolean]
  'toggle-htdy-alert': [ruleCode: string, enabled: boolean]
}>()

const dataDetailsOpen = ref(false)
const background = computed(() => props.research
  ? summarizeMarketBackground(props.research.daily_trend, props.research.weekly_trend)
  : null)
const subingEvents = computed(() => props.currentEvents.filter((event) => (
  isSubingStrategyAlertEvent(event)
)))
const subingRules = computed(() => props.alertRules.filter((rule) => (
  matchesAlertRuleCode(rule, ALERT_RULE_CODES.SUBING)
)))
const seriesLabel = computed(() => {
  if (props.seriesKind === 'actual_dominant') return '真实主力'
  if (props.seriesKind === 'continuous') return '主连'
  return '指定合约'
})

function trendLabel(value: ProductResearchResponse['daily_trend']) {
  return value === 'up' ? '上行' : value === 'down' ? '下行' : value === 'neutral' ? '中性' : '数据不足'
}

function percent(value: number | null) {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function ratio(value: number | null) {
  return value === null ? '—' : `${value.toFixed(2)}x`
}

function htdyObservationLabel(marker: KlineMarker) {
  if (marker.label === '买观察') return '买入观察'
  if (marker.label === '卖观察') return '卖出观察'
  return marker.label || '观察不可用'
}

function observationTime(value: string) {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '--:--'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

function updateDataDetailsOpen(event: Event) {
  dataDetailsOpen.value = (event.currentTarget as HTMLDetailsElement).open
}
</script>

<template>
  <aside class="product-check-sidebar product-workspace__sidebar" data-testid="product-check-sidebar">
    <header class="product-check-sidebar__header">
      <div>
        <span>当前检查栏</span>
        <strong>{{ dominant?.product.toUpperCase() || '--' }} {{ dominant?.product_name || '' }}</strong>
      </div>
    </header>

    <section class="product-check-sidebar__section" data-testid="product-check-observation">
      <h3>1. 当前观察</h3>
      <p v-if="selectedOverlay === 'none'">当前未选择策略观察</p>
      <SubingPanel
        v-else-if="selectedOverlay === 'subing'"
        :snapshot="subing"
        :supported="subingSupported"
        :loading="subingLoading"
        :error="subingError"
        :event-loading="currentEventsLoading"
        :event-status="currentEventsStatus"
        :current-events="subingEvents"
        :rules="subingRules"
        :runtime-status="alertRuntimeStatus"
        :alert-loading="alertLoading"
        :saving-rule-codes="savingRuleCodes"
        :strategy-episodes="subingStrategyEpisodes"
        :strategy-loading="subingStrategyLoading"
        :strategy-error="subingStrategyError"
        :strategy-supported="subingStrategySupported"
        :strategy-current="subingStrategyCurrent"
        :strategy-current-loading="subingStrategyCurrentLoading"
        :strategy-current-error="subingStrategyCurrentError"
        :strategy-reconciliation-errors="subingStrategyReconciliationErrors"
        :show-internal-process="showSubingInternalProcess"
        :focused-action-id="focusedActionId ?? null"
        @toggle-subing-alert="(ruleCode, enabled) => emit('toggle-subing-alert', ruleCode, enabled)"
      />
      <template v-else-if="selectedOverlay === 'htdy'">
        <strong v-if="htdyObservation">火天大有 · {{ htdyObservationLabel(htdyObservation) }} · {{ observationTime(htdyObservation.time) }}</strong>
        <p v-else>火天大有暂无当前观察</p>
        <p class="product-check-sidebar__warning">原始观察可能重绘，仅供人工观察</p>
        <ProductAlertRules
          :rules="alertRules"
          :frequency="frequency"
          :runtime-status="alertRuntimeStatus"
          :loading="alertLoading"
          :saving-rule-codes="savingRuleCodes"
          @toggle="(ruleCode, enabled) => emit('toggle-htdy-alert', ruleCode, enabled)"
        />
      </template>
    </section>

    <section class="product-check-sidebar__section" data-testid="product-check-background">
      <h3>2. 市场背景</h3>
      <p v-if="researchLoading">正在读取周线 / 日线…</p>
      <p v-else-if="researchError || !research" class="product-check-sidebar__warning">市场背景数据不可用</p>
      <template v-else>
        <dl class="product-check-sidebar__facts">
          <div><dt>周线</dt><dd>{{ trendLabel(research.weekly_trend) }}</dd></div>
          <div><dt>日线</dt><dd>{{ trendLabel(research.daily_trend) }}</dd></div>
          <div><dt>20日位置</dt><dd>{{ percent(research.position20) }}</dd></div>
          <div><dt>量比20</dt><dd>{{ ratio(research.volume_ratio20) }}</dd></div>
          <div><dt>OI 1D</dt><dd>{{ percent(research.oi_change_1d) }}</dd></div>
          <div><dt>ATR 分位</dt><dd>{{ percent(research.atr14_percentile252) }}</dd></div>
        </dl>
        <NTag size="small" :class="`product-check-sidebar__tone--${background?.tone}`">{{ background?.label }}</NTag>
      </template>
    </section>

    <details
      class="product-check-sidebar__details"
      data-testid="product-check-data-details"
      @toggle="updateDataDetailsOpen"
    >
      <summary>3. 数据详情</summary>
      <div v-if="dataDetailsOpen" class="product-check-sidebar__details-content">
        <PriceVolumeOiPanel v-if="research" :daily="research.recent_daily" />
        <p v-else-if="researchError" class="product-check-sidebar__warning">研究数据暂不可用；K 线保留当前展示行情。</p>
        <dl class="product-check-sidebar__facts">
          <div><dt>序列</dt><dd>{{ seriesLabel }}</dd></div>
          <div><dt>周期</dt><dd>{{ frequency }}</dd></div>
          <div><dt>当前合约</dt><dd>{{ seriesKind === 'contract' ? contract : dominant?.actual_contract || '--' }}</dd></div>
          <div><dt>映射日</dt><dd>{{ dominant?.dominant_mapping_date || '--' }}</dd></div>
          <div><dt>数据状态</dt><dd>{{ live ? 'Live' : 'Historical' }}</dd></div>
          <div><dt>市场状态</dt><dd>{{ phase }}</dd></div>
          <div><dt>Canonical 覆盖</dt><dd>{{ canonicalCoverage ? `${canonicalCoverage.start} → ${canonicalCoverage.end}` : '—' }}</dd></div>
          <div><dt>历史边界</dt><dd>{{ hasMoreBefore ? '可继续向左加载' : '已到当前可读边界' }}</dd></div>
        </dl>
      </div>
    </details>
  </aside>
</template>

<style scoped>
.product-check-sidebar { min-width: 0; padding: 14px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.product-check-sidebar__header { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.product-check-sidebar__header span { display: block; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.product-check-sidebar__header strong { display: block; margin-top: 2px; }
.product-check-sidebar__section { display: grid; gap: 8px; padding: 13px 0; border-top: 1px solid var(--gy-border); }
.product-check-sidebar__section:first-of-type { margin-top: 12px; }
.product-check-sidebar__section h3 { margin: 0; font-size: var(--gy-font-size-sm); }
.product-check-sidebar__section p, .product-check-sidebar__details p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); line-height: 1.45; }
.product-check-sidebar__warning { color: var(--gy-status-warning) !important; }
.product-check-sidebar__facts { display: grid; gap: 7px; margin: 0; }
.product-check-sidebar__facts > div { display: flex; align-items: start; justify-content: space-between; gap: 10px; min-width: 0; }
.product-check-sidebar__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.product-check-sidebar__facts dd { margin: 0; min-width: 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); overflow-wrap: anywhere; text-align: right; }
.product-check-sidebar__tone--up { color: var(--gy-up); }
.product-check-sidebar__tone--down { color: var(--gy-down); }
.product-check-sidebar__tone--warning { color: var(--gy-status-warning); }
.product-check-sidebar__details { border-top: 1px solid var(--gy-border); }
.product-check-sidebar__details > summary { padding: 13px 0; color: var(--gy-accent); font-size: var(--gy-font-size-sm); font-weight: 500; cursor: pointer; }
.product-check-sidebar__details-content { display: grid; gap: 16px; padding-bottom: 8px; }
.product-check-sidebar__details-content :deep(.price-volume-oi) { padding: 10px; }
</style>
