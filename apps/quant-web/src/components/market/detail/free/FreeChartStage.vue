<script setup lang="ts">
import type { PatternGeometry } from '@/utils/newowPatternDisplay'
import { computed } from 'vue'

import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import { markersForDetailView } from '@/utils/marketDetailMarkers'

const props = withDefaults(defineProps<{
  hasMoreBefore?: boolean; loadingBefore?: boolean; historyError?: string | null
  patternGeometry?: PatternGeometry | null
  bars: BarData[]
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
  markers?: readonly KlineMarker[]
}>(), { markers: () => [] })
const emit = defineEmits<{
  'visible-from-change': [time: string | null]
  'range-detector-result': [result: { count: number; calculationMs: number }]

  loadEarlier: []
  'focus-resolved': [focusBarEnd: string]
}>()
const freeMarkers = computed(() => markersForDetailView('free', props.markers))
</script>

<template>
  <MarketKlineStage :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError"
    :bars="bars"
    :pattern-geometry="patternGeometry"
    :mutation="mutation"
    :loading="loading"
    :error="error"
    :period="period"
    :series-kind="seriesKind"
    :visible-main-indicators="visibleMainIndicators"
    :range-detector-source-identity="rangeDetectorSourceIdentity"
    :range-detector-anchor-time="rangeDetectorAnchorTime"
    :identity-key="identityKey"
    :focus-bar-end="focusBarEnd"
    :markers="freeMarkers"
    @load-earlier="emit('loadEarlier')"
    @focus-resolved="emit('focus-resolved', $event)"
    @visible-from-change="emit('visible-from-change', $event)"
    @range-detector-result="emit('range-detector-result', $event)"
  />
</template>
