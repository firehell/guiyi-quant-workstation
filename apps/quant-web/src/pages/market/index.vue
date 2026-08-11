<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NDataTable, NTabPane, NTabs, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { getMarketDominants } from '@/api/market'
import type { DominantContractItem } from '@/types/market'
import {
  DEFAULT_PRODUCT_SECTOR,
  describeProduct,
  PRODUCT_SECTORS,
  type ProductSector,
} from '@/utils/productDirectory'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const dominants = ref<DominantContractItem[]>([])
const selectedSector = ref<ProductSector>(DEFAULT_PRODUCT_SECTOR)

const availableSectors = computed(() => PRODUCT_SECTORS.filter((sector) =>
  dominants.value.some((row) => describeProduct(row.product, row.product_name).sector === sector.id),
))

const sectorRows = (sector: ProductSector) => dominants.value.filter(
  (row) => describeProduct(row.product, row.product_name).sector === sector,
)

const columns: DataTableColumns<DominantContractItem> = [
  { title: '品种', key: 'product', width: 90, render: (row) => row.product.toUpperCase() },
  { title: '名称', key: 'product_name', minWidth: 130, render: (row) => describeProduct(row.product, row.product_name).name },
  { title: '交易所', key: 'exchange', width: 110 },
  { title: 'rank1 真实合约', key: 'actual_contract', width: 150 },
  { title: '映射交易日', key: 'dominant_mapping_date', width: 140 },
  {
    title: '操作',
    key: 'actions',
    width: 110,
    render: (row) => h(
      NButton,
      { size: 'small', type: 'primary', secondary: true, onClick: () => openChart(row) },
      { default: () => '查看 K 线' },
    ),
  },
]

function openChart(row: DominantContractItem) {
  void router.push({
    name: 'market-chart',
    query: {
      symbol: row.product,
      contract: row.actual_contract,
      series_kind: 'actual_dominant',
      frequency: '15m',
    },
  })
}

onMounted(async () => {
  loading.value = true
  try {
    dominants.value = (await getMarketDominants()).items
  } catch {
    message.error('加载当前主力映射失败')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="market-page">
    <header>
      <h2>期货行情</h2>
      <p>按产业板块浏览当前 rank1 主力映射；历史 K 线统一由 MarketDataService 读取 Canonical。</p>
    </header>
    <NCard size="small" :bordered="false">
      <NTabs v-model:value="selectedSector" type="line" animated>
        <NTabPane
          v-for="sector in availableSectors"
          :key="sector.id"
          :name="sector.id"
          :tab="`${sector.label} ${sectorRows(sector.id).length}`"
        >
          <NDataTable
            :columns="columns"
            :data="sectorRows(sector.id)"
            :loading="loading"
            :row-key="(row: DominantContractItem) => `${row.product}-${row.actual_contract}`"
            :pagination="false"
            size="small"
            striped
            flex-height
            style="height: calc(100vh - 238px); min-height: 430px"
          />
        </NTabPane>
      </NTabs>
    </NCard>
  </div>
</template>

<style scoped>
.market-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
header h2 { margin: 0 0 6px; }
header p { margin: 0; color: var(--gy-text-muted); }
</style>
