<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import MarketDetailDisclosure from '@/components/market/detail/MarketDetailDisclosure.vue'
import MarketDetailFactStrip from '@/components/market/detail/MarketDetailFactStrip.vue'
import FreeChartStage from '@/components/market/detail/free/FreeChartStage.vue'
import {
  RANGE_DETECTOR_WARMUP_INSUFFICIENT,
  RANGE_DETECTOR_WARMUP_LOAD_FAILED,
  useRangeDetectorOverlayWarmup,
} from '@/composables/useRangeDetectorOverlayWarmup'
import type { BarData, MarketFrequency, OptionalEmaIndicatorId, ProductResearchResponse } from '@/types/market'
import type { MarketSeriesMutation } from '@/composables/useMarketSeries'
import type { DetailViewModel, MarketDetailHeaderModel, MarketDetailIdentity } from '@/types/marketDetail'
import { MARKET_FREQUENCIES } from '@/types/market'
import { saveMarketDetailPreferences, type FlexibleDetailPreferences } from '@/utils/marketDetailPreferences'
import { buildFreeDetailViewModel } from '@/utils/freeDetailViewModel'

const props = defineProps<{
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  bars: BarData[]
  mutation: MarketSeriesMutation
  loading: boolean
  error: string | null
  research: ProductResearchResponse | null
  researchError: boolean
  preferences: FlexibleDetailPreferences
  htdyPreferences: FlexibleDetailPreferences
  hasMoreBefore: boolean
  identityWarning?: string | null
}>()
const emit = defineEmits<{ selectIdentity: [identity: MarketDetailIdentity], loadEarlier: [] }>()

const optionalEmaIndicators = ref<OptionalEmaIndicatorId[]>([...props.preferences.optionalEmaIndicators])
const showRangeDetector = ref(props.preferences.showRangeDetector)
const contract = ref(props.identity.contract ?? '')
const symbol = ref(props.identity.symbol)
const identityWarning = ref<string | null>(null)
const openDisclosureIds = ref<string[]>([])
const sourceIdentity = computed(() => [props.identity.seriesKind, props.identity.symbol, props.identity.contract ?? '', props.identity.frequency].join(':'))
const bars = computed(() => props.bars)
const hasMoreBefore = computed(() => props.hasMoreBefore)
const rangeWarmup = useRangeDetectorOverlayWarmup({
  bars,
  hasMoreBefore,
  enabled: showRangeDetector,
  identityKey: sourceIdentity,
  loadMoreBefore: () => new Promise<void>((resolve) => { emit('loadEarlier'); resolve() }),
})
const rangeState = computed<'disabled' | 'loading' | 'ready' | 'insufficient'>(() => {
  if (!showRangeDetector.value) return 'disabled'
  if (rangeWarmup.loading.value) return 'loading'
  return rangeWarmup.unavailableReason.value === null && rangeWarmup.anchorTime.value ? 'ready' : 'insufficient'
})
const model = computed<DetailViewModel>(() => buildFreeDetailViewModel({
  identity: props.identity,
  header: props.header,
  research: props.research,
  researchError: props.researchError,
  rangeState: rangeState.value,
}))
const indicators = computed(() => [
  ...optionalEmaIndicators.value,
  ...(showRangeDetector.value ? ['range_detector' as const] : []),
])
const rangeWarning = computed(() => rangeWarmup.unavailableReason.value === RANGE_DETECTOR_WARMUP_LOAD_FAILED
  ? '箱体历史预载失败'
  : rangeWarmup.unavailableReason.value === RANGE_DETECTOR_WARMUP_INSUFFICIENT ? '箱体历史预载不足' : null)
const identityHint = computed(() => props.identityWarning ?? identityWarning.value ?? (
  props.identity.seriesKind === 'actual_dominant'
    ? '切换品种时，指定合约会清除并回到真实主力。'
    : null
))

watch([optionalEmaIndicators, showRangeDetector], () => {
  saveMarketDetailPreferences({
    version: 1, lastView: 'free', htdy: props.htdyPreferences,
    free: { seriesKind: props.identity.seriesKind === 'continuous' ? 'continuous' : 'actual_dominant', frequency: props.identity.frequency, optionalEmaIndicators: optionalEmaIndicators.value, showRangeDetector: showRangeDetector.value },
  })
  if (!showRangeDetector.value) rangeWarmup.reset()
}, { deep: true })

watch(() => props.identity, () => {
  contract.value = props.identity.contract ?? ''
  symbol.value = props.identity.symbol
}, { deep: true })

function switchIdentity(next: Partial<Pick<MarketDetailIdentity, 'symbol' | 'seriesKind' | 'frequency' | 'contract'>>) {
  const nextSymbol = (next.symbol ?? symbol.value).trim().toLowerCase()
  if (!/^[a-z]+$/.test(nextSymbol)) return
  const seriesKind = next.seriesKind ?? props.identity.seriesKind
  const selectedContract = (next.contract ?? contract.value).trim().toUpperCase()
  const symbolChanged = nextSymbol !== props.identity.symbol
  if (symbolChanged && seriesKind === 'contract') {
    identityWarning.value = '已切换品种，指定合约已清除并回到真实主力。'
    contract.value = ''
    emit('selectIdentity', { view: 'free', symbol: nextSymbol, seriesKind: 'actual_dominant', frequency: next.frequency ?? props.identity.frequency })
    return
  }
  identityWarning.value = null
  if (seriesKind === 'contract' && !selectedContract) return
  emit('selectIdentity', {
    view: 'free', symbol: nextSymbol, seriesKind,
    frequency: next.frequency ?? props.identity.frequency,
    ...(seriesKind === 'contract' ? { contract: selectedContract } : {}),
  })
}

function toggleEma(value: OptionalEmaIndicatorId) {
  optionalEmaIndicators.value = optionalEmaIndicators.value.includes(value)
    ? optionalEmaIndicators.value.filter((item) => item !== value)
    : [...optionalEmaIndicators.value, value]
}

function updateSymbol() { switchIdentity({ symbol: symbol.value }) }

function toggleDisclosure(id: string) {
  openDisclosureIds.value = openDisclosureIds.value.includes(id)
    ? openDisclosureIds.value.filter((item) => item !== id)
    : [...openDisclosureIds.value, id]
}
</script>

<template>
  <section class="free-workspace" data-detail-workspace="free">
    <div class="free-workspace__controls" aria-label="自由看盘控制">
      <div class="free-workspace__control-group" aria-label="序列">
        <input v-model="symbol" aria-label="品种代码" @change="updateSymbol">
        <button v-for="item in [['actual_dominant', '真实主力'], ['continuous', '主连']] as const" :key="item[0]" type="button" :aria-pressed="identity.seriesKind === item[0]" @click="switchIdentity({ seriesKind: item[0] })">{{ item[1] }}</button>
        <input v-model="contract" aria-label="指定合约" placeholder="例如 JM2601" @change="switchIdentity({ seriesKind: 'contract' })">
        <button type="button" :aria-pressed="identity.seriesKind === 'contract'" @click="switchIdentity({ seriesKind: 'contract' })">指定合约</button>
      </div>
      <div class="free-workspace__control-group" aria-label="周期">
        <button v-for="item in MARKET_FREQUENCIES" :key="item" type="button" :aria-pressed="identity.frequency === item" @click="switchIdentity({ frequency: item as MarketFrequency })">{{ item === '1d' ? 'D' : item === '1w' ? 'W' : item }}</button>
      </div>
      <details open>
        <summary>指标设置</summary>
        <label v-for="item in [['ema_10', 'EMA10'], ['ema_21', 'EMA21'], ['ema_60', 'EMA60']] as const" :key="item[0]"><input type="checkbox" :checked="optionalEmaIndicators.includes(item[0])" @change="toggleEma(item[0])">{{ item[1] }}</label>
        <label><input v-model="showRangeDetector" type="checkbox">箱体识别（Range）</label>
      </details>
    </div>

    <MarketDetailFactStrip :facts="model.facts" />
    <p v-if="identityHint" class="free-workspace__hint" role="status">{{ identityHint }}</p>
    <p v-if="model.semanticBanner.tone === 'warning'" class="free-workspace__warning" role="status">{{ rangeWarning ?? model.semanticBanner.text }}</p>
    <FreeChartStage
      :bars="bars"
      :mutation="mutation"
      :loading="loading"
      :error="error"
      :period="identity.frequency"
      :series-kind="identity.seriesKind"
      :visible-main-indicators="indicators"
      :range-detector-source-identity="sourceIdentity"
      :range-detector-anchor-time="rangeState === 'ready' ? rangeWarmup.anchorTime.value : null"
      @load-earlier="emit('loadEarlier')"
    />
    <section class="free-workspace__context"><h2>市场背景</h2><p v-if="research">{{ research.product_name }} · {{ research.daily_trend === 'up' ? '日线偏强' : research.daily_trend === 'down' ? '日线偏弱' : '日线暂无方向结论' }}</p><p v-else>{{ researchError ? '市场背景暂不可用' : '暂无市场背景' }}</p></section>
    <section class="free-workspace__data">
      <h2>数据详情</h2>
      <MarketDetailDisclosure
        v-for="section in model.disclosureSections"
        :key="section.id"
        :section="section"
        :open="openDisclosureIds.includes(section.id)"
        @toggle="toggleDisclosure(section.id)"
      />
    </section>
  </section>
</template>

<style scoped>
.free-workspace { display: grid; gap: var(--gy-space-4); }
.free-workspace__controls { display: grid; gap: var(--gy-space-2); padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.free-workspace__control-group { display: flex; flex-wrap: wrap; gap: 6px; }
.free-workspace button, .free-workspace input { min-height: 36px; font: inherit; }
.free-workspace button { padding: 0 9px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: var(--gy-bg-panel); cursor: pointer; }
.free-workspace button[aria-pressed='true'] { border-color: var(--gy-border-focus); color: var(--gy-action-primary); }
.free-workspace input[type='text'], .free-workspace input:not([type]) { max-width: 128px; padding: 0 8px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-app); color: var(--gy-text-primary); }
.free-workspace details { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.free-workspace summary { cursor: pointer; }
.free-workspace label { margin: 0 8px 0 0; }
.free-workspace__warning { margin: 0; padding: var(--gy-space-2) var(--gy-space-3); border-radius: var(--gy-radius-sm); color: var(--gy-status-warning); background: color-mix(in srgb, var(--gy-status-warning) 10%, transparent); }
.free-workspace__hint { margin: 0; color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.free-workspace__context, .free-workspace__data { padding: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
.free-workspace h2 { margin: 0 0 var(--gy-space-2); font-size: var(--gy-font-size-base); }
.free-workspace__context p { margin: 0; color: var(--gy-text-secondary); }
@media (max-width: 480px) { .free-workspace button { min-height: 44px; } }
</style>
