<script setup lang="ts">
/** 期货主力列表：展示 rank=1 真实主力合约，单击「查看 K 线」或双击行进入详情。 */
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NCard, NDataTable, NStatistic, NTag, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { getMarketDominants } from '@/api/market'
import type { DominantContractItem } from '@/types/market'
import { preferredOpenPeriod } from '@/utils/marketChartWindow'
import { isDominantMappingStale, safeMarketApiError, staleDominantMappingMessage } from '@/utils/marketChartQuery'

const route = useRoute()
const router = useRouter()
const message = useMessage()

const loading = ref(false)
const dominants = ref<DominantContractItem[]>([])

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
  {
    title: '映射日',
    key: 'dominant_mapping_date',
    width: 130,
    render: (row) => {
      const label = row.dominant_mapping_date || '-'
      if (!isDominantMappingStale(row.dominant_mapping_date)) return label
      return h('div', { class: 'mapping-date-cell' }, [
        h('span', null, label),
        h(NTag, { size: 'tiny', type: 'warning', style: { marginLeft: '6px' } }, { default: () => '可能过期' }),
      ])
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 110,
    fixed: 'right',
    render: (row) =>
      h(
        NButton,
        {
          size: 'tiny',
          type: 'primary',
          secondary: true,
          disabled: loading.value,
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            openChart(row)
          },
        },
        { default: () => '查看 K 线' },
      ),
  },
]

onMounted(async () => {
  // 若 URL 已带 symbol/contract，直接重定向到 chart 页（deep-link 兼容）
  if (route.query.symbol && route.query.contract) {
    void router.replace({
      name: 'market-chart',
      query: { ...route.query },
    })
    return
  }
  await loadDominants()
})

/** 加载全部主力合约；失败时清空列表并 toast。 */
async function loadDominants() {
  loading.value = true
  try {
    const response = await getMarketDominants()
    dominants.value = response.items
  } catch (err) {
    message.error(safeMarketApiError(err, '加载主力合约列表失败'))
    dominants.value = []
  } finally {
    loading.value = false
  }
}

/** 双击行：按 coverage 选首选周期，跳转 market-chart。 */
function openChart(row: DominantContractItem) {
  if (isDominantMappingStale(row.dominant_mapping_date)) {
    message.warning(staleDominantMappingMessage())
  }
  if (!row.quote_ready) {
    message.warning('该主力暂无 Canonical 覆盖，打开后可能 DataGap；可改用主连研究。')
  }
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

</script>

<template>
  <div class="market-list-page">
    <section class="page-header">
      <div>
        <h2>期货主力行情</h2>
        <p>全部主力合约一览；单击「查看 K 线」或双击行进入品种 K 线详情。</p>
      </div>
      <div class="page-stats">
        <NStatistic label="主力总数" :value="dominants.length" />
        <NStatistic label="有K线" :value="quoteReadyCount" />
      </div>
    </section>

    <NCard size="small" :bordered="false" class="table-card">
      <NDataTable
        :columns="columns"
        :data="dominants"
        :loading="loading"
        :row-key="rowKey"
        :row-props="rowProps"
        :pagination="false"
        size="small"
        striped
        flex-height
        style="height: calc(100vh - 200px); min-height: 480px"
      />
      <p class="table-hint">
        行情 K 线使用 rank=1 真实主力合约；主连仅用于连续序列研究，不在此列表展示。
      </p>
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

.table-card {
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
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
}
</style>
