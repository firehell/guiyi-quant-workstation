<script setup lang="ts">
import { saveMarketHomeTab, type MarketHomeTab } from '@/utils/marketHomeTab'
import DetailPricePreview from '@/components/market/detail/DetailPricePreview.vue'
import { useMarketDetailQuote, projectMarketDetailQuoteHeader } from '@/composables/useMarketDetailQuote'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { candidatePreview } from '@/utils/candidatePreview'
import { computed, onBeforeUnmount, onUnmounted, provide, ref, watch } from 'vue'
import { createChart } from 'lightweight-charts'
import { createDetailChartSession, DETAIL_CHART_SESSION } from '@/utils/detailChartSession'
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
import FuturesWorkspace from '@/components/market/detail/futures/FuturesWorkspace.vue'
import { NEWOW_FREQUENCIES } from '@/types/marketDetail'
import { originalNewowCombinationSupported } from '@/utils/newowFutures'
import NewowProductWorkspace from '@/components/market/detail/newow/NewowProductWorkspace.vue'
import NewowAiAnalysisDialog from '@/components/market/detail/newow/NewowAiAnalysisDialog.vue'
import type { AiCombo } from '@/api/newowAiAnalysis'
import '@/styles/marketDetailUnified.css'
import { useNewowProduct } from '@/composables/useNewowProduct'
import { projectNewowDetail } from '@/utils/newowDetailPresentation'
import { useNewowCapabilities } from '@/composables/useNewowCapabilities'
import { useMarketDetailController } from '@/composables/useMarketDetailController'
import { buildMarketDetailHeaderModel } from '@/utils/marketDetailViewModel'
import type { MarketDetailIdentity } from '@/types/marketDetail'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
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
import { isNewowStrategySwitch, parseMarketDetailRoute, serializeMarketDetailIdentity } from '@/utils/marketDetailRoute'

const route = useRoute()
const router = useRouter()
const seriesPreferenceMigrated = ref(false)
const preferences = ref(loadMarketDetailPreferences(undefined, () => { seriesPreferenceMigrated.value = true }))
if (seriesPreferenceMigrated.value) saveMarketDetailPreferences(preferences.value)
const workspaceVisible = ref(true)
const productSelector = ref<InstanceType<typeof ProductSelector> | null>(null)
const controller = useMarketDetailController({ routeQuery: () => ({ ...route.query }) })
const routeResult = computed(() => parseMarketDetailRoute({ ...route.query }))
const explicitIdentity = computed(() => routeResult.value.kind === 'valid' ? routeResult.value.identity : null)
const chartSession = createDetailChartSession({ createChart })
provide(DETAIL_CHART_SESSION, chartSession)
watch(() => {
  const identity = explicitIdentity.value
  return identity ? [identity.symbol, identity.seriesKind, identity.contract ?? '', identity.frequency].join(':') : 'invalid'
}, key => chartSession.setIdentity(key), { immediate: true, flush: 'sync' })
const isWorkspacePreview = computed(() => ['newow', 'free', 'htdy', 'subing'].includes(explicitIdentity.value?.view ?? 'invalid'))
const isNewowView = computed(() => explicitIdentity.value?.view === 'newow')
const isFuturesMode = computed(() => isNewowView.value && explicitIdentity.value?.strategyModel === 'futures_bidir_v1')
const isOriginalNewow = computed(() => isNewowView.value && !isFuturesMode.value)
// Other views reuse the existing Newow trend chart price authority at this exact period.
const toolbarPriceIdentity = computed<MarketDetailIdentity | null>(() => {
  const identity = explicitIdentity.value
  return identity && ['htdy', 'subing', 'free'].includes(identity.view)
    && identity.seriesKind === 'actual_dominant' && identity.frequency !== '1m'
    ? { view: 'newow', symbol: identity.symbol, seriesKind: 'actual_dominant', frequency: identity.frequency, strategy: 'trend' } : null
})
const toolbarPrices = useNewowProduct({ identity: toolbarPriceIdentity })
const toolbarPriceSummary = computed(() => projectNewowDetail(
  toolbarPrices.sections.chart.data.value as NewowProductSectionResponse<'chart'> | null,
  toolbarPrices.sections.chart.state.value, null, 'not_requested', false,
  null, 'not_requested', false, toolbarPrices.currentChartWindow.value, toolbarPrices.historicalChartWindow.value,
))
const toolbarPriceStatus = computed(() => toolbarPrices.sections.chart.state.value === 'loading' ? '读取中' : '不可用')
onBeforeUnmount(toolbarPrices.dispose)

const detailPricePreview = {
  bars: computed(() => controller.bars.value), cached: ref(false), loading: computed(() => controller.state.value.loading),
  error: computed(() => controller.state.value.error), refresh: () => { if (explicitIdentity.value) void controller.switchIdentity(explicitIdentity.value) },
  cutoff: computed(() => controller.bars.value.at(-1)?.time ?? null),
}
const newowHistoricalAsOf = ref<string | null>(null)
const detailQuote = useMarketDetailQuote({ identity: explicitIdentity,
  enabled: computed(() => !candidatePreview.enabled), snapshotBefore: computed(() => newowHistoricalAsOf.value) })
const aiOpen = ref(false)
const aiAsOf = ref<string | null>(null)
function adoptAiRecommendation(combo: AiCombo) {
  const identity = explicitIdentity.value
  if (!identity || identity.view !== 'newow' || !newowOpenFrequencies.value.includes(combo.frequency)) return
  aiOpen.value = false
  selectIdentity({ view: 'newow', symbol: identity.symbol, strategy: combo.strategy,
    frequency: combo.frequency, seriesKind: 'actual_dominant' })
}
const newowDailyAsOf = ref<string | null>(null)
const newowDailyPending = ref(false)
const newowDailyChart = ref<NewowProductSectionResponse<'chart'> | null>(null)
const newowWeeklyQuoteContext = ref<{ asOf: string | null; physicalContract: string | null }>({ asOf: null, physicalContract: null })
const newowCapabilities = useNewowCapabilities()
const newowOpenFrequencies = computed(() => isFuturesMode.value ? [...NEWOW_FREQUENCIES] : newowCapabilities.openFrequenciesFor(explicitIdentity.value?.symbol ?? ''))
const newowFrequencyOpen = computed(() => explicitIdentity.value?.view !== 'newow' || isFuturesMode.value
  || (explicitIdentity.value.seriesKind === 'actual_dominant' && explicitIdentity.value.frequency !== '1m'
    && originalNewowCombinationSupported(explicitIdentity.value) && newowCapabilities.isFrequencyOpen(explicitIdentity.value.frequency as '1w' | '1d' | '5m' | '15m' | '30m' | '60m', explicitIdentity.value.symbol)))
const shellReady = computed(() => isWorkspacePreview.value && (
  (isFuturesMode.value || (isOriginalNewow.value && newowCapabilities.state.value !== 'loading')) || (controller.state.value.header !== null && !controller.state.value.loading)
))
const htdyWorkspace = ref<InstanceType<typeof HtdyDetailWorkspace> | null>(null)
const futuresWorkspace = ref<InstanceType<typeof FuturesWorkspace> | null>(null)
const newowWorkspace = ref<InstanceType<typeof NewowProductWorkspace> | null>(null)
const subingWorkspace = ref<InstanceType<typeof SubingDetailWorkspace> | null>(null)
const hasHtdyHistory = ref(false)
const hasSubingHistory = ref(false)
const productOptions = computed(() => normalizeProductOptions(controller.productCatalog.value))
const productSelectorStatus = computed(() => productOptions.value.length > 0
  ? 'ready' as const
  : controller.state.value.loading ? 'loading' as const : 'error' as const)
const quoteSourceNote = computed(() => {
  const quote = detailQuote.quote.value
  return quote ? `${quote.source === 'completed_1m' ? '分钟报价' : '日线报价'} ${formatBeijingInstant(quote.asOf)}${quote.daily ? ` · 日行情 ${quote.daily.tradingDay}` : ' · 日行情待确认'}` : '详情报价不可用'
})
const header = computed(() => {
  const identity = explicitIdentity.value
  const product = controller.productCatalog.value.find(item => item.product === identity?.symbol)
  const base = controller.state.value.header ?? (identity && product ? buildMarketDetailHeaderModel({ identity,
    dominant: null, product, bars: [], research: null, marketState: null, overlaySource: 'none', canonicalCoverage: null,
    hasMoreBefore: false, stale: true }) : null)
  return base ? projectMarketDetailQuoteHeader(base, detailQuote.quote.value) : null
})
const identityWarning = ref(
  typeof window !== 'undefined' && window.history.state?.contractCleared === true
    ? '已切换品种，指定合约已清除并回到真实主力。'
    : null,
)
const migrationNotice = ref<string | null>(
  seriesPreferenceMigrated.value || route.query.series_kind === 'continuous'
    ? '已切换为真实主力序列'
    : route.query.view === 'trend'
    ? '旧趋势详情已迁移到牛哇趋势策略（1d）；当前页面使用新的牛哇策略身份与公式版本。'
    : null,
)
const identityKey = computed(() => {
  const identity = explicitIdentity.value
  return identity
    ? [identity.view, identity.symbol, identity.strategy ?? '', identity.newowMode ?? '', identity.strategyModel ?? '', identity.newowTest ?? '', identity.seriesKind, identity.contract ?? '', identity.frequency].join(':')
    : 'invalid'
})
let activationGeneration = 0
let activatedIdentity: MarketDetailIdentity | null = null
async function activateRoute() {
  const generation = ++activationGeneration
  const result = routeResult.value
  const strategyOnly = result.kind === 'valid' && isNewowStrategySwitch(activatedIdentity, result.identity)
    && (newowHistoricalAsOf.value === null || activatedIdentity?.strategy === result.identity.strategy)
  activatedIdentity = result.kind === 'valid' ? result.identity : null
  if (!strategyOnly) {
    newowHistoricalAsOf.value = null
    newowDailyAsOf.value = null
    newowDailyPending.value = false
    newowDailyChart.value = null
    newowWeeklyQuoteContext.value = { asOf: null, physicalContract: null }
  }
  hasHtdyHistory.value = false
  hasSubingHistory.value = false
  if (result.kind !== 'valid' || !['newow', 'free', 'htdy', 'subing'].includes(result.identity.view)) return
  if (route.query.series_kind === 'continuous' || route.query.view === undefined || route.query.view === 'trend') {
    if (route.query.series_kind === 'continuous') migrationNotice.value = '已切换为真实主力序列'
    if (route.query.view === 'trend' && route.query.series_kind !== 'continuous') {
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
  const frequency = newowOpenFrequencies.value[0]
  if (identity?.view !== 'newow' || !frequency) return
  selectIdentity({ ...identity, frequency, focusBarEnd: undefined })
}

function selectIdentity(identity: MarketDetailIdentity) {
  migrationNotice.value = null
  if (identity.view === 'newow') {
    preferences.value = replaceNewowDetailPreferences(preferences.value, {
      strategy: identity.strategy,
      frequency: identity.frequency,
      strategyModel: identity.strategyModel, newowTest: identity.newowTest, newowMode: identity.newowMode,
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
  if (isFuturesMode.value) futuresWorkspace.value?.openHistory()
  else if (view === 'newow') newowWorkspace.value?.openHistory()
  else if (view === 'htdy') htdyWorkspace.value?.openHistory()
  else if (view === 'subing') subingWorkspace.value?.openHistory()
}

function goBack() {
  void router.push('/market')
}

function goHome(tab: MarketHomeTab) {
  if (typeof window !== 'undefined') {
    saveMarketHomeTab(tab)
  }
  void router.push('/market')
}

// Dual mode is a presentation change and retains the same chart input snapshot.
watch(() => {
  const i = explicitIdentity.value
  return i ? [i.view, i.symbol, i.strategy, i.strategyModel, i.newowTest, i.seriesKind, i.contract, i.frequency].join(':') : 'invalid'
}, () => { aiAsOf.value = null }, { flush: 'sync' })
watch([identityKey, () => route.query.series_kind === 'continuous'], () => { aiOpen.value = false; void activateRoute() }, { immediate: true })
watch(isOriginalNewow, (enabled) => { if (enabled) void newowCapabilities.load() }, { immediate: true })
onBeforeUnmount(() => { activationGeneration += 1; detailQuote.dispose(); controller.dispose() })
onUnmounted(() => chartSession.dispose())
</script>

<template>
  <main class="market-detail-page unified-detail-light" :data-detail-ready="shellReady ? 'true' : 'false'">
    <MarketNavigation @market="goHome('market')" @messages="goHome('messages')" @simnow="goHome('simnow')">
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
        static-identity
        :display-date="header?.tradingDay"
        hide-back
        :product-name="header?.productName ?? routeResult.identity.symbol.toUpperCase()"
        :symbol="routeResult.identity.symbol"
        :display-contract="header?.displayContract ?? routeResult.identity.contract ?? null"
        :history-label="routeResult.identity.view === 'htdy' || (routeResult.identity.view === 'subing' && routeResult.identity.frequency === '15m') ? '预警记录' : '参考记录'"
        :actions="{ canOpenHistory: routeResult.identity.view === 'htdy' || (routeResult.identity.view === 'subing' && routeResult.identity.frequency === '15m') || isFuturesMode || (routeResult.identity.view === 'newow' && newowFrequencyOpen && newowCapabilities.state.value === 'ready' && newowCapabilities.isSectionOpen('reference')), canManageAlert: false }"
        @back="goBack"
        @select-symbol="productSelector?.focus()"
        @open-history="openHistory"
      />
      <MarketDetailQuoteHeader v-if="header" :header="header" :source-note="quoteSourceNote" :identity-key="identityKey" :unified="isWorkspacePreview" :newow="true" :hide-extended-facts="['htdy', 'subing', 'free'].includes(routeResult.identity.view)" />
      <MarketDetailViewNav
        :identity="routeResult.identity"
        :products="controller.productCatalog.value"
        :newow-frequencies="newowOpenFrequencies"
        :target-price="toolbarPriceSummary.target?.display_value ?? null"
        :absorb-price="toolbarPriceSummary.absorb?.display_value ?? null"
        :reference-price-status="toolbarPriceStatus"
        :frequency-controls-target="controller.state.value.header && !controller.state.value.loading && !controller.state.value.error && workspaceVisible && ['htdy', 'subing', 'free'].includes(routeResult.identity.view) && !(routeResult.identity.view === 'subing' && (routeResult.identity.frequency === '1m' || routeResult.identity.seriesKind !== 'actual_dominant')) ? '#detail-chart-reference-toolbar' : undefined"
        :newow-frequency-in-workspace="!isFuturesMode && workspaceVisible && routeResult.identity.view === 'newow' && !!newowCapabilities.capabilities.value && newowFrequencyOpen"
        :restore="{ newow: preferences.newow, htdy: preferences.htdy, free: preferences.free }"
        @select="selectIdentity"
        @contract-cleared="selectContractCleared"
        @ai-analysis="aiOpen = true"
      >
      </MarketDetailViewNav>
      <NewowAiAnalysisDialog v-if="isOriginalNewow" :open="aiOpen" :product="routeResult.identity.symbol" :as-of="aiAsOf" :identity-key="identityKey" @close="aiOpen = false" @adopt="adoptAiRecommendation" />
        <p v-if="migrationNotice" class="market-detail-page__notice" data-testid="market-detail-migration-notice" role="status">{{ migrationNotice }}</p>
        <section
          class="market-detail-page__workspace"
          v-if="workspaceVisible"
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
          <template v-if="(routeResult.identity.view === 'subing' && (routeResult.identity.frequency === '1m' || routeResult.identity.seriesKind !== 'actual_dominant')) || (isFuturesMode && (routeResult.identity.seriesKind !== 'actual_dominant' || routeResult.identity.frequency === '1m'))">
            <p role="status">{{ routeResult.identity.view === 'subing' ? '苏冰预警' : '期货双向研究' }}不支持当前周期或指定合约，行情与当前周期已保留。</p>
            <DetailPricePreview :identity="routeResult.identity" :preview="detailPricePreview" />
          </template>
          <FuturesWorkspace v-else-if="isFuturesMode" ref="futuresWorkspace" :identity="routeResult.identity" :price-preview="detailPricePreview"/>
          <template v-else>
          <NewowProductWorkspace
            v-if="routeResult.identity.view === 'newow' && newowCapabilities.capabilities.value && newowFrequencyOpen"
            ref="newowWorkspace"
            :identity="routeResult.identity"
            :capabilities="newowCapabilities.capabilities.value"
            :price-preview="detailPricePreview"
            strategy-menu-target="#newow-strategy-test-anchor"
            channel-controls-target="#newow-channel-controls"
            @focus-resolved="resolveFocus"
            @snapshot-mode="newowHistoricalAsOf = $event"
            @daily-snapshot-as-of="newowDailyAsOf = $event"
            @daily-snapshot-pending="newowDailyPending = $event"
            @daily-chart="newowDailyChart = $event"
            @weekly-quote-context="newowWeeklyQuoteContext = $event"
            @analysis-as-of="aiAsOf = $event"
            @select-identity="selectIdentity"
          >
            <template #chart-frequency>
              <div class="newow-chart-frequency" role="group" aria-label="图表周期">
                <button v-for="frequency in newowOpenFrequencies" :key="frequency" type="button"
                  :class="{ 'is-active': routeResult.identity.frequency === frequency }"
                  :aria-pressed="routeResult.identity.frequency === frequency"
                  @click="selectIdentity({ ...routeResult.identity, frequency, focusBarEnd: undefined })"
                >{{ frequency === '1d' ? '日线' : frequency === '1w' ? '周线' : frequency.replace('m', '分钟') }}</button>
              </div>
            </template>
          </NewowProductWorkspace>
          <template v-else-if="routeResult.identity.view === 'newow'">
          <DetailPricePreview :identity="routeResult.identity" :preview="detailPricePreview" />
          <MarketDetailUnavailable
            :title="newowCapabilities.state.value === 'loading' || newowCapabilities.state.value === 'not_requested' ? '正在读取牛哇开放能力' : newowCapabilities.state.value === 'unavailable' ? '牛哇开放能力不可用' : '当前牛哇周期未开放'"
            :message="newowCapabilities.state.value === 'loading' || newowCapabilities.state.value === 'not_requested' ? '正在确认当前发布阶段及周期能力。' : newowCapabilities.state.value === 'unavailable' ? (newowCapabilities.error.value ?? '无法确认开放范围。') : newowFrequencyOpen ? '正在确认当前发布阶段。' : `${routeResult.identity.frequency} 尚未开放（${newowCapabilities.deferredFrequencyReason(routeResult.identity.frequency as '1w' | '1d' | '5m' | '15m' | '30m' | '60m') ?? 'NEWOW_FREQUENCY_NOT_OPEN'}）。`"
            :recovery-label="newowCapabilities.state.value === 'unavailable' ? '重试能力配置' : '切换到已开放日线'"
            :can-recover="newowCapabilities.state.value === 'unavailable' || (newowCapabilities.state.value === 'ready' && !newowFrequencyOpen && newowOpenFrequencies.length > 0)"
            :can-return-market="true"
            @recover="newowCapabilities.state.value === 'unavailable' ? newowCapabilities.load(true) : switchNewowToOpenFrequency()"
            @return-market="goBack"
          />
          </template>
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
            :loading-before="controller.loadingBefore.value"
            :history-error="controller.historyError.value"
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
            :loading-before="controller.loadingBefore.value"
            :history-error="controller.historyError.value"
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
            :loading-before="controller.loadingBefore.value"
            :history-error="controller.historyError.value"
            :load-earlier="controller.loadMoreBefore"
            :identity-warning="identityWarning"
            @history-availability="hasSubingHistory = $event"
            @focus-resolved="resolveFocus"
          />
          </template>
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
