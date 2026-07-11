<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NDataTable, NInput, NSelect, NStatistic, NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { getMarketDominants } from '@/api/market'
import type { DominantContractItem } from '@/types/market'
import { EXCHANGES } from '@/utils/constants'
import { formatAvailablePeriodTags, preferredOpenPeriod } from '@/utils/marketChartWindow'

const route = useRoute()
const router = useRouter()
const message = useMessage()

const loading = ref(false)
const dominants = ref<DominantContractItem[]>([])
const search = ref('')
const exchange = ref<string | null>(null)

const exchangeOptions = computed(() => {
  const codes = [...new Set(dominants.value.map((item) => item.exchange).filter(Boolean))] as string[]
  return codes.sort().map((code) => {
    const match = dominants.value.find((item) => item.exchange === code)
    const preset = EXCHANGES.find((item) => item.value === code)
    return {
      label: match?.exchange_name ? `${match.exchange_name} (${code})` : preset?.label || code,
      value: code,
    }
  })
})

const filteredRows = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return dominants.value.filter((item) => {
    if (exchange.value && item.exchange !== exchange.value) return false
    if (!needle) return true
    return [
      item.product,
      item.product_name,
      item.actual_contract,
      item.continuous_contract,
      item.exchange || '',
      item.exchange_name || '',
      item.sector || '',
      item.category || '',
    ]
      .join(' ')
      .toLowerCase()
      .includes(needle)
  })
})

const quoteReadyCount = computed(() => dominants.value.filter((item) => item.quote_ready).length)

const rowKey = (row: DominantContractItem) => `${row.product}-${row.actual_contract}`

const rowProps = (row: DominantContractItem) => ({
  class: row.quote_ready ? '' : 'dominant-table-row--muted',
  onDblclick: () => openChart(row),
})

const columns: DataTableColumns<DominantContractItem> = [
  {
    title: '品种代码',
    key: 'product',
    width: 90,
    render: (row) => row.product.toUpperCase(),
  },
  { title: '品种名称', key: 'product_name', width: 140, ellipsis: { tooltip: true } },
  {
    title: '交易所',
    key: 'exchange',
    width: 120,
    render: (row) => row.exchange_name || row.exchange || '-',
  },
  { title: '板块', key: 'sector', width: 100, render: (row) => row.sector || '-' },
  { title: '类型', key: 'category', width: 100, render: (row) => row.category || '-' },
  {
    title: '状态',
    key: 'is_active',
    width: 90,
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.is_active === false ? 'default' : 'success' },
        { default: () => (row.is_active === false ? '停用' : '启用') },
      ),
  },
  { title: '主力合约', key: 'actual_contract', width: 110 },
  { title: '映射日', key: 'dominant_mapping_date', width: 110 },
  {
    title: '可用周期',
    key: 'bars_coverage',
    width: 220,
    render: (row) => {
      const tags = formatAvailablePeriodTags(row.bars_coverage)
      if (!tags.length) return '-'
      return h(
        'div',
        { class: 'period-tag-list' },
        tags.map((period) => h(NTag, { size: 'tiny', type: 'info', style: { marginRight: '4px' } }, { default: () => period })),
      )
    },
  },
  {
    title: 'K线',
    key: 'quote_ready',
    width: 90,
    render: (row) =>
      h(
        NTag,
        { size: 'small', type: row.quote_ready ? 'success' : 'default' },
        { default: () => (row.quote_ready ? '有K线' : '暂无') },
      ),
  },
]

onMounted(async () => {
  if (route.query.symbol && route.query.contract) {
    void router.replace({
      name: 'market-chart',
      query: { ...route.query },
    })
    return
  }
  await loadDominants()
})

async function loadDominants() {
  loading.value = true
  try {
    const response = await getMarketDominants()
    dominants.value = response.items
  } catch (err) {
    message.error(apiError(err, '加载主力合约列表失败'))
    dominants.value = []
  } finally {
    loading.value = false
  }
}

function openChart(row: DominantContractItem) {
  const period = preferredOpenPeriod(row.bars_coverage)
  const contractView = period === '1d' || period === '1w' ? 'continuous' : undefined
  void router.push({
    name: 'market-chart',
    query: {
      symbol: row.product,
      contract: row.actual_contract,
      period,
      contract_view: contractView,
    },
  })
}

function apiError(err: unknown, fallback: string) {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response
    return response?.data?.detail || fallback
  }
  return err instanceof Error ? err.message : fallback
}
</script>

<template>
  <div class="market-list-page">
    <section class="page-header">
      <div>
        <h2>期货主力行情</h2>
        <p>全部主力合约一览，双击行进入品种 K 线详情。</p>
      </div>
      <div class="page-stats">
        <NStatistic label="主力总数" :value="dominants.length" />
        <NStatistic label="有K线" :value="quoteReadyCount" />
      </div>
    </section>

    <NCard size="small" :bordered="false" class="toolbar-card">
      <div class="toolbar">
        <NInput v-model:value="search" clearable placeholder="搜索品种 / 合约 / 交易所 / 板块" />
        <NSelect
          v-model:value="exchange"
          :options="exchangeOptions"
          clearable
          placeholder="全部交易所"
          style="width: 220px"
        />
      </div>
    </NCard>

    <NCard size="small" :bordered="false" class="table-card">
      <NDataTable
        :columns="columns"
        :data="filteredRows"
        :loading="loading"
        :row-key="rowKey"
        :row-props="rowProps"
        :pagination="{ pageSize: 20 }"
        size="small"
        striped
        flex-height
        style="height: calc(100vh - 260px); min-height: 480px"
      />
      <p class="table-hint">行情 K 线使用 rank=1 真实主力合约；主连仅用于回测，不在此列表展示。</p>
    </NCard>
  </div>
</template>

<style scoped>
.market-list-page {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
  min-width: 0;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-header h2 {
  margin: 0 0 4px;
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-xl);
  font-weight: 700;
}

.page-header p,
.table-hint {
  margin: 0;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-base);
}

.page-stats {
  display: flex;
  gap: var(--gy-space-6);
}

.toolbar-card,
.table-card {
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
}

.toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 220px;
  gap: var(--gy-space-3);
}

.table-hint {
  margin-top: 10px;
}

:deep(.dominant-table-row--muted td) {
  opacity: 0.72;
}

@media (max-width: 1199px) {
  .page-header {
    flex-direction: column;
  }

  .toolbar {
    grid-template-columns: 1fr;
  }
}
</style>
