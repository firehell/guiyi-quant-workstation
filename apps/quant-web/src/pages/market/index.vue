<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton } from 'naive-ui'
import MarketDetailTable from '@/components/market/MarketDetailTable.vue'
import MarketScatter from '@/components/market/MarketScatter.vue'
import MarketSummaryStrip from '@/components/market/MarketSummaryStrip.vue'
import MarketRadarSkeleton from '@/components/market/MarketRadarSkeleton.vue'
import MarketRuntimeStatus from '@/components/market/MarketRuntimeStatus.vue'
import SubingWorkbench from '@/components/market/SubingWorkbench.vue'
import { getMarketRadar, getSubingDailyWatchCurrent } from '@/api/market'
import { getRuntimeHealth } from '@/api/runtime'
import { getCurrentFormalSignals } from '@/api/alerts'
import type { CurrentFormalSignalItem } from '@/api/alerts'
import type {
  MarketRadarItem,
  MarketRadarResponse,
  SubingDailyWatchItem,
} from '@/types/market'
import { useLatestResource } from '@/composables/useLatestResource'
import { useSubingWorkbench } from '@/composables/useSubingWorkbench'
import {
  loadMarketWorkspacePreferences,
} from '@/utils/marketWorkspacePreferences'

const router = useRouter()
const subingWorkbench = useSubingWorkbench({
  fetchFormal: getCurrentFormalSignals,
  fetchDailyWatch: getSubingDailyWatchCurrent,
})
const runtimeState = useLatestResource({ fetch: getRuntimeHealth })
const radarState = useLatestResource<MarketRadarResponse>({ fetch: getMarketRadar })
const runtime = runtimeState.data
const radar = radarState.data
const error = radarState.failed
const loading = computed(() => (
  subingWorkbench.formalLoading.value
  || subingWorkbench.dailyLoading.value
  || runtimeState.loading.value
  || radarState.loading.value
))
const preferences = ref(loadMarketWorkspacePreferences())
const freshnessIssue = computed(() => {
  if (!radar.value || radar.value.freshness_state !== 'degraded') return ''
  const parts = [
    radar.value.stale.length ? `stale ${radar.value.stale.join(', ')}` : '',
    radar.value.unavailable.length ? `unavailable ${radar.value.unavailable.join(', ')}` : '',
  ].filter(Boolean)
  return `市场雷达数据不完整：${parts.join('；') || radar.value.freshness_message}`
})

function openChart(item: MarketRadarItem) {
  const frequency = preferences.value.frequency
  void router.push({
    name: 'market-chart',
    query: { symbol: item.symbol, series_kind: 'actual_dominant', frequency },
  })
}

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

function openFormalSignal(item: CurrentFormalSignalItem) {
  void router.push({
    name: 'market-chart',
    query: { symbol: item.symbol, series_kind: 'actual_dominant', frequency: item.frequency },
  })
}

async function refreshAll() {
  await Promise.all([
    subingWorkbench.refreshAll(),
    runtimeState.refresh(),
    radarState.refresh(),
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
  radarState.invalidate()
})
</script>

<template>
  <div class="market-radar-page">
    <header class="market-radar-page__intro">
      <div><h1>期货市场发现</h1><p>基于最近完整交易日的已校验日线研究快照；所有内容仅供人工观察。</p></div>
      <NButton secondary size="small" :loading="loading" :disabled="loading" @click="refreshAll">全部刷新</NButton>
    </header>
    <MarketRuntimeStatus
      :snapshot="runtime"
      :loading="runtimeState.loading.value"
      :stale="runtimeState.failed.value && Boolean(runtime)"
    />
    <SubingWorkbench
      :formal-loading="subingWorkbench.formalLoading.value"
      :formal-status="subingWorkbench.formalStatus.value"
      :formal-trading-day="subingWorkbench.formalTradingDay.value"
      :formal-items="subingWorkbench.formalItems.value"
      :formal-stale="subingWorkbench.formalStale.value"
      :daily-watch="subingWorkbench.dailyWatch.value"
      :daily-loading="subingWorkbench.dailyLoading.value"
      :daily-stale="subingWorkbench.dailyStale.value"
      @open-formal="openFormalSignal"
      @open-daily="openDailyWatch"
    />
    <MarketRadarSkeleton v-if="radarState.loading.value && !radar" />
    <template v-else>
      <div v-if="error" class="market-radar-page__error">
        <NAlert
          type="warning"
          :title="radar ? '市场雷达刷新失败' : '市场雷达暂不可用'"
        >
          {{ radar ? '已保留上一份成功快照；重试前请以其时点为准。' : '无法读取只读市场雷达；不影响品种工作台。' }}
        </NAlert>
      </div>
      <template v-if="radar">
        <NAlert v-if="freshnessIssue" type="warning" :title="freshnessIssue" />
        <details class="market-radar-page__research" data-testid="market-full-research">
          <summary>展开全市场研究</summary>
          <div class="market-radar-page__research-content">
            <MarketSummaryStrip :radar="radar" />
            <MarketScatter :items="radar.items" @open="openChart" />
            <MarketDetailTable :items="radar.items" :sectors="radar.sector_summary" @open="openChart" />
          </div>
        </details>
      </template>
    </template>
  </div>
</template>

<style scoped>
.market-radar-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.market-radar-page__intro { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.market-radar-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }
.market-radar-page__intro p { margin: 0; color: var(--gy-text-muted); }
.market-radar-page__error { display: flex; align-items: center; gap: 10px; }
.market-radar-page__error :deep(.n-alert) { min-width: 0; flex: 1; }
.market-radar-page__research { min-width: 0; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); }
.market-radar-page__research > summary { padding: 14px 16px; color: var(--gy-accent); font-weight: 500; cursor: pointer; }
.market-radar-page__research-content { display: flex; flex-direction: column; gap: 16px; padding: 0 16px 16px; }
</style>
