<script setup lang="ts">
import { onMounted, onScopeDispose, ref, shallowRef } from 'vue'
import MarketNavigation from '@/components/market/MarketNavigation.vue'
import NewowMarketReferencePanel from '@/components/market/detail/newow/NewowMarketReferencePanel.vue'
import { getMarketProductDirectory } from '@/api/market'
import type { MarketProductDirectoryItem } from '@/types/market'
import { NEWOW_PRODUCT_FREQUENCIES } from '@/types/newowProduct'

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

</script>

<template>
  <div class="research">
    <MarketNavigation active-tab="research" />
    <main>
      <h1>研究</h1>
      <nav aria-label="苏冰研究结果">
        <RouterLink to="/research/subing-decision?mode=history">苏冰历史回放</RouterLink>
        <RouterLink to="/research/new-subing">新苏冰历史研究</RouterLink>
      </nav>
      <section aria-labelledby="newow-research-heading">
        <h2 id="newow-research-heading">牛哇盘后参考</h2>
        <p v-if="error" role="alert">品种目录读取失败。</p>
        <div v-else class="selection">
          <label>品种 <select v-model="product"><option v-for="item in products" :key="item.product" :value="item.product">{{ item.product_name }} {{ item.product.toUpperCase() }}</option></select></label>
          <label>周期 <select v-model="frequency"><option v-for="period in NEWOW_PRODUCT_FREQUENCIES" :key="period">{{ period }}</option></select></label>
          <label>策略 <select v-model="strategy"><option value="trend">趋势</option><option value="oscillation">震荡</option><option value="main_rise">主升浪</option></select></label>
        </div>
        <NewowMarketReferencePanel v-if="product" :product="product" :strategy="strategy" :frequency="frequency" />
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
