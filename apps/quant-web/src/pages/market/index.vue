<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'
import MarketRuntimeStatus from '@/components/market/MarketRuntimeStatus.vue'
import SubingWorkbench from '@/components/market/SubingWorkbench.vue'
import { getCurrentStrategyActions } from '@/api/alerts'
import type { CurrentStrategyActionItem } from '@/api/alerts'
import { getSubingDailyWatchCurrent } from '@/api/market'
import { getRuntimeHealth } from '@/api/runtime'
import type { SubingDailyWatchItem } from '@/types/market'
import { useLatestResource } from '@/composables/useLatestResource'
import { useSubingWorkbench } from '@/composables/useSubingWorkbench'

const router = useRouter()
const subingWorkbench = useSubingWorkbench({
  fetchStrategyActions: getCurrentStrategyActions,
  fetchDailyWatch: getSubingDailyWatchCurrent,
})
const runtimeState = useLatestResource({ fetch: getRuntimeHealth })
const runtime = runtimeState.data
const loading = computed(() => (
  subingWorkbench.strategyLoading.value
  || subingWorkbench.dailyLoading.value
  || runtimeState.loading.value
))

function openDailyWatch(item: SubingDailyWatchItem) {
  void router.push({
    name: 'market-chart',
    query: {
      symbol: item.symbol,
      series_kind: 'actual_dominant',
      frequency: '15m',
      overlay: 'subing',
      entry: 'subing-daily-watch',
    },
  })
}

function openStrategyAction(item: CurrentStrategyActionItem) {
  void router.push({
    name: 'market-chart',
    query: {
      symbol: item.symbol,
      series_kind: 'actual_dominant',
      frequency: '15m',
      overlay: 'subing',
      entry: 'subing-strategy-action',
      action_id: item.action_id,
    },
  })
}

async function refreshAll() {
  await Promise.all([
    subingWorkbench.refreshAll(),
    runtimeState.refresh(),
  ])
}

async function refreshVisibleOperationalState() {
  await Promise.all([
    subingWorkbench.refreshOperational(),
    runtimeState.refresh(),
  ])
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
  subingWorkbench.dispose()
  runtimeState.invalidate()
})
</script>

<template>
  <div class="market-dashboard-page">
    <header class="market-dashboard-page__intro">
      <div><h1>行情看板</h1><p>Runtime、今日观察与当前策略动作；所有内容仅供人工观察。</p></div>
      <NButton secondary size="small" :loading="loading" :disabled="loading" @click="refreshAll">全部刷新</NButton>
    </header>
    <MarketRuntimeStatus
      :snapshot="runtime"
      :loading="runtimeState.loading.value"
      :stale="runtimeState.failed.value && Boolean(runtime)"
    />
    <SubingWorkbench
      :strategy-loading="subingWorkbench.strategyLoading.value"
      :strategy-status="subingWorkbench.strategyStatus.value"
      :strategy-trading-day="subingWorkbench.strategyTradingDay.value"
      :strategy-items="subingWorkbench.strategyItems.value"
      :strategy-stale="subingWorkbench.strategyStale.value"
      :daily-watch="subingWorkbench.dailyWatch.value"
      :daily-loading="subingWorkbench.dailyLoading.value"
      :daily-stale="subingWorkbench.dailyStale.value"
      @open-strategy="openStrategyAction"
      @open-daily="openDailyWatch"
    />
  </div>
</template>

<style scoped>
.market-dashboard-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.market-dashboard-page__intro { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.market-dashboard-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }
.market-dashboard-page__intro p { margin: 0; color: var(--gy-text-muted); }
</style>
