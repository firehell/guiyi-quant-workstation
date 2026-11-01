<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'

import NewowPublicPatternsPanel from '@/components/market/detail/newow/NewowPublicPatternsPanel.vue'
import { buildNewowPatternGeometry, type PatternChoice } from '@/utils/newowPatternDisplay'
import type { NewowProductChartBar } from '@/components/market/detail/newow/newowProductChartPrimitives'
import FreeChartStage from '@/components/market/detail/free/FreeChartStage.vue'
import { rangeDetectorStatusText } from '@/utils/rangeDetectorStatus'
import { useRangeDetectorOverlayWarmup } from '@/composables/useRangeDetectorOverlayWarmup'
import type { BarData, OptionalEmaIndicatorId, ProductResearchResponse } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import type { FlexibleDetailPreferences } from '@/utils/marketDetailPreferences'

const props = defineProps<{
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  bars: BarData[]
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  research: ProductResearchResponse | null
  researchError: boolean
  preferences: FlexibleDetailPreferences
  hasMoreBefore: boolean; loadingBefore?: boolean; historyError?: string | null
  loadEarlier: () => Promise<void>
  identityWarning?: string | null
}>()
const emit = defineEmits<{
  'focus-resolved': [focusBarEnd: string]
  updatePreferences: [preferences: FlexibleDetailPreferences]
}>()

const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([...props.preferences.optionalEmaIndicators])
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const showPatterns = ref(false)
const patternSelection = shallowRef<PatternChoice | null>(null)
const patternBars = computed<NewowProductChartBar[]>(() => props.bars.some(bar => !bar.physicalContract || !bar.trading_day) ? [] : props.bars.map(bar => ({
  ...bar, barEnd: bar.time, tradingDay: bar.trading_day ?? '',
  physicalContract: bar.physicalContract ?? '', segmentId: bar.calculationSegmentId ?? '',
  calculationSegmentId: bar.calculationSegmentId ?? '', sourceIdentity: sourceIdentity.value,
})))
const patternRevision = ref(0)
watch(() => props.mutation, () => { patternRevision.value++ }, { deep: true, flush: 'sync' })
const patternWindowKey = computed(() => JSON.stringify([sourceIdentity.value, patternRevision.value]))
const patternGeometry = computed(() => {
  const choice = patternSelection.value
  if (!showPatterns.value || props.loading || props.error || !choice || choice.windowKey !== patternWindowKey.value) return null
  try { return buildNewowPatternGeometry(choice, props.identity.frequency) } catch { return null }
})
watch([showPatterns, patternWindowKey], () => { patternSelection.value = null }, { flush: 'sync' })
const showRangeDetector = ref(props.preferences.showRangeDetector)
const visibleFrom = ref<string | null>(null)
const rangeCount = ref(0)
watch(sourceIdentity, () => { visibleFrom.value = null; rangeCount.value = 0 }, { flush: 'sync' })
const bars = computed(() => props.bars)
const hasMoreBefore = computed(() => props.hasMoreBefore)
const rangeWarmup = useRangeDetectorOverlayWarmup({
  bars,
  visibleFrom,
  hasMoreBefore,
  enabled: showRangeDetector,
  identityKey: sourceIdentity,
  loadMoreBefore: () => props.loadEarlier(),
})
const rangeState = computed<'disabled' | 'loading' | 'ready' | 'insufficient'>(() => {
  if (!showRangeDetector.value) return 'disabled'
  if (rangeWarmup.loading.value) return 'loading'
  return rangeWarmup.unavailableReason.value === null && rangeWarmup.anchorTime.value ? 'ready' : 'insufficient'
})
const indicators = computed(() => [
  ...optionalEmaIndicators.value,
  ...(showRangeDetector.value ? ['range_detector' as const] : []),
])
const emaIndicatorControls = [
  { id: 'ema_10', label: 'EMA10', tone: 'ema10' },
  { id: 'ema_21', label: 'EMA21', tone: 'ema21' },
  { id: 'ema_60', label: 'EMA60', tone: 'ema60' },
] as const
const rangeIndicatorLabel = computed(() => rangeState.value === 'loading' ? '箱体识别 · 加载中' : '箱体识别')
function updatePreferences(identity: MarketDetailIdentity) {
  emit('updatePreferences', {
    seriesKind: 'actual_dominant',
    frequency: identity.frequency,
    optionalEmaIndicators: [...optionalEmaIndicators.value],
    showRangeDetector: showRangeDetector.value,
  })
}

watch([optionalEmaIndicators, showRangeDetector], () => {
  updatePreferences(props.identity)
  if (!showRangeDetector.value) rangeWarmup.reset()
}, { deep: true })

watch(() => props.identity, () => {
  updatePreferences(props.identity)
}, { deep: true })

watch(() => props.preferences, (preferences) => {
  if (
    preferences.optionalEmaIndicators.length !== optionalEmaIndicators.value.length
    || preferences.optionalEmaIndicators.some((indicator, index) => indicator !== optionalEmaIndicators.value[index])
  ) optionalEmaIndicators.value = [...preferences.optionalEmaIndicators]
  if (preferences.showRangeDetector !== showRangeDetector.value) {
    showRangeDetector.value = preferences.showRangeDetector
  }
}, { deep: true })

function toggleEma(value: OptionalEmaIndicatorId) {
  optionalEmaIndicators.value = optionalEmaIndicators.value.includes(value)
    ? optionalEmaIndicators.value.filter((item) => item !== value)
    : [...optionalEmaIndicators.value, value]
}

function toggleRangeDetector() {
  showRangeDetector.value = !showRangeDetector.value
}

function loadEarlier() { void props.loadEarlier() }
</script>

<template>
  <section class="free-workspace" data-detail-workspace="free" :data-range-detector-status="rangeWarmup.status.value" :data-range-detector-visible-from="visibleFrom" :data-range-detector-warmup="rangeState" :data-range-detector-anchor="rangeWarmup.anchorTime.value" :data-range-detector-source-identity="sourceIdentity">
    <div class="free-workspace__indicators" role="group" aria-label="主图指标">
      <span class="free-workspace__indicators-title">指标</span>
      <button
        v-for="item in emaIndicatorControls"
        :key="item.id"
        class="indicator-chip"
        :class="[`indicator-chip--${item.tone}`, { 'indicator-chip--active': optionalEmaIndicators.includes(item.id) }]"
        type="button"
        :aria-pressed="optionalEmaIndicators.includes(item.id)"
        @click="toggleEma(item.id)"
      >
        <span class="indicator-chip__dot" aria-hidden="true" />
        {{ item.label }}
        <span v-if="optionalEmaIndicators.includes(item.id)" class="indicator-chip__check" aria-hidden="true">✓</span>
      </button>
      <button
        class="indicator-chip indicator-chip--range"
        :class="{ 'indicator-chip--active': showRangeDetector }"
        type="button"
        :aria-pressed="showRangeDetector"
        @click="toggleRangeDetector"
      >
        <span class="indicator-chip__dot" aria-hidden="true" />
        {{ rangeIndicatorLabel }}
        <span v-if="showRangeDetector" class="indicator-chip__check" aria-hidden="true">✓</span>
      </button>
      <button class="indicator-chip indicator-chip--patterns" :class="{ 'indicator-chip--active': showPatterns }" type="button" :aria-pressed="showPatterns" @click="showPatterns = !showPatterns">
        <span class="indicator-chip__dot" aria-hidden="true" />形态识别
        <span v-if="showPatterns" class="indicator-chip__check" aria-hidden="true">✓</span>
      </button>
    </div>
    <NewowPublicPatternsPanel v-if="showPatterns" :bars="patternBars" :period="identity.frequency" :window-key="patternWindowKey" @select="patternSelection = $event" @preview="patternSelection = $event" @clear="patternSelection = null" />
    <p v-if="identityWarning" class="free-workspace__hint" role="status">{{ identityWarning }}</p>
    <p v-if="showRangeDetector" class="free-workspace__hint" role="status">{{ rangeDetectorStatusText(rangeWarmup.status.value, rangeCount) }} 历史图形参考；加载更早数据可能修订箱体。</p>
    <div class="free-workspace__chart-surface"><div id="detail-chart-reference-toolbar" />
    <FreeChartStage
      :bars="bars"
      :pattern-geometry="patternGeometry"
      :mutation="mutation" :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError"
      :loading="loading"
      :error="error"
      :period="identity.frequency"
      :series-kind="identity.seriesKind"
      :visible-main-indicators="indicators"
      :range-detector-source-identity="sourceIdentity"
      :range-detector-anchor-time="rangeWarmup.anchorTime.value"
      :identity-key="sourceIdentity"
      :focus-bar-end="identity.focusBarEnd"
      @focus-resolved="emit('focus-resolved', $event)"
      @load-earlier="loadEarlier"
      @visible-from-change="visibleFrom = $event"
      @range-detector-result="rangeCount = $event.count"
    />
    </div>
  </section>
</template>

<style scoped>
.free-workspace { display: grid; gap: var(--gy-space-4); }
.free-workspace__indicators { display: flex; align-items: center; gap: var(--gy-space-2); min-height: 48px; padding: 6px 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.free-workspace__indicators-title { margin-right: 2px; color: var(--gy-text-primary); font-weight: 650; }
.indicator-chip { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; padding: 0 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-secondary); background: var(--gy-bg-panel); cursor: pointer; font: inherit; font-size: var(--gy-font-size-sm); transition: border-color 120ms ease, background-color 120ms ease, color 120ms ease; }
.indicator-chip:hover { border-color: color-mix(in srgb, var(--indicator-color) 58%, var(--gy-border)); }
.indicator-chip:focus-visible { outline: 2px solid color-mix(in srgb, var(--indicator-color) 65%, transparent); outline-offset: 2px; }
.indicator-chip--active { border-color: color-mix(in srgb, var(--indicator-color) 64%, var(--gy-border)); color: var(--indicator-color); background: color-mix(in srgb, var(--indicator-color) 10%, var(--gy-bg-panel)); font-weight: 600; }
.indicator-chip__dot { width: 7px; height: 7px; border-radius: 50%; background: var(--indicator-color); }
.indicator-chip__check { line-height: 1; }
.indicator-chip--ema10 { --indicator-color: #2563eb; }
.indicator-chip--ema21 { --indicator-color: #f59e0b; }
.indicator-chip--ema60 { --indicator-color: #7c3aed; }
.indicator-chip--patterns { --indicator-color: #15803d; }
.indicator-chip--range { --indicator-color: #2563eb; }
@media (max-width: 640px) { .free-workspace__indicators { align-items: flex-start; flex-wrap: wrap; } .free-workspace__indicators-title { width: 100%; } }
.free-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
