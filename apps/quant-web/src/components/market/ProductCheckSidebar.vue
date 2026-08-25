<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NTag } from 'naive-ui'
import PriceVolumeOiPanel from '@/components/market/PriceVolumeOiPanel.vue'
import ProductAlertRules from '@/components/market/ProductAlertRules.vue'
import ProductTodayAlertEvents from '@/components/market/ProductTodayAlertEvents.vue'
import SubingResearchSection from '@/components/market/SubingResearchSection.vue'
import type { AlertRuntimeStatus, ProductAlertRuleState } from '@/api/alerts'
import type { EventState } from '@/types/executionReview'
import {
  subingLifecycleProgressLabel,
  subingLifecycleStageLabel,
  subingSignalLabel,
  type AlertEvent,
  type DominantContractItem,
  type KlineMarker,
  type MarketFrequency,
  type ProductResearchResponse,
  type ResearchOverlayId,
  type SeriesKind,
  type SubingFactorSnapshot,
  type SubingResearchResponse,
} from '@/types/market'
import { summarizeFormalEvent, summarizeMarketBackground } from '@/utils/productCheck'

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
  currentEventStates: Record<number, EventState>
  htdyObservation: KlineMarker | null
}>()

const emit = defineEmits<{
  'toggle-alert': [ruleCode: string, enabled: boolean]
  'open-formal-event': [event: AlertEvent, state: EventState | null]
}>()

const formalEvent = computed(() => summarizeFormalEvent(props.currentEvents, props.currentEventStates))
const moreOpen = ref(false)
const background = computed(() => props.research
  ? summarizeMarketBackground(props.research.daily_trend, props.research.weekly_trend)
  : null)
const subingSignal = computed(() => props.subing?.resolved_signal ?? props.subing?.primary_signal ?? null)
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

function factorDirection(snapshot: SubingFactorSnapshot | null | undefined) {
  if (!snapshot) return '—'
  return snapshot.price_side === 'above' ? '↑' : snapshot.price_side === 'below' ? '↓' : '→'
}

function subingDirections() {
  const primary = props.subing?.primary.snapshot
  const companion = props.subing?.companion?.snapshot
  if (!primary) return ''
  const primaryLabel = `${primary.timeframe} ${factorDirection(primary)}`
  if (!companion) return primaryLabel
  const resonance = primary.price_side === companion.price_side ? '同向' : '分歧'
  return `${primaryLabel} / ${companion.timeframe} ${factorDirection(companion)} · ${resonance}`
}

function subingSignalSummary() {
  if (!subingSignal.value || !props.subing) return ''
  const timeframe = subingSignal.value.trigger_timeframe ?? props.subing.frequency
  const confirmation = subingSignal.value.lower_tf_confirmation ? ' · 低周期确认' : ''
  return `${timeframe} · ${subingSignalLabel(subingSignal.value)}${confirmation}`
}

function lifecycleProgress() {
  const lifecycle = props.subing?.lifecycle
  if (!lifecycle || lifecycle.availability !== 'ready') return '当前不可用'
  const progress = subingLifecycleProgressLabel(lifecycle)
  return `${subingLifecycleStageLabel(lifecycle.stage)}${progress === '—' ? '' : ` · ${progress}`}`
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

function updateMoreOpen(event: Event) {
  moreOpen.value = (event.currentTarget as HTMLDetailsElement).open
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

    <section class="product-check-sidebar__section" data-testid="product-check-now">
      <h3>1. 现在</h3>
      <p v-if="currentEventsLoading">正在读取正式事件…</p>
      <p v-else-if="currentEventsStatus === 'unavailable'" class="product-check-sidebar__warning">正式事件暂不可用</p>
      <template v-else-if="formalEvent">
        <strong>{{ formalEvent.headline }}</strong>
        <NButton
          v-if="formalEvent.actionLabel"
          size="small"
          type="primary"
          @click="emit('open-formal-event', formalEvent.event, formalEvent.state)"
        >{{ formalEvent.actionLabel }}</NButton>
        <p v-else>今日正式提醒记录</p>
      </template>
      <template v-else-if="currentEventsStatus === 'ready'">
        <strong>当前无正式事件</strong>
        <p>继续观察</p>
      </template>
      <p v-else>正式事件尚未读取</p>
    </section>

    <section class="product-check-sidebar__section" data-testid="product-check-background">
      <h3>2. 市场背景</h3>
      <p v-if="researchLoading">正在读取周线 / 日线…</p>
      <p v-else-if="researchError || !research" class="product-check-sidebar__warning">周线 / 日线数据不可用</p>
      <template v-else>
        <dl class="product-check-sidebar__facts">
          <div><dt>周线</dt><dd>{{ trendLabel(research.weekly_trend) }}</dd></div>
          <div><dt>日线</dt><dd>{{ trendLabel(research.daily_trend) }}</dd></div>
        </dl>
        <NTag size="small" :class="`product-check-sidebar__tone--${background?.tone}`">{{ background?.label }}</NTag>
      </template>
    </section>

    <section class="product-check-sidebar__section" data-testid="product-check-observation">
      <h3>3. 当前观察</h3>
      <p v-if="selectedOverlay === 'none'">当前未选择策略观察</p>
      <template v-else-if="selectedOverlay === 'subing'">
        <p v-if="!subingSupported" class="product-check-sidebar__warning">苏冰当前周期不可用，仅支持 5m / 15m / 1d</p>
        <p v-else-if="subingLoading">苏冰观察加载中</p>
        <p v-else-if="subingError || !subing" class="product-check-sidebar__warning">苏冰观察暂不可用；K 线保留当前展示行情</p>
        <p v-else-if="subing.primary.status !== 'ready' || !subing.primary.snapshot" class="product-check-sidebar__warning">苏冰 · 指标 warm-up 中 / 数据不足</p>
        <template v-else>
          <strong>苏冰 · {{ subingSignalSummary() }}</strong>
          <p>{{ subingDirections() }}</p>
          <div class="product-check-sidebar__lifecycle">
            <span>Lifecycle · {{ lifecycleProgress() }}</span>
            <NTag size="small" type="info">Research only</NTag>
          </div>
        </template>
      </template>
      <template v-else>
        <strong v-if="htdyObservation">火天大有 · {{ htdyObservationLabel(htdyObservation) }} · {{ observationTime(htdyObservation.time) }}</strong>
        <p v-else>火天大有暂无当前观察</p>
        <p class="product-check-sidebar__warning">原始观察可能重绘，仅供人工观察</p>
      </template>
    </section>

    <section class="product-check-sidebar__section" data-testid="product-check-participation">
      <h3>4. 位置 / 参与</h3>
      <p v-if="researchLoading">正在读取参与数据…</p>
      <p v-else-if="researchError || !research" class="product-check-sidebar__warning">位置 / 参与数据不可用</p>
      <dl v-else class="product-check-sidebar__facts">
        <div><dt>20日位置</dt><dd>{{ percent(research.position20) }}</dd></div>
        <div><dt>量比20</dt><dd>{{ ratio(research.volume_ratio20) }}</dd></div>
        <div><dt>OI 1D</dt><dd>{{ percent(research.oi_change_1d) }}</dd></div>
        <div><dt>ATR 分位</dt><dd>{{ percent(research.atr14_percentile252) }}</dd></div>
      </dl>
    </section>

    <section class="product-check-sidebar__section" data-testid="product-check-alerts">
      <h3>5. 提醒</h3>
      <ProductAlertRules
        :rules="alertRules"
        :runtime-status="alertRuntimeStatus"
        :loading="alertLoading"
        :saving-rule-codes="savingRuleCodes"
        @toggle="(ruleCode, enabled) => emit('toggle-alert', ruleCode, enabled)"
      />
    </section>

    <details
      class="product-check-sidebar__more"
      data-testid="product-check-more"
      @toggle="updateMoreOpen"
    >
      <summary>6. 更多研究</summary>
      <div v-if="moreOpen" class="product-check-sidebar__more-content">
        <SubingResearchSection
          v-if="selectedOverlay === 'subing'"
          :snapshot="subing"
          :loading="subingLoading"
          :error="subingError"
          :supported="subingSupported"
        />
        <ProductTodayAlertEvents
          :loading="currentEventsLoading"
          :status="currentEventsStatus"
          :items="currentEvents"
          :rules="alertRules"
        />
        <PriceVolumeOiPanel v-if="research" :daily="research.recent_daily" />
        <p v-else-if="researchError" class="product-check-sidebar__warning">研究数据暂不可用；K 线保留当前展示行情。</p>
        <section>
          <h4>数据 / 合约详情</h4>
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
        </section>
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
.product-check-sidebar__section h3, .product-check-sidebar__more h4 { margin: 0; font-size: var(--gy-font-size-sm); }
.product-check-sidebar__section p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); line-height: 1.45; }
.product-check-sidebar__warning { color: var(--gy-status-warning) !important; }
.product-check-sidebar__facts { display: grid; gap: 7px; margin: 0; }
.product-check-sidebar__facts > div { display: flex; align-items: start; justify-content: space-between; gap: 10px; min-width: 0; }
.product-check-sidebar__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.product-check-sidebar__facts dd { margin: 0; min-width: 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); overflow-wrap: anywhere; text-align: right; }
.product-check-sidebar__lifecycle { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--gy-text-secondary); font-size: var(--gy-font-size-sm); }
.product-check-sidebar__tone--up { color: var(--gy-up); }
.product-check-sidebar__tone--down { color: var(--gy-down); }
.product-check-sidebar__tone--warning { color: var(--gy-status-warning); }
.product-check-sidebar__more { border-top: 1px solid var(--gy-border); }
.product-check-sidebar__more > summary { padding: 13px 0; color: var(--gy-accent); font-size: var(--gy-font-size-sm); font-weight: 500; cursor: pointer; }
.product-check-sidebar__more-content { display: grid; gap: 16px; padding-bottom: 8px; }
.product-check-sidebar__more-content :deep(.price-volume-oi) { padding: 10px; }
</style>
