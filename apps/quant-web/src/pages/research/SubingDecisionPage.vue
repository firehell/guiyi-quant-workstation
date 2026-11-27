<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import SubingPortfolioWorkbench from '@/components/subing/SubingPortfolioWorkbench.vue'
import MarketNavigation from '@/components/market/MarketNavigation.vue'
import '@/styles/marketHome.css'

const route = useRoute()
const view = ref<'status' | 'history'>(route.query.mode === 'history' ? 'history' : 'status')
</script>

<template>
  <div class="market-dashboard-page subing-workbench">
    <MarketNavigation active-tab="subing-decision">
      <template #actions><span class="boundary">苏冰独立量化 · 16品种共享 Paper</span></template>
    </MarketNavigation>
    <main>
      <nav class="mode-nav" aria-label="苏冰数据模式">
        <button :aria-pressed="view === 'status'" @click="view = 'status'">持续模型</button>
        <button :aria-pressed="view === 'history'" @click="view = 'history'">历史回放</button>
      </nav>
      <SubingPortfolioWorkbench :mode="view" />
    </main>
  </div>
</template>

<style scoped>
.subing-workbench{background:#f8f9fb;--gy-detail-accent-soft:#fff4ee;--gy-border-focus:#ff6b2c}
.subing-workbench :deep(.market-navigation){background:#fff}
.subing-workbench :deep(.market-navigation__tabs button[aria-current=page]){color:#ff6b2c;background:#fff4ee;border-bottom:2px solid #ff6b2c;border-radius:0}
.subing-workbench main{padding:0 24px 24px;max-width:1920px;margin:auto}
.mode-nav{display:flex;gap:8px;padding-top:16px}
.mode-nav button{font:inherit;min-height:32px;border:1px solid #ebedf0;background:#fff;border-radius:6px;padding:5px 12px;color:#20242b;cursor:pointer}
.mode-nav button[aria-pressed=true]{background:#ff6b2c;color:white}
.boundary{font-size:12px;color:#667085}
</style>
