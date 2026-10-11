<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getNewowHomeCards } from '@/api/newowHomeCards'
import { createHomeCardLoader, homeDeliveryNotice, homeDirectionDisplay, homePeriodDisplay, homeReferenceDisplay, type CardDelivery, type HomePeriod, type HomeStrategy } from '@/utils/newowHomeCards'
import { newowReferencePrice } from '@/utils/newowPagePresentation'
import { formatBeijingInstant, formatMarketPercent } from '@/utils/marketDisplay'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { MarketHomeLiveDisplayRow } from '@/utils/marketHomeLiveView'
import type { MarketHomeSort, MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'

type Row = MarketHomeLiveDisplayRow<MarketHomeRow>
const props = defineProps<{ rows: Row[]; authority: string; refreshSequence: number; liveStale: boolean; sort: MarketHomeSort; sortDirection: MarketHomeSortDirection }>()
const emit = defineEmits<{ open: [row: Row]; chart: [symbol: string, strategy: HomeStrategy, frequency: HomePeriod]; sort: [sort: MarketHomeSort] }>()
const deliveries = shallowRef<Record<string, CardDelivery>>({})
const loader = createHomeCardLoader(getNewowHomeCards, value => { deliveries.value = value })
const strategy = ref<HomeStrategy>('trend')
const strategies = [{ code: 'trend' as const, label: '趋势' }, { code: 'oscillation' as const, label: '震荡' }]
const periods = ['1d', '1w'] as const
const sortOptions = [{ code: 'default', label: '默认' }, { code: 'close', label: '价格' }, { code: 'change', label: '涨跌幅' }, { code: 'volume', label: '成交量' }, { code: 'oi', label: '持仓量' }] as const
const productKey = computed(() => props.rows.map(row => row.symbol).sort().join(','))
watch([productKey, () => props.authority, () => props.refreshSequence], () => { void loader.load(productKey.value ? productKey.value.split(',') : []) }, { immediate: true })
onBeforeUnmount(() => loader.dispose())
function fact(symbol: string, period: HomePeriod) { return deliveries.value[symbol]?.card?.strategies[strategy.value][period] }
function direction(symbol: string) { return homeDirectionDisplay(fact(symbol, '1d'), fact(symbol, '1w')) }
function reference(symbol: string) { return homeReferenceDisplay(fact(symbol, '1d')) }
function periodLabel(period: HomePeriod) { return period === '1d' ? '日' : '周' }
function pending(symbol: string) { return periods.some(period => fact(symbol, period)?.freshness === 'pending_update') }
</script>

<template>
  <div class="strategy-list-toolbar">
    <div class="strategy-switch" aria-label="首页策略"><button v-for="option in strategies" :key="option.code" :aria-pressed="strategy === option.code" @click="strategy = option.code">{{ option.label }}</button></div>
    <div class="strategy-sort" aria-label="行情排序">排序 <button v-for="option in sortOptions" :key="option.code" :aria-pressed="sort === option.code" @click="emit('sort', option.code)">{{ option.label }}<span v-if="sort === option.code && sort !== 'default'">{{ sortDirection === 'desc' ? ' ↓' : ' ↑' }}</span></button></div>
  </div>
  <section class="strategy-list" aria-label="品种日周策略列表">
    <div class="strategy-list-columns" aria-hidden="true"><span>品种</span><span>价格</span><span>涨跌幅</span><span>目标/吸筹</span><span>日 / 周</span><span>趋势方向</span></div>
    <article v-for="row in rows" :key="row.symbol" class="strategy-list-item">
      <div class="strategy-list-row">
        <button class="product-name" @click="emit('open', row)"><strong>{{ row.product_name }}</strong><small>{{ row.symbol.toUpperCase() }}</small></button>
        <div class="list-price"><small class="mobile-label">价格</small><strong>{{ newowReferencePrice(String(row.close)) }}</strong></div>
        <div class="list-change" :class="row.price_change_1d == null ? '' : row.price_change_1d >= 0 ? 'up' : 'down'"><small class="mobile-label">涨跌幅</small>{{ formatMarketPercent(row.price_change_1d == null ? null : String(row.price_change_1d), 'ratio', true) }}</div>
        <div class="list-reference"><small>{{ reference(row.symbol).label }}</small><strong>{{ reference(row.symbol).text }}</strong></div>
        <div class="list-periods"><button v-for="period in periods" :key="period" :class="homePeriodDisplay(fact(row.symbol, period)).tone" :aria-label="`${row.product_name}${strategy === 'trend' ? '趋势' : '震荡'}${periodLabel(period)}线${homePeriodDisplay(fact(row.symbol, period)).label}，查看图表`" :title="`${periodLabel(period)}线 · ${homePeriodDisplay(fact(row.symbol, period)).label}`" @click="emit('chart', row.symbol, strategy, period)"><span>{{ periodLabel(period) }}</span><b>{{ homePeriodDisplay(fact(row.symbol, period)).icon }}</b></button></div>
        <div class="list-direction" :class="direction(row.symbol).tone" title="日周已就绪策略状态汇总：建仓/持有为上行侧，清仓/空仓为下行侧；不是预测信号。"><small class="mobile-label">趋势方向</small>{{ direction(row.symbol).label }}</div>
      </div>
      <div class="list-notices" role="status">
        <span v-if="homeDeliveryNotice(deliveries[row.symbol])">{{ homeDeliveryNotice(deliveries[row.symbol]) }}</span>
        <span v-if="row.liveQuote && liveStale">断线保留最新完成报价</span>
        <span v-if="pending(row.symbol)">等待最新周期更新</span>
        <span v-for="period in periods.filter(period => fact(row.symbol, period)?.status !== 'ready' && fact(row.symbol, period))" :key="period">{{ periodLabel(period) }}线{{ homePeriodDisplay(fact(row.symbol, period)).label }}</span>
      </div>
      <details class="list-details"><summary>来源与合约详情</summary>
        <p>{{ row.liveQuote ? `最新完成行情 · ${formatBeijingInstant(row.liveQuote.barEnd)}` : `日线收盘报价 · ${row.data_as_of}` }} · {{ row.liveQuote?.physicalContract ?? row.actual_contract }}</p>
        <p v-for="period in periods" :key="period">{{ periodLabel(period) }}线 · {{ homePeriodDisplay(fact(row.symbol, period)).label }} · {{ fact(row.symbol, period)?.physical_contract ?? '合约待确认' }} · 截至 {{ formatBeijingInstant(fact(row.symbol, period)?.bar_end) }}<br>来源 {{ fact(row.symbol, period)?.source_identity ?? '—' }} · 计算段 {{ fact(row.symbol, period)?.calculation_segment_id ?? '—' }}</p>
        <p>页面参考价格 · 非成交成本</p>
      </details>
    </article>
  </section>
</template>

<style scoped>
.strategy-list-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0;color:var(--gy-text-secondary);font-size:12px}
.strategy-switch,.strategy-sort{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.strategy-list-toolbar button{border:1px solid var(--gy-border);border-radius:7px;padding:5px 9px;background:var(--gy-bg-panel);color:inherit;cursor:pointer}
.strategy-list-toolbar button[aria-pressed=true]{color:#007aff;border-color:#007aff}
.strategy-list{background:var(--gy-bg-panel,#fff);border:1px solid var(--gy-border,#e8e8ed);border-radius:12px;overflow:hidden}
.strategy-list-columns,.strategy-list-row{display:grid;grid-template-columns:minmax(100px,1.2fr) minmax(78px,1fr) minmax(74px,.8fr) minmax(95px,1fr) 100px minmax(88px,.9fr);gap:10px;align-items:center;padding:10px 14px}
.strategy-list-columns{font-size:11px;color:var(--gy-text-secondary);background:var(--gy-bg-body,#f5f5f7)}
.strategy-list-item+.strategy-list-item{border-top:1px solid var(--gy-border,#e8e8ed)}
.strategy-list-row{min-height:54px;font-size:13px;font-variant-numeric:tabular-nums}
.product-name{display:flex;align-items:baseline;gap:7px;text-align:left;background:none;border:0;color:inherit;cursor:pointer;padding:0}
.product-name strong{font-size:14px}.product-name small,.list-reference small{font-size:10px;color:var(--gy-text-secondary)}
.list-price strong{font-size:15px}.list-reference{display:grid;gap:3px}.list-reference strong{font-size:13px}
.list-periods{display:flex;gap:5px}.list-periods button{display:flex;align-items:center;justify-content:center;gap:5px;border:0;border-radius:6px;padding:5px 7px;cursor:pointer;font-size:11px}.list-periods b{font-size:13px}
.up{color:#e63830}.down{color:#26964a}.mixed{color:#a56500}.build{color:#e63830;background:#ffebee}.hold{color:#c77900;background:#fff3e0}.clear{color:#26964a;background:#e8f5e9}.flat{color:#007aff;background:#e8f0fe}.pending{color:var(--gy-text-secondary,#888);background:var(--gy-bg-body,#f0f0f3)}
.list-notices{display:flex;gap:8px;flex-wrap:wrap;font-size:11px;color:#a56500;padding:0 14px}.list-notices:has(span){padding-bottom:7px}
.list-details{font-size:10px;color:var(--gy-text-secondary);padding:0 14px 8px;line-height:1.6;overflow-wrap:anywhere}.list-details summary{cursor:pointer;width:fit-content}.list-details p{margin:6px 0}.mobile-label{display:none}button:focus-visible,summary:focus-visible{outline:2px solid #007aff;outline-offset:2px}
@media(max-width:767px){.strategy-list-columns{display:none}.strategy-list-row{grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,1fr);gap:10px 7px;padding:11px 12px}.product-name{display:grid;gap:3px}.mobile-label{display:block;font-size:10px;color:var(--gy-text-secondary);margin-bottom:3px}.list-price,.list-change{text-align:right}.list-periods{justify-content:center}.list-direction{text-align:right;font-size:12px}.list-notices,.list-details{padding-left:12px;padding-right:12px}.strategy-sort{font-size:11px}.strategy-list-toolbar button{padding:5px 7px}}
</style>
