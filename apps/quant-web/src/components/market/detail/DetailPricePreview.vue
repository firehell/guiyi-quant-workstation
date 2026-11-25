<script setup lang="ts">
import KlineChart from '@/components/kline/KlineChart.vue'
import type { KlineMarker } from '@/types/market'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { DetailPricePreview } from '@/composables/useDetailPricePreview'
defineProps<{ identity: MarketDetailIdentity; preview: DetailPricePreview; afterMarket?: boolean; referenceMarkers?: KlineMarker[] }>()
</script>

<template>
  <section class="newow-product-workspace__price-preview" aria-label="价格预览">
    <p role="status">{{ afterMarket ? '行情 K 线' : preview.cached.value ? '历史缓存价格预览' : '价格预览' }} · 截止 {{ preview.cutoff.value ?? '读取中' }}<template v-if="!afterMarket"> · 策略确认后显示</template></p>
    <KlineChart :volume-scoring="false" :key="`${identity.symbol}:${identity.frequency}`" :bars="preview.bars.value" :series-kind="identity.seriesKind" :period="identity.frequency" :visible-main-indicators="[]" :show-derived-markers="!afterMarket" :research-markers="referenceMarkers" :marker-selection-enabled="false" :loading="preview.loading.value && preview.bars.value.length === 0" :error="preview.error.value" />
  </section>
</template>
