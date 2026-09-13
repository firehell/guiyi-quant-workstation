<script setup lang="ts">
withDefaults(defineProps<{ activeTab?: 'market' | 'messages' | null }>(), { activeTab: null })
const emit = defineEmits<{ market: []; messages: [] }>()
</script>

<template>
  <header class="market-navigation">
    <button class="market-navigation__brand" type="button" aria-label="归一量化市场首页" @click="emit('market')">归一量化</button>
    <nav class="market-navigation__tabs" role="tablist" aria-label="全局导航">
      <button type="button" role="tab" :aria-selected="activeTab === 'market'" :aria-current="activeTab === 'market' ? 'page' : undefined" @click="emit('market')">市场</button>
      <button type="button" role="tab" :aria-selected="activeTab === 'messages'" :aria-current="activeTab === 'messages' ? 'page' : undefined" @click="emit('messages')">消息</button>
    </nav>
    <div class="market-navigation__search"><slot name="search" /></div>
    <div class="market-navigation__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.market-navigation { position: relative; z-index: 20; display: grid; grid-template-columns: auto auto minmax(220px, 420px) 1fr; align-items: center; gap: 18px; min-height: 52px; padding: 8px clamp(12px, 2vw, 24px); border-bottom: 1px solid var(--gy-border-subtle); background: var(--gy-bg-header); }
.market-navigation button { min-height: 36px; border: 0; border-radius: var(--gy-radius-md); color: var(--gy-text-secondary); background: transparent; font: inherit; cursor: pointer; }
.market-navigation button:hover { background: var(--gy-bg-hover); }
.market-navigation button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.market-navigation__brand { padding: 0 8px; color: var(--gy-text-primary) !important; font-size: var(--gy-font-size-lg) !important; font-weight: 800 !important; letter-spacing: .04em; }
.market-navigation__tabs { display: flex; align-items: center; gap: 2px; }
.market-navigation__tabs button { padding: 0 14px; }
.market-navigation__tabs button[aria-current="page"] { color: var(--gy-text-primary); background: var(--gy-detail-accent-soft); font-weight: 700; }
.market-navigation__search { min-width: 0; }
.market-navigation__actions { display: flex; justify-content: flex-end; }
@media (max-width: 720px) {
  .market-navigation { grid-template-columns: auto 1fr auto; gap: 6px; min-height: auto; padding: 6px 12px 8px; }
  .market-navigation__brand { font-size: var(--gy-font-size-md) !important; }
  .market-navigation__tabs { justify-self: end; }
  .market-navigation__tabs button { min-width: 44px; min-height: 44px; padding: 0 8px; }
  .market-navigation__search { grid-column: 1 / -1; grid-row: 2; }
  .market-navigation__actions { grid-column: 3; grid-row: 1; }
}
</style>
