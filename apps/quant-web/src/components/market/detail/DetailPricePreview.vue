<script setup lang="ts">
import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { DetailPricePreview } from '@/composables/useDetailPricePreview'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'

defineProps<{
  identity: MarketDetailIdentity; preview: DetailPricePreview; mutation: MarketSeriesMutation; axisKey: string
  hasMoreBefore: boolean; loadingBefore: boolean; historyError: string | null
}>()
const emit = defineEmits<{ loadEarlier: []; 'focus-resolved': [time: string] }>()
</script>

<template>
  <section class="newow-product-workspace__price-preview" aria-label="价格预览">
    <p role="status">{{ preview.cached.value ? '历史缓存价格预览' : '价格预览' }} · 截止 {{ preview.cutoff.value ?? '读取中' }}</p>
    <MarketKlineStage :identity-key="axisKey" :bars="preview.bars.value" :mutation="mutation"
      :series-kind="identity.seriesKind" :period="identity.frequency" :visible-main-indicators="[]"
      range-detector-source-identity="" :range-detector-anchor-time="null"
      :focus-bar-end="identity.focusBarEnd" :marker-selection-enabled="false" :show-derived-markers="false" :volume-scoring="false"
      :loading="preview.loading.value && preview.bars.value.length === 0" :error="preview.error.value"
      :has-more-before="hasMoreBefore" :loading-before="loadingBefore" :history-error="historyError"
      @load-earlier="emit('loadEarlier')" @focus-resolved="emit('focus-resolved', $event)" />
  </section>
</template>
