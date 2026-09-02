<script setup lang="ts">
import { computed } from 'vue'
import type { DominantContractItem } from '@/types/market'
import { groupDominantsBySector, productSectorLabel } from '@/utils/productDirectory'

const props = defineProps<{
  items: DominantContractItem[]
  loading: boolean
  failed: boolean
  stale: boolean
}>()

const emit = defineEmits<{
  open: [item: DominantContractItem]
}>()

const groups = computed(() => groupDominantsBySector(props.items))
</script>

<template>
  <section class="market-product-directory" data-testid="market-product-directory" aria-label="品种列表">
    <header class="market-product-directory__header">
      <div>
        <h2>品种列表</h2>
        <p>按后端品种分类与最新主力映射展示。</p>
      </div>
      <span v-if="items.length" class="market-product-directory__count">{{ items.length }} 个品种</span>
    </header>

    <div v-if="!items.length" class="market-product-directory__unavailable">
      <strong>{{ loading ? '品种列表读取中' : failed ? '品种列表暂不可用' : '当前没有可用品种' }}</strong>
      <span>{{ loading ? '正在读取当前品种和真实主力合约。' : failed ? '本次读取失败，未获得可用目录。' : '后端当前未返回可用的真实主力合约。' }}</span>
    </div>
    <template v-else>
      <div v-if="stale" class="market-product-directory__stale" role="status">目录已过期：已保留上一份成功快照</div>
      <section v-for="group in groups" :key="group.id" class="market-product-directory__group" :aria-label="productSectorLabel(group.id)">
        <h3>{{ productSectorLabel(group.id) }}</h3>
        <div class="market-product-directory__grid">
          <button
            v-for="item in group.items"
            :key="item.product"
            type="button"
            class="market-product-directory__item"
            :data-testid="`market-product-${item.product}`"
            @click="emit('open', item)"
          >
            <strong>{{ item.product.toUpperCase() }}</strong>
            <span>{{ item.product_name }}</span>
            <small>{{ item.actual_contract }} · 映射 {{ item.dominant_mapping_date }}</small>
          </button>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.market-product-directory { border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); overflow: hidden; }
.market-product-directory__header { display: flex; align-items: start; justify-content: space-between; gap: 16px; padding: 13px 14px; border-bottom: .5px solid var(--gy-border); }
.market-product-directory__header h2 { margin: 0 0 4px; font-size: var(--gy-font-size-md); }
.market-product-directory__header p { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.market-product-directory__count { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); white-space: nowrap; }
.market-product-directory__group { padding: 12px 14px; }
.market-product-directory__group + .market-product-directory__group { border-top: .5px solid var(--gy-border); }
.market-product-directory__group h3 { margin: 0 0 9px; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); font-weight: 600; }
.market-product-directory__grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.market-product-directory__item { min-width: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 7px; align-items: baseline; padding: 9px 10px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); text-align: left; cursor: pointer; }
.market-product-directory__item:hover { border-color: var(--gy-accent); background: var(--gy-accent-soft); }
.market-product-directory__item:focus-visible { outline: 2px solid var(--gy-accent); outline-offset: 2px; }
.market-product-directory__item strong { font-size: var(--gy-font-size-sm); }
.market-product-directory__item span, .market-product-directory__item small { overflow: hidden; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
.market-product-directory__item small { grid-column: 1 / -1; }
.market-product-directory__stale { padding: 7px 14px; background: var(--gy-status-warning-soft); color: var(--gy-text-primary); font-size: var(--gy-font-size-xs); }
.market-product-directory__unavailable { display: flex; gap: 10px; align-items: baseline; padding: 14px; color: var(--gy-text-muted); }
.market-product-directory__unavailable strong { color: var(--gy-text-primary); }
@media (max-width: 1180px) { .market-product-directory__grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 800px) { .market-product-directory__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 560px) { .market-product-directory__header { align-items: flex-start; flex-direction: column; gap: 4px; } .market-product-directory__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
