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
import NewowProductWorkspace from '@/components/market/detail/newow/NewowProductWorkspace.vue'
import '@/styles/newowDetail.css'
import { useNewowDailyQuote } from '@/composables/useNewowDailyQuote'
import { useMarketDetailController } from '@/composables/useMarketDetailController'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import {
  loadMarketDetailPreferences,
  replaceFreeDetailPreferences,
  replaceHtdyDetailPreferences,
  replaceNewowDetailPreferences,
  saveMarketDetailPreferences,
  type FlexibleDetailPreferences,
} from '@/utils/marketDetailPreferences'
import { parseMarketDetailRoute, serializeMarketDetailIdentity } from '@/utils/marketDetailRoute'

const route = useRoute()
const router = useRouter()
const preferences = ref(loadMarketDetailPreferences())
const viewNav = ref<InstanceType<typeof MarketDetailViewNav> | null>(null)
const controller = useMarketDetailController({ routeQuery: () => ({ ...route.query }) })
const routeResult = computed(() => parseMarketDetailRoute({ ...route.query }))
const explicitIdentity = computed(() => routeResult.value.kind === 'valid' ? routeResult.value.identity : null)
const isWorkspacePreview = computed(() => ['newow', 'free', 'htdy', 'trend', 'subing'].includes(explicitIdentity.value?.view ?? 'invalid'))
const isNewowView = computed(() => explicitIdentity.value?.view === 'newow')
const newowHistoricalAsOf = ref<string | null>(null)
const shellReady = computed(() => isWorkspacePreview.value && (
  isNewowView.value || (controller.state.value.header !== null && !controller.state.value.loading)
))
const htdyWorkspace = ref<InstanceType<typeof HtdyDetailWorkspace> | null>(null)
const trendWorkspace = ref<InstanceType<typeof TrendDetailWorkspace> | null>(null)
const subingWorkspace = ref<InstanceType<typeof SubingDetailWorkspace> | null>(null)
const hasHtdyHistory = ref(false)
const hasTrendHistory = ref(false)
const hasSubingHistory = ref(false)
const dailyQuote = useNewowDailyQuote({
  symbol: computed(() => isNewowView.value ? explicitIdentity.value!.symbol : null),
  contract: computed(() => controller.productCatalog.value.find(item => item.product.toLowerCase() === explicitIdentity.value?.symbol)?.actual_contract ?? null),
})
const header = computed(() => {
  const base = controller.state.value.header
  if (!base || !isNewowView.value) return base
  const quote = dailyQuote.quote.value
  return { ...base, ...(quote ?? {}), displayContract: quote ? controller.productCatalog.value.find(item => item.product.toLowerCase() === explicitIdentity.value?.symbol)?.actual_contract ?? null : null, freshness: quote ? 'fresh' as const : 'unavailable' as const }
})
const identityWarning = ref(
  typeof window !== 'undefined' && window.history.state?.contractCleared === true
    ? '已切换品种，指定合约已清除并回到真实主力。'
    : null,
)
const identityKey = computed(() => {
  const identity = explicitIdentity.value
  return identity
    ? [identity.view, identity.symbol, identity.strategy ?? '', identity.seriesKind, identity.contract ?? '', identity.frequency].join(':')
    : 'invalid'
})
let activationGeneration = 0
async function activateRoute() {
  const generation = ++activationGeneration
  newowHistoricalAsOf.value = null
  hasHtdyHistory.value = false
  hasTrendHistory.value = false
  hasSubingHistory.value = false
  const result = routeResult.value
  if (result.kind !== 'valid' || !['newow', 'free', 'htdy', 'trend', 'subing'].includes(result.identity.view)) return
  if (route.query.view === undefined) {
    const failure = await router.replace({ path: '/market/chart', query: serializeMarketDetailIdentity(result.identity) })
    if (failure) return
  }
  if (generation !== activationGeneration || routeResult.value.kind !== 'valid'
    || JSON.stringify(routeResult.value.identity) !== JSON.stringify(result.identity)) return
  await controller.switchIdentity(result.identity)
}

function recover() {
  const recovery = routeResult.value.kind === 'invalid' ? routeResult.value.recovery : null
  if (!recovery) return
  void router.replace({ path: '/market/chart', query: serializeMarketDetailIdentity(recovery) })
}

function selectIdentity(identity: MarketDetailIdentity) {
  if (identity.view === 'newow') {
    preferences.value = replaceNewowDetailPreferences(preferences.value, {
      strategy: identity.strategy,
      frequency: identity.frequency,
    })
  }
  if (identity.view !== 'trend') preferences.value = { ...preferences.value, lastView: identity.view }
  saveMarketDetailPreferences(preferences.value)
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
  if ((identity?.view !== 'free' && identity?.view !== 'newow' && identity?.view !== 'htdy' && identity?.view !== 'subing' && identity?.view !== 'trend') || identity.focusBarEnd !== focusBarEnd) return
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
onBeforeUnmount(() => { activationGeneration += 1; dailyQuote.dispose(); controller.dispose() })
</script>

<template>
  <main class="market-detail-page" :class="{ 'newow-detail-light': isNewowView }" :data-detail-ready="shellReady ? 'true' : 'false'">
    <template v-if="routeResult.kind === 'invalid'">
      <MarketDetailUnavailable
        title="详情页地址无效"
        message="当前地址与统一详情页身份合同不一致，已拒绝静默修正。"
        :can-recover="routeResult.recovery !== null"
        :can-return-market="true"
        @recover="recover"
        @return-market="goBack"
      />
    </template>

    <template v-else-if="routeResult.kind === 'valid'">
      <MarketDetailTopBar
        v-if="!isNewowView"
        :product-name="header?.productName ?? routeResult.identity.symbol.toUpperCase()"
        :symbol="routeResult.identity.symbol"
        :display-contract="header?.displayContract ?? routeResult.identity.contract ?? null"
        :actions="{ canOpenHistory: routeResult.identity.view === 'trend' ? hasTrendHistory : routeResult.identity.view === 'htdy' ? hasHtdyHistory : routeResult.identity.view === 'subing' ? hasSubingHistory : false, canManageAlert: false }"
        @back="goBack"
        @select-symbol="viewNav?.focusSymbol()"
        @open-history="openHistory"
      />
      <p v-if="controller.state.value.loading" class="market-detail-page__loading" role="status">
        {{ routeResult.identity.view === 'newow' ? '正在加载品种元数据…' : '正在加载行情事实…' }}
      </p>
      <MarketDetailUnavailable
        v-else-if="controller.state.value.error || !header"
        :title="routeResult.identity.view === 'newow' ? '品种元数据不可用' : '行情事实不可用'"
        :message="controller.state.value.error || '当前身份没有可用的已完成 Bar。'"
        :can-return-market="true"
        @return-market="goBack"
      />
        <MarketDetailQuoteHeader v-if="!controller.state.value.loading && !controller.state.value.error && header && !(isNewowView && newowHistoricalAsOf)" :header="header" :identity-key="identityKey" :newow="isNewowView" />
        <MarketDetailViewNav
          ref="viewNav"
          :identity="routeResult.identity"
          :products="controller.productCatalog.value"
          :restore="{ newow: preferences.newow, htdy: preferences.htdy, free: preferences.free }"
          @select="selectIdentity"
          @contract-cleared="selectContractCleared"
        />
      <template v-if="routeResult.identity.view === 'newow' || (!controller.state.value.loading && !controller.state.value.error && header)">
        <section class="market-detail-page__workspace" data-detail-section="workspace-slot">
          <NewowProductWorkspace
            v-if="routeResult.identity.view === 'newow'"
            :identity="routeResult.identity"
            @focus-resolved="resolveFocus"
            @snapshot-mode="newowHistoricalAsOf = $event"
            @refresh-current="dailyQuote.refresh"
          />
          <FreeChartWorkspace
            v-else-if="routeResult.identity.view === 'free' && header"
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
            @focus-resolved="resolveFocus"
          />
          <HtdyDetailWorkspace
            v-else-if="routeResult.identity.view === 'htdy' && header"
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
            v-else-if="routeResult.identity.view === 'trend' && header"
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
            v-else-if="routeResult.identity.view === 'subing' && header"
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

@media (max-width: 480px) {
  .market-detail-page { padding-inline: var(--gy-space-3); }
}
</style>
