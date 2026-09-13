<script setup lang="ts">
import { computed } from 'vue'

import MarketNavigation from './MarketNavigation.vue'
import ProductSelector from './ProductSelector.vue'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { ProductOption } from '@/utils/productSearch'

type HomeView = 'newow' | 'htdy' | 'subing' | 'free'
const props = defineProps<{ rows: MarketHomeRow[]; loading: boolean; activeTab: 'market' | 'messages' }>()
const emit = defineEmits<{ openView: [view: HomeView, symbol: string]; refresh: []; selectTab: [tab: 'market' | 'messages'] }>()
const options = computed<ProductOption[]>(() => props.rows.map((row) => ({
  symbol: row.symbol.toLowerCase(), name: row.product_name, contract: row.actual_contract || null,
})).sort((left, right) => left.symbol.localeCompare(right.symbol)))

function openProduct(option: ProductOption) {
  emit('openView', 'newow', option.symbol)
}
</script>

<template>
  <MarketNavigation :active-tab="activeTab" @market="emit('selectTab', 'market')" @messages="emit('selectTab', 'messages')">
    <template #search>
      <ProductSelector
        :options="options"
        :status="loading && options.length === 0 ? 'loading' : options.length > 0 ? 'ready' : 'error'"
        label="搜索60品种"
        @select="openProduct"
      />
    </template>
    <template #actions>
      <button class="market-home-refresh" type="button" :disabled="loading" @click="$emit('refresh')">{{ loading ? '刷新中…' : '刷新' }}</button>
    </template>
  </MarketNavigation>
</template>
