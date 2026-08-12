<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NDivider, NTag } from 'naive-ui'
import type { DominantContractItem, MarketFrequency, SeriesKind } from '@/types/market'

const props = defineProps<{
  dominant: DominantContractItem | undefined
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract: string
  live: boolean
  phase: string
  hasMoreBefore: boolean
  watchlisted: boolean
}>()

const emit = defineEmits<{
  'toggle-watchlist': []
}>()

const seriesLabel = computed(() => {
  if (props.seriesKind === 'actual_dominant') return '真实主力'
  if (props.seriesKind === 'continuous') return '主连'
  return '指定合约'
})
</script>

<template>
  <aside class="research-sidebar">
    <div class="research-sidebar__header">
      <div>
        <span class="research-sidebar__eyebrow">品种上下文</span>
        <strong>{{ dominant?.product.toUpperCase() || '--' }} {{ dominant?.product_name || '' }}</strong>
      </div>
      <NButton size="small" :type="watchlisted ? 'primary' : 'default'" @click="emit('toggle-watchlist')">
        {{ watchlisted ? '已自选' : '加入自选' }}
      </NButton>
    </div>
    <dl class="research-sidebar__facts">
      <div><dt>序列</dt><dd>{{ seriesLabel }}</dd></div>
      <div><dt>周期</dt><dd>{{ frequency === '1d' ? 'D' : frequency === '1w' ? 'W' : frequency }}</dd></div>
      <div><dt>当前主力</dt><dd>{{ seriesKind === 'contract' ? contract : dominant?.actual_contract || '--' }}</dd></div>
      <div><dt>映射日</dt><dd>{{ dominant?.dominant_mapping_date || '--' }}</dd></div>
      <div><dt>数据状态</dt><dd><NTag size="small" :type="live ? 'success' : 'default'">{{ live ? 'Live' : 'Historical' }}</NTag></dd></div>
      <div><dt>市场状态</dt><dd>{{ phase }}</dd></div>
    </dl>
    <NDivider />
    <div class="research-sidebar__note">
      <span>历史浏览</span>
      <strong>{{ hasMoreBefore ? '可继续向左加载' : '已到当前可读边界' }}</strong>
    </div>
  </aside>
</template>

<style scoped>
.research-sidebar { min-width: 0; padding: 14px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.research-sidebar__header { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
.research-sidebar__header strong { display: block; margin-top: 2px; }
.research-sidebar__eyebrow { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.research-sidebar__facts { margin: 16px 0 0; display: grid; gap: 10px; }
.research-sidebar__facts > div { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.research-sidebar__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.research-sidebar__facts dd { margin: 0; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); text-align: right; }
.research-sidebar__note { display: grid; gap: 4px; font-size: var(--gy-font-size-sm); }
.research-sidebar__note > span { color: var(--gy-text-muted); }
</style>
