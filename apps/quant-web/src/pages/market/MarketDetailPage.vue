<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MarketDetailQuoteHeader from '@/components/market/detail/MarketDetailQuoteHeader.vue'
import MarketDetailTopBar from '@/components/market/detail/MarketDetailTopBar.vue'
import MarketDetailUnavailable from '@/components/market/detail/MarketDetailUnavailable.vue'
import MarketDetailViewNav from '@/components/market/detail/MarketDetailViewNav.vue'
import TrendDetailWorkspace from '@/components/market/detail/TrendDetailWorkspace.vue'
import FreeChartWorkspace from '@/components/market/detail/free/FreeChartWorkspace.vue'
import HtdyDetailWorkspace from '@/components/market/detail/htdy/HtdyDetailWorkspace.vue'
import SubingDetailWorkspace from '@/components/market/detail/subing/SubingDetailWorkspace.vue'
import { useMarketDetailController } from '@/composables/useMarketDetailController'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import {
  loadMarketDetailPreferences,
  replaceFreeDetailPreferences,
  replaceHtdyDetailPreferences,
  saveMarketDetailPreferences,
  type FlexibleDetailPreferences,
} from '@/utils/marketDetailPreferences'
import { parseMarketDetailRoute, serializeMarketDetailIdentity } from '@/utils/marketDetailRoute'

const route = useRoute()
const router = useRouter()
const preferences = ref(loadMarketDetailPreferences())
const moreOpen = ref(false)
const controller = useMarketDetailController({ routeQuery: () => ({ ...route.query }) })
const routeResult = computed(() => parseMarketDetailRoute({ ...route.query }))
const explicitIdentity = computed(() => routeResult.value.kind === 'valid' ? routeResult.value.identity : null)
const isWorkspacePreview = computed(() => ['free', 'htdy', 'trend', 'subing'].includes(explicitIdentity.value?.view ?? 'invalid'))
const shellReady = computed(() => isWorkspacePreview.value && controller.state.value.header !== null && !controller.state.value.loading)
const htdyWorkspace = ref<InstanceType<typeof HtdyDetailWorkspace> | null>(null)
const trendWorkspace = ref<InstanceType<typeof TrendDetailWorkspace> | null>(null)
const subingWorkspace = ref<InstanceType<typeof SubingDetailWorkspace> | null>(null)
const hasHtdyHistory = ref(false)
const hasTrendHistory = ref(false)
const hasSubingHistory = ref(false)
const header = computed(() => controller.state.value.header)
const identityWarning = ref(
  typeof window !== 'undefined' && window.history.state?.contractCleared === true
    ? '已切换品种，指定合约已清除并回到真实主力。'
    : null,
)
const identityKey = computed(() => {
  const identity = explicitIdentity.value
  return identity
    ? [identity.view, identity.symbol, identity.seriesKind, identity.contract ?? '', identity.frequency].join(':')
    : 'invalid'
})
async function activateRoute() {
  moreOpen.value = false
  hasHtdyHistory.value = false
  hasTrendHistory.value = false
  hasSubingHistory.value = false
  const result = routeResult.value
  if (result.kind !== 'valid' || !['free', 'htdy', 'trend', 'subing'].includes(result.identity.view)) return
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

function selectContractCleared(identity: MarketDetailIdentity) {
  identityWarning.value = '已切换品种，指定合约已清除并回到真实主力。'
  void router.push({
    path: '/market/chart',
    query: serializeMarketDetailIdentity(identity),
    state: { contractCleared: true },
  })
}

function updateFreePreferences(free: FlexibleDetailPreferences) {
  preferences.value = replaceFreeDetailPreferences(preferences.value, free)
  saveMarketDetailPreferences(preferences.value)
}

function updateHtdyPreferences(htdy: FlexibleDetailPreferences) {
  preferences.value = replaceHtdyDetailPreferences(preferences.value, htdy)
  saveMarketDetailPreferences(preferences.value)
}

function resolveFocus(focusBarEnd: string) {
  const identity = explicitIdentity.value
  if ((identity?.view !== 'htdy' && identity?.view !== 'subing' && identity?.view !== 'trend') || identity.focusBarEnd !== focusBarEnd) return
  const { focusBarEnd: _focus, ...next } = identity
  void router.replace({ path: '/market/chart', query: serializeMarketDetailIdentity(next) })
}

function openHistory() {
  const view = explicitIdentity.value?.view
  if (view === 'trend') trendWorkspace.value?.openHistory()
  else if (view === 'htdy') htdyWorkspace.value?.openHistory()
  else if (view === 'subing') subingWorkspace.value?.openHistory()
}

function goBack() {
  void router.push('/market')
}

watch(identityKey, () => { void activateRoute() }, { immediate: true })
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

    <template v-else-if="routeResult.kind === 'valid'">
      <MarketDetailTopBar
        :product-name="header?.productName ?? routeResult.identity.symbol.toUpperCase()"
        :symbol="routeResult.identity.symbol"
        :display-contract="header?.displayContract ?? routeResult.identity.contract ?? null"
        :actions="{ canOpenHistory: routeResult.identity.view === 'trend' ? hasTrendHistory : routeResult.identity.view === 'htdy' ? hasHtdyHistory : routeResult.identity.view === 'subing' ? hasSubingHistory : false, canManageAlert: false }"
        @back="goBack"
        @select-symbol="returnLegacy"
        @open-more="moreOpen = !moreOpen"
        @open-history="openHistory"
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
          @contract-cleared="selectContractCleared"
        />
        <section class="market-detail-page__workspace" data-detail-section="workspace-slot">
          <FreeChartWorkspace
            v-if="routeResult.identity.view === 'free'"
            :identity="routeResult.identity"
            :header="header"
            :bars="controller.bars.value"
            :mutation="controller.mutation.value"
            :loading="controller.state.value.loading"
            :error="controller.state.value.error"
            :research="controller.research.value"
            :research-error="controller.researchError.value"
            :preferences="preferences.free"
            :has-more-before="controller.hasMoreBefore.value"
            :load-earlier="controller.loadMoreBefore"
            :identity-warning="identityWarning"
            @update-preferences="updateFreePreferences"
          />
          <HtdyDetailWorkspace
            v-else-if="routeResult.identity.view === 'htdy'"
            ref="htdyWorkspace"
            :identity="routeResult.identity"
            :header="header"
            :bars="controller.bars.value"
            :mutation="controller.mutation.value"
            :loading="controller.state.value.loading"
            :error="controller.state.value.error"
            :preferences="preferences.htdy"
            :has-more-before="controller.hasMoreBefore.value"
            :load-earlier="controller.loadMoreBefore"
            :identity-warning="identityWarning"
            @update-preferences="updateHtdyPreferences"
            @history-availability="hasHtdyHistory = $event"
            @focus-resolved="resolveFocus"
          />
          <TrendDetailWorkspace
            v-else-if="routeResult.identity.view === 'trend'"
            ref="trendWorkspace"
            :identity="routeResult.identity"
            :header="header"
            :bars="controller.bars.value"
            :research="controller.research.value"
            @history-availability="hasTrendHistory = $event"
            :mutation="controller.mutation.value"
            :loading="controller.state.value.loading"
            :has-more-before="controller.hasMoreBefore.value"
            :load-earlier="controller.loadMoreBefore"
            @focus-resolved="resolveFocus"
          />
          <SubingDetailWorkspace
            v-else-if="routeResult.identity.view === 'subing'"
            ref="subingWorkspace"
            :identity="routeResult.identity"
            :focus-bar-end="routeResult.identity.focusBarEnd"
            :header="header"
            :bars="controller.bars.value"
            :mutation="controller.mutation.value"
            :loading="controller.state.value.loading"
            :error="controller.state.value.error"
            :has-more-before="controller.hasMoreBefore.value"
            :load-earlier="controller.loadMoreBefore"
            :identity-warning="identityWarning"
            @history-availability="hasSubingHistory = $event"
            @focus-resolved="resolveFocus"
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
