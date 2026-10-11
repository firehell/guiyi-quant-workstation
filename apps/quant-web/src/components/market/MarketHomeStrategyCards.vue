<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { getNewowHomeCards } from '@/api/newowHomeCards'
import { createHomeCardLoader, type CardDelivery, type HomePeriod, type HomePeriodFact, type HomeStrategy } from '@/utils/newowHomeCards'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { MarketHomeLiveDisplayRow } from '@/utils/marketHomeLiveView'
import type { MarketHomeSort, MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'

type Row = MarketHomeLiveDisplayRow<MarketHomeRow>
const props = defineProps<{ rows: Row[]; authority: string; refreshSequence: number; liveStale: boolean; sort: MarketHomeSort; sortDirection: MarketHomeSortDirection }>()
const emit = defineEmits<{ open: [row: Row]; chart: [symbol: string, strategy: HomeStrategy, frequency: HomePeriod]; sort: [sort: MarketHomeSort] }>()
const deliveries = shallowRef<Record<string, CardDelivery>>({})
const loader = createHomeCardLoader(getNewowHomeCards, value => { deliveries.value = value })
type Preferences = Record<string, { expanded: boolean; trend: HomePeriod; oscillation: HomePeriod }>
const preferences = ref<Preferences>(restore())
const strategies = [{ code: 'trend' as const, label: '趋势策略' }, { code: 'oscillation' as const, label: '震荡策略' }]
const steps = ['FLAT', 'BUILD', 'HOLD', 'CLEAR'] as const
const icons = { FLAT: '○', BUILD: '▲', HOLD: '✓', CLEAR: '↘' }
const labels = { BUILD: '建仓', HOLD: '持有', CLEAR: '清仓', FLAT: '空仓' }
const productKey = computed(() => props.rows.map(row => row.symbol).sort().join(','))
watch([productKey, () => props.authority, () => props.refreshSequence], () => { void loader.load(productKey.value ? productKey.value.split(',') : []) }, { immediate: true })
onBeforeUnmount(() => loader.dispose())

function restore(): Preferences {
  try {
    const value = JSON.parse(sessionStorage.getItem('guiyi.market-home.cards.v1') ?? '{}')
    return Object.fromEntries(Object.entries(value).filter(([, item]) => {
      const preference = item as Preferences[string]
      return preference && typeof preference.expanded === 'boolean' && ['1d', '1w'].includes(preference.trend) && ['1d', '1w'].includes(preference.oscillation)
    })) as Preferences
  } catch { return {} }
}
function preference(symbol: string) { return preferences.value[symbol] ?? { expanded: false, trend: '1d', oscillation: '1d' } }
function update(symbol: string, patch: Partial<Preferences[string]>) {
  preferences.value = { ...preferences.value, [symbol]: { ...preference(symbol), ...patch } }
  try { sessionStorage.setItem('guiyi.market-home.cards.v1', JSON.stringify(preferences.value)) } catch {}
}
function fact(symbol: string, strategy: HomeStrategy, period: HomePeriod): HomePeriodFact | undefined { return deliveries.value[symbol]?.card?.strategies[strategy][period] }
function selected(symbol: string, strategy: HomeStrategy) { return fact(symbol, strategy, preference(symbol)[strategy]) }
function status(value?: HomePeriodFact) { return value?.status === 'ready' && value.state ? labels[value.state] : value?.status === 'warming' ? '预热中' : value ? '不可用' : '加载中' }
function stateClass(value?: HomePeriodFact) { return value?.status === 'ready' && value.state ? value.state.toLowerCase() : 'pending' }
function price(value?: string | null) { return value == null ? '—' : Number(value).toFixed(2) }
function space(value?: string | null) { return value == null ? '—' : `${Number(value).toFixed(1)}%` }
function date(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return '—'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}
</script>

<template>
  <div class="strategy-cards-toolbar"><span>日周策略卡</span><div>排序 <button v-for="option in [{code:'default', label:'默认'}, {code:'close', label:'价格'}, {code:'change', label:'涨跌幅'}, {code:'volume', label:'成交量'}, {code:'oi', label:'持仓量'}] as const" :key="option.code" :aria-pressed="sort === option.code" @click="emit('sort', option.code)">{{ option.label }}<span v-if="sort === option.code && sort !== 'default'">{{ sortDirection === 'desc' ? ' ↓' : ' ↑' }}</span></button></div></div>
  <section class="strategy-cards" aria-label="品种日周策略卡">
    <article v-for="row in rows" :key="row.symbol" class="strategy-card">
      <header class="strategy-card-header">
        <button class="strategy-card-name" @click="emit('open', row)"><strong>{{ row.product_name }}</strong><span>{{ row.symbol.toUpperCase() }} · {{ row.liveQuote?.physicalContract ?? row.actual_contract }}</span></button>
        <div class="strategy-card-quote"><strong>{{ row.close }}</strong><span :class="row.price_change_1d == null ? '' : row.price_change_1d >= 0 ? 'up' : 'down'">{{ row.price_change_1d == null ? '—' : `${row.price_change_1d >= 0 ? '+' : ''}${(row.price_change_1d * 100).toFixed(2)}%` }}</span><small>{{ row.liveQuote ? `${liveStale ? '断线保留报价' : '最新完成行情'} · ${date(row.liveQuote.barEnd)}` : `日线收盘报价 · ${row.data_as_of}` }}</small></div>
      </header>
      <p v-if="deliveries[row.symbol]?.stale" class="card-notice" role="status">{{ deliveries[row.symbol]?.loading ? '策略刷新中，保留上次快照' : '策略刷新失败，保留上次快照' }}</p>
      <p v-else-if="deliveries[row.symbol]?.failed" class="card-notice" role="status">策略读取失败，可刷新重试</p>
      <div class="strategy-card-summary">
        <div v-for="strategy in strategies" :key="strategy.code"><b>{{ strategy.label }}</b><span v-for="period in ['1d', '1w'] as const" :key="period" class="card-status" :class="stateClass(fact(row.symbol, strategy.code, period))">{{ period === '1d' ? '日' : '周' }} · {{ status(fact(row.symbol, strategy.code, period)) }}</span></div>
      </div>
      <button class="card-expand" :aria-expanded="preference(row.symbol).expanded" :aria-controls="`card-${row.symbol}`" @click="update(row.symbol, { expanded: !preference(row.symbol).expanded })">{{ preference(row.symbol).expanded ? '收起策略详情 −' : '展开策略详情 ＋' }}</button>
      <div v-if="preference(row.symbol).expanded" :id="`card-${row.symbol}`" class="strategy-card-details">
        <section v-for="strategy in strategies" :key="strategy.code" class="trade-card" :aria-label="`${row.product_name}${strategy.label}`">
          <header class="trade-card-header"><strong>{{ strategy.label }}</strong><div class="period-switch" :aria-label="`${strategy.label}周期`"><button v-for="period in ['1d', '1w'] as const" :key="period" :aria-pressed="preference(row.symbol)[strategy.code] === period" @click="update(row.symbol, { [strategy.code]: period })">{{ period === '1d' ? '日线' : '周线' }}</button></div><span class="card-status" :class="stateClass(selected(row.symbol, strategy.code))">{{ status(selected(row.symbol, strategy.code)) }}</span></header>
          <ol class="card-progress" aria-label="策略阶段"><li v-for="step in steps" :key="step" :class="{ active: selected(row.symbol, strategy.code)?.status === 'ready' && selected(row.symbol, strategy.code)?.state === step }" :aria-current="selected(row.symbol, strategy.code)?.status === 'ready' && selected(row.symbol, strategy.code)?.state === step ? 'step' : undefined"><i :class="step.toLowerCase()">{{ icons[step] }}</i><span>{{ labels[step] }}</span></li></ol>
          <dl class="card-prices"><div><dt>目标价</dt><dd>{{ price(selected(row.symbol, strategy.code)?.target) }}</dd></div><div><dt>吸筹价</dt><dd>{{ price(selected(row.symbol, strategy.code)?.absorb) }}</dd></div><div><dt>参考成本</dt><dd>{{ price(selected(row.symbol, strategy.code)?.reference_cost) }}</dd></div><div><dt>目标空间</dt><dd>{{ space(selected(row.symbol, strategy.code)?.target_space_percent) }}</dd></div></dl>
          <p class="card-facts">{{ selected(row.symbol, strategy.code)?.physical_contract ?? '合约待确认' }} · 策略截至 {{ date(selected(row.symbol, strategy.code)?.bar_end) }}<span v-if="selected(row.symbol, strategy.code)?.freshness === 'pending_update'"> · 等待最新周期更新</span></p>
          <p class="card-facts">最近动作：{{ selected(row.symbol, strategy.code)?.recent_action ? `${labels[selected(row.symbol, strategy.code)!.recent_action!.kind]} · ${date(selected(row.symbol, strategy.code)?.recent_action?.bar_end)}` : '—' }}</p>
          <footer><small>页面参考价格 · 非成交成本</small><button @click="emit('chart', row.symbol, strategy.code, preference(row.symbol)[strategy.code])">查看图表 →</button></footer>
        </section>
      </div>
    </article>
  </section>
</template>

<style scoped>
.strategy-cards-toolbar>div{display:flex;flex-wrap:wrap;align-items:center;gap:4px}.strategy-cards-toolbar{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between;align-items:center;margin:12px 0;color:var(--gy-text-secondary);font-size:12px}.strategy-cards-toolbar button{margin-left:6px;border:1px solid var(--gy-border);border-radius:8px;padding:5px 9px;background:var(--gy-bg-panel);color:inherit}.strategy-cards-toolbar button[aria-pressed=true]{color:#007aff;border-color:#007aff}.strategy-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:start}.strategy-card{background:var(--gy-bg-panel,#fff);border:1px solid var(--gy-border,#e8e8ed);border-radius:14px;overflow:hidden}.strategy-card-header{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;gap:12px}.strategy-card-name{display:grid;text-align:left;gap:5px;background:none;border:0;color:inherit;cursor:pointer}.strategy-card-name strong{font-size:17px}.strategy-card-name span,.strategy-card-quote small{font-size:11px;color:var(--gy-text-secondary)}.strategy-card-quote{display:grid;grid-template-columns:auto auto;text-align:right;gap:4px 9px;align-items:baseline}.strategy-card-quote strong{font-size:20px;font-variant-numeric:tabular-nums}.strategy-card-quote span{font-size:13px}.strategy-card-quote small{grid-column:1/-1}.up{color:#ff3b30}.down{color:#34a866}.strategy-card-summary{padding:0 16px 10px;display:grid;gap:8px}.strategy-card-summary>div{display:flex;align-items:center;gap:8px}.strategy-card-summary b{font-size:12px;margin-right:auto}.card-status{font-size:11px;padding:3px 8px;border-radius:8px;font-weight:600;white-space:nowrap}.build{color:#ff3b30;background:#ffebee}.hold{color:#df8100;background:#fff3e0}.clear{color:#26964a;background:#e8f5e9}.flat{color:#007aff;background:#e8f0fe}.pending{color:#888;background:#f0f0f3}.card-expand{border:0;border-top:1px solid var(--gy-border,#eee);background:none;width:100%;padding:9px;color:var(--gy-text-secondary);font-size:11px;cursor:pointer}.strategy-card-details{padding:0 12px 4px}.trade-card{border:1px solid var(--gy-border,#e8e8ed);border-radius:12px;padding:12px 14px;margin:0 0 8px}.trade-card-header{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.trade-card-header>strong{font-size:13px;margin-right:auto}.period-switch{display:flex;border-radius:7px;background:var(--gy-bg-body,#f5f5f7);padding:2px}.period-switch button{border:0;border-radius:5px;background:none;padding:4px 7px;color:var(--gy-text-secondary);font-size:11px}.period-switch button[aria-pressed=true]{color:#007aff;background:var(--gy-bg-panel,#fff);box-shadow:0 1px 4px #0001}.card-progress{display:flex;list-style:none;padding:0;margin:14px 0 12px}.card-progress li{position:relative;display:grid;justify-items:center;gap:5px;flex:1;opacity:.38;font-size:10px}.card-progress li:before{content:'';position:absolute;height:2px;top:11px;background:var(--gy-border,#e8e8ed);width:100%}.card-progress li:first-child:before{left:50%;width:50%}.card-progress li:last-child:before{right:50%;width:50%}.card-progress i{z-index:1;display:grid;place-items:center;width:22px;height:22px;border-radius:50%;font-style:normal}.card-progress li.active{opacity:1;font-weight:600}.card-progress .active i{transform:scale(1.12)}.card-prices{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;border-top:1px solid var(--gy-border,#eee);padding-top:10px;margin:0 0 10px}.card-prices dt{font-size:10px;color:var(--gy-text-secondary)}.card-prices dd{margin:4px 0 0;font-size:14px;font-weight:600;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.card-facts{font-size:10px;color:var(--gy-text-secondary);line-height:1.5;margin:4px 0;overflow-wrap:anywhere}.trade-card footer{display:flex;align-items:center;justify-content:space-between;margin-top:9px;gap:4px}.trade-card footer small{font-size:10px;color:var(--gy-text-secondary)}.trade-card footer button{border:0;background:none;color:#007aff;font-size:11px;padding:4px 0;cursor:pointer}.card-notice{color:#a56500;background:#fff7e8;font-size:11px;margin:0 16px 8px;padding:6px 8px;border-radius:6px}button:focus-visible{outline:2px solid #007aff;outline-offset:2px}@media(max-width:767px){.strategy-cards{grid-template-columns:minmax(0,1fr);gap:9px}.strategy-card-header{padding:12px}.strategy-card-summary{padding:0 12px 10px}.trade-card{padding:12px}.strategy-card-quote strong{font-size:18px}}
</style>
