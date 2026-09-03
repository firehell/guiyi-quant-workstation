<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import MarketDetailFactStrip from '@/components/market/detail/MarketDetailFactStrip.vue'
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

function loadEarlier() { void props.loadEarlier() }
</script>

<template>
  <section class="free-workspace" data-detail-workspace="free" :data-range-detector-warmup="rangeState">
    <div class="free-workspace__indicators">
      <details open>
        <summary>指标设置</summary>
        <label v-for="item in [['ema_10', 'EMA10'], ['ema_21', 'EMA21'], ['ema_60', 'EMA60']] as const" :key="item[0]"><input type="checkbox" :checked="optionalEmaIndicators.includes(item[0])" @change="toggleEma(item[0])">{{ item[1] }}</label>
        <label><input v-model="showRangeDetector" type="checkbox">箱体识别（Range）</label>
      </details>
    </div>

    <p class="free-workspace__semantic" :class="{ 'free-workspace__warning': model.semanticBanner.tone === 'warning' }" role="status">{{ model.semanticBanner.text }}</p>
    <MarketDetailFactStrip :facts="model.facts" />
    <p v-if="identityWarning" class="free-workspace__hint" role="status">{{ identityWarning }}</p>
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
      @load-earlier="loadEarlier"
    />
    <MarketDetailInsightDeck :identity-key="sourceIdentity" :sections="backgroundSections" :default-open="false" />
    <MarketDetailInsightDeck :identity-key="sourceIdentity" :sections="dataSections" :default-open="false" />
  </section>
</template>

<style scoped>
.free-workspace { display: grid; gap: var(--gy-space-4); }
.free-workspace__indicators { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.free-workspace details { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.free-workspace summary { cursor: pointer; }
.free-workspace label { margin: 0 8px 0 0; }
.free-workspace__semantic { margin: 0; padding: var(--gy-space-2) var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-secondary); background: var(--gy-bg-panel); }
.free-workspace__warning { color: var(--gy-status-warning); background: color-mix(in srgb, var(--gy-status-warning) 10%, transparent); }
.free-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
