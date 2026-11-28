<script setup lang="ts">
import { useRouter } from 'vue-router'
import { lastWorkstationChart } from '@/utils/workstationRoutes'

const router = useRouter()
withDefaults(defineProps<{
  activeTab?: 'operations' | 'market' | 'research' | 'messages' | 'simulation' | 'subing-decision' | 'strategies' | 'backtests' | 'simulations' | null
}>(), { activeTab: null })
</script>

<template>
  <header class="market-navigation">
    <RouterLink class="market-navigation__brand" to="/workstation">归一量化</RouterLink>
    <nav class="market-navigation__tabs" role="tablist" aria-label="全局导航">
      <RouterLink to="/workstation" role="tab" :aria-selected="activeTab === 'operations'" :aria-current="activeTab === 'operations' ? 'page' : undefined">运行台</RouterLink>
      <button type="button" role="tab" :aria-selected="activeTab === 'market'" :aria-current="activeTab === 'market' ? 'page' : undefined" @click="router.push(lastWorkstationChart())">行情</button>
      <RouterLink to="/strategies" role="tab" :aria-selected="activeTab === 'strategies'" :aria-current="activeTab === 'strategies' ? 'page' : undefined">策略</RouterLink>
      <RouterLink to="/backtests" role="tab" :aria-selected="activeTab === 'backtests'" :aria-current="activeTab === 'backtests' ? 'page' : undefined">回测</RouterLink>
      <RouterLink to="/simulations" role="tab" :aria-selected="activeTab === 'simulations'" :aria-current="activeTab === 'simulations' ? 'page' : undefined">模拟交易</RouterLink>
      <RouterLink to="/research" role="tab" :aria-selected="activeTab === 'research' || activeTab === 'subing-decision'" :aria-current="activeTab === 'research' || activeTab === 'subing-decision' ? 'page' : undefined">研究</RouterLink>
      <RouterLink to="/market?tab=messages" :aria-current="activeTab === 'messages' ? 'page' : undefined">消息</RouterLink>
    </nav>
    <div class="market-navigation__search"><slot name="search" /></div>
    <div class="market-navigation__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.market-navigation a { text-decoration: none; }
.market-navigation { position: relative; z-index: 20; display: grid; grid-template-columns: auto auto minmax(220px, 420px) 1fr; align-items: center; gap: 18px; min-height: 52px; padding: 8px clamp(12px, 2vw, 24px); border-bottom: 1px solid var(--gy-border-subtle); background: var(--gy-bg-header); }
.market-navigation :is(button, .market-navigation__tabs a) { display: inline-flex; align-items: center; min-height: 36px; border: 0; border-radius: var(--gy-radius-md); color: var(--gy-text-secondary); background: transparent; font: inherit; cursor: pointer; }
.market-navigation :is(button, a):hover { background: var(--gy-bg-hover); }
.market-navigation :is(button, a):focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.market-navigation__brand { padding: 0 8px; color: var(--gy-text-primary) !important; font-size: var(--gy-font-size-lg) !important; font-weight: 800 !important; letter-spacing: .04em; }
.market-navigation__tabs { display: flex; align-items: center; gap: 2px; }
.market-navigation__tabs :is(button, a) { padding: 0 14px; }
.market-navigation__tabs :is(button, a)[aria-current="page"] { color: var(--gy-text-primary); background: var(--gy-detail-accent-soft); font-weight: 700; }
.market-navigation__search { min-width: 0; }
.market-navigation__actions { display: flex; justify-content: flex-end; gap: 12px; }
@media (max-width: 720px) {
  .market-navigation { grid-template-columns: auto 1fr auto; gap: 6px; min-height: auto; padding: 6px 12px 8px; }
  .market-navigation__brand { font-size: var(--gy-font-size-md) !important; }
  .market-navigation__tabs { min-width: 0; overflow-x: auto; }
  .market-navigation__tabs > * { flex: 0 0 auto; }
  .market-navigation__tabs :is(button, a) { min-width: 44px; min-height: 44px; padding: 0 8px; }
  .market-navigation__search { grid-column: 1 / -1; grid-row: 2; }
  .market-navigation__actions { grid-column: 3; grid-row: 1; }
}
</style>
