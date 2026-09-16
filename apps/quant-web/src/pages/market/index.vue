<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import '@/styles/marketHome.css'
import MarketHomeHeader from '@/components/market/MarketHomeHeader.vue'
import { normalizeProductOptions } from '@/utils/productSearch'
import { productSectorLabel } from '@/utils/productDirectory'
import MarketHomeLegend from '@/components/market/MarketHomeLegend.vue'
import MarketHomeMessages from '@/components/market/MarketHomeMessages.vue'
import MarketHomeMobileList from '@/components/market/MarketHomeMobileList.vue'
import MarketHomeSectorTicker from '@/components/market/MarketHomeSectorTicker.vue'
import MarketHomeSkeleton from '@/components/market/MarketHomeSkeleton.vue'
import MarketHomeTable from '@/components/market/MarketHomeTable.vue'
import { getMarketDominants, getMarketHomeOverview } from '@/api/market'
import { getRuntimeHealth } from '@/api/runtime'
import { useMarketHome } from '@/composables/useMarketHome'
import { useMarketHomeLive } from '@/composables/useMarketHomeLive'
import { useNewowCapabilities } from '@/composables/useNewowCapabilities'
import type { AlertEvent } from '@/types/market'
import { buildMarketHomeViewModel, type MarketHomeRow } from '@/utils/marketHomeViewModel'
import { loadMarketHomePreferences, saveMarketHomePreferences } from '@/utils/marketHomePreferences'
import { marketHomeEventChartQuery, marketHomeUnifiedProductChartQuery, marketHomeViewChartQuery } from '@/utils/marketHomeRoutes'
import { filterAndSortMarketHomeRows, nextMarketHomeSort, type MarketHomeSort, type MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'
import { projectMarketHomeLiveRows } from '@/utils/marketHomeLiveView'

const router = useRouter()
const initialPreferences = loadMarketHomePreferences()
const sector = ref(initialPreferences.sector)
const sort = ref<MarketHomeSort>(initialPreferences.sort)
const sortDirection = ref<MarketHomeSortDirection>(initialPreferences.sortDirection)
const compactDensity = ref(initialPreferences.compactDensity)
const activeTab = ref<'market' | 'messages'>(loadActiveTab())
const messageReloadSequence = ref(0)
const navigationError = ref<string | null>(null)
const newowCapabilities = useNewowCapabilities()
const home = useMarketHome({
  fetchOverview: getMarketHomeOverview,
  fetchDirectory: getMarketDominants,
  fetchRuntime: getRuntimeHealth,
  overviewCacheKey: 'market-home-overview-v1',
})
const productOptions = computed(() => normalizeProductOptions(home.directory.data.value?.items ?? []))
const directoryStatus = computed(() => home.directory.unavailable.value ? 'error' : home.directory.data.value == null ? 'loading' : 'ready')
const model = computed(() => buildMarketHomeViewModel({ overview: home.overview.data.value ?? null, overviewStale: home.overview.stale.value ?? false, runtime: home.runtime.data.value ?? null, runtimeStale: home.runtime.stale.value ?? false }))
const live = useMarketHomeLive({ onAuthorityChanged: () => { home.invalidateOverview(); void home.refreshOverviewIfExpired() } })
const loading = computed(() => Boolean(home.overview.loading.value || home.runtime.loading.value))
const displayRows = computed(() => projectMarketHomeLiveRows(model.value.rows, live.items.value))
const rows = computed(() => filterAndSortMarketHomeRows(displayRows.value, { query: '', sector: sector.value, filter: 'all', sort: sort.value, sortDirection: sortDirection.value }))
const sectors = computed(() => home.overview.data.value?.sectors ?? [])
const selectedSector = computed(() => sectors.value.find((item) => item.sector === sector.value))
const liveStatus = computed(() => {
  const observed = live.observedAt.value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(live.observedAt.value)) : null
  if (live.connection.value === 'connected') return `分钟行情已连接${observed ? ` · ${observed}` : ''}`
  if (live.connection.value === 'stale' || (live.connection.value === 'unavailable' && live.stale.value)) return `断线保留最新快照${observed ? ` · ${observed}` : ''}`
  if (live.connection.value === 'unavailable') return '分钟行情不可用'
  return '分钟行情连接中'
})
let restoreFrame: number | null = null

async function refreshAll() {
  if (activeTab.value === 'messages') {
    void home.directory.refresh()
    messageReloadSequence.value += 1
    return
  }
  await home.refreshAll()
  live.restart()
}

function openProduct(item: MarketHomeRow) {
  const frequency = newowCapabilities.openFrequencies.value[0]
  if (newowCapabilities.state.value !== 'ready' || !frequency) {
    navigationError.value = newowCapabilities.error.value ?? '牛哇开放能力仍在读取，暂不能安全进入。'
    return
  }
  rememberPageState()
  navigationError.value = null
  void router.push({
    name: 'market-chart',
    query: marketHomeUnifiedProductChartQuery(item.symbol, frequency),
  })
}

function openEvent(event: AlertEvent) { rememberPageState(); void router.push({ name: 'market-chart', query: marketHomeEventChartQuery(event) }) }
function openView(view: 'newow' | 'htdy' | 'subing' | 'free', symbol: string) {
  const frequency = newowCapabilities.openFrequencies.value[0] ?? null
  if (view === 'newow' && (newowCapabilities.state.value !== 'ready' || frequency === null)) {
    navigationError.value = newowCapabilities.error.value ?? '牛哇开放能力仍在读取，暂不能安全进入。'
    return
  }
  rememberPageState()
  navigationError.value = null
  void router.push({ name: 'market-chart', query: marketHomeViewChartQuery(view, symbol, frequency) })
}

function selectTab(tab: 'market' | 'messages') {
  activeTab.value = tab
  saveActiveTab(tab)
}

function homeScrollElement(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  const content = document.querySelector<HTMLElement>('.content--market-home')
  const nested = content?.querySelector<HTMLElement>('.n-layout-scroll-container') ?? null
  return [content, nested, document.scrollingElement as HTMLElement | null].find((element) => Boolean(element && element.scrollHeight > element.clientHeight + 1)) ?? content ?? nested
}

function rememberPageState() {
  if (typeof window === 'undefined') return
  try {
    saveActiveTab(activeTab.value)
    sessionStorage.setItem('guiyi.market-home.scroll.v1', String(homeScrollElement()?.scrollTop ?? 0))
  } catch {}
}

function restorePageScroll() {
  if (typeof window === 'undefined') return
  let top = 0
  try { top = Number(sessionStorage.getItem('guiyi.market-home.scroll.v1') ?? 0) || 0 } catch {}
  restoreFrame = window.requestAnimationFrame(() => {
    restoreFrame = window.requestAnimationFrame(() => {
      homeScrollElement()?.scrollTo({ top })
      restoreFrame = null
    })
  })
}

function loadActiveTab(): 'market' | 'messages' {
  if (typeof window === 'undefined') return 'market'
  try { return sessionStorage.getItem('guiyi.market-home.tab.v1') === 'messages' ? 'messages' : 'market' } catch { return 'market' }
}

function saveActiveTab(tab: 'market' | 'messages') {
  if (typeof window === 'undefined') return
  try { sessionStorage.setItem('guiyi.market-home.tab.v1', tab) } catch {}
}

function changeSort(column: MarketHomeSort) {
  const next = nextMarketHomeSort({ sort: sort.value, sortDirection: sortDirection.value }, column)
  sort.value = next.sort
  sortDirection.value = next.sortDirection
}

watch(sectors, (available) => {
  if (home.overview.data.value && sector.value && !available.some((item) => item.sector === sector.value)) sector.value = ''
})
watch([sector, sort, sortDirection, compactDensity], () => saveMarketHomePreferences({
  version: 1, sector: sector.value, sort: sort.value, sortDirection: sortDirection.value,
  compactDensity: compactDensity.value, detailFrequency: initialPreferences.detailFrequency,
  focusRailCollapsed: true,
}))

onMounted(() => {
  home.start()
  live.start()
  void newowCapabilities.load()
  void nextTick(restorePageScroll)
})

onBeforeUnmount(() => {
  rememberPageState()
  if (restoreFrame !== null && typeof window !== 'undefined') window.cancelAnimationFrame(restoreFrame)
  home.dispose()
  live.dispose()
})
</script>

<template>
  <div class="market-dashboard-page">
    <MarketHomeHeader :options="productOptions" :directory-status="directoryStatus" :loading="activeTab === 'market' && loading" :active-tab="activeTab" @select-tab="selectTab" @open-view="openView" @refresh="refreshAll" />
    <p v-if="navigationError" class="market-dashboard-page__navigation-error" role="alert">{{ navigationError }}</p>
    <template v-if="activeTab === 'market'">
      <MarketHomeSectorTicker :sectors="sectors" :active="home.overview.data.value?.active_count ?? null" :selected="sector" @select="sector = $event" />
      <MarketHomeLegend />
      <section class="market-home-main">
      <header class="market-home-list-heading">
        <div><h1>{{ sector ? productSectorLabel(sector) : '全部品种' }}</h1><span>{{ rows.length }}</span><p>{{ rows.some((row) => row.liveQuote) ? '最新已完成行情；日周指标仍为收盘口径' : '最近完整交易日收盘快照' }}</p></div>
        <div class="market-home-live-status" :class="`market-home-live-status--${live.connection.value}`" aria-live="polite"><span>{{ liveStatus }}</span><button v-if="live.connection.value === 'stale' || live.connection.value === 'unavailable'" type="button" @click="live.restart">重连行情</button></div>
      </header>
      <p v-if="home.overview.unavailable.value && !home.overview.data.value" class="market-dashboard-page__error" role="alert">行情快照暂不可用；没有可展示的上一份成功快照。</p>
      <p v-else-if="home.overview.stale.value" class="market-dashboard-page__error" role="alert">行情刷新失败；正在展示上一份成功快照。</p>
      <MarketHomeSkeleton v-if="loading && !home.overview.data.value" />
      <template v-else>
        <MarketHomeTable :rows="rows" :compact="compactDensity" :sort="sort" :sort-direction="sortDirection" :live-stale="live.stale.value" @sort="changeSort" @open="openProduct" />
        <MarketHomeMobileList :rows="rows" :live-stale="live.stale.value" @open="openProduct" />
        <p v-if="!rows.length && home.overview.data.value" class="market-home-empty">当前{{ sector ? productSectorLabel(sector) : '快照' }}暂无可用品种。<span v-if="selectedSector">可用 {{ selectedSector.participant_count }} / 总数 {{ selectedSector.active_count }}；缺失品种不生成行情行。</span></p>
      </template>
      </section>
    </template>
    <MarketHomeMessages v-else :options="productOptions" :directory-status="directoryStatus" :reload-sequence="messageReloadSequence" @open="openEvent" />
  </div>
</template>
