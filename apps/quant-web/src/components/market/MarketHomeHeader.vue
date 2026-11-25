<script setup lang="ts">

import MarketNavigation from './MarketNavigation.vue'
import ProductSelector from './ProductSelector.vue'
import type { ProductOption } from '@/utils/productSearch'

type HomeView = 'newow' | 'htdy' | 'subing' | 'free'
defineProps<{ options: ProductOption[]; directoryStatus: 'ready' | 'loading' | 'error'; loading: boolean; activeTab: 'market' | 'messages' | 'simulation' }>()
const emit = defineEmits<{ openView: [view: HomeView, symbol: string]; refresh: [] }>()

function openProduct(option: ProductOption) {
  emit('openView', 'newow', option.symbol)
}
</script>

<template>
  <MarketNavigation :active-tab="activeTab">
    <template #search>
      <ProductSelector
        :options="options"
        :status="options.length > 0 ? 'ready' : directoryStatus"
        label="搜索60品种"
        @select="openProduct"
      />
      <span v-if="directoryStatus === 'error' && options.length" role="alert">目录刷新失败，已保留上次选项。</span>
    </template>
    <template #actions>
      <RouterLink to="/market?tab=market">行情总览</RouterLink>
      <RouterLink to="/market?tab=simulation">快期详情</RouterLink>
    </template>
  </MarketNavigation>
</template>
