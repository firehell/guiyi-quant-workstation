<script setup lang="ts">
import ContractStrip from '@/components/workstation/ContractStrip.vue'
import MarketChartDesk from '@/components/workstation/MarketChartDesk.vue'
import { useWorkstationAccounts } from '@/composables/useWorkstationAccounts'
import { tqChartExecutions, subingChartExecutions, locateChartExecutions } from '@/utils/workstationChartActivity'
import { rememberWorkstationChart, rememberWorkstationNewowMode } from '@/utils/workstationRoutes'
import { paneOptions, selectPrimaryPane, type PaneId } from '@/utils/workstationChartPanes'
import { MAX_AUXILIARY_PANES } from '@guiyi/quant-chart'
import WorkstationChartSettings from '@/components/market/detail/newow/WorkstationChartSettings.vue'
import { useWorkstationChartPanes } from '@/composables/useWorkstationChartPanes'
import MarketKlineStage from '@/components/market/detail/MarketKlineStage.vue'
import DetailPricePreview from '@/components/market/detail/DetailPricePreview.vue'
import { useMarketDetailQuote, projectMarketDetailQuoteHeader } from '@/composables/useMarketDetailQuote'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { candidatePreview } from '@/utils/candidatePreview'
import { isGenericChartProfile, MARKET_CHART_STUDY_CONTEXT } from '@/utils/marketChartStudies'
import { computed, onBeforeUnmount, onUnmounted, provide, ref, watch } from 'vue'
import { createChart } from 'lightweight-charts'
import { createDetailChartSession, detailChartTime, DETAIL_CHART_SESSION } from '@/utils/detailChartSession'
import { useRoute, useRouter } from 'vue-router'

import MarketNavigation from '@/components/market/MarketNavigation.vue'
import ProductSelector from '@/components/market/ProductSelector.vue'
import MarketDetailQuoteHeader from '@/components/market/detail/MarketDetailQuoteHeader.vue'
import MarketChartProgress from '@/components/market/detail/MarketChartProgress.vue'
import MarketDetailTopBar from '@/components/market/detail/MarketDetailTopBar.vue'
import MarketDetailUnavailable from '@/components/market/detail/MarketDetailUnavailable.vue'
import DetailChartToolbar from '@/components/market/detail/DetailChartToolbar.vue'
import MarketDetailViewNav from '@/components/market/detail/MarketDetailViewNav.vue'
import FreeChartWorkspace from '@/components/market/detail/free/FreeChartWorkspace.vue'
import HtdyDetailWorkspace from '@/components/market/detail/htdy/HtdyDetailWorkspace.vue'
import SubingDetailWorkspace from '@/components/market/detail/subing/SubingDetailWorkspace.vue'
import { getMarketAfterClosePresentation } from '@/api/referenceTrading'
import { projectMarketReferenceChart } from '@/utils/newowMarketReference'
import type { MarketAfterClosePresentation, MarketAfterCloseReference } from '@/types/referenceTrading'
import NewowMarketReferencePanel from '@/components/market/detail/newow/NewowMarketReferencePanel.vue'
import NewowProductWorkspace from '@/components/market/detail/newow/NewowProductWorkspace.vue'
import NewowAiAnalysisDialog from '@/components/market/detail/newow/NewowAiAnalysisDialog.vue'
import type { AiCombo } from '@/api/newowAiAnalysis'
import '@/styles/marketDetailUnified.css'
import { useNewowProduct } from '@/composables/useNewowProduct'
import { projectNewowDetail } from '@/utils/newowDetailPresentation'
import { useNewowCapabilities } from '@/composables/useNewowCapabilities'
import { useMarketDetailController } from '@/composables/useMarketDetailController'
import { buildMarketDetailHeaderModel } from '@/utils/marketDetailViewModel'
import { NEWOW_FREQUENCIES, type MarketDetailIdentity } from '@/types/marketDetail'
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
  type FreeDetailPreferences,
} from '@/utils/marketDetailPreferences'
import { isNewowStrategySwitch, originalNewowCombinationSupported, parseMarketDetailRoute, serializeMarketDetailIdentity } from '@/utils/marketDetailRoute'

const route = useRoute()
const router = useRouter()
const seriesPreferenceMigrated = ref(false)
const preferences = ref(loadMarketDetailPreferences(undefined, () => { seriesPreferenceMigrated.value = true }))
if (seriesPreferenceMigrated.value) saveMarketDetailPreferences(preferences.value)
const workspaceVisible = ref(true)
const contractsOpen = ref(false)
const productSelector = ref<InstanceType<typeof ProductSelector> | null>(null)
const controller = useMarketDetailController({ routeQuery: () => ({ ...route.query }) })
const routeResult = computed(() => parseMarketDetailRoute({ ...route.query }))
const explicitIdentity = computed(() => routeResult.value.kind === 'valid' ? routeResult.value.identity : null)
const chartStudyContext = computed(() => {
  const identity = explicitIdentity.value
  if (identity?.view === 'newow' && newowAfterMarketOnly.value) {
    return {
      identity: { ...identity, profile: 'newow' as const }, talibMacd: false, toggleMacd() {},
      active: controller.studyActivity, allowCompleted: controller.studyCompletedAvailable,
      revision: controller.studyRevision, revisionPending: controller.studyRevisionPending, allowTail: false,
    }
  }
  if (!identity || !isGenericChartProfile(identity.view)) return null
  const profile = identity.view
  const talibMacd = preferences.value.talibMacd?.includes(profile) === true
  return {
    identity: { ...identity, profile },
    talibMacd,
    toggleMacd() {
      const current = preferences.value.talibMacd ?? []
      preferences.value = {
        ...preferences.value,
        talibMacd: talibMacd ? current.filter(value => value !== profile) : [...current, profile],
      }
      saveMarketDetailPreferences(preferences.value)
    },
    active: controller.studyActivity,
    allowCompleted: controller.studyCompletedAvailable,
    revision: controller.studyRevision,
    revisionPending: controller.studyRevisionPending,
    allowTail: !identity.focusBarEnd,
  }
})
provide(MARKET_CHART_STUDY_CONTEXT, chartStudyContext)
const marketFoundation = import.meta.env?.VITE_GUIYI_MARKET_FOUNDATION === '1'
const newowAfterMarketOnly = computed(() => marketFoundation || explicitIdentity.value?.newowSource === 'after-market')
const { rows: accountActivity, recentTqRecords, tq, subing, tqAccount, subingAccount } = useWorkstationAccounts()
const verifiedAccountSources = computed(() => ({
  htdy: tq.status.value === 'ready' && tqAccount.value.verified,
  subing: subing.status.value === 'ready' && subingAccount.value.verified,
}))
const showExecutions = ref(typeof window !== 'undefined' && window.history.state?.showWorkstationExecutions === true)
const executions = computed(() => {
  const identity = explicitIdentity.value
  if (!identity || !showExecutions.value) return []
  const bars = controller.bars.value
  const contracts = new Set(bars.map(bar => bar.physicalContract?.toUpperCase()))
  const tq = recentTqRecords.status.value === 'ready' && recentTqRecords.value.value?.coverage !== 'unavailable'
    ? tqChartExecutions(recentTqRecords.value.value?.items ?? [], '快期模拟主账户') : []
  const paper = subing.status.value === 'ready' ? subingChartExecutions(subing.value.value, identity.symbol) : []
  return [...tq, ...paper].filter(record => contracts.has(record.contract.toUpperCase())
    && (!identity.contract || record.contract.toUpperCase() === identity.contract))
})
const positionedExecutions = computed(() => {
  const identity = explicitIdentity.value
  return identity ? locateChartExecutions(executions.value, controller.bars.value, identity.frequency) : []
})
const activeOrderRows = computed(() => {
  const identity = explicitIdentity.value
  if (!identity || !showExecutions.value) return []
  const contract = identity.contract ?? controller.bars.value.at(-1)?.physicalContract?.toUpperCase()
  return accountActivity.value.filter(row => row.contract === contract && row.actions.length)
})
watch(explicitIdentity, identity => { if (identity) rememberWorkstationChart(identity) }, { immediate: true })
const chartSession = createDetailChartSession({ createChart })
provide(DETAIL_CHART_SESSION, chartSession)
const marketAxisKey = computed(() => {
  const identity = explicitIdentity.value
  return identity ? [identity.symbol, identity.seriesKind, identity.contract ?? '', identity.frequency].join(':') : 'invalid'
})
watch(marketAxisKey, key => chartSession.setIdentity(key), { immediate: true, flush: 'sync' })
watch([positionedExecutions, showExecutions], ([points, enabled]) => {
  const frequency = enabled ? explicitIdentity.value?.frequency ?? null : null
  chartSession.setExecutions(frequency ? points.map(point => ({
    id: point.id, at: point.time, physicalContract: point.contract.toUpperCase(),
    from: detailChartTime(point.before, frequency), to: detailChartTime(point.after, frequency),
    ratio: point.ratio, price: Number(point.price), source: point.source,
  })) : [], frequency)
}, { immediate: true })

const isWorkspacePreview = computed(() => ['newow', 'free', 'htdy', 'subing'].includes(explicitIdentity.value?.view ?? 'invalid'))
const isNewowView = computed(() => explicitIdentity.value?.view === 'newow')
const toolbarPriceIdentity = computed<MarketDetailIdentity | null>(() => {
  const identity = explicitIdentity.value
  return !newowAfterMarketOnly.value && identity && ['htdy', 'subing', 'free'].includes(identity.view)
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
const newowOpenFrequencies = computed(() => newowAfterMarketOnly.value
  ? NEWOW_FREQUENCIES : newowCapabilities.openFrequenciesFor(explicitIdentity.value?.symbol ?? ''))
const savedReference = ref<{ source: MarketAfterCloseReference; snapshot: string } | null>(null)
const savedPresentation = ref<(MarketAfterClosePresentation & { sourceRevision: string }) | null>(null)
const savedChartStatus = ref<'waiting' | 'loading' | 'ready' | 'unavailable'>('waiting')
const savedVisibleFrom = ref<string | null>(null)
const savedStrategy = computed(() => explicitIdentity.value?.newowMode === 'dual' ? 'dual_fusion' : explicitIdentity.value?.strategy ?? 'trend')
const savedChartSpan = computed(() => {
  const source = savedReference.value?.source
  if (!source || !newowAfterMarketOnly.value || explicitIdentity.value?.view !== 'newow') return ''
  const cutoff = Date.parse(source.cutoff)
  const bars = controller.bars.value.filter(bar => bar.sourceBarSha256 && bar.trading_day
    && source.since <= bar.trading_day && bar.trading_day <= source.through && Date.parse(bar.time) <= cutoff)
  if (!bars.length) return ''
  const anchor = savedVisibleFrom.value ? bars.findIndex(bar => Date.parse(bar.time) >= Date.parse(savedVisibleFrom.value!)) : -1
  const start = anchor < 0 ? Math.max(0, bars.length - 1200) : Math.max(0, Math.floor((anchor - 180) / 400) * 400)
  const first = bars[start]!
  const last = bars[Math.min(start + 1199, bars.length - 1)]!
  return JSON.stringify({ since: first.trading_day, through: last.trading_day, from: first.time, to: last.time })
})
watch([savedReference, savedChartSpan], async ([selection, span], _, onCleanup) => {
  savedPresentation.value = null
  savedChartStatus.value = 'waiting'
  if (!selection || !span) return
  const signal = new AbortController()
  onCleanup(() => signal.abort())
  savedChartStatus.value = 'loading'
  try {
    const presentation = await getMarketAfterClosePresentation(selection.source, selection.snapshot, JSON.parse(span), { signal: signal.signal })
    if (signal.signal.aborted) return
    savedPresentation.value = { ...presentation, sourceRevision: selection.source.revision_id }
    savedChartStatus.value = presentation.main_status === 'saved' ? 'ready' : 'unavailable'
  } catch {
    if (!signal.signal.aborted) savedChartStatus.value = 'unavailable'
  }
})
watch(() => {
  const id = explicitIdentity.value
  return id ? [id.view, id.symbol, id.frequency, id.contract, savedStrategy.value].join(':') : ''
}, () => {
  savedVisibleFrom.value = null
  savedReference.value = null
  savedPresentation.value = null
}, { flush: 'sync' })
const savedChart = computed(() => projectMarketReferenceChart(
  savedPresentation.value?.frames ?? [], controller.bars.value,
  explicitIdentity.value?.symbol ?? '', savedStrategy.value, explicitIdentity.value?.frequency ?? '',
  savedPresentation.value?.sourceRevision ?? null,
))
const singleChartVisible = ref(true)
const workstationChartScope = computed(() => {
  const identity = explicitIdentity.value
  return singleChartVisible.value && newowAfterMarketOnly.value && identity?.view === 'newow'
    ? { product: identity.symbol, strategy: savedStrategy.value, frequency: identity.frequency } : null
})
const { layers: workstationLayers, panes: workstationPanes } = useWorkstationChartPanes(
  () => workstationChartScope.value, () => savedReference.value?.source ?? null,
  controller.bars, () => savedChart.value.matched,
)
const savedLatest = computed(() => savedChart.value.matched.at(-1))
const newowFrequencyOpen = computed(() => explicitIdentity.value?.view !== 'newow'
  || ((newowAfterMarketOnly.value || explicitIdentity.value.seriesKind === 'actual_dominant') && explicitIdentity.value.frequency !== '1m'
    && (newowAfterMarketOnly.value || originalNewowCombinationSupported(explicitIdentity.value) && newowCapabilities.isFrequencyOpen(explicitIdentity.value.frequency as '1w' | '1d' | '5m' | '15m' | '30m' | '60m', explicitIdentity.value.symbol))))
const shellReady = computed(() => isWorkspacePreview.value && (
  (isNewowView.value && (newowAfterMarketOnly.value || newowCapabilities.state.value !== 'loading')) || (controller.state.value.header !== null && !controller.state.value.loading)
))
const htdyWorkspace = ref<InstanceType<typeof HtdyDetailWorkspace> | null>(null)
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

    : null,
)
const identityKey = computed(() => {
  const identity = explicitIdentity.value
  return identity
    ? [identity.view, identity.symbol, identity.strategy ?? '', identity.newowMode ?? '', identity.newowTest ?? '', identity.newowSource ?? '', identity.seriesKind, identity.contract ?? '', identity.frequency].join(':')
    : 'invalid'
})
watch(identityKey, chartSession.restoreInspectionCursor, { flush: 'post' })
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
  if (route.query.series_kind === 'continuous' || route.query.view === undefined) {
    if (route.query.series_kind === 'continuous') migrationNotice.value = '已切换为真实主力序列'
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
    if (identity.newowSource === 'after-market') rememberWorkstationNewowMode(identity)
    preferences.value = replaceNewowDetailPreferences(preferences.value, {
      strategy: identity.strategy,
      frequency: identity.frequency,
      newowTest: identity.newowTest, newowMode: identity.newowMode,
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

function addComparison(pane: PaneId) {
  const layers = workstationLayers.value
  if (layers.panes.length >= MAX_AUXILIARY_PANES || layers.panes.some(p => p.id === pane)) return
  workstationLayers.value = { ...layers, panes: [...layers.panes, { id: pane, height: 144 }] }
}

function updateFreePreferences(free: FreeDetailPreferences) {
  preferences.value = replaceFreeDetailPreferences(preferences.value, free)
  saveMarketDetailPreferences(preferences.value)
}

function updateHtdyPreferences(htdy: FlexibleDetailPreferences) {
  preferences.value = replaceHtdyDetailPreferences(preferences.value, htdy)
  saveMarketDetailPreferences(preferences.value)
}

const emaChoices = ['ema_10', 'ema_21', 'ema_60'] as const
const flexibleView = computed(() => {
  const view = explicitIdentity.value?.view
  return view === 'free' || view === 'htdy' ? view : null
})
function toggleDeskEma(id: typeof emaChoices[number]) {
  const view = flexibleView.value
  if (!view) return
  const current = preferences.value[view]
  const ids = current.optionalEmaIndicators
  const next = { ...current, optionalEmaIndicators: ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id] }
  if (view === 'free') updateFreePreferences(next)
  else updateHtdyPreferences(next)
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

function selectPhysicalContract(item: { product: string; contract: string }) {
  const identity = explicitIdentity.value
  if (!identity) return
  selectIdentity({ ...identity, symbol: item.product, contract: item.contract, seriesKind: 'contract',
    focusBarEnd: undefined, homeContext: undefined })
}

// Dual mode is a presentation change and retains the same chart input snapshot.
watch(() => {
  const i = explicitIdentity.value
  return i ? [i.view, i.symbol, i.strategy, i.newowTest, i.seriesKind, i.contract, i.frequency].join(':') : 'invalid'
}, () => { aiAsOf.value = null }, { flush: 'sync' })
watch([identityKey, () => route.query.series_kind === 'continuous'], () => { aiOpen.value = false; void activateRoute() }, { immediate: true })
watch([isNewowView, newowAfterMarketOnly], ([enabled, afterMarket]) => { if (enabled && !afterMarket) void newowCapabilities.load() }, { immediate: true })
onBeforeUnmount(() => { activationGeneration += 1; detailQuote.dispose(); controller.dispose() })
onUnmounted(() => chartSession.dispose())
</script>

<template>
  <main class="market-detail-page workstation-market" :data-detail-ready="shellReady ? 'true' : 'false'">
    <MarketNavigation active-tab="market" mast>
      <template #search>
        <ProductSelector
          ref="productSelector"
          :options="productOptions"
          :selected-symbol="explicitIdentity?.symbol ?? null"
          :status="productSelectorStatus"
          :label="marketFoundation ? '搜索品种' : '搜索60品种'"
          @select="selectProduct"
        />
      </template>
      <template v-if="routeResult.kind === 'valid'" #actions>
        <button type="button" class="ws-button ws-contract-toggle" :aria-expanded="contractsOpen" aria-controls="ws-physical-contracts" @click="contractsOpen = !contractsOpen">合约列表</button>
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
      <ContractStrip v-if="contractsOpen" id="ws-physical-contracts" :active-contract="routeResult.identity.contract ?? header?.displayContract" :active-product="routeResult.identity.symbol"
        :activity="accountActivity" :verified-sources="verifiedAccountSources" @select="selectPhysicalContract" />
      <div class="ws-quote-band">
      <MarketDetailTopBar
        static-identity
        :display-date="header?.tradingDay"
        hide-back
        :product-name="header?.productName ?? routeResult.identity.symbol.toUpperCase()"
        :symbol="routeResult.identity.symbol"
        :display-contract="header?.displayContract ?? routeResult.identity.contract ?? null"
        :history-label="routeResult.identity.view === 'htdy' || (routeResult.identity.view === 'subing' && routeResult.identity.frequency === '15m') ? '预警记录' : '参考记录'"
        :actions="{ canOpenHistory: routeResult.identity.view === 'htdy' || (routeResult.identity.view === 'subing' && routeResult.identity.frequency === '15m') || (!newowAfterMarketOnly && routeResult.identity.view === 'newow' && newowFrequencyOpen && newowCapabilities.state.value === 'ready' && newowCapabilities.isSectionOpen('reference')), canManageAlert: false }"
        @back="goBack"
        @select-symbol="productSelector?.focus()"
        @open-history="openHistory"
      />
      <MarketDetailQuoteHeader v-if="header" :header="header" :source-note="quoteSourceNote" :identity-key="identityKey" :unified="isWorkspacePreview" :newow="true" :hide-extended-facts="['htdy', 'subing', 'free'].includes(routeResult.identity.view)" />
      </div>
      <MarketDetailViewNav
        :identity="routeResult.identity"
        :products="controller.productCatalog.value"
        :newow-frequencies="newowOpenFrequencies"
        :after-market="newowAfterMarketOnly"
        :market-foundation="marketFoundation"
        :show-reference-prices="!newowAfterMarketOnly"
        :target-price="toolbarPriceSummary.target?.display_value ?? null"
        :absorb-price="toolbarPriceSummary.absorb?.display_value ?? null"
        :reference-price-status="toolbarPriceStatus"
        :frequency-in-workspace="workspaceVisible && ((!newowAfterMarketOnly && routeResult.identity.view === 'newow' && !!newowCapabilities.capabilities.value && newowFrequencyOpen) || (!!header && (['htdy', 'free'].includes(routeResult.identity.view) || (routeResult.identity.view === 'subing' && routeResult.identity.frequency !== '1m' && routeResult.identity.seriesKind === 'actual_dominant'))))"
        :restore="{ newow: preferences.newow, htdy: preferences.htdy, free: preferences.free }"
        @select="selectIdentity"
        @contract-cleared="selectContractCleared"
        @ai-analysis="aiOpen = true"
      >
        <template #display-controls>
          <label class="execution-toggle"><input v-model="showExecutions" type="checkbox"> 委托/成交</label>
          <div v-if="isWorkspacePreview" class="chart-navigation" role="group" aria-label="图表视窗">
            <button type="button" :disabled="!controller.bars.value.length" @click="chartSession.zoom('out')">缩小</button>
            <button type="button" :disabled="!controller.bars.value.length" @click="chartSession.zoom('in')">放大</button>
            <button type="button" :disabled="!controller.bars.value.length" @click="chartSession.scrollToLatest()">回到最新</button>
          </div>
        </template>
      </MarketDetailViewNav>
      <NewowAiAnalysisDialog v-if="isNewowView && !newowAfterMarketOnly" :open="aiOpen" :product="routeResult.identity.symbol" :as-of="aiAsOf" :identity-key="identityKey" @close="aiOpen = false" @adopt="adoptAiRecommendation" />
        <p v-if="migrationNotice" class="market-detail-page__notice" data-testid="market-detail-migration-notice" role="status">{{ migrationNotice }}</p>
        <MarketChartDesk :identity="routeResult.identity" :session="chartSession" :products="productOptions" :status="productSelectorStatus"
          :preferences="{ chart: preferences, workstation: workstationLayers }"
          :bars="controller.studyActivity.value?.bar ? [...controller.bars.value, controller.studyActivity.value.bar] : controller.bars.value"
          @single="singleChartVisible = $event" @select="selectProduct" @period="selectIdentity({ ...routeResult.identity, frequency: $event, focusBarEnd: undefined })">
          <template #settings>
            <WorkstationChartSettings v-if="routeResult.identity.view === 'newow' && newowAfterMarketOnly" v-model="workstationLayers" :strategy="savedStrategy" />
            <fieldset v-else-if="chartStudyContext" class="desk-generic-studies">
              <legend>Quant Core · 显示设置</legend>
              <template v-if="flexibleView">
                <label v-for="id in emaChoices" :key="id"><input type="checkbox" :checked="preferences[flexibleView].optionalEmaIndicators.includes(id)" @change="toggleDeskEma(id)"/>主图 {{ id.replace('_', '').toUpperCase() }}</label>
              </template>
              <label v-if="flexibleView === 'free'"><input type="checkbox" :checked="preferences.free.showBoll" @change="updateFreePreferences({ ...preferences.free, showBoll: preferences.free.showBoll ? undefined : true })"/>主图 BOLL (20, 2)</label>
              <label><input type="checkbox" :checked="chartStudyContext.talibMacd" @change="chartStudyContext.toggleMacd()"/>副图 MACD (12, 26, 9)</label>
            </fieldset>
          </template>
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
          <template v-if="(routeResult.identity.view === 'subing' && (routeResult.identity.frequency === '1m' || routeResult.identity.seriesKind !== 'actual_dominant'))">
            <p role="status">苏冰预警不支持当前周期或指定合约，行情与当前周期已保留。</p>
            <DetailPricePreview :identity="routeResult.identity" :preview="detailPricePreview" :axis-key="marketAxisKey"
              :mutation="controller.mutation.value" :has-more-before="controller.hasMoreBefore.value"
              :loading-before="controller.loadingBefore.value" :history-error="controller.historyError.value"
              @load-earlier="controller.loadMoreBefore" @focus-resolved="resolveFocus" />
          </template>
          <template v-else>
          <template v-if="routeResult.identity.view === 'newow' && newowAfterMarketOnly">
            <MarketKlineStage :workstation-panes="workstationPanes" :workstation-styles="workstationLayers.strokes" :log-price="workstationLayers.logPrice"
              :identity-key="marketAxisKey" :bars="controller.bars.value" :mutation="controller.mutation.value"
              :loading="controller.state.value.loading" :error="controller.state.value.error"
              :period="routeResult.identity.frequency" :series-kind="routeResult.identity.seriesKind"
              :visible-main-indicators="workstationLayers.overlays" range-detector-source-identity="" :range-detector-anchor-time="null"
              :volume-scoring="false" :show-derived-markers="false" :marker-selection-enabled="false"
              :research-markers="savedChart.markers"
              :saved-reference-lines="savedChart.lines"
              @visible-from-change="savedVisibleFrom = $event"
              :focus-bar-end="routeResult.identity.focusBarEnd"
              :has-more-before="controller.hasMoreBefore.value" :loading-before="controller.loadingBefore.value"
              :history-error="controller.historyError.value"
              @load-earlier="controller.loadMoreBefore" @focus-resolved="resolveFocus"
            />
            <div class="workstation-quick-pane" role="group" aria-label="切换首个副图">
              <button v-for="option in paneOptions.filter(item => item.id !== 'macd')" :key="option.id"
                type="button" :aria-pressed="workstationLayers.panes[0]?.id === option.id"
                @click="workstationLayers = selectPrimaryPane(workstationLayers, option.id)">{{ option.label }}</button>
              <label><select aria-label="添加副图对照" value="" :disabled="workstationLayers.panes.length >= MAX_AUXILIARY_PANES"
                @change="addComparison(($event.target as HTMLSelectElement).value as PaneId); ($event.target as HTMLSelectElement).value = ''">
                <option value="" disabled>{{ workstationLayers.panes.length >= MAX_AUXILIARY_PANES ? '已有三个副图' : '＋ 对照' }}</option>
                <option v-for="option in paneOptions.filter(item => !workstationLayers.panes.some(p => p.id === item.id))" :key="option.id" :value="option.id">{{ option.label }}</option>
              </select></label>
            </div>
            <p v-if="routeResult.identity.newowTest" role="status">此历史策略入口不属于盘后系列。</p>
            <p v-else-if="!newowFrequencyOpen" role="status">当前周期没有牛哇盘后结果，保留行情底图。</p>
            <div v-if="newowFrequencyOpen" class="market-detail-page__reference-note">
              <p role="status" :data-saved-newow-chart-status="savedChartStatus">
                <template v-if="savedChartStatus === 'loading'">正在读取已保存的牛哇主图事实。</template>
                <template v-else-if="savedChart.matched.length">已绑定 {{ savedChart.matched.length }} 根权威行情与 {{ savedChart.markers.length }} 个盘后参考动作。</template>
                <template v-else>当前图表范围没有与权威行情版本匹配的盘后主图事实。</template>
              </p>
              <details v-if="savedLatest">
                <summary>盘后主图事实与版本</summary>
                <p>{{ formatBeijingInstant(savedLatest.bar_end) }} · {{ savedLatest.physical_contract }} · {{ savedLatest.main_state }}</p>
                <p>{{ savedLatest.formula_versions.join(' · ') }} · {{ savedLatest.availability?.status ?? '状态未保存' }}</p>
                <p v-if="savedLatest.hints.length">提示 {{ savedLatest.hints.map(item => item.kind).join('、') }}</p>
              </details>
              <p>跨周期综合解释暂未开放。盘后视图只读取已保存结果。</p>
            </div>
            <NewowMarketReferencePanel v-if="newowFrequencyOpen && !routeResult.identity.newowTest"
              :product="routeResult.identity.symbol" :frequency="routeResult.identity.frequency"
              :strategy="savedStrategy" @selected="savedReference = $event" />
          </template>
          <NewowProductWorkspace
            v-else-if="routeResult.identity.view === 'newow' && newowCapabilities.capabilities.value && newowFrequencyOpen"
            ref="newowWorkspace"
            :identity="routeResult.identity"
            :capabilities="newowCapabilities.capabilities.value"
            :price-preview="detailPricePreview"
            strategy-menu-target="#newow-strategy-test-anchor"
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
          <DetailPricePreview :identity="routeResult.identity" :preview="detailPricePreview" :axis-key="marketAxisKey"
              :mutation="controller.mutation.value" :has-more-before="controller.hasMoreBefore.value"
              :loading-before="controller.loadingBefore.value" :history-error="controller.historyError.value"
              @load-earlier="controller.loadMoreBefore" @focus-resolved="resolveFocus" />
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
            :canonical-end="controller.canonicalCoverage.value?.end ?? null"
            :identity="routeResult.identity"
            :header="header"
            :bars="controller.bars.value"
            :active-bar="routeResult.identity.focusBarEnd ? null : controller.activeBar.value"
            :quote="routeResult.identity.focusBarEnd ? null : controller.quote.value"
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
          >
            <template #chart-toolbar>
              <DetailChartToolbar :show-reference-prices="toolbarPriceSummary.target?.display_value != null || toolbarPriceSummary.absorb?.display_value != null" :identity="routeResult.identity" :target-price="toolbarPriceSummary.target?.display_value ?? null"
                :absorb-price="toolbarPriceSummary.absorb?.display_value ?? null" :status="toolbarPriceStatus"
                @select="selectIdentity({ ...routeResult.identity, frequency: $event, focusBarEnd: undefined })" />
            </template>
          </FreeChartWorkspace>
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
          >
            <template #chart-toolbar>
              <DetailChartToolbar :identity="routeResult.identity" :target-price="toolbarPriceSummary.target?.display_value ?? null"
                :absorb-price="toolbarPriceSummary.absorb?.display_value ?? null" :status="toolbarPriceStatus"
                @select="selectIdentity({ ...routeResult.identity, frequency: $event, focusBarEnd: undefined })" />
            </template>
          </HtdyDetailWorkspace>
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
          >
            <template #chart-toolbar>
              <DetailChartToolbar :identity="routeResult.identity" :target-price="toolbarPriceSummary.target?.display_value ?? null"
                :absorb-price="toolbarPriceSummary.absorb?.display_value ?? null" :status="toolbarPriceStatus"
                @select="selectIdentity({ ...routeResult.identity, frequency: $event, focusBarEnd: undefined })" />
            </template>
          </SubingDetailWorkspace>
          </template>
          <MarketChartProgress v-if="!candidatePreview.enabled" :key="identityKey"
            :identity="routeResult.identity" :historical="!!newowHistoricalAsOf" />
        </section>
        </MarketChartDesk>
      <section v-if="showExecutions" class="execution-details" aria-label="只读委托与成交">
        <h2>只读委托与成交</h2>
        <p>□ 快期原生委托　■ 快期原生成交　● 苏冰模型成交。图点按原始时间与价格定位，坐标缺乏依据时保留记录。</p>
        <p v-if="recentTqRecords.status.value === 'error' || subing.status.value === 'error'" role="status">部分账户记录读取失败。</p>
        <p>快期活动委托覆盖未核验。苏冰待处理动作按模型原始状态列示。</p>
        <ul>
          <li v-for="row in activeOrderRows" :key="row.source + row.contract">
            {{ row.account }} · {{ row.contract }}
            <div v-for="(action, index) in row.actions" :key="index">{{ action.label }} · {{ formatBeijingInstant(action.at) }}</div>
          </li>
          <li v-for="record in executions" :key="record.source + record.id">
            {{ record.source }} · {{ record.account }} · {{ record.contract }} · <time>{{ record.time }}</time> · {{ record.price }}
          </li>
        </ul>
      </section>
    </template>
  </main>
</template>

<style scoped>
.execution-toggle { padding-inline: 8px; white-space: nowrap; }
.execution-details { padding: 12px; border-top: 1px solid var(--gy-border); }
.execution-details h2 { margin: 0; font-size: 16px; }
.execution-details p, .execution-details li { margin-block: 8px; font-size: 13px; }


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

.chart-navigation { display: flex; gap: 4px; }
.chart-navigation button { padding: 4px 8px; border: 1px solid var(--gy-border); border-radius: 4px; background: var(--gy-bg-panel); color: inherit; font: inherit; white-space: nowrap; }
.chart-navigation button:not(:disabled) { cursor: pointer; }

.market-detail-page > :deep(.market-navigation) {
  margin-inline: calc(-1 * clamp(16px, 4vw, 64px));
}

@media (max-width: 480px) {
  .market-detail-page { padding-inline: var(--gy-space-3); }
  .market-detail-page > :deep(.market-navigation) { margin-inline: calc(-1 * var(--gy-space-3)); }
}
</style>

<style scoped>
.workstation-quick-pane { display: flex; flex-wrap: wrap; gap: 5px; padding: 5px 8px; }
.workstation-quick-pane select { background: var(--gy-bg-panel); color: var(--gy-text-primary); border: 1px solid var(--gy-border); border-radius: 4px; padding: 3px 7px; cursor: pointer; }
.workstation-quick-pane button { cursor: pointer; color: inherit; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: 4px; padding: 3px 9px; }
.workstation-quick-pane button[aria-pressed=true] { border-color: var(--gy-color-primary, #5782cc); }
</style>
