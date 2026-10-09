<script setup lang="ts">
import { newowReferencePrice, newowReferencePercent } from '@/utils/newowPagePresentation'
import { computed, ref, watch, useId } from 'vue'
import type { PagePerformance } from '@/utils/newowPagePerformance'
import { pagePerformancePlot } from '@/utils/newowPagePerformance'
import { newowReferenceWindow } from '@/utils/newowReferenceWindows'
const props = defineProps<{ value: PagePerformance | null | undefined; since?: string; through?: string; floor?: string; loading?: boolean }>()
const emit = defineEmits<{ reload: [window: {performanceSince: string; performanceThrough: string}] }>()
const selection = ref<'ordinary' | 'ideal'>('ordinary')
const count = ref(3)
const analysisOpen = ref(false)
const gradientId = `page-return-${useId()}`
const windowSelection = ref('all')
const active = computed(() => props.value?.[selection.value] ?? null)
const idealExplanation = computed(() => ({
  trend: '回看最高收盘价，包含清仓当根',
  main_rise: '回看建仓后最高收盘价，不含清仓当根',
  oscillation: '回看滚动区间高点，可含建仓前高点',
  fusion: '回看最高价，不含清仓当根',
}[props.value?.strategy ?? 'trend']))
const segments = computed(() => pagePerformancePlot(active.value))
const chartTicks = computed(() => {
  const values = active.value?.equity.map(Number) ?? []
  let low = 0, high = 0
  for (const value of values) { low = Math.min(low, value); high = Math.max(high, value) }
  if (high === low) high = low + 1
  const span = high - low
  return Array.from({length:5}, (_,i) => ({position:i * 25, label:`${(high - span * i / 4).toFixed(1)}%`}))
})
const dateTicks = computed(() => {
  const dates = active.value?.trading_days ?? []
  const total = Math.min(7,dates.length)
  return Array.from({length:total}, (_,i) => {
    const index = Math.round(i * (dates.length - 1) / Math.max(1,total - 1))
    return {position:i * 100 / Math.max(1,total - 1), label:dates[index]?.slice(5), anchor:i === 0 ? 'start' : i === total - 1 ? 'end' : ''}
  })
})
const areaPaths = computed(() => segments.value.map(points => {
  const pairs = points.trim().split(' ')
  return `M ${pairs[0]?.split(',')[0]},140 L ${pairs.join(' L ')} L ${pairs.at(-1)?.split(',')[0]},140 Z`
}))
const shortDate = (date: string) => date.slice(5,10)
const drawdown = computed(() => active.value ? `${newowReferencePrice(active.value.summary.maxDrawdown)}%` : '—')
const records = computed(() => [...(active.value?.trades ?? [])].reverse().slice(0, count.value))
watch(() => [props.value, selection.value], () => { count.value = 3 })
function preset(kind: 'three_months' | 'one_year' | 'three_years' | 'ytd' | 'all') {
  windowSelection.value = kind
  if (props.through) emit('reload', newowReferenceWindow(props.through, kind, props.floor ?? props.since))
}
</script>
<template>
  <section class="page-performance newow-reference" aria-label="公开页面收益投影" :aria-busy="loading">
    <header class="newow-reference__returns-heading"><strong>策略收益率走势</strong><button type="button" class="newow-reference__analysis-link" @click="analysisOpen = true">收益分析 ›</button></header>
    <div v-if="value" class="newow-reference__presets page-performance__toolbar" aria-label="页面统计快捷窗口">
      <button v-for="item in ([['three_months','近3月'], ['one_year','近1年'], ['three_years','近3年'], ['ytd','今年']] as const)" :key="item[0]" type="button" :aria-pressed="windowSelection === item[0]" :disabled="loading || !through" @click="preset(item[0])">{{ item[1] }}</button>
      <button type="button" class="newow-reference__ideal" :aria-pressed="selection === 'ideal'" @click="selection = selection === 'ideal' ? 'ordinary' : 'ideal'">理论值</button>
      <button type="button" :aria-pressed="windowSelection === 'all'" :disabled="loading || !through" @click="preset('all')">全部</button>
    </div>
    <details class="page-performance__disclosure"><summary>页面参考口径</summary><p>页面乐观收益 · 零手续费、零滑点；{{ selection === 'ideal' ? idealExplanation : '包含末根估值平仓' }}，不代表模拟账户或可执行收益。</p></details>
    <p v-if="!active" role="status">{{ loading ? '正在读取页面收益投影…' : '当前页面收益投影不可用。' }}</p>
    <template v-else>

      <section class="newow-reference__curve" aria-label="页面估值收益曲线">
        <p v-if="segments.length === 0" role="status">当前区间无页面收益曲线。</p>
        <div v-else class="newow-reference__plot">
          <div class="newow-reference__plot-area">
            <span v-for="tick in chartTicks" :key="tick.position" class="newow-reference__value-tick" :style="{top:`${tick.position}%`}">{{ tick.label }}</span>
            <span v-for="tick in dateTicks" :key="tick.position" class="newow-reference__date-tick" :data-anchor="tick.anchor" :style="{left:`${tick.position}%`}">{{ tick.label }}</span>
            <svg viewBox="0 0 712 140" preserveAspectRatio="none" role="img" :aria-label="`${selection === 'ideal' ? '理论' : '普通'}页面收益曲线，区段中断处断线`">
              <defs><linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff403a" stop-opacity="0.14"/><stop offset="100%" stop-color="#ff403a" stop-opacity="0.01"/></linearGradient></defs>
              <line v-for="tick in chartTicks" :key="tick.position" x1="0" x2="712" :y1="tick.position * 1.4" :y2="tick.position * 1.4" stroke="#f0f1f3" stroke-width="1" />
              <path v-for="(path,index) in areaPaths" :key="`area-${index}`" :d="path" :fill="`url(#${gradientId})`" />
              <polyline v-for="(part,index) in segments" :key="index" :points="part" fill="none" stroke="#ff403a" stroke-width="1.5" vector-effect="non-scaling-stroke" />
            </svg>
          </div>
        </div>
      </section>
      <section class="newow-reference__summary">
      <dl class="newow-reference__metrics" data-testid="page-performance-summary">
        <div><dt>累计收益</dt><dd :data-direction="Number(active.summary.cumReturn) >= 0 ? 'up' : 'down'">{{ newowReferencePercent(active.summary.cumReturn) }}</dd></div>
        <div><dt>胜率</dt><dd>{{ active.summary.accuracy }}%</dd></div>
        <div><dt :title="selection === 'ideal' ? '完整历史按单笔最大亏损；原站日期窗口过滤会重算归一化曲线回撤，保持对应原式。' : '累计页面收益峰值与当前值之差，单位为百分点。'">{{ selection === 'ideal' ? '单笔最大亏损' : '最大回撤' }}</dt><dd class="newow-reference__drawdown">{{ drawdown }}</dd></div>
        <div><dt>交易次数</dt><dd>{{ active.summary.tradeCount }}</dd></div>
      </dl>
      </section>
      <p v-if="value?.ordinary_interrupted_count">{{ value.ordinary_interrupted_count }} 笔跨区段未完成配对未计入普通收益。</p>
      <p v-if="selection === 'ideal' && value?.ideal_open_count">{{ value.ideal_open_count }} 笔理论未平仓未计入完成统计。</p>
      <header class="page-performance__records-heading"><h3>回测操盘提醒</h3><span>历史页面参考，仅供参考，不作为实时买卖提示</span></header>

      <p v-if="records.length === 0">当前口径暂无页面估值交易。</p>
      <article v-for="(trade,index) in records" :key="`${trade.segment_id}:${trade.buyDate}:${trade.sellDate}:${index}`" class="newow-reference__card" :data-page-force-close="trade.forceClose">
        <header><div class="page-performance__record-meta"><strong class="page-performance__badge" :data-open="trade.forceClose">{{ trade.forceClose ? '持仓参考中' : active.period === 'week' ? '周K' : active.period === 'hour' ? '60分' : '日K' }}</strong><span>{{ shortDate(trade.buyDate) }} → {{ trade.forceClose ? '至估值日' : shortDate(trade.sellDate) }}</span></div><strong :data-direction="Number(trade.pct) >= 0 ? 'up' : 'down'">{{ trade.forceClose ? '参考浮动' : '盈亏' }} {{ newowReferencePercent(trade.pct) }}</strong></header>
        <p class="page-performance__record-line"><span><b class="page-performance__buy">建仓</b> 买入 <strong>{{ newowReferencePrice(trade.buyPrice) }}</strong></span><time :datetime="trade.buyDate" :title="trade.buyDate">{{ shortDate(trade.buyDate) }}</time></p>
        <p class="page-performance__record-line"><span><b :class="trade.forceClose ? '' : 'page-performance__sell'">{{ trade.forceClose ? '参考估值' : '清仓' }}</b> {{ trade.forceClose ? '' : '卖出' }} <strong>{{ newowReferencePrice(trade.sellPrice) }}</strong></span><time :datetime="trade.sellDate" :title="trade.sellDate">{{ shortDate(trade.sellDate) }}</time></p>
        <span v-if="trade.buyBarIsLive" class="page-performance__note">末根新建仓的页面估值投影；不代表真实成交。</span>
      </article>
      <p class="page-performance__record-count">共 {{ active.trades.length }} 笔页面参考记录，{{ count === 3 ? '仅展示最近3笔' : '已展开全部' }}</p>
      <button class="page-performance__show-all" v-if="count < active.trades.length" type="button" @click="count = active.trades.length">查看全部 {{ active.trades.length }} 笔页面记录</button>
      <button v-else-if="count > 3 && active.trades.length > 3" type="button" @click="count = 3">收起</button>
    </template>
    <div v-if="analysisOpen" class="newow-reference__analysis-backdrop" @click.self="analysisOpen = false" @keydown.esc="analysisOpen = false">
      <section class="newow-reference__analysis-dialog" role="dialog" aria-modal="true" aria-label="收益分析">
        <header><strong>收益分析</strong><button type="button" aria-label="关闭收益分析" @click="analysisOpen = false">×</button></header>
        <p>{{ since }} → {{ through }} · {{ selection === 'ideal' ? '理论值' : '普通值' }}</p>
        <p>曲线、统计与下方记录使用同一页面投影。零手续费、零滑点，不代表模拟账户或可执行收益。</p>
        <p>{{ selection === 'ideal' ? idealExplanation : '普通值包含末根估值平仓；该估值不代表真实清仓。' }}</p>
        <p>普通值回撤为累计页面收益峰值与当前值之差，单位为百分点；理论值统计保留原站单笔最大亏损口径。</p>
        <p>物理合约区段切换处断线，未配对记录不跨合约连接。</p>
        <button type="button" @click="analysisOpen = false">知道了</button>
      </section>
    </div>
  </section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>
.page-performance { gap:6px; }
.page-performance > p,.page-performance__disclosure { font-size:11px; color:#8e8e93; margin:2px 0; }
.page-performance__disclosure summary { cursor:pointer; }
.page-performance > h3 { font-size:13px; margin:4px 0; }
.page-performance > article { padding:8px 12px; border-radius:8px; }
.page-performance > article p { font-size:12px; margin:4px 0 0; }
.page-performance > article header { display:flex; justify-content:space-between; font-size:13px; }
</style>

<style scoped>
.page-performance__toolbar { justify-content:center; margin:6px 0 8px; flex-wrap:nowrap; }
.page-performance__records-heading { display:flex; align-items:center; justify-content:space-between; margin-top:14px; gap:12px; }
.page-performance__records-heading h3 { margin:0; font-size:13px; }
.page-performance__records-heading > span,.page-performance__record-meta > span,.page-performance__record-line time,.page-performance__note { color:#999; font-size:11px; }
.page-performance__record-meta { display:flex; align-items:center; gap:8px; }
.page-performance__badge { background:#ff9500; color:white; border-radius:3px; padding:3px 7px; font-size:11px; }
.page-performance__badge[data-open="true"] { background:#007aff; }
.page-performance__record-line { display:flex; align-items:center; justify-content:space-between; }
.page-performance__record-line b { margin-right:5px; }
.page-performance__buy,[data-direction="up"] { color:#ff403a; }
.page-performance__sell,[data-direction="down"] { color:#34c759; }
.page-performance__record-count { text-align:center; }
.page-performance__show-all { align-self:center; padding:7px 22px; border:1px solid #e5e5ea; background:white; border-radius:20px; font-size:12px; cursor:pointer; }
@media(max-width:600px) { .page-performance__toolbar { gap:5px; }.page-performance__toolbar button { padding:4px 9px; }.page-performance__records-heading > span { max-width:52%; text-align:right; } }
</style>
