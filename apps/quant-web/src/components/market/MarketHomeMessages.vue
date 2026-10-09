<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AlertEvent, AlertRuleCode } from '@/types/market'
import type { ProductOption } from '@/utils/productSearch'
import { ALERT_RULE_CODES, alertEventHomeResultLabel, alertEventRuleShortLabel } from '@/utils/alertRules'
import { useMarketMessages } from '@/composables/useMarketMessages'
import { getNewowMessages, newowMessageStrategies, type NewowMessage } from '@/api/newowMessages'
import { recordingPointLabel } from '@/utils/newowRecording'
import MarketChevron from './MarketChevron.vue'

const props = defineProps<{ options: ProductOption[]; directoryStatus: 'ready' | 'loading' | 'error'; reloadSequence: number }>()
const emit = defineEmits<{ open: [event: AlertEvent]; openNewow: [event: NewowMessage] }>()
const today = localDay(new Date())
const rangeStart = new Date()
rangeStart.setDate(rangeStart.getDate() - 6)
const saved = loadQuery()
const startDay = ref(saved?.startDay ?? localDay(rangeStart))
const endDay = ref(saved?.endDay ?? today)
const symbol = ref(saved?.symbol ?? '')
const ruleCode = ref<AlertRuleCode | null>(saved?.ruleCode ?? null)
const search = ref('')
const newowStrategy = ref(saved?.newowStrategy ?? '')
const frequency = ref(saved?.frequency ?? '')
const newowItems = ref<NewowMessage[]>([])
const newowLoading = ref(false)
const newowError = ref(false)
const newowTruncated = ref(false)
let newowController: AbortController | null = null
const newowVisible = computed(() => newowItems.value.filter(event => {
  const term = search.value.trim().toLowerCase()
  return !term || `${productName(event)} ${event.symbol} ${event.contract ?? ''}`.toLowerCase().includes(term)
}))
const strategyName = (value: string) => newowMessageStrategies.find(row => row.value === value)?.label ?? value
async function loadNewow() {
  newowController?.abort()
  const controller = new AbortController()
  newowController = controller
  newowItems.value = []; newowError.value = false
  if (ruleCode.value !== null || !validRange.value) { newowLoading.value = false; return }
  newowLoading.value = true
  try {
    const page = await getNewowMessages({ since: startDay.value, through: endDay.value,
      ...(symbol.value ? { product: symbol.value } : {}), ...(newowStrategy.value ? { strategy: newowStrategy.value } : {}),
      ...(frequency.value ? { frequency: frequency.value } : {}) }, controller.signal)
    if (controller.signal.aborted) return
    newowItems.value = page.items; newowTruncated.value = page.truncated
  } catch { if (!controller.signal.aborted) newowError.value = true }
  finally { if (!controller.signal.aborted) newowLoading.value = false }
}
function chooseNewow(value: string) { newowStrategy.value = value; ruleCode.value = null }
const filtersOpen = ref(false)
const messages = useMarketMessages({ cacheKey: 'market-home-messages-v1' })
const productName = (event: AlertEvent | NewowMessage) => props.options.find(row => row.symbol === event.symbol)?.name ?? event.symbol.toUpperCase()
const visibleMessages = computed(() => {
  const term = search.value.trim().toLocaleLowerCase()
  return (newowStrategy.value ? [] : messages.items.value).filter(event => (!frequency.value || event.frequency === frequency.value) && (!term || `${productName(event)} ${event.symbol} ${event.contract}`.toLocaleLowerCase().includes(term)))
})
const todayCount = computed(() => [...visibleMessages.value, ...newowVisible.value].filter(event => event.trading_day === today).length)
const periodLabel = (frequency: string) => ({ '1d': '日线', '1w': '周线', '1m': '1分钟', '5m': '5分钟', '15m': '15分钟', '30m': '30分钟', '60m': '60分钟' }[frequency] ?? frequency)
const validRange = computed(() => startDay.value <= endDay.value)
const query = () => ({ startDay: startDay.value, endDay: endDay.value, symbol: symbol.value, ruleCode: ruleCode.value })
let mounted = false

function load(force = false) { if (validRange.value && !newowStrategy.value) void messages.load(query(), { force }); void loadNewow() }
function persistQuery() {
  try { sessionStorage.setItem('guiyi.market-home.messages.v1', JSON.stringify({ ...query(), newowStrategy: newowStrategy.value, frequency: frequency.value })) } catch {}
}
function messageScrollElement(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  const content = document.querySelector<HTMLElement>('.content--market-home')
  const nested = content?.querySelector<HTMLElement>('.n-layout-scroll-container') ?? null
  return [content, nested, document.scrollingElement as HTMLElement | null]
    .find((element) => Boolean(element && element.scrollHeight > element.clientHeight + 1)) ?? content ?? nested
}
function rememberScroll() { messages.rememberScrollTop(messageScrollElement()?.scrollTop ?? 0) }
async function restoreScroll() {
  await nextTick()
  const top = messages.restoreScrollTop()
  if (top > 0) window.requestAnimationFrame(() => messageScrollElement()?.scrollTo({ top }))
}
function open(event: AlertEvent) { rememberScroll(); persistQuery(); emit('open', event) }
watch([startDay, endDay, symbol, ruleCode, newowStrategy, frequency], () => { persistQuery(); if (mounted) load() })
watch(() => props.reloadSequence, () => { if (mounted) load(true) })
onMounted(() => { mounted = true; load(); void restoreScroll() })
onBeforeUnmount(() => { rememberScroll(); messages.dispose(); newowController?.abort() })

function localDay(value: Date) { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}` }
function time(value: string) { return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) }
function loadQuery(): { startDay: string; endDay: string; symbol: string; ruleCode: AlertRuleCode | null; newowStrategy?: string; frequency?: string } | null {
  try {
    const value = JSON.parse(sessionStorage.getItem('guiyi.market-home.messages.v1') ?? 'null')
    const allowedRules = [null, ALERT_RULE_CODES.HTDY, ALERT_RULE_CODES.SUBING_THS]
    if (!value || typeof value !== 'object' || typeof value.startDay !== 'string' || typeof value.endDay !== 'string' || typeof value.symbol !== 'string' || !allowedRules.includes(value.ruleCode)) return null
    if (value.newowStrategy !== undefined && !['', 'trend', 'oscillation', 'main_rise', 'dual_fusion'].includes(value.newowStrategy)) return null
    if (value.frequency !== undefined && !['', '1w', '1d', '60m'].includes(value.frequency)) return null
    return value
  } catch { return null }
}
</script>

<template>
  <section class="market-home-messages" aria-label="历史消息">
    <header class="market-message-header"><h1>消息</h1><div><button type="button" :aria-expanded="filtersOpen" @click="filtersOpen = !filtersOpen">筛选</button><button type="button" :disabled="messages.refreshing.value || newowLoading" @click="load(true)">{{ messages.refreshing.value || newowLoading ? '刷新中…' : '刷新消息' }}</button></div></header>
    <div class="market-message-kinds" aria-label="消息类型">
        <button type="button" :aria-pressed="ruleCode === null && !newowStrategy" @click="newowStrategy = ''; ruleCode = null">全部</button>
        <button type="button" :aria-pressed="ruleCode === ALERT_RULE_CODES.HTDY" @click="newowStrategy = ''; ruleCode = ALERT_RULE_CODES.HTDY">火天大有</button>
        <button type="button" :aria-pressed="ruleCode === ALERT_RULE_CODES.SUBING_THS" @click="newowStrategy = ''; ruleCode = ALERT_RULE_CODES.SUBING_THS">苏冰预警</button>
        <button v-for="strategy in newowMessageStrategies" :key="strategy.value" type="button" :aria-pressed="newowStrategy === strategy.value && ruleCode === null" @click="chooseNewow(strategy.value)">{{ strategy.label }}</button>
    </div>
    <div class="market-message-kinds" aria-label="信号周期"><button v-for="period in [{ value: '', label: '全部周期' }, { value: '1w', label: '周线' }, { value: '1d', label: '日线' }, { value: '60m', label: '60分钟' }]" :key="period.value" type="button" :aria-pressed="frequency === period.value" @click="frequency = period.value">{{ period.label }}</button></div>
    <div class="market-message-search"><input v-model="search" type="search" aria-label="搜索消息" placeholder="搜索品种名称/代码..." /></div>
    <div class="market-message-stats"><span>今日已加载 {{ todayCount }} 条</span><span>当前已加载 {{ (newowStrategy ? 0 : messages.items.value.length) + newowItems.length }} 条 · 匹配 {{ visibleMessages.length + newowVisible.length }} 条</span></div>
    <div v-if="filtersOpen" class="market-message-filters">
      <label>品种<span class="market-message-select"><select v-model="symbol"><option value="">全部品种</option><option v-for="row in options" :key="row.symbol" :value="row.symbol">{{ row.name }} {{ row.symbol.toUpperCase() }}</option></select><MarketChevron /></span></label>
      <label>开始交易日<input v-model="startDay" type="date" /></label>
      <label>结束交易日<input v-model="endDay" type="date" /></label>
    </div>
    <p v-if="newowLoading" class="market-message-status">正在读取牛哇策略信号…</p>
    <p v-if="newowError" class="market-dashboard-page__error" role="alert">牛哇策略信号读取失败，请刷新重试。</p>
    <div v-if="newowVisible.length" class="market-message-list" aria-label="牛哇策略信号">
      <button v-for="event in newowVisible" :key="event.id" type="button" @click="rememberScroll(); emit('openNewow', event)">
        <span class="market-message-row1"><strong>{{ productName(event) }}</strong><span class="market-message-code">({{ event.symbol.toUpperCase() }})</span><span class="market-message-rule">{{ strategyName(event.strategy) }}</span><span class="market-message-period" :data-frequency="event.frequency">{{ periodLabel(event.frequency) }}</span><time :datetime="event.bar_end">{{ time(event.bar_end) }}</time></span>
        <span class="market-message-row2"><span class="market-message-action" :class="{ 'is-sell': ['CLEAR', 'CLOSE_LONG', 'CLOSE', 'REDUCE'].includes(String(event.point.value.kind)) }">{{ recordingPointLabel(event.point) }}</span><span>{{ event.contract ?? '合约未记录' }}</span><span v-if="event.point.value.reference_price">参考价 {{ event.point.value.reference_price }}</span></span>
        <small>策略参考信号<span v-if="event.point.value.retrospective"> · 回看提示</span> · 记录于 {{ time(event.observed_at) }}</small>
      </button>
    </div>
    <p v-if="newowTruncated && ruleCode === null" class="market-message-note">牛哇信号显示最近 500 条，请缩小日期或品种范围查看。</p>
    <p v-if="directoryStatus === 'loading'" class="market-message-status">正在读取品种目录…</p>
    <p v-else-if="directoryStatus === 'error'" class="market-dashboard-page__error" role="alert">品种目录刷新失败；已保留可用选项，可点击刷新重试。</p>
    <p v-if="!validRange" class="market-dashboard-page__error" role="alert">开始日期不能晚于结束日期。</p>
    <p v-if="!newowStrategy && messages.error.value && !messages.items.value.length" class="market-dashboard-page__error" role="alert">火天大有／苏冰预警记录暂不可用，请刷新重试。</p>
    <p v-if="!newowStrategy && messages.loading.value" class="market-message-status">正在读取消息…</p>
    <div v-else-if="!visibleMessages.length && !newowVisible.length && !newowLoading && !newowError" class="market-message-empty"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M10 21h4"/></svg><p>{{ search ? '暂无匹配消息' : '暂无消息' }}</p></div>
    <div v-else class="market-message-list">
      <button v-for="event in visibleMessages" :key="event.id" type="button" @click="open(event)">
        <span class="market-message-row1"><strong>{{ productName(event) }}</strong><span class="market-message-code">({{ event.symbol.toUpperCase() }})</span><span class="market-message-rule">{{ alertEventRuleShortLabel(event) }}</span><span class="market-message-period" :data-frequency="event.frequency">{{ periodLabel(event.frequency) }}</span><time :datetime="event.bar_end">{{ time(event.bar_end) }}</time></span>
        <span class="market-message-row2"><span class="market-message-action" :class="{ 'is-sell': event.result_codes.length === 1 && event.result_codes[0] === 'sell' }">{{ alertEventHomeResultLabel(event) }}</span><span>{{ event.contract }}</span></span>
        <small>{{ event.notification_attempted_at ? `已尝试发送 · ${time(event.notification_attempted_at)}` : '未记录发送尝试' }}</small>
      </button>
    </div>
    <button v-if="!newowStrategy && messages.nextBefore.value" class="market-message-more" type="button" :disabled="messages.refreshing.value || messages.loadingMore.value" @click="messages.loadMore()">{{ messages.refreshing.value ? '刷新中…' : messages.loadingMore.value ? '读取中…' : '加载更多' }}</button>
    <p class="market-message-note">牛哇信号为已保存的策略参考记录；历史预警的发送尝试不代表已送达。</p>
    <p v-if="!newowStrategy && messages.error.value && messages.items.value.length" class="market-dashboard-page__error" role="alert">下一页读取失败；已保留当前消息。</p>
  </section>
</template>
