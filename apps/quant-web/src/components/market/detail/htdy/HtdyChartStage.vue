<script setup lang="ts">
import { computed } from 'vue'

import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import { markersForDetailView } from '@/utils/marketDetailMarkers'

const props = defineProps<{
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
  markers: readonly KlineMarker[]
}>()
const emit = defineEmits<{ 'load-earlier': []; 'focus-resolved': [focusBarEnd: string] }>()
const htdyMarkers = computed(() => markersForDetailView('htdy', props.markers))
</script>

<template>
  <MarketKlineStage
    :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="period" :series-kind="seriesKind"
    :visible-main-indicators="visibleMainIndicators" :range-detector-source-identity="rangeDetectorSourceIdentity"
    :range-detector-anchor-time="rangeDetectorAnchorTime" :identity-key="identityKey" :focus-bar-end="focusBarEnd"
    :markers="htdyMarkers" @load-earlier="emit('load-earlier')" @focus-resolved="emit('focus-resolved', $event)"
  />
</template>
