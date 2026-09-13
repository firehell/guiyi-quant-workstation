<script setup lang="ts">
import { nextTick } from 'vue'
import { RouterLink } from 'vue-router'
import MarketChevron from './MarketChevron.vue'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'

type HomeView = 'newow' | 'htdy' | 'subing' | 'free'
defineProps<{ rows: MarketHomeRow[]; loading: boolean; activeTab: 'market' | 'messages' }>()
const emit = defineEmits<{ openView: [view: HomeView, symbol: string]; refresh: []; selectTab: [tab: 'market' | 'messages'] }>()
const views: Array<{ view: HomeView; label: string }> = [
  { view: 'newow', label: '牛哇' }, { view: 'htdy', label: '火天大有' },
  { view: 'subing', label: '苏冰预警' }, { view: 'free', label: '自由看盘' },
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
async function openMenuFromKeyboard(event: KeyboardEvent) {
  const details = (event.currentTarget as HTMLElement).closest('details')
  if (!details) return
  details.open = true
  await nextTick()
  details.querySelector<HTMLButtonElement>('.market-home-view-products button')?.focus()
}
function moveMenuFocus(event: KeyboardEvent, direction: number | 'first' | 'last') {
  const buttons = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('button')]
  if (!buttons.length) return
  const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const index = direction === 'first' ? 0 : direction === 'last' ? buttons.length - 1 : (current + direction + buttons.length) % buttons.length
  buttons[index]?.focus()
}
</script>

<template>
  <header class="market-home-header">
    <RouterLink class="market-home-brand" to="/market" aria-label="归一量化市场首页" @click="emit('selectTab', 'market')">归一量化</RouterLink>
    <nav aria-label="首页导航">
      <span class="market-home-tabs" role="tablist" aria-label="首页内容">
        <button role="tab" type="button" :aria-selected="activeTab === 'market'" @click="emit('selectTab', 'market')">市场</button>
        <button role="tab" type="button" :aria-selected="activeTab === 'messages'" @click="emit('selectTab', 'messages')">消息</button>
      </span>
      <details v-for="item in views" :key="item.view" @keydown.esc.prevent="closeMenu">
        <summary @keydown.down.prevent="openMenuFromKeyboard">{{ item.label }}<MarketChevron /></summary>
        <div class="market-home-view-menu">
          <strong>{{ item.label }} · 选择品种</strong>
          <p v-if="!rows.length">当前快照暂无可用品种，暂时无法进入该视角。</p>
          <div v-else class="market-home-view-products" @keydown.down.prevent="moveMenuFocus($event, 1)" @keydown.up.prevent="moveMenuFocus($event, -1)" @keydown.home.prevent="moveMenuFocus($event, 'first')" @keydown.end.prevent="moveMenuFocus($event, 'last')">
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
