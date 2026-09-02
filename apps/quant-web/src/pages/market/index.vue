<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'
import MarketProductDirectory from '@/components/market/MarketProductDirectory.vue'
import MarketRuntimeStatus from '@/components/market/MarketRuntimeStatus.vue'
import { getMarketDominants } from '@/api/market'
import { getRuntimeHealth } from '@/api/runtime'
import { useLatestResource } from '@/composables/useLatestResource'
import type { DominantContractItem } from '@/types/market'
import { loadMarketWorkspacePreferences } from '@/utils/marketWorkspacePreferences'

const router = useRouter()
const runtimeState = useLatestResource({ fetch: getRuntimeHealth })
const productDirectoryState = useLatestResource({ fetch: getMarketDominants })
const runtime = runtimeState.data
const products = computed(() => productDirectoryState.data.value?.items ?? [])
const loading = computed(() => runtimeState.loading.value || productDirectoryState.loading.value)

async function refreshAll() {
  await Promise.all([runtimeState.refresh(), productDirectoryState.refresh()])
}

async function refreshVisibleOperationalState() {
  await Promise.all([runtimeState.refresh(), productDirectoryState.refresh()])
}

function openProduct(item: DominantContractItem) {
  const preferences = loadMarketWorkspacePreferences()
  void router.push({
    name: 'market-chart',
    query: { symbol: item.product, series_kind: 'actual_dominant', frequency: preferences.frequency },
  })
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') void refreshVisibleOperationalState()
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  void refreshAll()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  runtimeState.invalidate()
  productDirectoryState.invalidate()
})
</script>

<template>
  <div class="market-dashboard-page">
    <header class="market-dashboard-page__intro">
      <div><h1>行情看板</h1><p>运行状态与品种目录；所有内容仅供人工观察。</p></div>
      <NButton secondary size="small" :loading="loading" :disabled="loading" @click="refreshAll">全部刷新</NButton>
    </header>
    <MarketRuntimeStatus
      :snapshot="runtime"
      :loading="runtimeState.loading.value"
      :stale="runtimeState.failed.value && Boolean(runtime)"
    />
    <MarketProductDirectory
      :items="products"
      :loading="productDirectoryState.loading.value"
      :failed="productDirectoryState.failed.value"
      :stale="productDirectoryState.failed.value && Boolean(products.length)"
      @open="openProduct"
    />
  </div>
</template>

<style scoped>
.market-dashboard-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.market-dashboard-page__intro { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.market-dashboard-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }
.market-dashboard-page__intro p { margin: 0; color: var(--gy-text-muted); }
</style>
