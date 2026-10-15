<script setup lang="ts">
import PerformancePanel from '../../../performance/PerformancePanel.vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
import { marketFrequencyLabel, formatPerformancePercent } from '@/utils/marketDisplay'
import ReturnCurveSvg from '../../../charts/ReturnCurveSvg.vue'
import { newowReferencePoints, newowReferencePrice, newowReferencePercent } from '@/utils/newowPagePresentation'
import { computed, ref, watch } from 'vue'
import type { PagePerformance } from '@/utils/newowPagePerformance'
import { pagePerformanceSegmentAnnualized, pagePerformanceLayout, pagePerformanceSummaryAnnualized } from '@/utils/newowPagePerformance'
import { newowReferenceWindow } from '@/utils/newowReferenceWindows'
const props = defineProps<{ value: PagePerformance | null | undefined; since?: string; through?: string; floor?: string; loading?: boolean }>()
const emit = defineEmits<{ reload: [window: {performanceSince: string; performanceThrough: string}] }>()
const selection = ref<'ordinary' | 'ideal'>('ordinary')
const count = ref(3)
const analysisOpen = ref(false)
const windowSelection = ref('all')
const active = computed(() => props.value?.[selection.value] ?? null)
const segmentAnnuals = computed(() => pagePerformanceSegmentAnnualized(active.value))
const annualized = computed(() => pagePerformanceSummaryAnnualized(active.value))
const periodLabel = computed(() => ({day:'日线',week:'周线',hour:'60分钟'}[active.value?.period ?? ''] ?? marketFrequencyLabel(active.value?.period as import('@/types/market').MarketFrequency) ?? '—'))
const idealExplanation = computed(() => ({
  trend: '回看最高收盘价，包含清仓当根',
  main_rise: '回看建仓后最高收盘价，不含清仓当根',
  oscillation: '回看滚动区间高点，可含建仓前高点',
  fusion: '回看最高价，不含清仓当根',
}[props.value?.strategy ?? 'trend']))
const plot = computed(() => pagePerformanceLayout(active.value))
const shortDate = (date: string) => date.slice(5,10)
const drawdown = computed(() => active.value ? newowReferencePoints(active.value.summary.maxDrawdown) : '—')
const records = computed(() => [...(active.value?.trades ?? [])].reverse().slice(0, count.value))
watch(() => [props.value, selection.value], () => { count.value = 3 })
function preset(kind: 'three_months' | 'one_year' | 'three_years' | 'ytd' | 'all') {
  windowSelection.value = kind
  if (props.through) emit('reload', newowReferenceWindow(props.through, kind, props.floor ?? props.since))
}
</script>
<template>
  <PerformancePanel class="page-performance newow-reference" kind="页面参考" :since="since" :through="through" :version="value?.version" :loading="loading" description="页面参考 · 零手续费、零滑点 · 非账户收益">
    <header class="newow-reference__returns-heading"><span class="newow-reference__annualized" title="按当前页面累计曲线的首末值及完整自然日跨度折算；跨合约段为页面汇总统计，零手续费与滑点，不代表账户或可执行收益。">页面参考年化 {{ annualized === null ? '不可计算' : `${annualized.toFixed(2)}%` }}{{ segmentAnnuals.length > 1 ? ` · ${segmentAnnuals.length}个合约段汇总` : '' }}</span><button type="button" class="newow-reference__analysis-link" @click="analysisOpen = true">收益分析 ›</button></header>
    <div v-if="value" class="newow-reference__presets page-performance__toolbar" aria-label="页面统计快捷窗口">
      <button v-for="item in ([['three_months','近3月'], ['one_year','近1年'], ['three_years','近3年'], ['ytd','今年']] as const)" :key="item[0]" type="button" :aria-pressed="windowSelection === item[0]" :disabled="loading || !through" @click="preset(item[0])">{{ item[1] }}</button>
      <button type="button" class="newow-reference__ideal" :aria-pressed="selection === 'ideal'" @click="selection = selection === 'ideal' ? 'ordinary' : 'ideal'">理论值</button>
      <button type="button" :aria-pressed="windowSelection === 'all'" :disabled="loading || !through" @click="preset('all')">全部</button>
    </div>
    <details class="page-performance__disclosure"><summary>详情与口径</summary><p>页面乐观收益 · 零手续费、零滑点；{{ selection === 'ideal' ? idealExplanation : '包含末根估值平仓' }}，不代表模拟账户或可执行收益。</p><p>页面参考年化按当前累计曲线首末值和完整自然日跨度计算；跨合约段汇总不相加各段年化，不补齐换月成交。有效样本不足或曲线首末参考净值非正时不可计算。</p></details>
    <p v-if="!active" role="status">{{ loading ? '正在读取页面收益投影…' : '当前页面收益投影不可用。' }}</p>
    <template v-else>

      <section class="newow-reference__curve" aria-label="页面估值收益曲线">
        <p v-if="plot.segments.length === 0" role="status">当前区间无页面收益曲线。</p>
        <ReturnCurveSvg v-else :plot="plot" :label="`${selection === 'ideal' ? '理论' : '普通'}页面收益曲线，区段中断处断线`" area style="--return-curve-width:1.5;--return-curve-grid:#f0f1f3" />
      </section>
      <details v-if="segmentAnnuals.length > 1" class="page-performance__segment-annuals"><summary>各合约段年化 · 不跨段计算</summary><p v-for="(segment,index) in segmentAnnuals" :key="segment.segmentId" :title="segment.segmentId">合约段 {{ index + 1 }} · {{ shortDate(segment.since) }} → {{ shortDate(segment.through) }} · 年化 {{ segment.annualized === null ? '--' : `${segment.annualized.toFixed(2)}%` }}</p></details>
      <section class="newow-reference__summary">
      <dl class="newow-reference__metrics" data-testid="page-performance-summary">
        <div><dt>累计参考收益（百分点）</dt><dd :data-direction="Number(active.summary.cumReturn) >= 0 ? 'up' : 'down'">{{ newowReferencePoints(active.summary.cumReturn) }}</dd></div>
        <div><dt>胜率</dt><dd>{{ formatPerformancePercent(String(active.summary.accuracy)) }}</dd></div>
        <div><dt :title="selection === 'ideal' ? '完整历史按单笔最大亏损；原站日期窗口过滤会重算归一化曲线回撤，保持对应原式。' : '累计页面收益峰值与当前值之差，单位为百分点。'">{{ active.drawdown_kind === 'maximum_trade_loss' ? '单笔最大亏损（百分点）' : active.drawdown_kind === 'peak_difference' || selection === 'ordinary' ? '页面曲线回撤（百分点）' : '分段页面损失统计（百分点）' }}</dt><dd class="newow-reference__drawdown">{{ drawdown }}</dd></div>
        <div><dt>交易次数</dt><dd>{{ active.summary.tradeCount }}</dd></div>
      </dl>
      </section>
      <p v-if="value?.ordinary_interrupted_count">{{ value.ordinary_interrupted_count }} 笔跨区段未完成配对未计入普通收益。</p>
      <p v-if="selection === 'ideal' && value?.ideal_open_count">{{ value.ideal_open_count }} 笔理论未平仓未计入完成统计。</p>
      <header class="page-performance__records-heading"><h3>历史参考记录</h3><span>历史页面参考，仅供参考，不作为实时买卖提示</span></header>

      <p v-if="records.length === 0">当前口径暂无页面估值交易。</p>
      <article v-for="(trade,index) in records" :key="`${trade.segment_id}:${trade.buyDate}:${trade.sellDate}:${index}`" class="newow-reference__card" :data-page-force-close="trade.forceClose">
        <header><div class="page-performance__record-meta"><strong class="page-performance__badge" :data-open="trade.forceClose">{{ trade.forceClose ? '持仓参考中' : periodLabel }}</strong><span>{{ shortDate(trade.buyDate) }} → {{ trade.forceClose ? '至估值日' : shortDate(trade.sellDate) }}</span></div><strong :data-direction="Number(trade.pct) >= 0 ? 'up' : 'down'">{{ trade.forceClose ? '参考浮动' : '盈亏' }} {{ newowReferencePercent(trade.pct) }}</strong></header>
        <p class="page-performance__record-line"><span><b class="page-performance__buy">建仓参考</b> <strong>{{ newowReferencePrice(trade.buyPrice) }}</strong></span><time :datetime="trade.buyDate" :title="trade.buyDate">{{ shortDate(trade.buyDate) }}</time></p>
        <p class="page-performance__record-line"><span><b :class="trade.forceClose ? '' : 'page-performance__sell'">{{ trade.forceClose ? '参考估值' : '清仓参考' }}</b>  <strong>{{ newowReferencePrice(trade.sellPrice) }}</strong></span><time :datetime="trade.sellDate" :title="trade.sellDate">{{ shortDate(trade.sellDate) }}</time></p>
        <span v-if="trade.buyBarIsLive" class="page-performance__note">末根新建仓的页面估值投影；不代表真实成交。</span>
      </article>
      <p class="page-performance__record-count">共 {{ active.trades.length }} 笔页面参考记录，{{ `已加载 ${Math.min(count, active.trades.length)} 笔` }}</p>
      <button class="page-performance__show-all" v-if="count < active.trades.length" type="button" @click="count += 50">加载更多参考记录</button>
      <button v-else-if="count > 3 && active.trades.length > 3" type="button" @click="count = 3">收起</button>
    </template>
    <NewowDetailDialog v-if="analysisOpen" :open="analysisOpen" title="收益分析" :identity-key="`${value?.input_sha256}:${selection}`" @close="analysisOpen = false">
      <p>{{ since }} → {{ through }} · {{ selection === 'ideal' ? '理论值' : '普通值' }}</p>
      <p>曲线、统计与下方记录使用同一页面投影。零手续费、零滑点，不代表模拟账户或可执行收益。</p>
      <p>{{ selection === 'ideal' ? idealExplanation : '普通值包含末根参考估值；该估值不代表清仓成交。' }}</p>
      <p>回撤单位为百分点；指标类型以来源声明为准：完整理论历史为单笔最大亏损，日期过滤后可变为曲线回撤；旧投影未声明或混合区段时标为分段损失统计。物理合约切换处断线，不跨合约配对。</p>
    </NewowDetailDialog>
  </PerformancePanel>
</template>
<style scoped src="./newowReferencePanel.css"></style>
<style scoped>
.page-performance__segment-annuals{padding:8px 12px;font-size:11px;color:var(--gy-text-muted)}.page-performance__segment-annuals summary{cursor:pointer}

.page-performance { gap:6px; }
.page-performance > p,.page-performance__disclosure { font-size:11px; color:var(--gy-text-muted); margin:2px 0; }
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
.page-performance__records-heading > span,.page-performance__record-meta > span,.page-performance__record-line time,.page-performance__note { color:var(--gy-text-muted); font-size:11px; }
.page-performance__record-meta { display:flex; align-items:center; gap:8px; }
.page-performance__badge { background:#ff9500; color:white; border-radius:3px; padding:3px 7px; font-size:11px; }
.page-performance__badge[data-open="true"] { background:var(--gy-accent); }
.page-performance__record-line { display:flex; align-items:center; justify-content:space-between; }
.page-performance__record-line b { margin-right:5px; }
.page-performance__buy,[data-direction="up"] { color:#ff403a; }
.page-performance__sell,[data-direction="down"] { color:#34c759; }
.page-performance__record-count { text-align:center; }
.page-performance__show-all { align-self:center; padding:7px 22px; border:1px solid var(--gy-border); background:white; border-radius:20px; font-size:12px; cursor:pointer; }
@media(max-width:600px) { .page-performance__toolbar { gap:5px; }.page-performance__toolbar button { padding:4px 9px; }.page-performance__records-heading > span { max-width:52%; text-align:right; } }
</style>
