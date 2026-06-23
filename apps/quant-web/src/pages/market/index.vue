<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NDatePicker, NSelect, NStatistic, useMessage } from 'naive-ui'
import KlineChart from '@/components/kline/KlineChart.vue'
import { getContracts, getCoverage } from '@/api/data'
import { getKlines } from '@/api/market'
import type { ContractInfo, CoverageInfo } from '@/types/data'
import type { BarData } from '@/types/market'
import { PERIODS } from '@/utils/constants'

interface CoverageOption {
  symbol: string
  contract: string
  exchange: string
  period: string
  startTime: string
  endTime: string
  rowCount: number
  qualityStatus: string
}

const message = useMessage()
const loadingMeta = ref(false)
const loadingBars = ref(false)
const error = ref<string | null>(null)
const contracts = ref<ContractInfo[]>([])
const coverage = ref<CoverageOption[]>([])
const bars = ref<BarData[]>([])
const selectedSymbol = ref<string | null>(null)
const selectedContract = ref<string | null>(null)
const selectedPeriod = ref<string | null>(null)
const dateRange = ref<[number, number] | null>(null)

const instrumentOptions = computed(() => {
  const symbols = new Map<string, CoverageOption>()
  coverage.value.forEach((item) => {
    if (!symbols.has(item.symbol)) symbols.set(item.symbol, item)
  })
  return [...symbols.values()].map((item) => ({
    label: `${contractName(item.contract) || item.symbol} (${item.symbol})`,
    value: item.symbol,
  }))
})

const contractOptions = computed(() => {
  const items = coverage.value.filter((item) => item.symbol === selectedSymbol.value)
  const contractsByCode = new Map<string, CoverageOption>()
  items.forEach((item) => {
    if (!contractsByCode.has(item.contract)) contractsByCode.set(item.contract, item)
  })
  return [...contractsByCode.values()].map((item) => ({
    label: `${contractName(item.contract) || item.contract} · ${item.exchange}`,
    value: item.contract,
  }))
})

const periodOptions = computed(() => {
  const available = new Set(
    coverage.value
      .filter((item) => item.symbol === selectedSymbol.value && item.contract === selectedContract.value)
      .map((item) => item.period),
  )
  return PERIODS.filter((period) => available.has(period.value)).map((period) => ({
    label: period.label,
    value: period.value,
  }))
})

const selectedCoverage = computed(() =>
  coverage.value.find(
    (item) =>
      item.symbol === selectedSymbol.value &&
      item.contract === selectedContract.value &&
      item.period === selectedPeriod.value,
  ),
)

const latestBar = computed(() => bars.value.at(-1))
const priceChange = computed(() => {
  if (bars.value.length < 2) return null
  const previous = bars.value.at(-2)!.close
  const current = bars.value.at(-1)!.close
  return current - previous
})
const priceChangePercent = computed(() => {
  if (bars.value.length < 2) return null
  const previous = bars.value.at(-2)!.close
  if (previous === 0) return null
  return ((bars.value.at(-1)!.close - previous) / previous) * 100
})

onMounted(async () => {
  await loadMeta()
})

watch([selectedSymbol, selectedContract, selectedPeriod], () => {
  syncDateRange()
})

async function loadMeta() {
  loadingMeta.value = true
  error.value = null
  try {
    const [contractRows, coverageRows] = await Promise.all([getContracts(), getCoverage()])
    contracts.value = contractRows
    coverage.value = normalizeCoverage(coverageRows)
    pickDefaultSelection()
    await loadBars()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loadingMeta.value = false
  }
}

async function loadBars() {
  if (!selectedSymbol.value || !selectedContract.value || !selectedPeriod.value) {
    bars.value = []
    return
  }
  loadingBars.value = true
  error.value = null
  try {
    const range = dateRange.value
    const rows = await getKlines({
      symbol: selectedSymbol.value,
      contract: selectedContract.value,
      period: selectedPeriod.value,
      start: range ? formatDate(range[0]) : undefined,
      end: range ? formatDate(range[1]) : undefined,
      limit: 10000,
    })
    bars.value = rows
    if (rows.length === 0) message.warning('当前选择没有可展示的 K 线')
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'K 线加载失败'
    bars.value = []
  } finally {
    loadingBars.value = false
  }
}

function normalizeCoverage(rows: CoverageInfo[]): CoverageOption[] {
  return rows
    .filter((row) => row.file_path.includes('/canonical/bars/') && row.quality_status !== 'failed')
    .map((row) => ({
      symbol: row.instrument_symbol || '',
      contract: row.contract_code || '',
      exchange: extractPartition(row.file_path, 'exchange') || '',
      period: row.period || '',
      startTime: row.start_time,
      endTime: row.end_time,
      rowCount: row.row_count || 0,
      qualityStatus: row.quality_status,
    }))
    .filter((row) => row.symbol && row.contract && row.period)
    .sort((first, second) => {
      if (first.symbol !== second.symbol) return first.symbol.localeCompare(second.symbol)
      if (first.contract !== second.contract) return first.contract.localeCompare(second.contract)
      return periodRank(first.period) - periodRank(second.period)
    })
}

function pickDefaultSelection() {
  if (coverage.value.length === 0) return
  const rb5m = coverage.value.find((item) => item.symbol === 'rb' && item.contract === 'rb.MAIN' && item.period === '5m')
  const preferred = rb5m || coverage.value.find((item) => item.period === '5m') || coverage.value[0]
  selectedSymbol.value = preferred.symbol
  selectedContract.value = preferred.contract
  selectedPeriod.value = preferred.period
  syncDateRange()
}

function syncDateRange() {
  const currentCoverage = selectedCoverage.value
  if (!currentCoverage) return
  const end = new Date(currentCoverage.endTime).getTime()
  const start = Math.max(new Date(currentCoverage.startTime).getTime(), end - 90 * 24 * 60 * 60 * 1000)
  dateRange.value = [start, end]
}

function handleSymbolUpdate(value: string) {
  selectedSymbol.value = value
  const nextContract = contractOptions.value[0]?.value || null
  selectedContract.value = nextContract
  selectedPeriod.value = pickPeriod(nextContract)
}

function handleContractUpdate(value: string) {
  selectedContract.value = value
  selectedPeriod.value = pickPeriod(value)
}

function handlePeriodUpdate(value: string) {
  selectedPeriod.value = value
}

function pickPeriod(contract: string | null) {
  if (!contract) return null
  const periods = coverage.value
    .filter((item) => item.symbol === selectedSymbol.value && item.contract === contract)
    .map((item) => item.period)
  return periods.includes('5m') ? '5m' : periods[0] || null
}

function contractName(contract: string) {
  return contracts.value.find((item) => item.contract_code === contract)?.name
}

function extractPartition(path: string, key: string) {
  const match = path.match(new RegExp(`${key}=([^/]+)`))
  return match?.[1]
}

function periodRank(period: string) {
  const order = ['5m', '15m', '30m', '60m', '1d']
  const index = order.indexOf(period)
  return index === -1 ? 99 : index
}

function formatDate(value: number) {
  const date = new Date(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
</script>

<template>
  <div class="market-page">
    <section class="toolbar">
      <NSelect
        class="toolbar__select"
        :value="selectedSymbol"
        :options="instrumentOptions"
        :loading="loadingMeta"
        placeholder="品种"
        filterable
        @update:value="handleSymbolUpdate"
      />
      <NSelect
        class="toolbar__select toolbar__select--wide"
        :value="selectedContract"
        :options="contractOptions"
        :loading="loadingMeta"
        placeholder="合约"
        @update:value="handleContractUpdate"
      />
      <NSelect
        class="toolbar__select toolbar__select--period"
        :value="selectedPeriod"
        :options="periodOptions"
        placeholder="周期"
        @update:value="handlePeriodUpdate"
      />
      <NDatePicker v-model:value="dateRange" class="toolbar__range" type="daterange" clearable />
      <NButton type="primary" :loading="loadingBars" @click="loadBars">刷新</NButton>
    </section>

    <section class="stats">
      <NStatistic label="最新价" :value="latestBar?.close ?? '-'" />
      <NStatistic label="涨跌" :value="priceChange === null ? '-' : priceChange.toFixed(2)" />
      <NStatistic label="涨跌幅" :value="priceChangePercent === null ? '-' : `${priceChangePercent.toFixed(2)}%`" />
      <NStatistic label="成交量" :value="latestBar?.volume ?? '-'" />
      <NStatistic label="K线数量" :value="bars.length" />
    </section>

    <KlineChart :bars="bars" :loading="loadingBars || loadingMeta" :error="error" />
  </div>
</template>

<style scoped>
.market-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  background: #111827;
  border: 1px solid #1f2937;
  border-radius: 6px;
}

.toolbar__select {
  width: 180px;
}

.toolbar__select--wide {
  width: 240px;
}

.toolbar__select--period {
  width: 120px;
}

.toolbar__range {
  width: 260px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
  padding: 12px;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
}

@media (max-width: 980px) {
  .toolbar {
    flex-wrap: wrap;
  }

  .toolbar__select,
  .toolbar__select--wide,
  .toolbar__select--period,
  .toolbar__range {
    width: calc(50% - 5px);
  }

  .stats {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
</style>
