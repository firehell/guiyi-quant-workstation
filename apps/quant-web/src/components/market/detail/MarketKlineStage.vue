<script setup lang="ts">
import type { ArchivePane, WorkstationStyles } from '@/utils/workstationChartPanes'
import type { ChartProfileId } from '@guiyi/quant-chart'
import type { DynamicRangeDisplay } from '@/utils/dynamicRange'
import type { PatternGeometry } from '@/utils/newowPatternDisplay'
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { KlineQualityBreak, KlineReferenceCallout, KlineReferenceIndicator, KlineReferenceSelection } from '@/types/referenceCallout'
import KlineChart from '@/components/kline/KlineChart.vue'
import ChartLayerDiagnostics from '@/components/kline/ChartLayerDiagnostics.vue'
import MarketDetailIcon from '@/components/market/detail/MarketDetailIcon.vue'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import { DETAIL_CHART_SESSION } from '@/utils/detailChartSession'
import type { SavedReferenceLine } from '@/utils/newowMarketReference'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import { MARKET_CHART_STUDY_BAR_LIMIT, MARKET_CHART_STUDY_CONTEXT } from '@/utils/marketChartStudies'
import { candidatePreview } from '@/utils/candidatePreview'
import { useMarketChartStudies } from '@/composables/useMarketChartStudies'

const props = withDefaults(defineProps<{
  chartProfile?: ChartProfileId
  workstationPanes?: ArchivePane[]
  workstationStyles?: WorkstationStyles
  logPrice?: boolean
  dynamicRange?: DynamicRangeDisplay | null
  patternGeometry?: PatternGeometry | null
  subingVolumeTiers?: boolean
  volumeScoring?: boolean
  researchMarkers?: KlineMarker[]
  savedReferenceLines?: SavedReferenceLine[]
  bars: BarData[]
  activeBar?: BarData | null
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  period: string
  seriesKind: SeriesKind
  visibleMainIndicators: MainIndicatorId[]
  rangeDetectorSourceIdentity: string
  rangeDetectorAnchorTime: string | null
  identityKey: string
  focusBarEnd?: string | null
  showNavigationButtons?: boolean
  showDerivedMarkers?: boolean
  markers?: KlineMarker[]
  markerSelectionEnabled?: boolean
  referenceCallouts?: KlineReferenceCallout[]
  referenceIndicators?: KlineReferenceIndicator[]
  referenceSelection?: KlineReferenceSelection[]
  qualityBreaks?: KlineQualityBreak[]
  hasMoreBefore?: boolean
  loadingBefore?: boolean
  historyError?: string | null
  focusRequestId?: number
}>(), { volumeScoring: true, markers: () => [], markerSelectionEnabled: true, showDerivedMarkers: true, showNavigationButtons: true })

const emit = defineEmits<{
  loadEarlier: []
  'visible-from-change': [time: string | null]
  'range-detector-result': [result: { count: number; calculationMs: number }]
  'focus-resolved': [focusBarEnd: string]
  'marker-select': [marker: KlineMarker]
}>()
const pageOwnsNavigation = Boolean(inject(DETAIL_CHART_SESSION, null))
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const market = inject(MARKET_CHART_STUDY_CONTEXT, null)
const studyContext = computed(() => {
  const context = market?.value
  if (!context || context.identity.profile !== (props.workstationPanes ? 'newow' : props.chartProfile)
    || context.identity.frequency !== props.period || context.identity.seriesKind !== props.seriesKind) return null
  return props.focusBarEnd ? { ...context, allowTail: false } : context
})
const showTalibMacd = computed(() => props.workstationPanes ? props.workstationPanes.some(p => p.id === 'macd') : studyContext.value?.talibMacd === true)
const { demand: studyRequest, canonical: studyDisplay, canonicalIssue: studyIssue, historyUnavailable: studyUnavailable,
  completed: studyCompleted, preview: studyPreview, tailIssue: studyTailIssue } = useMarketChartStudies(
  () => studyContext.value,
  () => props.bars,
  () => showTalibMacd.value ? [...props.visibleMainIndicators, 'macd'] : props.visibleMainIndicators,
)
const activeDisplayBar = computed(() => props.activeBar ?? (studyContext.value?.allowTail ? studyContext.value.active.value?.bar : null) ?? null)
const followLatest = ref(true)
const fullscreen = ref(false)
let resolvedFocusKey: string | null = null

function resolveFocus(): boolean {
  if (!props.focusBarEnd) return false
  const focusKey = `${props.identityKey}:${props.focusBarEnd}:${props.focusRequestId ?? 0}`
  if (resolvedFocusKey === focusKey) return true
  if (!chart.value?.revealTime(props.focusBarEnd)) return false
  resolvedFocusKey = focusKey
  followLatest.value = false
  emit('focus-resolved', props.focusBarEnd)
  return true
}

watch(() => props.identityKey, () => {
  resolvedFocusKey = null
  followLatest.value = true
})

watch(() => [props.identityKey, props.focusBarEnd, props.focusRequestId], async () => {
  await nextTick()
  resolveFocus()
}, { immediate: true })

onMounted(async () => {
  await nextTick()
  requestAnimationFrame(() => resolveFocus())
})

watch(() => props.mutation, async (mutation) => {
  await nextTick()
  if (!chart.value) return
  if (mutation.kind === 'replace') chart.value.replaceBars(props.bars, !followLatest.value)
  else if (mutation.kind === 'prepend') chart.value.prependBars(mutation.bars)
  else {
    chart.value.updateLiveBars(props.bars)
    if (followLatest.value) chart.value.scrollToLatest()
  }
  resolveFocus()
}, { deep: true })

function syncFullscreen() { fullscreen.value = Boolean(document.fullscreenElement) }
document.addEventListener('fullscreenchange', syncFullscreen)
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', syncFullscreen))
defineExpose({ inspectLayers: () => chart.value?.inspectLayers() ?? [] })
</script>

<template>
  <section class="market-kline-stage" :class="{ 'market-kline-stage--fullscreen': fullscreen }">
    <div class="market-kline-stage__controls">
      <button v-if="showNavigationButtons && !pageOwnsNavigation && !followLatest" type="button" @click="chart?.scrollToLatest()"><MarketDetailIcon name="refresh" :size="16" />回到最新</button>
    </div>
    <div v-if="hasMoreBefore !== undefined && (loadingBefore || historyError || hasMoreBefore === false)" class="market-kline-stage__history" role="status">
      <button v-if="hasMoreBefore && historyError" type="button" :disabled="loading || loadingBefore" @click="emit('loadEarlier')">
        {{ loadingBefore ? '加载中…' : '重试' }}
      </button>
      <span v-if="loadingBefore">加载中…</span>
      <span v-if="hasMoreBefore === false && !loading && bars.length">已到最早可用数据</span>
      <span v-if="historyError">{{ historyError }}</span>
    </div>
    <p v-if="studyUnavailable" class="market-kline-stage__history" role="status">当前行情窗口的所选指标暂不可用。</p>
    <p v-else-if="studyDisplay && studyRequest?.truncatedBefore" class="market-kline-stage__history" role="status">
      所选通用指标仅覆盖最近 {{ MARKET_CHART_STUDY_BAR_LIMIT.toLocaleString('zh-CN') }} 根已完成行情。
    </p>
    <KlineChart
      :key="identityKey"
      :chart-profile="chartProfile"
      :workstation-panes="workstationPanes" :workstation-styles="workstationStyles" :log-price="logPrice"
      :show-derived-markers="showDerivedMarkers"
      ref="chart"
      :bars="bars"
      :active-bar="activeDisplayBar"
      :subing-volume-tiers="subingVolumeTiers"
      :volume-scoring="volumeScoring"
      :research-markers="researchMarkers"
      :saved-reference-lines="savedReferenceLines"
      :dynamic-range="dynamicRange"
      :pattern-geometry="patternGeometry"
      :loading="loading"
      :error="error"
      :period="period"
      :series-kind="seriesKind"
      :visible-main-indicators="visibleMainIndicators"
      :study-display="studyDisplay"
      :study-issue="studyIssue"
      :study-completed="studyCompleted"
      :study-preview="studyPreview"
      :study-tail-issue="studyTailIssue"
      :talib-macd="showTalibMacd"
      :allow-generic-macd="Boolean(studyContext) && !candidatePreview.enabled"
      @toggle-talib-macd="studyContext?.toggleMacd()"
      :range-detector-source-identity="rangeDetectorSourceIdentity"
      :range-detector-anchor-time="rangeDetectorAnchorTime"
      :alert-markers="markers"
      :marker-selection-enabled="markerSelectionEnabled"
      :reference-callouts="referenceCallouts"
      :reference-indicators="referenceIndicators"
      :reference-selection="referenceSelection"
      :quality-breaks="qualityBreaks"
      @need-more-before="!loadingBefore && !historyError && hasMoreBefore !== false && emit('loadEarlier')"
      @follow-latest-change="followLatest = $event"
      @visible-from-change="emit('visible-from-change', $event)"
      @range-detector-result="emit('range-detector-result', $event)"
      @marker-select="emit('marker-select', $event)"
    />
    <ChartLayerDiagnostics v-if="chart" :key="identityKey" :inspect="chart.inspectLayers" />
  </section>
</template>

<style scoped>
.market-kline-stage { position: relative; min-width: 0; }
.market-kline-stage__history { display: flex; align-items: center; gap: 8px; min-height: 32px; font-size: 12px; color: var(--gy-text-secondary); }
.market-kline-stage__history button { cursor: pointer; padding: 4px 10px; border: 1px solid var(--gy-border); border-radius: 4px; background: var(--gy-bg-panel); color: inherit; }
.market-kline-stage__controls { position: absolute; z-index: 4; top: 10px; right: 10px; display: flex; gap: 8px; }
.market-kline-stage__controls button { min-height: 44px; min-width: 44px; padding: 0 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.market-kline-stage--fullscreen { display: grid; height: 100vh; padding: 16px; background: var(--gy-bg-app); }
.market-kline-stage--fullscreen :deep(.kline-shell) { height: 100%; }
</style>
