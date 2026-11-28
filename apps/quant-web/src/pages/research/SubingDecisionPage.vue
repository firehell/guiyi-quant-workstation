<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SubingPortfolioWorkbench from '@/components/subing/SubingPortfolioWorkbench.vue'
import MarketNavigation from '@/components/market/MarketNavigation.vue'

const route = useRoute()
const router = useRouter()
const view = computed(() => route.query.mode === 'history' ? 'history' : 'status')
function selectView(mode: 'status' | 'history') {
  void router.push({ name: 'subing-decision', query: { ...route.query, mode: mode === 'history' ? mode : undefined } })
}
</script>

<template>
  <div class="subing-workbench">
    <MarketNavigation active-tab="subing-decision">
      <template #actions><span class="boundary">16品种共享模型 · 研究候选</span></template>
    </MarketNavigation>
    <main>
      <nav class="mode-nav" aria-label="苏冰数据模式">
        <button :aria-pressed="view === 'status'" @click="selectView('status')">持续模型</button>
        <button :aria-pressed="view === 'history'" @click="selectView('history')">历史回放</button>
      </nav>
      <SubingPortfolioWorkbench :mode="view" />
    </main>
  </div>
</template>

<style scoped>
.subing-workbench{min-height:100%;background:var(--gy-bg-app);color:var(--gy-text-primary)}
.subing-workbench main{padding:0 24px 24px;max-width:1920px;margin:auto}
.mode-nav{display:flex;gap:8px;padding-top:16px}
.mode-nav button{font:inherit;min-height:32px;border:1px solid var(--gy-border);background:var(--gy-bg-panel);border-radius:6px;padding:5px 12px;color:var(--gy-text-primary);cursor:pointer}
.mode-nav button[aria-pressed=true]{background:var(--gy-detail-accent-soft);color:var(--gy-link)}
.boundary{font-size:12px;color:var(--gy-text-secondary)}
</style>
