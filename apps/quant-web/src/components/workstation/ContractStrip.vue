<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef } from 'vue'
import { getMarketDominants } from '@/api/market'
import type { DominantContractItem } from '@/types/market'
import { physicalContract, type WorkstationContractActivity } from '@/utils/workstationAccounts'

const props = defineProps<{ activeContract?: string | null; activeProduct: string; activity: WorkstationContractActivity[] }>()
const emit = defineEmits<{ select: [item: ContractChoice] }>()
interface ContractChoice { product: string; contract: string; name: string }
const storageKey = 'guiyi.workstation.watchlist.v1'
function readWatched(): ContractChoice[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '[]')
    if (!Array.isArray(value)) return []
    return value.filter(item => item && typeof item.product === 'string' && typeof item.contract === 'string'
      && typeof item.name === 'string' && physicalContract(item.product, item.contract) === item.contract)
  } catch { return [] }
}
const watched = shallowRef(readWatched())
const dominants = shallowRef<DominantContractItem[]>([])
const directoryStatus = ref<'loading' | 'ready' | 'error'>('loading')
const filter = ref<'active' | 'watched' | 'all'>('all')
const search = ref('')
const controller = new AbortController()
onMounted(async () => {
  try {
    const result = await getMarketDominants(controller.signal)
    dominants.value = result.items
    directoryStatus.value = 'ready'
  } catch { if (!controller.signal.aborted) directoryStatus.value = 'error' }
})
onScopeDispose(() => controller.abort())
const productNames = computed(() => new Map(dominants.value.map(item => [item.product.toLowerCase(), item.product_name])))
const active = computed(() => props.activity.map(row => ({
  product: row.product, contract: row.contract, name: productNames.value.get(row.product) ?? row.product.toUpperCase(),
})))
const defaultContracts = computed(() => dominants.value.flatMap(item => {
  const contract = typeof item.actual_contract === 'string' ? physicalContract(item.product, item.actual_contract) : null
  return contract ? [{ product: item.product.toLowerCase(), contract, name: item.product_name }] : []
}))
const shown = computed(() => {
  const items = filter.value === 'active' ? active.value : filter.value === 'watched' ? watched.value
    : [...defaultContracts.value, ...active.value, ...watched.value]
  const query = search.value.trim().toLowerCase()
  return [...new Map(items.map(item => [item.contract, item])).values()]
    .filter(item => `${item.contract} ${item.product} ${item.name}`.toLowerCase().includes(query))
})
const activeChoice = computed<ContractChoice | null>(() => {
  const contract = props.activeContract && physicalContract(props.activeProduct, props.activeContract)
  return contract ? { product: props.activeProduct, contract, name: productNames.value.get(props.activeProduct) ?? props.activeProduct.toUpperCase() } : null
})
const isWatched = (contract: string) => watched.value.some(item => item.contract === contract)
function toggle(item: ContractChoice) {
  watched.value = isWatched(item.contract) ? watched.value.filter(row => row.contract !== item.contract)
    : [...watched.value, item]
  try { localStorage.setItem(storageKey, JSON.stringify(watched.value)) } catch { /* The list stays usable for this session. */ }
}
const filters = [{ id: 'active', label: '持仓/挂单' }, { id: 'watched', label: '重点关注' }, { id: 'all', label: '全部' }] as const
</script>

<template>
  <section class="contract-strip" aria-label="合约列表">
    <div class="contract-strip__controls">
      <div role="group" aria-label="合约筛选">
        <button v-for="option in filters" :key="option.id" type="button" :aria-pressed="filter === option.id" @click="filter = option.id">{{ option.label }}</button>
      </div>
      <input v-model="search" type="search" aria-label="搜索合约" placeholder="搜索合约或品种">
      <button v-if="activeChoice" type="button" :aria-pressed="isWatched(activeChoice.contract)" @click="toggle(activeChoice)">{{ isWatched(activeChoice.contract) ? '移出重点关注' : '加入重点关注' }}</button>
    </div>
    <p v-if="filter === 'active'" class="note">已读取的账户持仓与待处理记录 · 账户核验与覆盖见运行台</p>
    <p v-if="filter === 'all' && directoryStatus === 'error'" role="status">当前主力合约目录读取失败。</p>
    <ul v-if="shown.length">
      <li v-for="item in shown" :key="item.contract">
        <button type="button" :aria-current="item.contract === activeContract ? 'true' : undefined" @click="emit('select', item)"><strong>{{ item.contract }}</strong><span>{{ item.name }}</span></button>
        <button type="button" :aria-label="`${isWatched(item.contract) ? '取消关注' : '关注'} ${item.contract}`" :aria-pressed="isWatched(item.contract)" @click="toggle(item)">{{ isWatched(item.contract) ? '★' : '☆' }}</button>
      </li>
    </ul>
    <p v-else-if="filter === 'all' && directoryStatus === 'loading'" role="status">正在读取合约目录…</p>
    <p v-else class="note">{{ search ? '没有匹配的合约' : filter === 'watched' ? '尚未添加关注合约' : '当前列表没有已读取的合约' }}</p>
  </section>
</template>

<style scoped>
.contract-strip { border-bottom: 1px solid var(--gy-border-subtle); padding-block: 8px; }
.contract-strip__controls, .contract-strip__controls > div, ul, li { display: flex; align-items: center; gap: 6px; }
input, button { font: inherit; color: inherit; border: 1px solid var(--gy-border); background: var(--gy-bg-panel); border-radius: 5px; padding: 4px 8px; min-height: 30px; white-space: nowrap; }
button { cursor: pointer; }
button[aria-pressed=true], button[aria-current=true] { background: var(--gy-detail-accent-soft); border-color: var(--gy-detail-accent); }
ul { overflow-x: auto; list-style: none; margin: 8px 0 0; padding: 0 0 4px; }
li { gap: 0; }
li button:first-child { border-radius: 5px 0 0 5px; }
li button + button { border-radius: 0 5px 5px 0; border-left: none; }
li span { color: var(--gy-text-secondary); margin-left: 6px; }
.note { font-size: 12px; color: var(--gy-text-secondary); margin: 5px 0 0; }
</style>
