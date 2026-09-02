<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'
import MarketHomeFocusRail from '@/components/market/MarketHomeFocusRail.vue'
import MarketHomeLegend from '@/components/market/MarketHomeLegend.vue'
import MarketHomeMobileList from '@/components/market/MarketHomeMobileList.vue'
import MarketHomeSectorTicker from '@/components/market/MarketHomeSectorTicker.vue'
import MarketHomeSkeleton from '@/components/market/MarketHomeSkeleton.vue'
import MarketHomeSummary from '@/components/market/MarketHomeSummary.vue'
import MarketHomeTable from '@/components/market/MarketHomeTable.vue'
import MarketHomeToolbar from '@/components/market/MarketHomeToolbar.vue'
import MarketHomeTrustStrip from '@/components/market/MarketHomeTrustStrip.vue'
import { getMarketHomeOverview } from '@/api/market'
import { getCurrentHtdyEvents } from '@/api/alerts'
import { getRuntimeHealth } from '@/api/runtime'
import { useMarketHome } from '@/composables/useMarketHome'
import type { AlertEvent } from '@/types/market'
import { buildMarketHomeViewModel, type MarketHomeRow } from '@/utils/marketHomeViewModel'
import { loadMarketHomePreferences, saveMarketHomePreferences } from '@/utils/marketHomePreferences'
import { marketHomeEventChartQuery, marketHomeProductChartQuery } from '@/utils/marketHomeRoutes'
import { filterAndSortMarketHomeRows, type MarketHomeAlignmentFilter, type MarketHomeDataFilter, type MarketHomeEventFilter, type MarketHomeLocalFilter, type MarketHomeSort, type MarketHomeTrendFilter } from '@/utils/marketHomeWorkspace'

const router = useRouter()
const initialPreferences = loadMarketHomePreferences()
const query = ref(initialPreferences.query)
const sector = ref(initialPreferences.sector)
const summaryFilter = ref<MarketHomeLocalFilter>('all')
const sort = ref<MarketHomeSort>(initialPreferences.sort)
const daily = ref<MarketHomeTrendFilter>('all')
const weekly = ref<MarketHomeTrendFilter>('all')
const alignment = ref<MarketHomeAlignmentFilter>('all')
const event = ref<MarketHomeEventFilter>('all')
const data = ref<MarketHomeDataFilter>('all')
const home = useMarketHome({ fetchOverview: getMarketHomeOverview, fetchRuntime: getRuntimeHealth, fetchEvents: getCurrentHtdyEvents })
const model = computed(() => buildMarketHomeViewModel({ overview: home.overview.data.value ?? null, overviewStale: home.overview.stale.value ?? false, runtime: home.runtime.data.value ?? null, runtimeStale: home.runtime.stale.value ?? false, events: home.events.data.value ?? null, eventsStale: home.events.stale.value ?? false }))
const loading = computed(() => home.overview.loading.value || home.runtime.loading.value || home.events.loading.value)
const rows = computed(() => filterAndSortMarketHomeRows(model.value.rows, { query: query.value, sector: sector.value, filter: summaryFilter.value, sort: sort.value, daily: daily.value, weekly: weekly.value, alignment: alignment.value, event: event.value, data: data.value }))
const latestEventTime = computed(() => home.events.data.value?.items[0]?.detected_at ?? null)

async function refreshAll() {
  await home.refreshAll()
}

function openProduct(item: MarketHomeRow) {
  void router.push({
    name: 'market-chart',
    query: marketHomeProductChartQuery(item.symbol),
  })
}

function openEvent(event: AlertEvent) { void router.push({ name: 'market-chart', query: marketHomeEventChartQuery(event) }) }
watch([query,sector,sort], () => saveMarketHomePreferences({ version: 1, query: query.value, sector: sector.value, sort: sort.value }))

onMounted(() => {
  home.start()
})

onBeforeUnmount(() => {
  home.dispose()
})
</script>

<template>
  <div class="market-dashboard-page">
    <header class="market-dashboard-page__intro">
      <div><h1>行情看板</h1><p>完成周期市场事实与 HTDY 观察；所有内容仅供人工复核。</p></div>
      <NButton secondary size="small" :loading="loading" :disabled="loading" @click="refreshAll">全部刷新</NButton>
    </header>
    <MarketHomeSectorTicker class="market-dashboard-page__ticker" :sectors="home.overview.data.value?.sectors??[]" @select="sector=$event"/>
    <MarketHomeLegend class="market-dashboard-page__legend"/>
    <MarketHomeTrustStrip class="market-dashboard-page__trust" :target-as-of="home.overview.data.value?.target_as_of??null" :as-of="home.overview.data.value?.data_as_of??null" :participants="home.overview.data.value?.participant_count??0" :active="home.overview.data.value?.active_count??0" :stale-count="home.overview.data.value?.stale_count??0" :unavailable-count="home.overview.data.value?.unavailable_count??0" :overview="model.overview.availability" :runtime="model.runtime.status" :event-state="model.events.availability" :overview-stale="model.overview.cachedStale" :runtime-stale="model.runtime.cachedStale" :event-stale="model.events.cachedStale"/>
    <MarketHomeSummary class="market-dashboard-page__summary" :summary="home.overview.data.value?.summary??null" :active="summaryFilter" :event-count="home.events.data.value?.items.length??0" :latest-event-time="latestEventTime" @filter="summaryFilter=$event"/>
    <p v-if="home.overview.unavailable.value" class="market-dashboard-page__error" role="alert">Market Home overview 暂不可用；没有可展示的上一份成功快照。</p>
    <MarketHomeSkeleton v-if="loading&&!home.overview.data.value"/>
    <template v-else><div class="market-dashboard-page__workspace"><div><MarketHomeToolbar v-model:query="query" v-model:sort="sort" v-model:daily="daily" v-model:weekly="weekly" v-model:alignment="alignment" v-model:event="event" v-model:data="data"/><MarketHomeTable :rows="rows" @open="openProduct"/><MarketHomeMobileList :rows="rows" @open="openProduct"/></div><MarketHomeFocusRail :availability="model.events.availability" :events="home.events.data.value?.items??[]" @open="openEvent"/></div></template>
  </div>
</template>

<style scoped>
.market-dashboard-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.market-dashboard-page__intro { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.market-dashboard-page__intro h1 { margin: 0 0 6px; font-size: var(--gy-font-size-xl); }
.market-dashboard-page__intro p { margin: 0; color: var(--gy-text-muted); }
.market-dashboard-page__error{margin:0;padding:12px;border-radius:var(--gy-radius-md);background:var(--gy-surface-error);color:var(--gy-text-primary)}
.market-dashboard-page__workspace{display:grid;grid-template-columns:minmax(0,1fr) 304px;gap:16px}.market-dashboard-page__workspace>div{min-width:0}@media(max-width:1199px){.market-dashboard-page__workspace{display:flex;flex-direction:column}.market-dashboard-page__workspace aside{order:-1}}@media(max-width:767px){.market-dashboard-page{gap:12px}.market-dashboard-page__ticker,.market-dashboard-page__legend,.market-dashboard-page__summary{display:none}.market-dashboard-page__workspace{gap:12px}.market-dashboard-page__workspace aside{order:-1}}
</style>
