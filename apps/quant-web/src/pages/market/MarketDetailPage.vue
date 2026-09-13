<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MarketNavigation from '@/components/market/MarketNavigation.vue'
import ProductSelector from '@/components/market/ProductSelector.vue'
import MarketDetailQuoteHeader from '@/components/market/detail/MarketDetailQuoteHeader.vue'
import MarketDetailTopBar from '@/components/market/detail/MarketDetailTopBar.vue'
import MarketDetailUnavailable from '@/components/market/detail/MarketDetailUnavailable.vue'
import MarketDetailViewNav from '@/components/market/detail/MarketDetailViewNav.vue'
import FreeChartWorkspace from '@/components/market/detail/free/FreeChartWorkspace.vue'
import HtdyDetailWorkspace from '@/components/market/detail/htdy/HtdyDetailWorkspace.vue'
import SubingDetailWorkspace from '@/components/market/detail/subing/SubingDetailWorkspace.vue'
import NewowProductWorkspace from '@/components/market/detail/newow/NewowProductWorkspace.vue'
import '@/styles/marketDetailUnified.css'
import { useNewowDailyQuote } from '@/composables/useNewowDailyQuote'
import { useNewowCapabilities } from '@/composables/useNewowCapabilities'
import { useMarketDetailController } from '@/composables/useMarketDetailController'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { ProductOption } from '@/utils/productSearch'
import { normalizeProductOptions } from '@/utils/productSearch'
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
const productSelector = ref<InstanceType<typeof ProductSelector> | null>(null)
const controller = useMarketDetailController({ routeQuery: () => ({ ...route.query }) })
const routeResult = computed(() => parseMarketDetailRoute({ ...route.query }))
const explicitIdentity = computed(() => routeResult.value.kind === 'valid' ? routeResult.value.identity : null)
const isWorkspacePreview = computed(() => ['newow', 'free', 'htdy', 'subing'].includes(explicitIdentity.value?.view ?? 'invalid'))
const isNewowView = computed(() => explicitIdentity.value?.view === 'newow')
const newowHistoricalAsOf = ref<string | null>(null)
const newowCapabilities = useNewowCapabilities()
const newowFrequencyOpen = computed(() => explicitIdentity.value?.view !== 'newow'
  || newowCapabilities.isFrequencyOpen(explicitIdentity.value.frequency as '1w' | '1d' | '60m'))
const shellReady = computed(() => isWorkspacePreview.value && (
  (isNewowView.value && newowCapabilities.state.value !== 'loading') || (controller.state.value.header !== null && !controller.state.value.loading)
))
const htdyWorkspace = ref<InstanceType<typeof HtdyDetailWorkspace> | null>(null)
const newowWorkspace = ref<InstanceType<typeof NewowProductWorkspace> | null>(null)
const subingWorkspace = ref<InstanceType<typeof SubingDetailWorkspace> | null>(null)
const hasHtdyHistory = ref(false)
const hasSubingHistory = ref(false)
const dailyQuote = useNewowDailyQuote({
  symbol: computed(() => isNewowView.value ? explicitIdentity.value!.symbol : null),
  contract: computed(() => controller.productCatalog.value.find(item => item.product.toLowerCase() === explicitIdentity.value?.symbol)?.actual_contract ?? null),
})
const productOptions = computed(() => normalizeProductOptions(controller.productCatalog.value))
const productSelectorStatus = computed(() => productOptions.value.length > 0
  ? 'ready' as const
  : controller.state.value.loading ? 'loading' as const : 'error' as const)
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
const migrationNotice = ref<string | null>(
  route.query.view === 'trend'
    ? '旧趋势详情已迁移到牛哇趋势策略（1d）；当前页面使用新的牛哇策略身份与公式版本。'
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
  hasSubingHistory.value = false
  const result = routeResult.value
  if (result.kind !== 'valid' || !['newow', 'free', 'htdy', 'subing'].includes(result.identity.view)) return
  if (route.query.view === undefined || route.query.view === 'trend') {
    if (route.query.view === 'trend') {
      migrationNotice.value = '旧趋势详情已迁移到牛哇趋势策略（1d）；当前页面使用新的牛哇策略身份与公式版本。'
    }
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

function switchNewowToOpenFrequency() {
  const identity = explicitIdentity.value
  const frequency = newowCapabilities.openFrequencies.value[0]
  if (identity?.view !== 'newow' || !frequency) return
  selectIdentity({ ...identity, frequency, focusBarEnd: undefined })
}

function selectIdentity(identity: MarketDetailIdentity) {
  migrationNotice.value = null
  if (identity.view === 'newow') {
    preferences.value = replaceNewowDetailPreferences(preferences.value, {
      strategy: identity.strategy,
      frequency: identity.frequency,
    })
  }
  preferences.value = { ...preferences.value, lastView: identity.view === 'trend' ? 'newow' : identity.view }
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

function selectProduct(option: ProductOption) {
  const identity = explicitIdentity.value
  if (!identity || option.symbol === identity.symbol) return
  if (identity.seriesKind === 'contract') {
    selectContractCleared({
      view: identity.view,
      symbol: option.symbol,
      seriesKind: 'actual_dominant',
      frequency: identity.frequency,
      ...(identity.view === 'newow' ? { strategy: identity.strategy } : {}),
    })
    return
  }
  selectIdentity({ ...identity, symbol: option.symbol, focusBarEnd: undefined })
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
  if ((identity?.view !== 'free' && identity?.view !== 'newow' && identity?.view !== 'htdy' && identity?.view !== 'subing') || identity.focusBarEnd !== focusBarEnd) return
  const { focusBarEnd: _focus, ...next } = identity
  void router.replace({ path: '/market/chart', query: serializeMarketDetailIdentity(next) })
}

function openHistory() {
  const view = explicitIdentity.value?.view
  if (view === 'newow') newowWorkspace.value?.openHistory()
  else if (view === 'htdy') htdyWorkspace.value?.openHistory()
  else if (view === 'subing') subingWorkspace.value?.openHistory()
}

function goBack() {
  void router.push('/market')
}

function goHome(tab: 'market' | 'messages') {
  if (typeof window !== 'undefined') {
    try { sessionStorage.setItem('guiyi.market-home.tab.v1', tab) } catch {}
  }
  void router.push('/market')
}

watch(identityKey, () => { void activateRoute() }, { immediate: true })
watch(isNewowView, (enabled) => { if (enabled) void newowCapabilities.load() }, { immediate: true })
onBeforeUnmount(() => { activationGeneration += 1; dailyQuote.dispose(); controller.dispose() })
</script>

<template>
  <main class="market-detail-page unified-detail-light" :data-detail-ready="shellReady ? 'true' : 'false'">
    <MarketNavigation @market="goHome('market')" @messages="goHome('messages')">
      <template #search>
        <ProductSelector
          ref="productSelector"
          :options="productOptions"
          :selected-symbol="explicitIdentity?.symbol ?? null"
          :status="productSelectorStatus"
          label="搜索60品种"
          @select="selectProduct"
        />
      </template>
    </MarketNavigation>
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
        :product-name="header?.productName ?? routeResult.identity.symbol.toUpperCase()"
        :symbol="routeResult.identity.symbol"
        :display-contract="header?.displayContract ?? routeResult.identity.contract ?? null"
        :history-label="routeResult.identity.view === 'htdy' || routeResult.identity.view === 'subing' ? '预警记录' : '参考记录'"
        :actions="{ canOpenHistory: ['htdy', 'subing'].includes(routeResult.identity.view) || (routeResult.identity.view === 'newow' && newowFrequencyOpen && newowCapabilities.state.value === 'ready' && newowCapabilities.isSectionOpen('reference')), canManageAlert: false }"
        @back="goBack"
        @select-symbol="productSelector?.focus()"
        @open-history="openHistory"
      />
      <MarketDetailQuoteHeader v-if="!controller.state.value.error && header && !(isNewowView && newowHistoricalAsOf)" :header="header" :identity-key="identityKey" :unified="isWorkspacePreview" :newow="isNewowView" />
      <MarketDetailViewNav
        :identity="routeResult.identity"
        :products="controller.productCatalog.value"
        :newow-frequencies="newowCapabilities.openFrequencies.value"
        :restore="{ newow: preferences.newow, htdy: preferences.htdy, free: preferences.free }"
        @select="selectIdentity"
        @contract-cleared="selectContractCleared"
      />
        <p v-if="migrationNotice" class="market-detail-page__notice" data-testid="market-detail-migration-notice" role="status">{{ migrationNotice }}</p>
        <section
          class="market-detail-page__workspace"
          data-detail-section="workspace-slot"
          :data-active-view="routeResult.identity.view"
          :aria-busy="controller.state.value.loading"
        >
          <p v-if="controller.state.value.loading && routeResult.identity.view !== 'newow'" class="market-detail-page__loading" role="status">正在加载当前图表…</p>
          <MarketDetailUnavailable
            v-else-if="routeResult.identity.view !== 'newow' && (controller.state.value.error || !header)"
            title="行情事实不可用"
            :message="controller.state.value.error || '当前身份没有可用的已完成 Bar。'"
            :can-return-market="true"
            @return-market="goBack"
          />
          <NewowProductWorkspace
            v-if="routeResult.identity.view === 'newow' && newowCapabilities.capabilities.value && newowFrequencyOpen"
            ref="newowWorkspace"
            :identity="routeResult.identity"
            :capabilities="newowCapabilities.capabilities.value"
            @focus-resolved="resolveFocus"
            @snapshot-mode="newowHistoricalAsOf = $event"
            @refresh-current="dailyQuote.refresh"
          />
          <MarketDetailUnavailable
            v-else-if="routeResult.identity.view === 'newow'"
            :title="newowCapabilities.state.value === 'loading' || newowCapabilities.state.value === 'not_requested' ? '正在读取牛哇开放能力' : newowCapabilities.state.value === 'unavailable' ? '牛哇开放能力不可用' : '当前牛哇周期未开放'"
            :message="newowCapabilities.state.value === 'unavailable' ? (newowCapabilities.error.value ?? '无法确认开放范围。') : newowFrequencyOpen ? '正在确认当前发布阶段。' : `${routeResult.identity.frequency} 尚未开放（${newowCapabilities.deferredFrequencyReason(routeResult.identity.frequency as '1w' | '1d' | '60m') ?? 'NEWOW_FREQUENCY_NOT_OPEN'}）。`"
            recovery-label="切换到已开放周线"
            :can-recover="newowCapabilities.state.value === 'ready' && !newowFrequencyOpen && newowCapabilities.openFrequencies.value.length > 0"
            :can-return-market="true"
            @recover="switchNewowToOpenFrequency"
            @return-market="goBack"
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
  min-height: 320px;
  margin: 0;
  display: grid;
  place-items: center;
  color: var(--gy-text-muted);
  background: var(--gy-bg-panel);
}

.market-detail-page__workspace {
  min-height: 420px;
  padding: var(--gy-space-2) 0 var(--gy-space-5);
}

.market-detail-page__notice {
  margin: var(--gy-space-2) 0 0;
  padding: 8px 12px;
  border: 1px solid #F5C89A;
  color: #9A4D12;
  background: #FFF8F0;
  font-size: var(--gy-font-size-sm);
}

.market-detail-page > :deep(.market-navigation) {
  margin-inline: calc(-1 * clamp(16px, 4vw, 64px));
}

@media (max-width: 480px) {
  .market-detail-page { padding-inline: var(--gy-space-3); }
  .market-detail-page > :deep(.market-navigation) { margin-inline: calc(-1 * var(--gy-space-3)); }
}
</style>
