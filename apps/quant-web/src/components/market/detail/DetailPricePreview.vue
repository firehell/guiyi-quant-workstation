<script setup lang="ts">
import KlineChart from '@/components/kline/KlineChart.vue'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { DetailPricePreview } from '@/composables/useDetailPricePreview'
defineProps<{ identity: MarketDetailIdentity; preview: DetailPricePreview }>()
</script>

<template>
  <section class="newow-product-workspace__price-preview" aria-label="价格预览">
    <p role="status">{{ preview.cached.value ? '历史缓存价格预览' : '价格预览' }} · 截止 {{ preview.cutoff.value ?? '读取中' }} · 策略确认后显示</p>
    <KlineChart :key="`${identity.symbol}:${identity.frequency}`" :bars="preview.bars.value" :series-kind="identity.seriesKind" :period="identity.frequency" :visible-main-indicators="[]" :marker-selection-enabled="false" :loading="preview.loading.value && preview.bars.value.length === 0" :error="preview.error.value" />
  </section>
</template>
