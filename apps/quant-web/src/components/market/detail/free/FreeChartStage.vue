<script setup lang="ts">
import { computed } from 'vue'

import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import { markersForDetailView } from '@/utils/marketDetailMarkers'

const props = withDefaults(defineProps<{
  bars: BarData[]
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  period: string
  seriesKind: SeriesKind
  visibleMainIndicators: MainIndicatorId[]
  rangeDetectorSourceIdentity: string
  rangeDetectorAnchorTime: string | null
  markers?: readonly KlineMarker[]
}>(), { markers: () => [] })
const emit = defineEmits<{ loadEarlier: [] }>()
const freeMarkers = computed(() => markersForDetailView('free', props.markers))
</script>

<template>
  <MarketKlineStage
    :bars="bars"
    :mutation="mutation"
    :loading="loading"
    :error="error"
    :period="period"
    :series-kind="seriesKind"
    :visible-main-indicators="visibleMainIndicators"
    :range-detector-source-identity="rangeDetectorSourceIdentity"
    :range-detector-anchor-time="rangeDetectorAnchorTime"
    :markers="freeMarkers"
    @load-earlier="emit('loadEarlier')"
  />
</template>
