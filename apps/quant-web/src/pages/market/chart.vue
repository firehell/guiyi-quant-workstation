<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NDatePicker, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getCanonicalMarketCoverage, getMarketBars, getMarketDominants } from '@/api/market'
import type {
  BarData,
  DominantContractItem,
  MarketBarsResponse,
  MarketCoverageItem,
  MarketFrequency,
  SeriesKind,
} from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const loading = ref(false)
const metadataLoading = ref(false)
const error = ref<string | null>(null)
const dominants = ref<DominantContractItem[]>([])
const coverageItems = ref<MarketCoverageItem[]>([])
const bars = ref<BarData[]>([])
const response = ref<MarketBarsResponse | null>(null)

const symbol = ref(String(route.query.symbol || '').toLowerCase())
const contract = ref(String(route.query.contract || '').toUpperCase())
const seriesKind = ref<SeriesKind>(normalizeSeriesKind(route.query.series_kind))
const frequency = ref<MarketFrequency>(normalizeFrequency(route.query.frequency))
const range = ref<[number, number]>(defaultRange())

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

onMounted(async () => {
  metadataLoading.value = true
  try {
    dominants.value = (await getMarketDominants()).items
    if (!symbol.value) symbol.value = dominants.value[0]?.product || ''
    syncDominantContract()
    await loadCoverage()
    applyCoverageRange()
    await loadBars()
  } catch {
    error.value = '行情元数据加载失败'
  } finally {
    metadataLoading.value = false
  }
})

watch(symbol, async () => {
  syncDominantContract()
  await loadCoverage()
  applyCoverageRange()
})

watch([seriesKind, frequency], () => applyCoverageRange())

function syncDominantContract() {
  const value = dominants.value.find((item) => item.product === symbol.value)
  if (value) contract.value = value.actual_contract
}

async function loadCoverage() {
  if (!symbol.value) return
  coverageItems.value = (await getCanonicalMarketCoverage(symbol.value)).items
}

function applyCoverageRange() {
  const item = selectedCoverage.value
  if (item) range.value = [Date.parse(item.start), Date.parse(item.end)]
}

async function loadBars() {
  if (!symbol.value || !range.value) return
  if (seriesKind.value === 'contract' && !contract.value) {
    error.value = '指定真实合约时 contract 必填'
    return
  }
  loading.value = true
  error.value = null
  try {
    const result = await getMarketBars({
      series_kind: seriesKind.value,
      symbol: symbol.value,
      contract: seriesKind.value === 'contract' ? contract.value : undefined,
      frequency: frequency.value,
      start: new Date(range.value[0]).toISOString(),
      end: new Date(range.value[1]).toISOString(),
    })
    response.value = result
    bars.value = result.bars.map((item) => ({
      time: item.bar_end,
      trading_day: item.trading_day,
      open: Number(item.open),
      high: Number(item.high),
      low: Number(item.low),
      close: Number(item.close),
      volume: Number(item.volume),
      turnover: item.turnover === null ? undefined : Number(item.turnover),
      openInterest: item.open_interest === null ? undefined : Number(item.open_interest),
    }))
    await router.replace({ query: {
      symbol: symbol.value,
      contract: contract.value,
      series_kind: seriesKind.value,
      frequency: frequency.value,
    } })
  } catch (caught) {
    bars.value = []
    response.value = null
    error.value = '读取失败：窗口可能与 DataGap 相交，或 Catalog/Manifest/Map 不完整'
    message.error(error.value)
  } finally {
    loading.value = false
  }
}

function defaultRange(): [number, number] {
  const end = Date.now()
  return [end - 90 * 24 * 60 * 60 * 1000, end]
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
      <NDatePicker v-model:value="range" type="datetimerange" clearable class="date-range" />
      <NButton type="primary" :loading="loading" @click="loadBars">读取</NButton>
    </div>

    <NSpin :show="metadataLoading">
      <NAlert v-if="error" type="error" :show-icon="true">{{ error }}</NAlert>
      <NCard size="small" :bordered="false" class="identity-card">
        <div class="identity-row">
          <strong>{{ symbol.toUpperCase() }} {{ selectedDominant?.product_name }}</strong>
          <NTag>{{ seriesKind }}</NTag>
          <NTag>{{ frequency }}</NTag>
          <span>{{ bars.length }} bars</span>
          <span v-if="response?.coverage">{{ response.coverage.start }} → {{ response.coverage.end }}</span>
        </div>
        <div v-if="response" class="digest-row">
          <span>分区 {{ response.partition_digests.length }}</span>
          <span>合约段 {{ response.resolved_contract_segments.length }}</span>
          <span v-if="response.main_map_digest">Map {{ response.main_map_digest.slice(0, 12) }}</span>
        </div>
      </NCard>
      <KlineChart :bars="bars" :loading="loading" :error="error" :period="frequency" />
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
.date-range { width: 360px; }
.identity-card { background: var(--gy-bg-panel); }
.identity-row, .digest-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.digest-row { margin-top: 8px; color: var(--gy-text-muted); font-size: 12px; }
</style>
