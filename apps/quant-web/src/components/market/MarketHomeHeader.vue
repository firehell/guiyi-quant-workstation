<script setup lang="ts">
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'

type HomeView = 'newow' | 'htdy' | 'subing' | 'free'
defineProps<{ rows: MarketHomeRow[]; loading: boolean }>()
const emit = defineEmits<{ openView: [view: HomeView, symbol: string]; refresh: [] }>()
const views: Array<{ view: HomeView; label: string }> = [
  { view: 'newow', label: '牛哇' }, { view: 'htdy', label: '火天大有' },
  { view: 'subing', label: '苏冰预警' }, { view: 'free', label: '更多' },
]
function openView(event: MouseEvent, view: HomeView, symbol: string) {
  const button = event.currentTarget as HTMLButtonElement
  button.closest('details')?.removeAttribute('open')
  emit('openView', view, symbol)
}
function closeMenu(event: KeyboardEvent) {
  const menu = event.currentTarget as HTMLDetailsElement
  menu.open = false
  menu.querySelector('summary')?.focus()
}
</script>

<template>
  <header class="market-home-header">
    <a class="market-home-brand" href="/market" aria-label="归一量化市场首页">归一量化</a>
    <nav aria-label="行情视角">
      <span class="market-home-nav-current" aria-current="page">市场</span>
      <details v-for="item in views" :key="item.view" @keydown.esc.prevent="closeMenu">
        <summary>{{ item.label }}<span v-if="item.view === 'free'" aria-hidden="true">⌄</span></summary>
        <div class="market-home-view-menu">
          <strong>{{ item.view === 'free' ? '自由看盘 · 选择品种' : `${item.label} · 选择品种` }}</strong>
          <p v-if="!rows.length">当前快照暂无可用品种，暂时无法进入该视角。</p>
          <div v-else class="market-home-view-products">
            <button v-for="row in rows" :key="row.symbol" type="button" @click="openView($event, item.view, row.symbol)">
              {{ row.product_name }} <span>{{ row.symbol.toUpperCase() }}</span>
            </button>
          </div>
        </div>
      </details>
    </nav>
    <button class="market-home-refresh" type="button" :disabled="loading" @click="$emit('refresh')">{{ loading ? '刷新中…' : '刷新' }}</button>
  </header>
</template>
