<script setup lang="ts">
import { computed } from 'vue'

import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import { markersForDetailView } from '@/utils/marketDetailMarkers'

const props = defineProps<{
  bars: BarData[]; mutation: MarketSeriesMutation; loading: boolean; error: string | null; period: string; seriesKind: SeriesKind
  identityKey: string; focusBarEnd?: string | null; markers: readonly KlineMarker[]; visibleMainIndicators: MainIndicatorId[]
}>()
const emit = defineEmits<{ 'load-earlier': []; 'focus-resolved': [focusBarEnd: string]; 'marker-select': [marker: KlineMarker] }>()
const subingMarkers = computed(() => markersForDetailView('subing', props.markers))
function selectMarker(marker: KlineMarker) {
  if (subingMarkers.value.some((item) => item.id === marker.id)) emit('marker-select', marker)
}
</script>

<template>
  <MarketKlineStage
    :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="period" :series-kind="seriesKind"
    :visible-main-indicators="visibleMainIndicators" range-detector-source-identity="" :range-detector-anchor-time="null"
    :identity-key="identityKey" :focus-bar-end="focusBarEnd" :markers="subingMarkers"
    @load-earlier="emit('load-earlier')" @focus-resolved="emit('focus-resolved', $event)" @marker-select="selectMarker"
  />
</template>
