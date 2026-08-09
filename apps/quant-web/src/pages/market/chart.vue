<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getCanonicalMarketCoverage, getMarketDominants } from '@/api/market'
import { useMarketSeries } from '@/composables/useMarketSeries'
import type {
  DominantContractItem,
  MarketCoverageItem,
  MarketFrequency,
  SeriesKind,
} from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const metadataLoading = ref(false)
const error = ref<string | null>(null)
const dominants = ref<DominantContractItem[]>([])
const coverageItems = ref<MarketCoverageItem[]>([])
const chart = ref<InstanceType<typeof KlineChart> | null>(null)
const {
  bars,
  hasMoreBefore,
  loadingInitial,
  loadingBefore,
  marketState,
  liveUnavailable,
  mutation,
  replaceSeries,
  loadMoreBefore,
  dispose,
} = useMarketSeries()
let metadataReady = false
let synchronizingSymbol = false

const symbol = ref(String(route.query.symbol || '').toLowerCase())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(normalizeSeriesKind(route.query.series_kind))
const frequency = ref<MarketFrequency>(normalizeFrequency(route.query.frequency))

const loading = computed(() => loadingInitial.value || loadingBefore.value)
const followLatest = ref(true)
const symbolOptions = computed(() => dominants.value.map((item) => ({
  label: `${item.product.toUpperCase()} ${item.product_name}`,
  value: item.product,
})))
const selectedDominant = computed(() => dominants.value.find((item) => item.product === symbol.value))
const frequencyOptions = MARKET_FREQUENCIES.map((value) => ({ label: value, value }))
const seriesOptions = [
  { label: '真实主力（查询时拼接）', value: 'actual_dominant' },
  { label: '主连', value: 'continuous' },
  { label: '指定真实合约', value: 'contract' },
]
const selectedCoverage = computed(() => coverageItems.value.find((item) =>
  item.frequency === frequency.value
  && item.kind === (seriesKind.value === 'continuous' ? 'continuous' : 'contract')
  && (seriesKind.value !== 'contract' || item.series_or_contract === contract.value),
))
const isLiveDisplay = computed(() => !!marketState.value?.live_eligible
  && !!marketState.value.live_available
  && !liveUnavailable.value)
const phaseLabel = computed(() => {
  switch (marketState.value?.phase) {
    case 'TRADING': return '交易中'
    case 'BREAK': return '盘中休市'
    case 'CLOSED': return '已收盘'
    default: return '状态未知'
  }
})
const afterMarketFailed = computed(() => {
  const afterMarket = marketState.value?.after_market
  return !!afterMarket && typeof afterMarket === 'object' && afterMarket.last_failure != null
})

onMounted(async () => {
  metadataLoading.value = true
  try {
    dominants.value = (await getMarketDominants()).items
    if (!symbol.value) symbol.value = dominants.value[0]?.product || ''
    syncDominantContract()
    await loadCoverage()
    await refreshSeries()
    metadataReady = true
  } catch {
    error.value = '行情元数据加载失败'
  } finally {
    metadataLoading.value = false
  }
})

watch(symbol, async () => {
  if (!metadataReady) return
  synchronizingSymbol = true
  syncDominantContract()
  try {
    await loadCoverage()
  } finally {
    synchronizingSymbol = false
  }
  await refreshSeries()
})

watch([contract, seriesKind, frequency], () => {
  if (metadataReady && !synchronizingSymbol) void refreshSeries()
})

watch(mutation, (nextMutation) => {
  if (!chart.value) return
  if (nextMutation.kind === 'replace') {
    chart.value.replaceBars(bars.value, !followLatest.value)
    return
  }
  if (nextMutation.kind === 'prepend') {
    chart.value.prependBars(nextMutation.bars)
    return
  }
  for (const bar of nextMutation.bars) chart.value.updateBar(bar)
  if (followLatest.value) chart.value.scrollToLatest()
})

onUnmounted(dispose)

function syncDominantContract() {
  const value = dominants.value.find((item) => item.product === symbol.value)
  if (value) contract.value = value.actual_contract
}

async function loadCoverage() {
  if (!symbol.value) return
  coverageItems.value = (await getCanonicalMarketCoverage(symbol.value)).items
}

function currentIdentity() {
  return {
    seriesKind: seriesKind.value,
    symbol: symbol.value,
    contract: seriesKind.value === 'contract' ? contract.value : undefined,
    frequency: frequency.value,
  }
}

async function refreshSeries() {
  if (!symbol.value) return
  if (seriesKind.value === 'contract' && !contract.value) {
    error.value = '指定真实合约时 contract 必填'
    return
  }
  const requested = currentIdentity()
  error.value = null
  followLatest.value = true
  try {
    await replaceSeries(requested)
    if (!isCurrentIdentity(requested)) return
    await router.replace({ query: {
      symbol: requested.symbol,
      contract: contract.value,
      series_kind: requested.seriesKind,
      frequency: requested.frequency,
    } })
  } catch {
    if (!isCurrentIdentity(requested)) return
    error.value = '读取失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
  }
}

async function loadEarlierBars() {
  try {
    await loadMoreBefore()
  } catch {
    error.value = '读取更早历史失败：数据集、月分区或主力映射不完整'
    message.error(error.value)
  }
}

function isCurrentIdentity(candidate: ReturnType<typeof currentIdentity>) {
  return candidate.seriesKind === seriesKind.value
    && candidate.symbol === symbol.value
    && candidate.contract === (seriesKind.value === 'contract' ? contract.value : undefined)
    && candidate.frequency === frequency.value
}

function normalizeFrequency(value: unknown): MarketFrequency {
  return MARKET_FREQUENCIES.includes(value as MarketFrequency) ? value as MarketFrequency : '15m'
}

function normalizeSeriesKind(value: unknown): SeriesKind {
  return value === 'continuous' || value === 'contract' ? value : 'actual_dominant'
}
</script>

<template>
  <div class="chart-page">
    <div class="toolbar">
      <NButton secondary @click="router.push({ name: 'market' })">返回</NButton>
      <NSelect v-model:value="symbol" :options="symbolOptions" filterable class="symbol-select" />
      <NSelect v-model:value="seriesKind" :options="seriesOptions" class="series-select" />
      <NSelect v-if="seriesKind === 'contract'" v-model:value="contract" :options="[{ label: contract, value: contract }]" class="contract-select" />
      <NSelect v-model:value="frequency" :options="frequencyOptions" class="frequency-select" />
      <NButton type="primary" :loading="loadingInitial" @click="refreshSeries">读取最新页</NButton>
    </div>

    <NSpin :show="metadataLoading">
      <NAlert v-if="error" type="error" :show-icon="true">{{ error }}</NAlert>
      <NCard size="small" :bordered="false" class="identity-card">
        <div class="identity-row">
          <strong>{{ symbol.toUpperCase() }} {{ selectedDominant?.product_name }}</strong>
          <NTag>{{ seriesKind }}</NTag>
          <NTag>{{ frequency }}</NTag>
          <span>{{ bars.length }} bars</span>
          <span v-if="selectedCoverage">{{ selectedCoverage.start }} → {{ selectedCoverage.end }}</span>
          <NTag v-if="hasMoreBefore" type="info">可继续向前加载</NTag>
          <NTag :type="isLiveDisplay ? 'success' : 'default'">{{ isLiveDisplay ? 'Live' : 'Historical' }}</NTag>
          <NTag>{{ phaseLabel }}</NTag>
          <span v-if="isLiveDisplay && marketState?.live_contract">当前 Live 主力合约 {{ marketState.live_contract }}</span>
          <NTag v-if="afterMarketFailed" type="warning">最近盘后更新失败</NTag>
          <NButton v-if="!followLatest" size="small" secondary @click="chart?.scrollToLatest()">回到最新</NButton>
        </div>
      </NCard>
      <KlineChart
        ref="chart"
        :bars="bars"
        :loading="loading"
        :error="error"
        :period="frequency"
        @need-more-before="loadEarlierBars"
        @follow-latest-change="followLatest = $event"
      />
    </NSpin>
  </div>
</template>

<style scoped>
.chart-page { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.symbol-select { width: 190px; }
.series-select { width: 220px; }
.contract-select { width: 150px; }
.frequency-select { width: 90px; }
.identity-card { background: var(--gy-bg-panel); }
.identity-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
</style>
