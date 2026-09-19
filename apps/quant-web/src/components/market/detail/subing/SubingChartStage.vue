<script setup lang="ts">
import type { KlineQualityBreak, KlineReferenceCallout, KlineReferenceSelection } from '@/types/referenceCallout'
import { computed } from 'vue'

import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { BarData, KlineMarker, MainIndicatorId, SeriesKind } from '@/types/market'
import type { SubingReferenceIndicator } from '@/types/subingReference'
import { markersForDetailView } from '@/utils/marketDetailMarkers'

const props = defineProps<{
  bars: BarData[]; mutation: MarketSeriesMutation; loading: boolean; error: string | null; period: string; seriesKind: SeriesKind
  referenceCallouts?: KlineReferenceCallout[]
  referenceIndicators?: SubingReferenceIndicator[]
  referenceSelection?: KlineReferenceSelection[]
  qualityBreaks?: KlineQualityBreak[]
  focusRequestId?: number
  identityKey: string; focusBarEnd?: string | null; markers: readonly KlineMarker[]; visibleMainIndicators: MainIndicatorId[]
}>()
const emit = defineEmits<{ 'load-earlier': []; 'focus-resolved': [focusBarEnd: string] }>()
const subingMarkers = computed(() => markersForDetailView('subing', props.markers))
</script>

<template>
  <MarketKlineStage
    :bars="bars" :mutation="mutation" :loading="loading" :error="error" :period="period" :series-kind="seriesKind"
    :visible-main-indicators="visibleMainIndicators" range-detector-source-identity="" :range-detector-anchor-time="null"
    :reference-callouts="referenceCallouts" :reference-selection="referenceSelection" :focus-request-id="focusRequestId" :marker-selection-enabled="false"
    :reference-indicators="referenceIndicators" :quality-breaks="qualityBreaks"
    :identity-key="identityKey" :focus-bar-end="focusBarEnd" :markers="subingMarkers"
    @load-earlier="emit('load-earlier')" @focus-resolved="emit('focus-resolved', $event)"
  />
</template>
