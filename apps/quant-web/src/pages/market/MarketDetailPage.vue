<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MarketDetailQuoteHeader from '@/components/market/detail/MarketDetailQuoteHeader.vue'
import MarketDetailTopBar from '@/components/market/detail/MarketDetailTopBar.vue'
import MarketDetailUnavailable from '@/components/market/detail/MarketDetailUnavailable.vue'
import MarketDetailViewNav from '@/components/market/detail/MarketDetailViewNav.vue'
import { useMarketDetailController } from '@/composables/useMarketDetailController'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import { loadMarketDetailPreferences } from '@/utils/marketDetailPreferences'
import { parseMarketDetailRoute, serializeMarketDetailIdentity } from '@/utils/marketDetailRoute'

const route = useRoute()
const router = useRouter()
const preferences = loadMarketDetailPreferences()
const moreOpen = ref(false)
const controller = useMarketDetailController({ routeQuery: () => ({ ...route.query }) })
const routeResult = computed(() => parseMarketDetailRoute({ ...route.query }))
const explicitIdentity = computed(() => routeResult.value.kind === 'valid' ? routeResult.value.identity : null)
const isFreePreview = computed(() => explicitIdentity.value?.view === 'free')
const shellReady = computed(() => isFreePreview.value && controller.state.value.header !== null && !controller.state.value.loading)
const header = computed(() => controller.state.value.header)
const identityKey = computed(() => {
  const identity = explicitIdentity.value
  return identity
    ? [identity.view, identity.symbol, identity.seriesKind, identity.contract ?? '', identity.frequency].join(':')
    : 'invalid'
})
async function activateRoute() {
  moreOpen.value = false
  const result = routeResult.value
  if (result.kind !== 'valid' || result.identity.view !== 'free') return
  await controller.switchIdentity(result.identity)
}

function legacyQuery(identity: MarketDetailIdentity | null) {
  if (routeResult.value.kind === 'valid') {
    const { view: _view, ...query } = route.query
    const identity = routeResult.value.identity
    return {
      ...query,
      symbol: identity.symbol,
      series_kind: identity.seriesKind,
      frequency: identity.frequency,
      contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
      ...(identity.view === 'htdy' ? { overlay: 'htdy' } : {}),
    }
  }
  if (!identity) {
    const symbol = typeof route.query.symbol === 'string' ? route.query.symbol : ''
    return symbol ? { symbol } : {}
  }
  const { view: _view, ...query } = serializeMarketDetailIdentity(identity)
  return {
    ...query,
    ...(identity.view === 'htdy' ? { overlay: 'htdy' } : {}),
  }
}

function returnLegacy() {
  void router.push({ path: '/market/chart', query: legacyQuery(explicitIdentity.value ?? (routeResult.value.kind === 'invalid' ? routeResult.value.recovery : null)) })
}

function recover() {
  const recovery = routeResult.value.kind === 'invalid' ? routeResult.value.recovery : null
  if (!recovery) return
  void router.replace({ path: '/market/chart', query: serializeMarketDetailIdentity(recovery) })
}

function selectIdentity(identity: MarketDetailIdentity) {
  void router.push({ path: '/market/chart', query: serializeMarketDetailIdentity(identity) })
}

function goBack() {
  void router.push('/market')
}

onMounted(activateRoute)
onBeforeUnmount(controller.dispose)
</script>

<template>
  <main class="market-detail-page" :data-detail-ready="shellReady ? 'true' : 'false'">
    <template v-if="routeResult.kind === 'invalid'">
      <MarketDetailUnavailable
        title="详情页地址无效"
        message="当前地址与统一详情页身份合同不一致，已拒绝静默修正。"
        :can-recover="routeResult.recovery !== null"
        :can-return-legacy="true"
        @recover="recover"
        @return-legacy="returnLegacy"
      />
    </template>

    <template v-else-if="routeResult.kind === 'valid' && routeResult.identity.view !== 'free'">
      <MarketDetailUnavailable
        title="当前视角尚未接入统一详情页"
        message="Slice A 仅开放自由看盘的 Shell 预览入口；该 Workspace 将在对应后续 Slice 中接入。"
        :can-return-legacy="true"
        @return-legacy="returnLegacy"
      />
    </template>

    <template v-else-if="routeResult.kind === 'valid'">
      <MarketDetailTopBar
        :product-name="header?.productName ?? routeResult.identity.symbol.toUpperCase()"
        :symbol="routeResult.identity.symbol"
        :display-contract="header?.displayContract ?? routeResult.identity.contract ?? null"
        :actions="{ canOpenHistory: false, canManageAlert: false }"
        @back="goBack"
        @select-symbol="returnLegacy"
        @open-more="moreOpen = !moreOpen"
      />
      <div v-if="moreOpen" class="market-detail-page__more" role="menu" aria-label="更多操作">
        <button type="button" role="menuitem" @click="returnLegacy">返回旧版详情</button>
      </div>

      <p v-if="controller.state.value.loading" class="market-detail-page__loading" role="status">正在加载行情事实…</p>
      <MarketDetailUnavailable
        v-else-if="controller.state.value.error || !header"
        title="行情事实不可用"
        :message="controller.state.value.error || '当前身份没有可用的已完成 Bar。'"
        :can-return-legacy="true"
        @return-legacy="returnLegacy"
      />
      <template v-else>
        <MarketDetailQuoteHeader :header="header" :identity-key="identityKey" />
        <MarketDetailViewNav
          :identity="routeResult.identity"
          :restore="{ htdy: preferences.htdy, free: preferences.free }"
          @select="selectIdentity"
        />
        <section class="market-detail-page__workspace" data-detail-section="workspace-slot">
          <MarketDetailUnavailable
            title="自由看盘工作区尚未接入统一详情页"
            message="当前仅验证共享行情头、视角导航和 Workspace 安全过渡 seam；完整 K 线、指标、Marker 与 Range 属于 Slice B1。"
            :can-return-legacy="true"
            @return-legacy="returnLegacy"
          />
        </section>
      </template>
    </template>
  </main>
</template>

<style scoped>
.market-detail-page {
  position: relative;
  min-height: 100vh;
  padding: 0 clamp(16px, 4vw, 64px) var(--gy-space-6);
  color: var(--gy-text-primary);
  background: var(--gy-detail-page-bg);
}

.market-detail-page__loading {
  margin: var(--gy-space-6) 0;
  color: var(--gy-text-muted);
}

.market-detail-page__workspace {
  padding: var(--gy-space-5) 0;
}

.market-detail-page__more {
  position: absolute;
  z-index: 10;
  top: 52px;
  right: clamp(16px, 4vw, 64px);
  padding: var(--gy-space-1);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
  background: var(--gy-bg-overlay);
  box-shadow: var(--gy-shadow-overlay);
}

.market-detail-page__more button {
  min-height: 44px;
  padding: 0 var(--gy-space-3);
  border: 0;
  border-radius: var(--gy-radius-sm);
  color: var(--gy-text-primary);
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.market-detail-page__more button:hover { background: var(--gy-bg-hover); }
.market-detail-page__more button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }

@media (max-width: 480px) {
  .market-detail-page { padding-inline: var(--gy-space-3); }
  .market-detail-page__more { right: var(--gy-space-3); }
}
</style>
