<script setup lang="ts">
import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { BarData, MainIndicatorId, SeriesKind } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'

defineProps<{
  bars: BarData[]
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  period: string
  seriesKind: SeriesKind
  visibleMainIndicators: MainIndicatorId[]
  rangeDetectorSourceIdentity: string
  rangeDetectorAnchorTime: string | null
}>()
const emit = defineEmits<{ loadEarlier: [] }>()
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
    @load-earlier="emit('loadEarlier')"
  />
</template>
