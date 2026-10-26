<script setup lang="ts">
import { homeContext, type NewowHomeContext } from '@/utils/newowHomeContext'
import MarketStateIcon from './MarketStateIcon.vue'
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getNewowHomeProjection } from '@/api/newowHomeCards'
import { homeSnapshotCache } from '@/api/homeSnapshotCache'
import { normalizeHomeCards, type HomeCard } from '@/utils/newowHomeCards'
import { homeCardPresentation, homeRowHints, homeCautionNotice, homeCardSpace, homeControlLabel, homePagePerformance, homeCompositeDisplay, homeTrendDisplay, homeDeliveryNotice, homePeriodDisplay, type CardDelivery, type HomePeriod, type HomeStrategy } from '@/utils/newowHomeCards'
import { newowReferencePrice } from '@/utils/newowPagePresentation'
import { formatBeijingInstant, formatMarketPercent } from '@/utils/marketDisplay'
import { marketHomeQualityNotice } from '@/utils/marketHomePresentation'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { MarketHomeLiveDisplayRow } from '@/utils/marketHomeLiveView'
import type { MarketHomeSort, MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'

type Row = MarketHomeLiveDisplayRow<MarketHomeRow>
const props = defineProps<{ rows: Row[]; products: readonly string[]; authority: string; refreshSequence: number; liveStale: boolean; sort: MarketHomeSort; sortDirection: MarketHomeSortDirection; active?: boolean }>()
const emit = defineEmits<{ open: [row: Row]; chart: [symbol: string, strategy: HomeStrategy, frequency: HomePeriod, focusBarEnd?: string, context?: NewowHomeContext]; sort: [sort: MarketHomeSort] }>()
const deliveries = shallowRef<Record<string, CardDelivery>>({})
let generation = 0
let controller: AbortController | null = null
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollCount = 0
function clearPoll() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null } }
async function readProjection(resetPoll = true) {
  const owner = ++generation
  controller?.abort(); controller = new AbortController()
  const signal = controller.signal
  clearPoll()
  if (resetPoll) pollCount = 0
  for (const symbol of props.products) {
    if (!deliveries.value[symbol]) {
      const cached = homeSnapshotCache.peek<HomeCard>(`card:${symbol}`)
      if (cached) try {
        const response = normalizeHomeCards({ schema_version: 'newow_home_cards_v2', requested_at: new Date(cached.savedAt).toISOString(), items: [cached.value] }, [symbol])
        deliveries.value[symbol] = { card: response.items[0]!, stale: true, loading: true, failed: false, savedAt: response.requested_at }
      } catch { void homeSnapshotCache.discard(`card:${symbol}`) }
    }
  }
  deliveries.value = Object.fromEntries(Object.entries(deliveries.value).map(([symbol, entry]) => [symbol, { ...entry, loading: true, stale: Boolean(entry.card) }]))
  try {
    const response = await getNewowHomeProjection(signal)
    if (signal.aborted || owner !== generation) return
    const next: Record<string, CardDelivery> = {}
    for (const item of response.items) {
      const hasSnapshot = item.computed_at !== null
      const previous = deliveries.value[item.product]
      next[item.product] = { card: hasSnapshot ? item : previous?.card ?? null, loading: false,
        stale: item.projection_status !== 'ready', failed: item.projection_status === 'failed',
        savedAt: item.computed_at ?? previous?.savedAt, projectionStatus: item.projection_status }
      if (hasSnapshot) void homeSnapshotCache.put(`card:${item.product}`, item)
    }
    deliveries.value = next
    if (response.items.some(item => item.projection_status !== 'ready') && pollCount++ < 30 && props.active !== false && (typeof document === 'undefined' || document.visibilityState === 'visible')) {
      pollTimer = setTimeout(() => { void readProjection(false) }, 10_000)
    }
  } catch {
    if (signal.aborted || owner !== generation) return
    deliveries.value = Object.fromEntries(Object.entries(deliveries.value).map(([symbol, entry]) => [symbol, { ...entry, loading: false, stale: Boolean(entry.card), failed: true }]))
  }
}
const strategy = ref<HomeStrategy>('trend')
const expanded = ref(new Set<string>())
function toggleSummary(symbol: string) { const next = new Set(expanded.value); if (next.has(symbol)) next.delete(symbol); else next.add(symbol); expanded.value = next }
const strategies = [{ code: 'trend' as const, label: '趋势' }, { code: 'oscillation' as const, label: '震荡' }]
const periods = ['1d', '1w'] as const

watch([() => props.authority, () => props.refreshSequence], () => { if (props.authority) void readProjection() }, { immediate: true })
watch(() => props.active, (active, previous) => { if (active === false) clearPoll(); else if (previous === false) void readProjection() })
let wasHidden = false
function visibilityChanged() {
  if (document.visibilityState !== 'visible') { wasHidden = true; clearPoll() }
  else if (wasHidden && props.active !== false) { wasHidden = false; void readProjection() }
}
if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibilityChanged)
onBeforeUnmount(() => { ++generation; controller?.abort(); clearPoll(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibilityChanged) })
function fact(symbol: string, period: HomePeriod) { return deliveries.value[symbol]?.card?.strategies[strategy.value][period] }
function periodDisplay(symbol: string, period: HomePeriod) { return homePeriodDisplay(fact(symbol, period)) }
function composite(symbol: string) { return homeCompositeDisplay(fact(symbol, '1d'), fact(symbol, '1w')) }
function space(symbol: string) { return homeCardSpace(fact(symbol, '1d')) }
function performance(symbol: string) { return homePagePerformance(fact(symbol, '1d'), strategy.value) }
function performanceNotice(symbol: string) { return deliveries.value[symbol]?.projectionStatus === 'updating' ? '计算中…' : '参考收益待确认' }
function presentation(symbol: string) { return homeCardPresentation(fact(symbol, '1d'), fact(symbol, '1w')) }
function reference(symbol: string) { return composite(symbol).reference }
function periodLabel(period: HomePeriod) { return period === '1d' ? '日' : '周' }
function change(row: Row) { return formatMarketPercent(row.price_change_1d == null ? null : String(row.price_change_1d), 'ratio', true).replace(/^([+-]?\d+)(?:\.(\d+))?%$/, (_match, whole: string, fraction: string | undefined) => `${whole}.${(fraction ?? '').padEnd(2, '0')}%`) }
function priceTone(row: Row) { return row.price_change_1d == null ? 'pending' : row.price_change_1d > 0 ? 'up' : row.price_change_1d < 0 ? 'down' : 'flat' }
function iconState(symbol: string, period: HomePeriod) { return ({ build: 'up', hold: 'aligned', clear: 'down', flat: 'neutral', pending: 'unavailable' } as const)[homePeriodDisplay(fact(symbol, period)).tone as 'build'|'hold'|'clear'|'flat'|'pending'] }
const stages = [{ state: 'FLAT', label: '空仓', icon: 'neutral' }, { state: 'BUILD', label: '买入', icon: 'up' }, { state: 'HOLD', label: '持股', icon: 'aligned' }, { state: 'CLEAR', label: '卖出', icon: 'down' }] as const
function openChart(symbol:string,period:HomePeriod,focus?:string){const context=homeContext(symbol,strategy.value,period,fact(symbol,period));if(context)emit('chart',symbol,strategy.value,period,focus,context);else if(focus)emit('chart',symbol,strategy.value,period,focus);else emit('chart',symbol,strategy.value,period)}
function openSummary(row: Row) { openChart(row.symbol,'1d') }
function trendDisplay(symbol: string) { return homeTrendDisplay(deliveries.value[symbol]?.card?.strategies.trend['1d'], deliveries.value[symbol]) }
function pending(symbol: string) { return periods.some(period => fact(symbol, period)?.freshness === 'pending_update') }
</script>

<template>
  <div class="strategy-list-toolbar">
    <div class="strategy-switch" aria-label="首页策略"><button v-for="option in strategies" :key="option.code" :aria-pressed="strategy === option.code" @click="strategy = option.code">{{ option.label }}</button></div>

  </div>
  <section class="strategy-list" aria-label="品种日周策略列表">
    <div class="strategy-list-columns"><span>品种</span><span>价格</span><span><button class="change-sort" type="button" :aria-pressed="sort === 'change'" :aria-label="sort === 'change' ? `涨跌幅排序，当前${sortDirection === 'desc' ? '降序' : '升序'}` : '涨跌幅排序，当前默认'" @click="emit('sort', 'change')">涨跌幅<span class="sort-arrow" aria-hidden="true">{{ sort === 'change' ? sortDirection === 'desc' ? '▾' : '▴' : '' }}</span></button></span><span>目标价</span><span>日</span><span>周</span><span>趋势</span></div>
    <slot name="status" />
    <article v-for="row in rows" :key="row.symbol" class="strategy-list-item">
      <div class="strategy-list-row" role="button" tabindex="0" :aria-label="`${row.product_name}展开策略摘要`" :aria-expanded="expanded.has(row.symbol)" :aria-controls="`home-summary-${row.symbol}`" @click="toggleSummary(row.symbol)" @keydown.enter.prevent="toggleSummary(row.symbol)" @keydown.space.prevent="toggleSummary(row.symbol)">
        <div class="product-cell"><span class="product-name"><strong>{{ row.product_name }}</strong><small><span>{{ row.symbol.toUpperCase() }}</span><span class="row-hints"><button type="button" v-for="hint in homeRowHints(fact(row.symbol, '1d'))" :key="hint.label" class="row-hint" :title="hint.title" :aria-label="`${hint.label}：${hint.title}。点击定位对应K线`" @click.stop="openChart(row.symbol,'1d',hint.focusBarEnd)">{{ hint.label }}</button><span v-if="homeCautionNotice(fact(row.symbol, '1d'))" class="row-hint-pending" role="status" :title="homeCautionNotice(fact(row.symbol, '1d')) ?? undefined" :aria-label="homeCautionNotice(fact(row.symbol, '1d')) ?? undefined">小心待确认</span></span></small></span></div>
        <div class="list-price" :class="priceTone(row)"><strong>{{ newowReferencePrice(String(row.close)) }}</strong></div>
        <div class="list-change"><span :class="priceTone(row)">{{ change(row) }}</span></div>
        <div class="list-reference"><strong :class="reference(row.symbol).label === '目标' ? 'target' : reference(row.symbol).label === '吸筹' ? 'absorb' : 'pending'" :title="`${reference(row.symbol).label} · 页面参考价格，非成交成本`">{{ reference(row.symbol).text }}</strong></div>
        <div class="list-periods"><span v-for="period in periods" :key="period" :aria-label="`${row.product_name}${strategy === 'trend' ? '趋势' : '震荡'}${periodLabel(period)}线${periodDisplay(row.symbol, period).label}`" :title="`${periodLabel(period)}线 · ${periodDisplay(row.symbol, period).label}`"><MarketStateIcon :state="iconState(row.symbol, period)" /></span></div>
        <div class="list-direction" :title="trendDisplay(row.symbol).title">
          <svg v-if="trendDisplay(row.symbol).tone !== 'pending'" class="independent-trend-icon" viewBox="0 0 24 24" width="22" height="22" role="img" :aria-label="trendDisplay(row.symbol).label">
            <circle cx="12" cy="12" r="11" :fill="trendDisplay(row.symbol).tone === 'up' ? 'rgba(255,59,48,0.12)' : 'rgba(52,199,89,0.12)'"/>
            <g fill="none" :stroke="trendDisplay(row.symbol).tone === 'up' ? '#FF3B30' : '#34C759'" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline :points="trendDisplay(row.symbol).tone === 'up' ? '6.5,15 10.5,11 12.5,13 17.5,8' : '6.5,9 10.5,13 12.5,11 17.5,16'"/>
              <polyline :points="trendDisplay(row.symbol).tone === 'up' ? '13.5,8 17.5,8 17.5,12' : '13.5,16 17.5,16 17.5,12'"/>
            </g>
          </svg>
          <svg v-else class="independent-trend-pending" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#C7C7CC" stroke-width="2" role="img" :aria-label="trendDisplay(row.symbol).label"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        </div>
      </div>
      <p v-if="marketHomeQualityNotice(row.reason_codes)" class="list-quality-note" role="status">{{ marketHomeQualityNotice(row.reason_codes) }}</p>
      <div class="list-notices" role="status">
        <span v-if="homeDeliveryNotice(deliveries[row.symbol])" :title="homeDeliveryNotice(deliveries[row.symbol]) ?? undefined">{{ homeDeliveryNotice(deliveries[row.symbol]) }}<template v-if="deliveries[row.symbol]?.stale && deliveries[row.symbol]?.savedAt"> · {{ formatBeijingInstant(fact(row.symbol, '1d')?.bar_end ?? deliveries[row.symbol]?.savedAt) }}</template></span>
        <span v-if="pending(row.symbol)">等待最新周期更新</span>
        <span v-for="period in periods.filter(period => fact(row.symbol, period)?.status !== 'ready' && fact(row.symbol, period))" :key="period">{{ periodLabel(period) }}线{{ periodDisplay(row.symbol, period).label }}</span>
      </div>
      <section v-if="expanded.has(row.symbol)" :id="`home-summary-${row.symbol}`" class="list-composite" :aria-label="`${row.product_name}日周综合摘要`">
        <div class="composite-card" :class="presentation(row.symbol).state?.toLowerCase() ?? 'pending'" role="link" tabindex="0" :aria-label="`${row.product_name}${strategy === 'trend' ? '趋势' : '震荡'}策略详情`" @click="openSummary(row)" @keydown.enter.self.prevent="openSummary(row)" @keydown.space.self.prevent="openSummary(row)">
          <div class="composite-heading">
            <strong>{{ presentation(row.symbol).prefix }} <span v-if="presentation(row.symbol).price !== '--'" class="composite-price">{{ presentation(row.symbol).price }}</span><span v-else class="composite-price pending">—</span> {{ presentation(row.symbol).suffix }}</strong>
            <span class="composite-signal" :class="presentation(row.symbol).state?.toLowerCase() ?? 'pending'"><span aria-hidden="true">{{ presentation(row.symbol).glyph }}</span> {{ presentation(row.symbol).signal }}</span>
          </div>
          <p class="composite-context">{{ presentation(row.symbol).context }}</p>
          <div class="composite-stages" aria-label="策略状态阶段" :class="{ 'has-state': presentation(row.symbol).stageIndex >= 0 }" :style="{ '--stage-index': presentation(row.symbol).stageIndex }">
            <div v-for="(stage, index) in stages" :key="stage.state" class="composite-stage" :class="{ 'is-active': composite(row.symbol).state === stage.state, 'is-complete': index < presentation(row.symbol).stageIndex }" :aria-current="composite(row.symbol).state === stage.state ? 'step' : undefined">
              <MarketStateIcon v-if="composite(row.symbol).state === stage.state" :state="stage.icon" />
              <span v-else class="stage-idle" aria-hidden="true">{{ index < presentation(row.symbol).stageIndex ? '✓' : '−' }}</span><span>{{ stage.label }}</span>
            </div>
          </div>
          <div class="composite-footer"><div class="composite-tags"><span class="control-tag">{{ homeControlLabel(fact(row.symbol, '1d')) }}</span><span class="performance-tag" :title="performance(row.symbol) ? `页面普通参考收益 · ${performance(row.symbol)?.trade_count} 笔参考交易 · ${performance(row.symbol)?.since} 至 ${performance(row.symbol)?.through} · 零手续费与滑点` : '日线页面参考收益暂不可用'"><template v-if="performance(row.symbol)">日线 {{ performance(row.symbol)?.trade_count ? formatMarketPercent(performance(row.symbol)?.cum_return_percent, 'percentage_points', false) : '—' }}</template><template v-else>{{ performanceNotice(row.symbol) }}</template></span></div><strong v-if="space(row.symbol).value != null" :class="space(row.symbol).target ? 'space-up' : 'space-down'">{{ space(row.symbol).target ? '距目标价' : '距吸筹价' }} {{ formatMarketPercent(space(row.symbol).value, 'percentage_points', true) }}</strong><span v-else>空间待确认</span></div>
        </div>
      </section>
    </article>
  </section>
</template>

<style scoped>
.strategy-list-toolbar{display:flex;align-items:center;justify-content:space-between;min-height:32px;padding:0 12px;background:#fafafa;color:var(--gy-text-muted);font-size:12px}
.strategy-switch{display:flex;gap:14px}.strategy-switch button{border:0;background:none;padding:6px 0;color:var(--gy-text-muted);font-size:12px;cursor:pointer}.strategy-switch button[aria-pressed=true]{color:#ff6535}
.change-sort{display:inline-flex;align-items:center;justify-content:center;gap:1px;min-height:28px;padding:0;border:0;background:none;color:inherit;font:inherit;cursor:pointer}.sort-arrow{color:#ff3b30;font-size:10px;min-width:7px}

.strategy-list{--gy-market-icon-up:#ef493b;--gy-market-icon-aligned:#f6a51a;--gy-market-icon-down:#30c759;--gy-market-icon-neutral:#315cf5;--gy-market-icon-unavailable:#c5c5c9;--gy-market-pill-up-soft:#ffebe9;--gy-market-pill-down-soft:#eaf8ec;background:white;color:#252525}
.strategy-list-columns,.strategy-list-row{display:grid;grid-template-columns:minmax(100px,1fr) 80px 64px 64px 32px 32px 28px;column-gap:2px;align-items:center;padding:0 12px}
.strategy-list-columns{height:38px;background:#fafafa;font-size:12px;color:var(--gy-text-muted)}.strategy-list-columns>span{text-align:center}.strategy-list-columns>span:first-child{text-align:left}.strategy-list-columns>span:nth-child(2){text-align:right}
.strategy-list-item{position:relative;border-bottom:1px solid #f6f6f6}.strategy-list-row{height:60px;font-size:13px;font-variant-numeric:tabular-nums}
.product-cell{display:flex;align-items:flex-end;min-width:0;gap:3px}.product-cell>.product-name{flex:1}.product-name{display:flex;flex-direction:column;align-items:flex-start;gap:4px;min-width:0;text-align:left;background:none;border:0;color:#252525;cursor:pointer;padding:0}.product-name strong{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}.product-name small{display:flex;align-items:center;gap:3px;width:100%;font-size:11px;color:var(--gy-text-muted);font-weight:400}.row-hints{margin-left:auto;display:flex;gap:3px}.row-hint{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;appearance:none;border:0;box-shadow:none;background:#2e8b57;color:#fff;border-radius:3px;padding:1px 3px;font-family:inherit;font-size:10px;font-weight:600;line-height:1;white-space:nowrap;opacity:1;cursor:pointer}.row-hint:focus-visible{outline:2px solid #2e8b57;outline-offset:2px}.flat{color:var(--gy-text-muted)}.list-change>.flat{background:var(--gy-bg-elevated)}
.list-price{text-align:right;white-space:nowrap}.list-price strong{font-size:15px;font-weight:600}.list-change{text-align:center;white-space:nowrap}.list-change>span{display:inline-block;border-radius:4px;padding:3px 7px;font-size:12px;font-weight:600;line-height:1.1}.list-change>.up{background:#ffebe9}.list-change>.down{background:#eaf8ec}
.up{color:#ff403a}.down{color:#2dc653}.pending{color:#a1a1a6}.list-reference{text-align:center}.list-reference strong{display:inline-block;border-radius:4px;padding:3px 5px;font-size:11px;font-weight:650;white-space:nowrap;line-height:1.1}.target{color:#ff9500;background:#fff3e6}.absorb{color:#1681ff;background:#eaf1ff}
.list-periods{display:contents}.list-periods>span{display:flex;align-items:center;justify-content:center;border:0;padding:0;background:none;cursor:pointer}.list-direction{display:flex;justify-content:center}.list-direction :deep(.market-state-icon){width:22px;height:22px;flex-basis:22px}
.list-quality-note{margin:0;padding:0 12px 6px;color:var(--gy-text-secondary);font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.list-notices{position:absolute;left:12px;top:49px;max-width:calc(100% - 440px);display:flex;gap:5px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:9px;color:#b88134;line-height:10px}.list-notices>span{overflow:hidden;text-overflow:ellipsis}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}button:focus-visible,summary:focus-visible{outline:2px solid #ff6535;outline-offset:3px}
@media(max-width:600px){.strategy-list-columns,.strategy-list-row{grid-template-columns:minmax(68px,1fr) 62px 54px 52px 28px 28px 28px;column-gap:3px;padding:0 10px}.strategy-list-row{height:60px}.product-name strong{font-size:13px}.list-price strong{font-size:13px}.list-change>span{font-size:10px;padding:3px}.list-reference strong{font-size:10px;padding:3px}.list-periods :deep(.market-state-icon){width:24px;height:24px;flex-basis:24px}.list-direction :deep(.market-state-icon){width:22px;height:22px;flex-basis:22px}.list-notices{left:10px;max-width:calc(100% - 268px);font-size:8px}.strategy-list-columns{font-size:10px}}
.strategy-list-row{cursor:pointer}.strategy-list-row{transition:background .15s}.strategy-list-row:hover,.strategy-list-row[aria-expanded=true]{background:#f8f8fa}.strategy-list-row:active{background:#f8f8f8}.strategy-list-row:focus-visible,.composite-card:focus-visible{outline:2px solid #ff6535;outline-offset:-2px}
.list-composite{padding:0 12px 10px;background:#fff;border:0}
.composite-card{border:1px solid #e5e5ea;border-radius:12px;padding:12px 14px;cursor:pointer;background:#fff}
.composite-card:hover{border-color:#d1d1d6}
.composite-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:nowrap;min-height:20px}
.composite-heading strong{font-size:13px;line-height:20px;font-weight:400;color:#222}
.composite-heading strong>.composite-price{font-size:15px;font-weight:700;color:#ff3b30}
.composite-card.flat .composite-price{color:#007aff}
.composite-card.clear .composite-price{color:#34c759}
.composite-heading strong>.composite-price.pending{color:#8e8e93}
.composite-signal{display:inline-flex;align-items:center;gap:3px;flex-shrink:0;padding:2px 8px;border-radius:12px;font-size:10px;font-weight:500;line-height:15px}
.composite-signal>span{color:#fff;font-size:11px}
.composite-signal.flat{color:#007aff;background:#eaf2ff}.composite-signal.build{color:#ff3b30;background:#ffebef}.composite-signal.hold{color:#ff9500;background:#fff3e6}.composite-signal.clear{color:#34c759;background:#eaf8ec}.composite-signal.pending{color:#8e8e93;background:#f2f2f7}
.composite-card .composite-context{color:#8e8e93;font-size:11px;line-height:17px;margin:5px 0}
.composite-stages{position:relative;display:flex;justify-content:space-around;margin:7px 0 5px;--rail-y:14px}
.composite-stages:before,.composite-stages.has-state:after{content:'';position:absolute;left:1%;top:var(--rail-y);height:2px;background:#e5e5ea}
.composite-stages:before{right:1%}.composite-stages.has-state:after{width:calc(11.5% + var(--stage-index)*25%);background:#007aff}
.composite-stage{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:3px;width:25%;color:#c7c7cc;font-size:10px;line-height:14px;padding-top:3px}
.composite-stage.is-active{color:#ff3b30;padding-top:0;font-weight:500}
.composite-card.hold .composite-stage.is-active{color:#ff9500}.composite-card.clear .composite-stage.is-active{color:#34c759}.composite-card.flat .composite-stage.is-active{color:#007aff}
.stage-idle{display:grid;place-items:center;width:22px;height:22px;flex-shrink:0;border-radius:50%;background:#e5e5ea;color:#b8b8bd;font-size:12px}
.composite-stage.is-complete .stage-idle{background:#d1d1d6;color:#fff}
.composite-stage.is-active :deep(.market-state-icon){width:28px;height:28px;flex-basis:28px;box-shadow:0 0 0 4px #ff3b3033}
.composite-card.hold .is-active :deep(.market-state-icon){box-shadow:0 0 0 4px #ff950033}.composite-card.clear .is-active :deep(.market-state-icon){box-shadow:0 0 0 4px #34c75933}.composite-card.flat .is-active :deep(.market-state-icon){box-shadow:0 0 0 4px #007aff22}
.composite-footer{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;border-top:1px solid #f2f2f7;padding-top:8px;margin-top:5px;color:#8e8e93;font-size:10px;line-height:17px}
.composite-tags{display:flex;flex-wrap:wrap;gap:6px}.composite-tags>span{border-radius:10px;padding:1px 6px;font-size:10px;line-height:15px}
.composite-tags>.control-tag{color:#ff9500;background:#fff3e6}.composite-tags>.performance-tag{color:#007aff;background:#eaf2ff}
.composite-footer strong{font-size:13px;font-weight:600}.space-up{color:#ff3b30}.space-down{color:#34c759}
@media(max-width:600px){.composite-card{padding:10px}.composite-heading strong{font-size:12px;line-height:18px}.composite-heading strong>.composite-price{font-size:15px}.composite-heading{gap:5px}.composite-signal{padding:2px 6px;font-size:10px}.composite-card .composite-context{font-size:10px}.composite-footer strong{font-size:12px}}
</style>

<style scoped>
.row-hint-pending { font-size:10px; color:#667085; border:1px dashed #98a2b3; border-radius:8px; padding:1px 4px; cursor:help; }
</style>
