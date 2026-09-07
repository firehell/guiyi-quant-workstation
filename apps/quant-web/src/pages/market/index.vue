<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import '@/styles/marketHome.css'
import MarketHomeHeader from '@/components/market/MarketHomeHeader.vue'
import { productSectorLabel } from '@/utils/productDirectory'
import MarketHomeFocusRail from '@/components/market/MarketHomeFocusRail.vue'
import MarketHomeLegend from '@/components/market/MarketHomeLegend.vue'
import MarketHomeMobileList from '@/components/market/MarketHomeMobileList.vue'
import MarketHomeSectorTicker from '@/components/market/MarketHomeSectorTicker.vue'
import MarketHomeSkeleton from '@/components/market/MarketHomeSkeleton.vue'
import MarketHomeTable from '@/components/market/MarketHomeTable.vue'
import MarketHomeTrustStrip from '@/components/market/MarketHomeTrustStrip.vue'
import { getMarketHomeOverview } from '@/api/market'
import { getCurrentAlertEvents } from '@/api/alerts'
import { getRuntimeHealth } from '@/api/runtime'
import { useMarketHome } from '@/composables/useMarketHome'
import type { AlertEvent } from '@/types/market'
import { buildMarketHomeViewModel, type MarketHomeRow } from '@/utils/marketHomeViewModel'
import { loadMarketHomePreferences, saveMarketHomePreferences } from '@/utils/marketHomePreferences'
import { marketHomeEventChartQuery, marketHomeUnifiedProductChartQuery, marketHomeViewChartQuery } from '@/utils/marketHomeRoutes'
import { filterAndSortMarketHomeRows, nextMarketHomeSort, type MarketHomeSort, type MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'

const router = useRouter()
const initialPreferences = loadMarketHomePreferences()
const sector = ref(initialPreferences.sector)
const sort = ref<MarketHomeSort>(initialPreferences.sort)
const sortDirection = ref<MarketHomeSortDirection>(initialPreferences.sortDirection)
const compactDensity = ref(initialPreferences.compactDensity)
const focusRailCollapsed = ref(initialPreferences.focusRailCollapsed)
const home = useMarketHome({ fetchOverview: getMarketHomeOverview, fetchRuntime: getRuntimeHealth, fetchEvents: getCurrentAlertEvents, isEventUnavailable: (value) => value.status === 'unavailable' })
const model = computed(() => buildMarketHomeViewModel({ overview: home.overview.data.value ?? null, overviewStale: home.overview.stale.value ?? false, runtime: home.runtime.data.value ?? null, runtimeStale: home.runtime.stale.value ?? false, events: home.events.data.value ?? null, eventsStale: home.events.stale.value ?? false, eventsUnavailable: home.events.unavailable.value ?? false }))
const loading = computed(() => Boolean(home.overview.loading.value || home.runtime.loading.value || home.events.loading.value))
const rows = computed(() => filterAndSortMarketHomeRows(model.value.rows, { query: '', sector: sector.value, filter: 'all', sort: sort.value, sortDirection: sortDirection.value }))
const sectors = computed(() => home.overview.data.value?.sectors ?? [])
const selectedSector = computed(() => sectors.value.find((item) => item.sector === sector.value))
const eventItems = computed(() => model.value.events.availability === 'unavailable' ? [] : home.events.data.value?.items ?? [])

async function refreshAll() {
  await home.refreshAll()
}

function openProduct(item: MarketHomeRow) {
  void router.push({
    name: 'market-chart',
    query: marketHomeUnifiedProductChartQuery(item.symbol),
  })
}

function openEvent(event: AlertEvent) { void router.push({ name: 'market-chart', query: marketHomeEventChartQuery(event) }) }
function openView(view: 'newow' | 'htdy' | 'subing' | 'free', symbol: string) {
  void router.push({ name: 'market-chart', query: marketHomeViewChartQuery(view, symbol) })
}

function changeSort(column: MarketHomeSort) {
  const next = nextMarketHomeSort({ sort: sort.value, sortDirection: sortDirection.value }, column)
  sort.value = next.sort
  sortDirection.value = next.sortDirection
}

watch(sectors, (available) => {
  if (home.overview.data.value && sector.value && !available.some((item) => item.sector === sector.value)) sector.value = ''
})
watch([sector, sort, sortDirection, compactDensity, focusRailCollapsed], () => saveMarketHomePreferences({
  version: 1, sector: sector.value, sort: sort.value, sortDirection: sortDirection.value,
  compactDensity: compactDensity.value, detailFrequency: initialPreferences.detailFrequency,
  focusRailCollapsed: focusRailCollapsed.value,
}))

onMounted(() => {
  home.start()
})

onBeforeUnmount(() => {
  home.dispose()
})
</script>

<template>
  <div class="market-dashboard-page">
    <MarketHomeHeader :rows="model.rows" :loading="loading" @open-view="openView" @refresh="refreshAll" />
    <MarketHomeSectorTicker :sectors="sectors" :active="home.overview.data.value?.active_count ?? null" :selected="sector" @select="sector = $event" />
    <MarketHomeLegend />
    <section class="market-home-main">
      <header class="market-home-list-heading">
        <div><h1>{{ sector ? productSectorLabel(sector) : '全部品种' }}</h1><span>{{ rows.length }}</span><p>最近完整交易日收盘快照</p></div>
        <button type="button" :aria-expanded="!focusRailCollapsed" aria-controls="market-home-observations" @click="focusRailCollapsed = !focusRailCollapsed">研究观察 <span aria-hidden="true">{{ focusRailCollapsed ? '›' : '⌄' }}</span></button>
      </header>
      <MarketHomeFocusRail :availability="model.events.availability" :events="eventItems" :collapsed="focusRailCollapsed" @open="openEvent" />
      <MarketHomeTrustStrip :target-as-of="home.overview.data.value?.target_as_of ?? null" :as-of="home.overview.data.value?.data_as_of ?? null" :participants="home.overview.data.value?.participant_count ?? null" :active="home.overview.data.value?.active_count ?? null" :stale-count="home.overview.data.value?.stale_count ?? null" :unavailable-count="home.overview.data.value?.unavailable_count ?? null" :overview="model.overview.availability" :runtime="model.runtime.status" :event-state="model.events.availability" :overview-stale="model.overview.cachedStale" :runtime-stale="model.runtime.cachedStale" :event-stale="model.events.cachedStale" :overview-error="home.overview.error.value ?? null" />
      <p v-if="home.overview.unavailable.value && !home.overview.data.value" class="market-dashboard-page__error" role="alert">行情快照暂不可用；没有可展示的上一份成功快照。</p>
      <p v-else-if="home.overview.stale.value" class="market-dashboard-page__error" role="alert">行情刷新失败；正在展示上一份成功快照。</p>
      <MarketHomeSkeleton v-if="loading && !home.overview.data.value" />
      <template v-else>
        <MarketHomeTable :rows="rows" :event-availability="model.events.availability" :compact="compactDensity" :sort="sort" :sort-direction="sortDirection" @sort="changeSort" @open="openProduct" />
        <MarketHomeMobileList :rows="rows" :event-availability="model.events.availability" @open="openProduct" />
        <p v-if="!rows.length && home.overview.data.value" class="market-home-empty">当前{{ sector ? productSectorLabel(sector) : '快照' }}暂无可用品种。<span v-if="selectedSector">可用 {{ selectedSector.participant_count }} / 总数 {{ selectedSector.active_count }}；缺失品种不生成行情行。</span></p>
        <footer class="market-home-list-footer">已显示 {{ rows.length }} / {{ selectedSector?.active_count ?? home.overview.data.value?.active_count ?? '—' }} 品种 · {{ rows.length ? '向下滚动查看更多' : '等待可用快照' }}</footer>
      </template>
    </section>
  </div>
</template>
