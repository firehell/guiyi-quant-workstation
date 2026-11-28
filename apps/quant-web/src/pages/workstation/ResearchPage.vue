<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef } from 'vue'
import MarketNavigation from '@/components/market/MarketNavigation.vue'
import NewowBacktestPanel from '@/components/market/detail/newow/NewowBacktestPanel.vue'
import { getMarketProductDirectory } from '@/api/market'
import type { MarketProductDirectoryItem } from '@/types/market'
import { workstationChartLink } from '@/utils/workstationRoutes'
import { physicalContract } from '@/utils/workstationAccounts'
import { backtestFrequencies, type LatestBacktest } from '@/utils/newowBacktestReader'

const products = shallowRef<MarketProductDirectoryItem[]>([])
const product = ref('')
const frequency = ref<string>('60m')
const strategy = ref('trend')
const error = ref(false)
const controller = new AbortController()
onMounted(async () => {
  try {
    const result = await getMarketProductDirectory(controller.signal)
    products.value = result.items
    product.value = result.items[0]?.product ?? ''
  } catch { if (!controller.signal.aborted) error.value = true }
})
onScopeDispose(() => controller.abort())

const published = shallowRef<LatestBacktest['result']>(null)
const referenceChartLink = computed(() => {
  const result = published.value
  if (!result) return null
  if (result.qualification !== 'QUALIFIED' || result.summary.result_kind !== 'reference_only'
    || typeof result.manifest.physical_contract !== 'string') return null
  const contract = physicalContract(product.value, result.manifest.physical_contract)
  const period = backtestFrequencies.find(item => item === frequency.value)
  if (!contract || !period) return null
  const link = workstationChartLink({
    view: 'newow', newowSource: 'after-market', symbol: product.value, seriesKind: 'contract', contract,
    frequency: period, strategy: strategy.value === 'oscillation' ? 'oscillation' : 'trend',
    newowMode: strategy.value === 'dual_fusion' ? 'dual' : undefined,
  })
  return { ...link, query: { ...link.query, reference_run: result.run_id } }
})
</script>

<template>
  <div class="research">
    <MarketNavigation active-tab="research" />
    <main>
      <h1>研究</h1>
      <nav aria-label="研究入口">
        <RouterLink to="/backtests">回测中心</RouterLink>
        <RouterLink to="/research/subing-decision?mode=history">苏冰独立量化回放</RouterLink>
      </nav>
      <section aria-labelledby="newow-research-heading">
        <h2 id="newow-research-heading">牛哇盘后与固定回测</h2>
        <p v-if="error" role="alert">品种目录读取失败。</p>
        <div v-else class="selection">
          <label>品种 <select v-model="product"><option v-for="item in products" :key="item.product" :value="item.product">{{ item.product_name }} {{ item.product.toUpperCase() }}</option></select></label>
          <label>周期 <select v-model="frequency"><option v-for="period in backtestFrequencies" :key="period">{{ period }}</option></select></label>
          <label>策略 <select v-model="strategy"><option value="trend">趋势</option><option value="oscillation">震荡</option><option value="dual_fusion">双策略</option></select></label>
        </div>
        <NewowBacktestPanel v-if="product" :product="product" :strategy="strategy" :frequency="frequency" after-market @published="published = $event">
          <template #result-actions>
            <RouterLink v-if="referenceChartLink" :to="referenceChartLink">在行情中查看</RouterLink>
          </template>
        </NewowBacktestPanel>
      </section>
    </main>
  </div>
</template>

<style scoped>
.research { min-height: 100%; background: var(--gy-bg-app); }
main { max-width: 1600px; margin: auto; padding: 24px 32px; }
h1 { margin: 0 0 14px; font-size: 24px; }
h2 { margin: 0 0 12px; font-size: 16px; }
nav, .selection { display: flex; align-items: center; gap: 16px; }
section { margin-top: 16px; padding: 16px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
select { padding: 4px 8px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: inherit; font: inherit; }
</style>
