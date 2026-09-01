<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { NButton } from 'naive-ui'
import MarketRuntimeStatus from '@/components/market/MarketRuntimeStatus.vue'
import { getRuntimeHealth } from '@/api/runtime'
import { useLatestResource } from '@/composables/useLatestResource'

const runtimeState = useLatestResource({ fetch: getRuntimeHealth })
const runtime = runtimeState.data
const loading = computed(() => runtimeState.loading.value)

async function refreshAll() {
  await runtimeState.refresh()
}

async function refreshVisibleOperationalState() {
  await runtimeState.refresh()
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
})
</script>

<template>
  <div class="market-dashboard-page">
    <header class="market-dashboard-page__intro">
      <div><h1>行情看板</h1><p>Runtime 状态；所有内容仅供人工观察。</p></div>
      <NButton secondary size="small" :loading="loading" :disabled="loading" @click="refreshAll">全部刷新</NButton>
    </header>
    <MarketRuntimeStatus
      :snapshot="runtime"
      :loading="runtimeState.loading.value"
      :stale="runtimeState.failed.value && Boolean(runtime)"
    />
  </div>
</template>

<style scoped>
.market-dashboard-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.market-dashboard-page__intro { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.market-dashboard-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }
.market-dashboard-page__intro p { margin: 0; color: var(--gy-text-muted); }
</style>
