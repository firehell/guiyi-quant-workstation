<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import MarketDetailInsightDeck from '@/components/market/detail/MarketDetailInsightDeck.vue'
import FreeChartStage from '@/components/market/detail/free/FreeChartStage.vue'
import { useRangeDetectorOverlayWarmup } from '@/composables/useRangeDetectorOverlayWarmup'
import type { BarData, OptionalEmaIndicatorId, ProductResearchResponse } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { DetailViewModel, MarketDetailDisclosureSection, MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import type { FlexibleDetailPreferences } from '@/utils/marketDetailPreferences'
import { buildFreeDetailViewModel } from '@/utils/freeDetailViewModel'

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
  hasMoreBefore: boolean
  loadEarlier: () => Promise<void>
  identityWarning?: string | null
}>()
const emit = defineEmits<{
  'focus-resolved': [focusBarEnd: string]
  updatePreferences: [preferences: FlexibleDetailPreferences]
}>()

const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([...props.preferences.optionalEmaIndicators])
const showRangeDetector = ref(props.preferences.showRangeDetector)
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const bars = computed(() => props.bars)
const hasMoreBefore = computed(() => props.hasMoreBefore)
const rangeWarmup = useRangeDetectorOverlayWarmup({
  bars,
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
const model = computed<DetailViewModel>(() => buildFreeDetailViewModel({
  identity: props.identity,
  header: props.header,
  research: props.research,
  researchError: props.researchError,
  rangeState: rangeState.value,
}))
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
const backgroundSections = computed<readonly MarketDetailDisclosureSection[]>(() => [{
  id: 'market-background',
  title: '市场背景',
  summary: props.research ? '已加载市场事实' : props.researchError ? '暂不可用' : '暂无市场背景',
  updatedAt: props.header.asOf,
  tone: props.researchError ? 'unavailable' : 'default',
  rows: props.research
    ? [
        { label: '日线趋势', value: props.research.daily_trend, source: 'market' },
        { label: '周线趋势', value: props.research.weekly_trend, source: 'market' },
        { label: '20日位置', value: String(props.research.position20 ?? '—'), source: 'market' },
        { label: '量比20', value: String(props.research.volume_ratio20 ?? '—'), source: 'market' },
        { label: 'OI 1D', value: String(props.research.oi_change_1d ?? '—'), source: 'market' },
        { label: 'ATR分位', value: String(props.research.atr14_percentile252 ?? '—'), source: 'market' },
      ]
    : [{ label: '状态', value: props.researchError ? '市场背景暂不可用' : '暂无市场背景', source: 'market' }],
}])
const dataSections = computed<readonly MarketDetailDisclosureSection[]>(() => [{
  id: 'market-data-details',
  title: '数据详情',
  summary: model.value.disclosureSections.length > 0 ? '展开查看行情扩展事实' : '暂无扩展数据',
  updatedAt: props.header.asOf,
  tone: model.value.disclosureSections.some((section) => section.tone === 'unavailable')
    ? 'unavailable'
    : model.value.disclosureSections.some((section) => section.tone === 'warning') ? 'warning' : 'default',
  rows: model.value.disclosureSections.length > 0
    ? model.value.disclosureSections.flatMap((section) => section.rows.map((row) => ({
        ...row, label: `${section.title} · ${row.label}`,
      })))
    : [{ label: '状态', value: '暂无扩展数据', source: 'market' }],
}])
function updatePreferences(identity: MarketDetailIdentity) {
  emit('updatePreferences', {
    seriesKind: identity.seriesKind === 'continuous' ? 'continuous' : 'actual_dominant',
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
  <section class="free-workspace" data-detail-workspace="free" :data-range-detector-warmup="rangeState" :data-range-detector-anchor="rangeWarmup.anchorTime.value" :data-range-detector-source-identity="sourceIdentity">
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
    </div>
    <p v-if="identityWarning" class="free-workspace__hint" role="status">{{ identityWarning }}</p>
    <p v-if="showRangeDetector" class="free-workspace__hint" role="status">{{ model.semanticBanner.text }}</p>
    <FreeChartStage
      :bars="bars"
      :mutation="mutation"
      :loading="loading"
      :error="error"
      :period="identity.frequency"
      :series-kind="identity.seriesKind"
      :visible-main-indicators="indicators"
      :range-detector-source-identity="sourceIdentity"
      :range-detector-anchor-time="rangeState === 'ready' ? rangeWarmup.anchorTime.value : null"
      :identity-key="sourceIdentity"
      :focus-bar-end="identity.focusBarEnd"
      @focus-resolved="emit('focus-resolved', $event)"
      @load-earlier="loadEarlier"
    />
    <MarketDetailInsightDeck :identity-key="sourceIdentity" :sections="backgroundSections" :default-open="false" />
    <MarketDetailInsightDeck :identity-key="sourceIdentity" :sections="dataSections" :default-open="false" />
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
.indicator-chip--range { --indicator-color: #2563eb; }
@media (max-width: 640px) { .free-workspace__indicators { align-items: flex-start; flex-wrap: wrap; } .free-workspace__indicators-title { width: 100%; } }
.free-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
