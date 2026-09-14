<script setup lang="ts">

import MarketNavigation from './MarketNavigation.vue'
import ProductSelector from './ProductSelector.vue'
import type { ProductOption } from '@/utils/productSearch'

type HomeView = 'newow' | 'htdy' | 'subing' | 'free'
defineProps<{ options: ProductOption[]; directoryStatus: 'ready' | 'loading' | 'error'; loading: boolean; activeTab: 'market' | 'messages' }>()
const emit = defineEmits<{ openView: [view: HomeView, symbol: string]; refresh: []; selectTab: [tab: 'market' | 'messages'] }>()

function openProduct(option: ProductOption) {
  emit('openView', 'newow', option.symbol)
}
</script>

<template>
  <MarketNavigation :active-tab="activeTab" @market="emit('selectTab', 'market')" @messages="emit('selectTab', 'messages')">
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
      <button class="market-home-refresh" type="button" :disabled="loading" @click="$emit('refresh')">{{ loading ? '刷新中…' : '刷新' }}</button>
    </template>
  </MarketNavigation>
</template>
